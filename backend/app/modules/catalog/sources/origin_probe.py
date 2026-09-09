"""Bounded, SSRF-safe reachability probes for remote dataset origins.

Distinct from ``probe.py``, which detects what KIND of service a URL is.
This module asks whether a pointer GeoLens already stored is still there,
via :func:`make_safe_client` (Rule 2's sanctioned door).

fix(#1222): answers in a 3-value vocabulary (``missing``/``inaccessible``/
``healthy``), not a boolean — a 401/403 (auth now required) must map to
``inaccessible``, never ``missing``, or an operator is told to replace data
that is still there.

fix(#1755): :func:`probe_arcgis_origin` reads past the status code
because ArcGIS reports auth refusals as an error envelope inside an HTTP
200 body; it maps ``error.code`` ``498``/``499`` onto
``inaccessible``/``auth_required``.

fix(#1222): ``source_health_detail`` is persisted and served on ordinary
dataset reads, so it must never carry provider text, response bodies, or
URLs (which may hold signed query strings). It only ever returns one member
of :data:`DETAIL_CODES`, a closed, checkable, translatable set.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.core.service_tokens import (
    STAC_SERVICE_FORMAT,
    ServiceCredential,
    build_credential_header,
)
from app.modules.catalog.sources.adapters.arcgis import (
    build_arcgis_count_query_url,
)
from app.modules.catalog.sources.adapters.wfs import build_capabilities_url
from app.platform.security import (
    SSRFError,
    SSRFResolutionError,
    make_safe_client,
)

# ADR-002's stored source_health values. Mirrors SOURCE_HEALTH_VALUES in
# app/platform/dataset_origin.py, which is the schema-facing spelling; these
# constants exist so the probe never types the literals inline.
HEALTHY = "healthy"
MISSING = "missing"
INACCESSIBLE = "inaccessible"

# Seconds. Matches the timeout the VRT member probe has always used.
PROBE_TIMEOUT_SECONDS = 10.0

# fix(#1266): bounds a hostile origin streaming an endless body; real STAC
# items run under 100 KB.
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

# The closed detail vocabulary. Every value is GeoLens's own word for a class
# of outcome; none is derived from anything the origin sent us.
NOT_FOUND = "not_found"  # 404/410 on the probed resource
ITEM_WITHDRAWN = "item_withdrawn"  # the STAC item document is gone
UNAUTHORIZED = "unauthorized"  # 401/403 — access lost, not the resource
SERVER_ERROR = "server_error"  # 5xx
UNEXPECTED_STATUS = "unexpected_status"  # any other >= 400
TIMEOUT = "timeout"
NETWORK_ERROR = "network_error"  # connect failure, DNS, TLS, bad redirect chain
BLOCKED_BY_POLICY = "blocked_by_policy"  # SSRF validation refused the target
# fix(#1746): separate from UNAUTHORIZED, whose copy says the source "now
# requires" access — wrong for a service that has been org-only since import
# (the common ArcGIS 499 case).
AUTH_REQUIRED = "auth_required"

DETAIL_CODES: frozenset[str] = frozenset(
    {
        NOT_FOUND,
        ITEM_WITHDRAWN,
        UNAUTHORIZED,
        SERVER_ERROR,
        UNEXPECTED_STATUS,
        TIMEOUT,
        NETWORK_ERROR,
        BLOCKED_BY_POLICY,
        AUTH_REQUIRED,
    }
)

# fix(#1746): the two ways an origin can demand a credential we lack —
# ArcGIS's 200-wrapped error envelope, and a plain 401/403 from everything
# else — collapsed to one set for callers deciding whether to ask for a token.
AUTH_CHALLENGE_DETAILS: frozenset[str] = frozenset({UNAUTHORIZED, AUTH_REQUIRED})

# "The origin answered and the resource is gone." 404 and 410 only.
_GONE_STATUSES = frozenset({404, 410})
# "The origin answered and we are no longer allowed to look." Deliberately
# NOT gone: the resource may be entirely intact behind new authentication.
_DENIED_STATUSES = frozenset({401, 403})


@dataclass(frozen=True)
class OriginProbeResult:
    """Outcome of one origin probe, in ADR-002's health vocabulary."""

    health: str
    detail: str | None = None
    # fix(#1271): False ONLY for a pre-flight SSRF policy block — that
    # never puts a packet on the wire, so it must not overwrite a real
    # earlier ``last_checked_at``. A timeout/TLS failure still counts as
    # contact.
    contacted: bool = True
    # fix(#1746): body was sub-400 but exceeded `max_bytes`
    # and was never parsed. Not a detail code — the persisted vocabulary is a
    # wire contract every consumer enumerates; this is internal-only.
    oversized: bool = False

    @property
    def ok(self) -> bool:
        """True only for ``healthy`` — the boolean the VRT flow wants."""
        return self.health == HEALTHY


def _classify_failure(exc: BaseException, *, responded: bool) -> tuple[str, bool]:
    """Classify a transport failure into (detail code, contacted).

    ``SSRFResolutionError`` is an ``SSRFError`` is a ``ValueError`` — check
    the most specific class first. NXDOMAIN is a property of the origin
    (``network_error``); a policy refusal is a property of GeoLens
    (``blocked_by_policy``), and ``contacted`` reflects whether a response
    hop arrived before the refusal.
    """
    if isinstance(exc, SSRFResolutionError):
        return NETWORK_ERROR, responded
    if isinstance(exc, SSRFError):
        return BLOCKED_BY_POLICY, responded
    if isinstance(exc, httpx.TimeoutException):
        return TIMEOUT, True
    # fix(#1271): the OUTER deadline can expire during DNS resolution,
    # before any packet goes out, so contact is whatever the response hook
    # proved rather than assumed.
    if isinstance(exc, TimeoutError):
        return TIMEOUT, responded
    # fix(#1271): raised while CONSTRUCTING the request — a malformed
    # stored URL never puts a packet on the wire.
    if isinstance(exc, (httpx.InvalidURL, httpx.UnsupportedProtocol)):
        return NETWORK_ERROR, responded
    return NETWORK_ERROR, True


def _status_result(status_code: int) -> OriginProbeResult:
    if status_code < 400:
        return OriginProbeResult(HEALTHY)
    if status_code in _GONE_STATUSES:
        return OriginProbeResult(MISSING, NOT_FOUND)
    if status_code in _DENIED_STATUSES:
        return OriginProbeResult(INACCESSIBLE, UNAUTHORIZED)
    if status_code >= 500:
        return OriginProbeResult(INACCESSIBLE, SERVER_ERROR)
    return OriginProbeResult(INACCESSIBLE, UNEXPECTED_STATUS)


async def probe_remote_uri(
    uri: str,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    credential: ServiceCredential | None = None,
) -> OriginProbeResult:
    """Probe *uri* without downloading its body.

    A ranged ``GET`` rather than ``HEAD``: a meaningful minority of origins
    reject ``HEAD`` with 405, which would reintroduce the ambiguity the
    three-value vocabulary exists to remove. Streaming plus the
    context-manager close bounds the body even if the range header is
    ignored.

    feat(#1764): a STAC asset behind an API key is probed WITH that key, so
    a protected asset reads as healthy rather than as ``unauthorized``. The
    credential reaches this function from a door or from the refresh
    worker's single-use claim.
    """
    # fix(#1271): records whether ANY response hop arrived, so a
    # mid-chain policy refusal (public origin redirecting to a blocked
    # target) still counts as a contact. First in the hook list so it runs
    # before the revalidation hook can raise.
    responded = False

    async def _mark_responded(_response: httpx.Response) -> None:
        nonlocal responded
        responded = True

    headers = {"Range": "bytes=0-0"}
    pair: tuple[str, str] | None = None
    if credential is not None:
        pair = build_credential_header(
            replace(credential, service_format=STAC_SERVICE_FORMAT)
        )
        if pair is not None:
            headers[pair[0]] = pair[1]
    try:
        # fix(#1271): hard deadline around the WHOLE op — the guard
        # transport resolves DNS before httpx's phase timeouts apply, so a
        # stalling resolver would otherwise exceed the advertised bound.
        # Doubled: this is a backstop, not the primary bound.
        async with asyncio.timeout(timeout * 2):
            async with make_safe_client(
                timeout=timeout, credential_header=None if pair is None else pair[0]
            ) as client:
                # hasattr: duck-typed clients in tests may not carry
                # event_hooks, and an AttributeError here would masquerade
                # as a probe failure.
                if hasattr(client, "event_hooks"):
                    hooks = client.event_hooks
                    hooks["response"] = [
                        _mark_responded,
                        *hooks.get("response", []),
                    ]
                    client.event_hooks = hooks
                async with client.stream("GET", uri, headers=headers) as response:
                    status_code = response.status_code
    except (
        Exception
    ) as exc:  # broad: every transport failure means "could not determine"
        # Only the classification crosses this boundary. The exception itself
        # is never rendered: httpx puts the full request URL in its messages.
        detail, contacted = _classify_failure(exc, responded=responded)
        return OriginProbeResult(INACCESSIBLE, detail, contacted=contacted)

    return _status_result(status_code)


# fix(#1746): ArcGIS reports auth refusals as an error envelope
# inside an HTTP 200 (499 token required, 498 token rejected); a status-code
# probe alone reads both as healthy.
_ARCGIS_AUTH_ERROR_CODES = frozenset({498, 499})


async def probe_arcgis_origin(
    uri: str, *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> OriginProbeResult:
    """Probe an ArcGIS FeatureServer layer and read its error envelope.

    Not ``probe_arcgis_service`` — that name is taken by the import-time
    detector in ``adapters/arcgis.py``, which answers a different question
    with layer metadata.

    Reads the body, so it inherits ``fetch_json_document``'s size cap; an
    oversized sub-400 answer resolves in the origin's favour (see below).

    fix(#1746): probes ``<layer>/query`` (what the worker actually
    fetches), not the layer document — a deployment that serves layer
    metadata publicly but gates the query op would otherwise pass probing
    and fail on ingest.
    """
    try:
        target = build_arcgis_count_query_url(uri)
    except (ValueError, AttributeError):
        # Let the fetch classify a malformed stored URL, rather than raising
        # out of a handler that has already released its DB session.
        target = uri
    result, body, _final_url = await fetch_json_document(target, timeout=timeout)
    if result.oversized:
        # fix(#1746): an ArcGIS auth envelope is a few
        # hundred bytes, so an oversized sub-400 body is not a refusal —
        # calling it `inaccessible` for answering at LENGTH would be the
        # false negative mirroring the false positive this probe closes.
        return OriginProbeResult(HEALTHY)
    if not result.ok:
        return result
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("code") in _ARCGIS_AUTH_ERROR_CODES:
        # No provider text: `source_health_detail` is served on every dataset
        # read, and the closed vocabulary is what keeps it leak-proof.
        return OriginProbeResult(INACCESSIBLE, AUTH_REQUIRED)
    return result


def service_probe_target(origin_ref: Any, origin_uri: str | None) -> str | None:
    """The URL a probe of a service origin should contact, or ``None``.

    fix(#1271): only ArcGIS's ``origin_uri`` (``<base>/<numeric id>``)
    addresses a real HTTP resource directly. WFS and OGC API address layers
    through a typename/collection parameter, so their enriched URI is a
    non-endpoint whose 404 would be a false verdict — those two probe the
    canonical service base instead (WFS via ``build_capabilities_url``,
    since many servers 4xx a bare base).

    No fallback to ``origin_uri`` on the WFS/OGC API branches: migration
    0036's legacy branch can leave ``url`` unset, and probing the
    non-endpoint would still be a false verdict. ``None`` means "nothing
    safe to probe".

    fix(#1746): lifted out of ``router_health`` so the refresh door decides
    what to contact the same way the health endpoint does; takes the two
    stored columns rather than a ``Dataset`` to keep this module independent
    of the catalog ORM.
    """
    ref = origin_ref if isinstance(origin_ref, dict) else {}
    service_type = ref.get("service_type")
    if service_type in ("wfs", "ogcapi_features"):
        target = ref.get("url")
        if target and service_type == "wfs":
            target = build_capabilities_url(target)
    else:
        target = origin_uri or ref.get("url")
    return target or None


async def probe_service_origin(
    target: str, service_type: str | None, *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> OriginProbeResult:
    """Probe a service origin with the probe its service type needs.

    fix(#1746): one place decides which probe answers for which service, so
    the health endpoint and the refresh door cannot drift into disagreeing
    about whether an ArcGIS 200 was healthy.
    """
    if service_type == "arcgis_featureserver":
        return await probe_arcgis_origin(target, timeout=timeout)
    return await probe_remote_uri(target, timeout=timeout)


# fix(#1746): "too big to parse" and "not JSON" say
# different things about whether an ArcGIS auth envelope could have been in
# there — only the size case can be ruled out by arithmetic — so two
# constants, though the persisted health value and detail code are identical.
_UNREADABLE_DOCUMENT = OriginProbeResult(INACCESSIBLE, UNEXPECTED_STATUS)
_OVERSIZED_DOCUMENT = OriginProbeResult(INACCESSIBLE, UNEXPECTED_STATUS, oversized=True)


async def fetch_json_document(
    uri: str,
    *,
    method: str = "GET",
    json_body: Any | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    max_bytes: int = MAX_DOCUMENT_BYTES,
    credential: ServiceCredential | None = None,
) -> tuple[OriginProbeResult, Any | None, str]:
    """Fetch *uri* and return its verdict, its parsed body, and its final URL.

    feat(#1266): like :func:`probe_remote_uri` but keeps the body, for a
    re-resolved STAC item document that names where its assets live now.
    Goes through :func:`make_safe_client` like everything else here, so the
    SSRF contract has one place to rot.

    Body is returned ONLY for a sub-400 response that parses as JSON inside
    ``max_bytes``; otherwise ``None`` plus ``unexpected_status`` (the closed
    vocabulary, since ``source_health_detail`` is persisted and served).

    The third element is the URL the document actually CAME from, after any
    redirect — STAC hrefs are legally relative, so resolving them against
    the requested URL instead would point a redirected catalog's assets at
    the wrong host. The SSRF transport restores the hostname after each
    pinned hop, so this is never the pinned IP.

    feat(#1764): ``credential`` is the key a protected catalog needs.
    Composed here rather than passed in as a finished header, so the
    single-producer rule holds on this path too, and declared to the client
    so a 302 cannot carry the key to the origin the Location names.
    """
    responded = False
    final_url = uri

    async def _mark_responded(_response: httpx.Response) -> None:
        nonlocal responded
        responded = True

    headers = {"Accept": "application/geo+json, application/json"}
    pair: tuple[str, str] | None = None
    if credential is not None:
        pair = build_credential_header(
            replace(credential, service_format=STAC_SERVICE_FORMAT)
        )
        if pair is not None:
            headers[pair[0]] = pair[1]
    raw = bytearray()
    try:
        # The same doubled hard deadline probe_remote_uri takes, and for the
        # same reason: httpx's phase timeouts do not cover the guard
        # transport's DNS resolution.
        async with asyncio.timeout(timeout * 2):
            async with make_safe_client(
                timeout=timeout, credential_header=None if pair is None else pair[0]
            ) as client:
                if hasattr(client, "event_hooks"):
                    hooks = client.event_hooks
                    hooks["response"] = [_mark_responded, *hooks.get("response", [])]
                    client.event_hooks = hooks
                async with client.stream(
                    method,
                    uri,
                    json=json_body,
                    headers=headers,
                ) as response:
                    status_code = response.status_code
                    final_url = str(response.url)
                    if status_code < 400:
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > max_bytes:
                                # Leaving the context manager closes the
                                # response, so nothing keeps arriving.
                                return _OVERSIZED_DOCUMENT, None, final_url
    except (
        Exception
    ) as exc:  # broad: every transport failure means "could not determine"
        detail, contacted = _classify_failure(exc, responded=responded)
        return (
            OriginProbeResult(INACCESSIBLE, detail, contacted=contacted),
            None,
            final_url,
        )

    result = _status_result(status_code)
    if not result.ok:
        return result, None, final_url
    try:
        return result, json.loads(raw), final_url
    except (ValueError, RecursionError):
        # Not folded into the transport handler above: a non-JSON body is
        # not a transport failure.
        # fix(#1858): `RecursionError` joins it — a JSON depth bomb well
        # under `max_bytes` (300k nested `[` is ~600 KB) raised unclassified
        # past this point before, 500ing `GET /datasets/{id}/health`.
        return _UNREADABLE_DOCUMENT, None, final_url


async def remote_asset_exists(asset_uri: str) -> bool:
    """Boolean form of :func:`probe_remote_uri`, for the VRT member flow.

    Remote STAC assets are deliberately not passed to the configured object
    storage provider: the safe client pins validated public IPs and
    revalidates redirects, which no storage backend does for an arbitrary
    HTTP(S) href.
    """
    return (await probe_remote_uri(asset_uri)).ok

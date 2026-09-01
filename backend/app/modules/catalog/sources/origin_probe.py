"""Bounded, SSRF-safe reachability probes for remote dataset origins.

feat(#1222): one probe, two callers. ``router_vrt.py`` grew a private
``_remote_asset_exists`` for VRT member health; the standalone STAC and
service origins need the same request with a richer answer, and a second
copy would be a second place for the SSRF contract to rot. Everything here
goes through :func:`make_safe_client`, which is Rule 2's only sanctioned
door (per-hop redirect revalidation plus connect-time IP pinning).

Distinct from the sibling ``probe.py``, which detects what KIND of service a
URL is at import time. This module asks a much smaller question about a
pointer GeoLens already stored: is it still there.

The probe answers in ADR-002's three-value health vocabulary rather than a
boolean, because the two states a boolean collapses are the ones an operator
has to act on differently:

- ``missing`` — the origin answered authoritatively that the resource is
  gone (404/410). Someone deleted it upstream; the dataset will never work
  again without a new pointer.
- ``inaccessible`` — GeoLens could not determine whether it is still there.
  A timeout, a TLS failure, an SSRF refusal, or a 401/403. Possibly
  transient, and specifically NOT a reason to go re-import anything.

The 401/403 split is the one worth stating twice, because collapsing it is
the easy mistake: an upstream that newly requires authentication answers
exactly like one that deleted the file, and calling that ``missing`` tells
an operator to replace data that is still sitting there.

``healthy`` is a status below 400, matching what the VRT probe has always
meant by "the file is there".

### Why ``detail`` is a code and not a sentence

``source_health_detail`` is persisted and served on ordinary dataset reads
(``DatasetResponse``), so anything that reaches it is readable by everyone
who can read the dataset. Provider error text, response bodies, headers and
URLs are therefore all out — an origin URI may legitimately carry a signed
query string, and httpx bakes the full request URL into its exception
messages. Rather than trying to scrub free text, the probe never composes
any: it returns one member of :data:`DETAIL_CODES`, a closed set defined
here. A closed set is checkable (``test_source_health_1222`` asserts every
persisted value is in it), translatable by the frontend, and structurally
incapable of leaking, which "remember to redact" is not.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

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

# feat(#1266): the ceiling on a document body this module will hold in memory.
# The only caller reads STAC item documents, which run to a few kilobytes in
# practice — a Sentinel-2 item carrying every band is well under 100 KB — so
# this is generous for a real catalog and small enough that a hostile origin
# streaming an endless body cannot walk a refresh worker out of memory.
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
# fix(#1746): the origin wants a credential we do not hold. Separate from
# UNAUTHORIZED, whose shipped copy says the source "now requires" access —
# that misdescribes a service which has been org-only since the day it was
# imported, which is the common case for an ArcGIS 499.
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

# fix(#1746): the two ways an origin can say "you need a credential I do not
# hold" — ArcGIS's error envelope inside a 200, and a plain 401/403 from
# everything else. They are one fact to a caller deciding whether to ask for a
# token, so the set is named once here rather than spelled out at each reader.
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
    # fix(#1271 review): whether an outbound attempt actually left GeoLens.
    # ``last_checked_at`` means "last time GeoLens contacted the origin at
    # all", and an SSRF refusal happens before any packet goes out — stamping
    # it would overwrite a real earlier contact time with a policy-check
    # time. False ONLY for policy blocks: a timeout or TLS failure was still
    # an attempt on the wire. Conservative on redirect chains — a mid-chain
    # SSRF refusal did contact the first hop, but under-stamping a contact
    # is recoverable while fabricating one is not.
    contacted: bool = True

    @property
    def ok(self) -> bool:
        """True only for ``healthy`` — the boolean the VRT flow wants."""
        return self.health == HEALTHY


def _classify_failure(exc: BaseException, *, responded: bool) -> tuple[str, bool]:
    """Classify a transport failure into (detail code, contacted).

    Order matters twice over. ``SSRFResolutionError`` is an ``SSRFError`` and
    ``SSRFError`` is a ``ValueError``, so the most specific class goes first.
    And the two SSRF shapes report different facts: NXDOMAIN is a property of
    the origin (``network_error``), a policy refusal is a property of GeoLens
    (``blocked_by_policy``).

    ``contacted`` for the SSRF shapes is whether any response hop arrived
    before the failure — a public origin that redirects to a blocked target
    WAS contacted (it answered), while a first-hop refusal never put a packet
    on the wire. Timeouts and connect failures were attempts on the wire and
    keep their stamp.
    """
    if isinstance(exc, SSRFResolutionError):
        return NETWORK_ERROR, responded
    if isinstance(exc, SSRFError):
        return BLOCKED_BY_POLICY, responded
    if isinstance(exc, httpx.TimeoutException):
        return TIMEOUT, True
    # fix(#1271 review): the OUTER deadline (asyncio.timeout around the whole
    # probe) — unlike httpx's phase timeouts it can expire during DNS
    # resolution, before any packet goes out, so contact is whatever the
    # response hook can prove rather than assumed.
    if isinstance(exc, TimeoutError):
        return TIMEOUT, responded
    # fix(#1271 review): raised while CONSTRUCTING the request — a malformed
    # stored URL (migration 0036 backfills check only prefix and credentials)
    # never puts a packet on the wire, so it must not advance the contact
    # clock the way a connect or TLS failure legitimately does.
    if isinstance(exc, (httpx.InvalidURL, httpx.UnsupportedProtocol)):
        return NETWORK_ERROR, responded
    return NETWORK_ERROR, True


def _status_result(status_code: int) -> OriginProbeResult:
    """Map an HTTP status onto a health value and a detail code."""
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
    uri: str, *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> OriginProbeResult:
    """Probe *uri* without downloading its body.

    A ranged ``GET`` rather than ``HEAD``: object stores and tile services
    answer ``Range: bytes=0-0`` uniformly, while a meaningful minority reject
    ``HEAD`` with 405 — which this function would then have to special-case
    back into "probably fine", reintroducing the ambiguity the three-value
    vocabulary exists to remove. Streaming plus the context-manager close
    bounds the response body even for a server that ignores the range header.
    """
    # fix(#1271 review): records whether ANY response hop arrived, so a
    # mid-chain policy refusal (public origin redirecting to a blocked
    # target) still counts as a contact. First in the hook list so it runs
    # before the revalidation hook can raise.
    responded = False

    async def _mark_responded(_response: httpx.Response) -> None:
        nonlocal responded
        responded = True

    try:
        # fix(#1271 review): a hard deadline around the WHOLE operation. The
        # guard transport resolves DNS before httpx's phase timeouts apply,
        # so a stalling resolver would otherwise hold the probe (and its
        # caller's request) far beyond the advertised bound. Doubled because
        # the phase timeouts remain the primary bound — this is the backstop
        # for the phases they cannot see.
        async with asyncio.timeout(timeout * 2):
            async with make_safe_client(timeout=timeout) as client:
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
                async with client.stream(
                    "GET", uri, headers={"Range": "bytes=0-0"}
                ) as response:
                    status_code = response.status_code
    except (
        Exception
    ) as exc:  # broad: every transport failure means "could not determine"
        # Only the classification crosses this boundary. The exception itself
        # is never rendered: httpx puts the full request URL in its messages.
        detail, contacted = _classify_failure(exc, responded=responded)
        return OriginProbeResult(INACCESSIBLE, detail, contacted=contacted)

    return _status_result(status_code)


# ArcGIS reports auth refusals as an error envelope inside an HTTP 200 body:
# 499 "Token Required" for an org-only service, 498 for a token it rejected.
# A status-code probe reads both as healthy, which is the false positive this
# closes (#1746 finding 12).
_ARCGIS_AUTH_ERROR_CODES = frozenset({498, 499})


async def probe_arcgis_service(
    uri: str, *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> OriginProbeResult:
    """Probe an ArcGIS FeatureServer layer and read its error envelope.

    NOT the namesake in ``sources/adapters/arcgis.py``. That one is the
    import-time detector — it takes a client and a token, asks whether a URL
    is a FeatureServer at all, and answers with layer metadata. This one asks
    the much smaller question this module exists for, about a pointer GeoLens
    already stored: does it still answer, and is it asking us to authenticate.
    Do not import the two into the same namespace.
    """
    try:
        target = str(httpx.URL(uri).copy_set_param("f", "json"))
    except (httpx.InvalidURL, ValueError):
        # Let the fetch classify a malformed stored URL, rather than raising
        # out of a handler that has already released its DB session.
        target = uri
    result, body, _final_url = await fetch_json_document(target, timeout=timeout)
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

    fix(#1271 review): the target depends on the service type. Ingest stores
    ``origin_uri`` as ``<base>/<layer identity>`` for provenance, and only
    ArcGIS's flavor of that (``<base>/<numeric id>``) is a real HTTP resource
    — WFS and OGC API address layers through a typename or collection
    parameter, so their enriched URI is a non-endpoint and probing it records
    whatever the server's 404 fallback happens to say about a URL nobody
    serves. For those two the canonical service base in ``origin_ref.url`` is
    the thing whose reachability the answer describes, and for WFS the base
    alone is not enough either: many servers 4xx a request without
    ``service=WFS&request=GetCapabilities``, so the probe asks the same
    question the import adapter asks, through the same URL builder. An OGC API
    base is a plain JSON landing page and needs no parameters.

    No fallback to ``origin_uri`` on the WFS and OGC API branches: migration
    0036's legacy branch deliberately leaves ``url`` unset when the base is
    not derivable, so the only value on hand is the non-endpoint, and probing
    it would produce a false verdict. ``None`` means "nothing safe to probe",
    which each caller answers in its own vocabulary.

    fix(#1746): lifted out of ``router_health`` so the refresh door can decide
    what to contact the same way the health endpoint does. It takes the two
    stored columns rather than a ``Dataset`` so this module keeps its
    independence from the catalog ORM.
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
        return await probe_arcgis_service(target, timeout=timeout)
    return await probe_remote_uri(target, timeout=timeout)


# "The origin answered, and what it said is not something GeoLens can act
# on." One verdict for both shapes of that, because they are one fact to the
# person reading it and neither is a transport failure.
_OVERSIZED_OR_UNREADABLE = OriginProbeResult(INACCESSIBLE, UNEXPECTED_STATUS)


async def fetch_json_document(
    uri: str,
    *,
    method: str = "GET",
    json_body: Any | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> tuple[OriginProbeResult, Any | None, str]:
    """Fetch *uri* and return its verdict, its parsed body, and its final URL.

    feat(#1266). :func:`probe_remote_uri` asks whether a pointer still
    resolves and deliberately throws the body away. Re-resolving a moved STAC
    item asks the same question and then needs the answer's CONTENT — the
    item document names where its assets live now. This is that request:
    the same safe client, the same closed detail vocabulary, the same status
    mapping, with the body kept.

    It lives here rather than beside its caller for the reason the module
    docstring already gives for the probe: everything outbound goes through
    :func:`make_safe_client`, which is Rule 2's only sanctioned door, and a
    second fetch written elsewhere is a second place for the SSRF contract
    and the health mapping to rot apart. Nothing in the refresh strategy
    constructs an HTTP client of its own.

    The body is returned ONLY for a sub-400 response, and only when it parses
    as JSON inside ``max_bytes``. Anything else — an oversized stream, a body
    that is not JSON, a 4xx or 5xx — yields ``None`` beside a verdict, so a
    caller cannot accidentally read half a document. An unparseable or
    oversized body reports ``unexpected_status``: the origin answered, and
    what it answered with is not something GeoLens can act on. That is a
    member of the closed vocabulary rather than a new code, because
    ``source_health_detail`` is persisted and served, and widening the set
    costs every consumer that enumerates it.

    The third element is the URL the document actually CAME from, after any
    redirect, falling back to the requested one. STAC hrefs are legally
    relative, and resolving them against the address that was asked for
    rather than the one that answered would point a redirected catalog's
    assets at the wrong host. ``search_stac_items`` reads ``resp.url`` for
    the same reason; the SSRF transport restores the hostname after each
    pinned hop, so this is the logical URL and never the pinned IP.
    """
    responded = False
    final_url = uri

    async def _mark_responded(_response: httpx.Response) -> None:
        nonlocal responded
        responded = True

    raw = bytearray()
    try:
        # The same doubled hard deadline probe_remote_uri takes, and for the
        # same reason: httpx's phase timeouts do not cover the guard
        # transport's DNS resolution.
        async with asyncio.timeout(timeout * 2):
            async with make_safe_client(timeout=timeout) as client:
                if hasattr(client, "event_hooks"):
                    hooks = client.event_hooks
                    hooks["response"] = [_mark_responded, *hooks.get("response", [])]
                    client.event_hooks = hooks
                async with client.stream(
                    method,
                    uri,
                    json=json_body,
                    headers={"Accept": "application/geo+json, application/json"},
                ) as response:
                    status_code = response.status_code
                    final_url = str(response.url)
                    if status_code < 400:
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > max_bytes:
                                # Stop reading rather than stop the request:
                                # leaving the context manager closes the
                                # response, so nothing keeps arriving.
                                return _OVERSIZED_OR_UNREADABLE, None, final_url
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
    except ValueError:
        # Deliberately not folded into the handler above: a body that is not
        # JSON is not a transport failure, and classifying it as one would
        # report `network_error` for an origin that answered perfectly well
        # with an HTML error page.
        return _OVERSIZED_OR_UNREADABLE, None, final_url


async def remote_asset_exists(asset_uri: str) -> bool:
    """Boolean form of :func:`probe_remote_uri`, for the VRT member flow.

    Remote STAC assets are deliberately not passed to the configured object
    storage provider: the safe client pins validated public IPs and
    revalidates redirects, which no storage backend does for an arbitrary
    HTTP(S) href.
    """
    return (await probe_remote_uri(asset_uri)).ok

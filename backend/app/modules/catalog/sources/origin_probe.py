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

from dataclasses import dataclass

import httpx

from app.modules.catalog.sources.security import SSRFError, make_safe_client

# ADR-002's stored source_health values. Mirrors SOURCE_HEALTH_VALUES in
# app/platform/dataset_origin.py, which is the schema-facing spelling; these
# constants exist so the probe never types the literals inline.
HEALTHY = "healthy"
MISSING = "missing"
INACCESSIBLE = "inaccessible"

# Seconds. Matches the timeout the VRT member probe has always used.
PROBE_TIMEOUT_SECONDS = 10.0

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
    }
)

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


def _failure_code(exc: BaseException) -> str:
    """Classify a transport failure into the closed vocabulary.

    Order matters: ``SSRFError`` is a ``ValueError``, and it can surface
    either from the guard transport at connect time or from the redirect
    revalidation hook mid-chain, so it is checked before anything broader.
    """
    if isinstance(exc, SSRFError):
        return BLOCKED_BY_POLICY
    if isinstance(exc, httpx.TimeoutException):
        return TIMEOUT
    return NETWORK_ERROR


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
    try:
        async with make_safe_client(timeout=timeout) as client:
            async with client.stream(
                "GET", uri, headers={"Range": "bytes=0-0"}
            ) as response:
                status_code = response.status_code
    except (
        Exception
    ) as exc:  # broad: every transport failure means "could not determine"
        # Only the classification crosses this boundary. The exception itself
        # is never rendered: httpx puts the full request URL in its messages.
        return OriginProbeResult(
            INACCESSIBLE,
            _failure_code(exc),
            contacted=not isinstance(exc, SSRFError),
        )

    return _status_result(status_code)


async def remote_asset_exists(asset_uri: str) -> bool:
    """Boolean form of :func:`probe_remote_uri`, for the VRT member flow.

    Remote STAC assets are deliberately not passed to the configured object
    storage provider: the safe client pins validated public IPs and
    revalidates redirects, which no storage backend does for an arbitrary
    HTTP(S) href.
    """
    return (await probe_remote_uri(asset_uri)).ok

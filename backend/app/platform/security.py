"""SSRF validation, URL scheme checking, and IP resolution blocking."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

ALLOWED_SCHEMES = frozenset({"http", "https"})

# User decision: 10 second timeout for probe requests
PROBE_TIMEOUT = httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0)


class SSRFError(ValueError):
    """URL targets a private/internal network or uses a disallowed scheme."""


class SSRFResolutionError(SSRFError):
    """The hostname did not resolve at all.

    fix(#1271): a subclass, not a sibling — NXDOMAIN reports
    ``network_error`` (dead DNS), a policy refusal reports
    ``blocked_by_policy``; collapsing them misdirects an operator to audit
    egress policy for a domain that no longer exists.
    """


# SEC-013: ranges is_private/is_reserved miss but must be blocked for SSRF.
# CGNAT 100.64.0.0/10 (not flagged by is_private on Python <=3.10); IPv6 ULA
# fc00::/7 (missed on some older builds); NAT64 64:ff9b::/96 (embeds an IPv4
# address that may itself be private).
_EXTRA_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 CGNAT
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
)


def _is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        return True
    # SEC-013: check ranges not covered by the standard predicates above.
    for network in _EXTRA_BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


async def _resolve_and_validate(host: str, port: int | None) -> str:
    """Resolve *host*, validate every resolved IP, and return one validated IP.

    SEC-008: the caller pins the connection to this address, closing the gap
    between validation-time and connect-time DNS. Raises SSRFError if
    resolution fails or any resolved address is blocked.
    """
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise SSRFResolutionError(f"Could not resolve hostname: {host}")
    if not results:
        raise SSRFResolutionError(f"Could not resolve hostname: {host}")
    for _family, _type, _proto, _canon, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError("URLs targeting private/internal networks are not allowed")
    return str(ipaddress.ip_address(results[0][4][0]))


async def validate_url_for_ssrf(url: str) -> None:
    """Validate a URL is safe to fetch (no SSRF).

    Checks:
    1. Scheme is http or https
    2. Hostname is present
    3. Hostname resolves to non-private IP addresses

    Raises SSRFError with a user-friendly message on failure.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFError("Only http and https URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: no hostname found")

    # asyncio.to_thread avoids blocking the event loop on slow DNS.
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo, hostname, parsed.port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise SSRFResolutionError(f"Could not resolve hostname: {hostname}")

    if not results:
        raise SSRFResolutionError(f"Could not resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError("URLs targeting private/internal networks are not allowed")


# HYG-03: include 305 (Use Proxy) for completeness even though RFC 7231
# deprecated it and httpx doesn't follow it by default. Cheap defense-in-depth.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 305, 307, 308})

# Default ports so `https://host` and `https://host:443` are one origin.
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Headers that ARE a credential regardless of caller declaration. httpx
# strips `Authorization` on a cross-origin redirect already; it forwards
# this one unless refused explicitly.
_ALWAYS_CREDENTIAL_HEADERS = frozenset({"x-esri-authorization"})

# Names the policy, never the header value: this reaches a response body, a
# log line, and a job row.
CROSS_ORIGIN_CREDENTIAL_POLICY = (
    "Refusing to send a credential header to a different origin after a "
    "redirect. Point the source at the address that answers directly, or ask "
    "the service operator why it redirects a credentialed request elsewhere."
)


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    """Scheme, host and port, with the scheme's default port filled in."""
    scheme = (url.scheme or "").lower()
    return (scheme, (url.host or "").lower(), url.port or _DEFAULT_PORTS.get(scheme))


def same_origin(first: str, second: str) -> bool:
    """Whether two URLs address the same origin: scheme, host and port.

    fix(#1746): the public form of the redirect hook's rule, for callers
    (e.g. an adapter following a link from a response document) that issue
    a fresh request no redirect hook ever sees. Total: an unparseable URL
    is never the same origin as anything, including itself, so a caller
    deciding whether to send a credential never sends one on a parse error.
    """
    try:
        return _origin(httpx.URL(first)) == _origin(httpx.URL(second))
    except (httpx.InvalidURL, ValueError, TypeError):
        return False


def _refuse_cross_origin_credential(
    response: httpx.Response, watched: frozenset[str]
) -> None:
    """Keep a credential on the origin it was given to.

    fix(#1746): httpx strips `Authorization` on a cross-origin redirect but
    forwards any other header unchanged, so a caller-named key (`X-API-Key`,
    `Ocp-Apim-Subscription-Key`) follows a 302 to an origin that is public
    and SSRF-valid but not the service it was issued to. Runs from the
    response hook, before httpx follows the redirect, so the second request
    is never issued.
    """
    if response.status_code not in _REDIRECT_STATUSES:
        return
    location = response.headers.get("Location")
    if not location:
        return
    request = response.request
    # Headers membership is case-insensitive: `X-API-Key` matches `x-api-key`.
    if not any(name in request.headers for name in watched):
        return
    if _origin(httpx.URL(response.url).join(location)) == _origin(request.url):
        return
    raise SSRFError(CROSS_ORIGIN_CREDENTIAL_POLICY)


async def _revalidate_redirect(response: httpx.Response) -> None:
    """httpx response hook: re-validate the Location target on every redirect hop.

    SEC-S04: `follow_redirects=True` silently retargets to attacker-controlled
    internal IPs on a 302; `validate_url_for_ssrf` runs at submission time but
    not per-hop, so this hook closes the gap. Raising SSRFError here aborts
    further redirect-following.

    fix(#1746): also refuses a hop carrying a credential header to a
    different origin, checked first since it needs no DNS lookup and the
    Location may otherwise be a perfectly SSRF-valid public host.
    """
    _refuse_cross_origin_credential(response, _ALWAYS_CREDENTIAL_HEADERS)
    if response.status_code not in _REDIRECT_STATUSES:
        return
    location = response.headers.get("Location")
    if not location:
        return
    # Resolve relative redirects against the original response URL.
    target = str(httpx.URL(response.url).join(location))
    await validate_url_for_ssrf(target)


def _redirect_hook(credential_header: str | None):
    """Response hook a client installs, for the header it declared.

    A closure rather than another parameter on ``_revalidate_redirect``:
    that function is named directly by AGENTS.md Rule 2 and by tests, so it
    stays a plain single-argument coroutine.
    """
    if not credential_header:
        return _revalidate_redirect

    watched = _ALWAYS_CREDENTIAL_HEADERS | {credential_header.lower()}

    async def _hook(response: httpx.Response) -> None:
        _refuse_cross_origin_credential(response, watched)
        await _revalidate_redirect(response)

    return _hook


class _SSRFGuardTransport(httpx.AsyncHTTPTransport):
    """Transport that re-resolves, re-validates, and PINS the IP at connect time.

    SEC-008: `validate_url_for_ssrf` resolves DNS once at submission time,
    but the client does its own lookup at connect time — a low-TTL attacker
    domain can answer public at validation and private at connect (DNS
    rebinding). This transport resolves + validates immediately before
    connecting and pins by rewriting the URL host to the validated IP, while
    keeping the original hostname for the Host header and TLS SNI. httpx
    builds a fresh request per redirect hop, so every hop is re-pinned.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_url = request.url
        host = original_url.host
        validated_ip = await _resolve_and_validate(host, original_url.port)
        # sni_hostname keeps the hostname for TLS SNI/verification.
        request.url = original_url.copy_with(host=validated_ip)
        request.extensions["sni_hostname"] = host
        try:
            return await super().handle_async_request(request)
        finally:
            # fix(#1271): restore the hostname after connect — leaving the
            # pinned IP would break relative-redirect resolution (next hop's
            # SNI would be the IP, failing TLS) and leak the IP into
            # response.url, cookies, and caller-side URL derivation.
            request.url = original_url


def make_safe_transport() -> httpx.AsyncBaseTransport:
    """Return an HTTP transport that blocks SSRF and DNS rebinding.

    Transport-level counterpart to :func:`make_safe_client`, for libraries
    (e.g. Authlib) that build their own ``httpx`` client but accept a
    transport via kwargs.
    """
    return _SSRFGuardTransport()


def make_safe_client(
    timeout: float | httpx.Timeout = PROBE_TIMEOUT,
    credential_header: str | None = None,
) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient with SSRF IP-pinning and per-hop revalidation.

    SEC-S04: use this factory instead of `httpx.AsyncClient(
    follow_redirects=True, ...)` for any handler that fetches user-supplied
    URLs. SEC-008: uses `_SSRFGuardTransport`, which re-resolves, validates,
    and pins at connect time, so a DNS-rebinding answer after submission-time
    validation can't reach an internal IP; `_revalidate_redirect` re-validates
    each 3xx Location and the transport re-pins each hop.

    fix(#1746): pass ``credential_header`` when the request carries a
    service-chosen credential name, so a 302 can't carry it cross-origin;
    ``X-Esri-Authorization`` is refused on a cross-origin hop whether or not it
    was declared. A caller passing nothing gets today's behaviour.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
        event_hooks={"response": [_redirect_hook(credential_header)]},
        transport=make_safe_transport(),
    )

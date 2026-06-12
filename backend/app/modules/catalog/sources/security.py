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


# SEC-013: additional ranges that Python's ipaddress module does NOT flag via
# the standard is_private / is_reserved predicates but must be blocked for SSRF.
#
# RFC 6598 CGNAT shared address space — 100.64.0.0/10
#   ip.is_private returns False for this range in Python ≤ 3.10; Python 3.11+
#   includes it via the updated RFC 1918 list, but we guard explicitly so the
#   check is correct regardless of Python version.
# IPv6 ULA — fc00::/7
#   ip.is_private includes this on Python 3.11+ but not all older builds.
# NAT64 well-known prefix — 64:ff9b::/96
#   Used to embed IPv4 addresses in IPv6 (RFC 6146); targets an IPv4 private IP
#   when the embedded address is in a blocked range.
_EXTRA_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 CGNAT
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
)


def _is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Check if an IP address falls within a blocked range."""
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

    SEC-008: returns the exact address the connection should use so the caller
    can PIN it — eliminating the gap between validation-time DNS and connect-time
    DNS. Raises SSRFError if resolution fails or ANY resolved address is blocked
    (matching validate_url_for_ssrf's conservative semantics).
    """
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise SSRFError(f"Could not resolve hostname: {host}")
    if not results:
        raise SSRFError(f"Could not resolve hostname: {host}")
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

    # Resolve hostname to IP(s) before making any request
    # Use asyncio.to_thread to avoid blocking the event loop on slow DNS
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo, hostname, parsed.port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise SSRFError(f"Could not resolve hostname: {hostname}")

    if not results:
        raise SSRFError(f"Could not resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError("URLs targeting private/internal networks are not allowed")


async def _revalidate_redirect(response: httpx.Response) -> None:
    """httpx response hook: re-validate the Location target on every redirect hop.

    Phase 1061 SEC-S04: httpx follow_redirects=True silently retargets to
    attacker-controlled internal IPs (169.254.169.254 / 127.x / 10.x) when the
    first hop returns 302. validate_url_for_ssrf is called at submission time
    but not per-hop. This hook closes the gap.

    Raising SSRFError from a response hook aborts further redirect-following
    and propagates the exception to the awaiting caller.
    """
    # HYG-03 (Phase 1070, v1014 IN-01): include HTTP 305 (Use Proxy) for
    # completeness even though RFC 7231 deprecated it and httpx does not
    # follow 305 redirects by default. Cheap defense-in-depth.
    if response.status_code not in (301, 302, 303, 305, 307, 308):
        return
    location = response.headers.get("Location")
    if not location:
        return
    # Resolve relative redirects against the original response URL.
    target = str(httpx.URL(response.url).join(location))
    await validate_url_for_ssrf(target)


class _SSRFGuardTransport(httpx.AsyncHTTPTransport):
    """Transport that re-resolves, re-validates, and PINS the IP at connect time.

    SEC-008: validate_url_for_ssrf resolves DNS once at submission time, but the
    client performs its OWN DNS lookup when it actually connects. A low-TTL
    attacker domain can answer with a public IP at validation and a private IP
    (169.254.169.254 / 127.x / 10.x) at connect — DNS rebinding. This transport
    resolves + validates immediately before connecting and pins the connection
    to the exact validated IP by rewriting the URL host to that IP while keeping
    the original hostname for the Host header and TLS SNI/verification. httpx
    builds a fresh request per redirect hop, so every hop is independently
    re-resolved, re-validated, and re-pinned.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        validated_ip = await _resolve_and_validate(host, request.url.port)
        # Pin to the validated address. The Host header was already set from the
        # original URL at request-build time (left intact); sni_hostname keeps
        # the hostname for TLS SNI and certificate verification.
        request.url = request.url.copy_with(host=validated_ip)
        request.extensions["sni_hostname"] = host
        return await super().handle_async_request(request)


def make_safe_client(
    timeout: float | httpx.Timeout = PROBE_TIMEOUT,
) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient with SSRF IP-pinning and per-hop revalidation.

    Phase 1061 SEC-S04: use this factory instead of `httpx.AsyncClient(
    follow_redirects=True, ...)` for any request handler that fetches
    user-supplied URLs (service probes, STAC adapters, OGC API adapters).

    SEC-008: the client uses _SSRFGuardTransport, which re-resolves and validates
    the host at connect time and pins the connection to the validated IP — so a
    DNS-rebinding answer between submission-time validation and connect cannot
    reach an internal IP. The response hook _revalidate_redirect additionally
    re-validates each 3xx Location, and the transport re-pins each redirect hop.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
        event_hooks={"response": [_revalidate_redirect]},
        transport=_SSRFGuardTransport(),
    )

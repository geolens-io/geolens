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


def _is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Check if an IP address falls within a blocked range."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


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
    if response.status_code not in (301, 302, 303, 307, 308):
        return
    location = response.headers.get("Location")
    if not location:
        return
    # Resolve relative redirects against the original response URL.
    target = str(httpx.URL(response.url).join(location))
    await validate_url_for_ssrf(target)


def make_safe_client(
    timeout: float | httpx.Timeout = PROBE_TIMEOUT,
) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient with per-hop SSRF revalidation.

    Phase 1061 SEC-S04: use this factory instead of `httpx.AsyncClient(
    follow_redirects=True, ...)` for any request handler that fetches
    user-supplied URLs (service probes, STAC adapters, OGC API adapters).

    The response hook _revalidate_redirect intercepts every 3xx hop and
    re-validates the Location against validate_url_for_ssrf — the same gate
    that runs at submission time.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
        event_hooks={"response": [_revalidate_redirect]},
    )

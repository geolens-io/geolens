"""SSRF validation, URL scheme checking, and IP resolution blocking."""

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


def validate_url_for_ssrf(url: str) -> None:
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
    try:
        results = socket.getaddrinfo(hostname, parsed.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise SSRFError(f"Could not resolve hostname: {hostname}")

    if not results:
        raise SSRFError(f"Could not resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError("URLs targeting private/internal networks are not allowed")

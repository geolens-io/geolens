"""Regression tests for SEC-013: SSRF blocklist missing CGNAT 100.64.0.0/10.

The existing _is_blocked_ip() check relies on ip.is_private etc., but CGNAT
addresses (100.64.0.0/10) are NOT flagged by Python's ipaddress as private —
they are "shared address space" per RFC 6598. This test confirms they are
blocked after the fix.

Also covers IPv6 ULA (fc00::/7) and NAT64 (64:ff9b::/96) additions.

Test pattern: RED before fix (100.64.x.x allowed), GREEN after fix (blocked).
"""

import socket

import httpx
import pytest

from app.modules.catalog.sources import security as sec


pytestmark = pytest.mark.anyio


def _addrinfo(ip: str, port: int | None = None):
    """Minimal getaddrinfo return for one address."""
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))]


# ---------------------------------------------------------------------------
# SEC-013: CGNAT range 100.64.0.0/10 must be blocked
# ---------------------------------------------------------------------------


async def test_cgnat_lower_bound_blocked(monkeypatch):
    """100.64.0.1 (bottom of CGNAT range) must be rejected.

    FAILS before fix: ip.is_private is False for CGNAT addresses.
    PASSES after fix: explicit check for 100.64.0.0/10.
    """
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("100.64.0.1", p)
    )
    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://cgnat.attacker.test/steal")
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await transport.handle_async_request(req)


async def test_cgnat_upper_bound_blocked(monkeypatch):
    """100.127.255.254 (top of CGNAT range) must be rejected."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("100.127.255.254", p)
    )
    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://cgnat.attacker.test/steal")
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await transport.handle_async_request(req)


async def test_cgnat_midrange_blocked(monkeypatch):
    """100.96.1.1 (mid CGNAT) must be rejected."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("100.96.1.1", p)
    )
    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://cgnat.attacker.test/steal")
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await transport.handle_async_request(req)


async def test_cgnat_via_validate_url_for_ssrf(monkeypatch):
    """validate_url_for_ssrf (submit-time check) also rejects CGNAT."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("100.64.0.1", p)
    )
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await sec.validate_url_for_ssrf("http://cgnat.attacker.test/steal")


# ---------------------------------------------------------------------------
# SEC-013: address just outside CGNAT (100.128.0.0) must NOT be blocked
# ---------------------------------------------------------------------------


async def test_address_just_above_cgnat_allowed(monkeypatch):
    """100.128.0.0 is outside the CGNAT range and should be allowed.

    This guards against over-blocking (blocking all of 100.x.x.x).
    """
    captured: dict = {}

    async def _fake_super(self, request):
        captured["host"] = request.url.host
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("100.128.0.0", p)
    )

    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://ok.example.test/data")
    resp = await transport.handle_async_request(req)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SEC-013: public IP still allowed (regression guard)
# ---------------------------------------------------------------------------


async def test_public_ip_still_allowed(monkeypatch):
    """93.184.216.34 (example.com) must NOT be blocked after CGNAT fix."""
    captured: dict = {}

    async def _fake_super(self, request):
        captured["host"] = request.url.host
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("93.184.216.34", p)
    )

    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "https://example.com/data")
    resp = await transport.handle_async_request(req)
    assert resp.status_code == 200
    assert captured["host"] == "93.184.216.34"


# ---------------------------------------------------------------------------
# SEC-013: IPv6 ULA fc00::/7 blocked (if added)
# ---------------------------------------------------------------------------


async def test_ipv6_ula_blocked(monkeypatch):
    """fc00::1 (IPv6 ULA) must be rejected."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("fc00::1", p)
    )
    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://ula.attacker.test/steal")
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await transport.handle_async_request(req)


async def test_ipv6_ula_fd_prefix_blocked(monkeypatch):
    """fd00::1 (also within fc00::/7 ULA range) must be rejected."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("fd00::1", p)
    )
    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://ula.attacker.test/steal")
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await transport.handle_async_request(req)


# ---------------------------------------------------------------------------
# SEC-013: NAT64 64:ff9b::/96 blocked (if added)
# ---------------------------------------------------------------------------


async def test_nat64_blocked(monkeypatch):
    """64:ff9b::192.0.2.1 (NAT64) must be rejected."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("64:ff9b::c000:201", p)
    )
    transport = sec._SSRFGuardTransport()
    req = httpx.Request("GET", "http://nat64.attacker.test/steal")
    with pytest.raises(sec.SSRFError, match="private/internal"):
        await transport.handle_async_request(req)

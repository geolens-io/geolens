"""Regression tests for SSRF DNS-rebinding via resolve-then-fetch.

validate_url_for_ssrf resolved DNS once at submission time, but make_safe_client
returned a plain client that performed its OWN DNS lookup at connect time. A
low-TTL attacker domain could answer with a public IP at validation and a
private IP (169.254.169.254 / 127.x / 10.x) at connect. make_safe_client now
uses _SSRFGuardTransport, which re-resolves + re-validates + pins the validated
IP at the moment of connection.

These tests drive the transport directly with a mocked socket.getaddrinfo, so no
real network is touched. Each runs against the httpx guard and the httpx2 guard
that authlib's OAuth client dials through.
"""

import socket

import httpx
import httpx2
import pytest

from app.platform import security as sec

_GUARDS = pytest.mark.parametrize(
    ("guard", "http"),
    [
        pytest.param(sec._SSRFGuardTransport, httpx, id="httpx"),
        pytest.param(sec._SSRFGuardTransportHttpx2, httpx2, id="httpx2"),
    ],
)


def _addrinfo(ip: str, port: int | None):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))]


@pytest.mark.anyio
@_GUARDS
async def test_transport_blocks_private_resolved_ip(monkeypatch, guard, http):
    """A host that resolves to a private IP at connect time is blocked by the
    transport (the connection is never made). Fails on main — make_safe_client
    had no transport guard, so the client would connect to the private IP."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("169.254.169.254", p)
    )
    transport = guard()
    req = http.Request("GET", "http://rebind.attacker.test/data")
    with pytest.raises(sec.SSRFError):
        await transport.handle_async_request(req)


@pytest.mark.anyio
@_GUARDS
async def test_transport_pins_validated_public_ip(monkeypatch, guard, http):
    """A valid public host is pinned: the connection target becomes the resolved
    IP while the Host header and TLS SNI keep the original hostname."""
    captured: dict = {}

    async def _fake_super(self, request):
        captured["host"] = request.url.host
        captured["sni"] = request.extensions.get("sni_hostname")
        captured["host_header"] = request.headers.get("host")
        return http.Response(200)

    monkeypatch.setattr(http.AsyncHTTPTransport, "handle_async_request", _fake_super)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("93.184.216.34", p)
    )

    transport = guard()
    req = http.Request("GET", "https://example.com/x")
    resp = await transport.handle_async_request(req)

    assert resp.status_code == 200
    assert captured["host"] == "93.184.216.34", "connection must be pinned to the IP"
    assert captured["sni"] == "example.com", "TLS SNI must keep the hostname"
    assert captured["host_header"] == "example.com", (
        "Host header must keep the hostname"
    )


@pytest.mark.anyio
@_GUARDS
async def test_dns_rebinding_blocked_at_connect(monkeypatch, guard, http):
    """End-to-end TOCTOU: validation resolves a public IP and passes, but the
    connect-time resolution returns a private IP — the transport blocks it.
    Fails on main (no connect-time re-validation)."""
    calls = {"n": 0}

    def _rebinding(host, port, *a, **k):
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "169.254.169.254"
        return _addrinfo(ip, port)

    monkeypatch.setattr(socket, "getaddrinfo", _rebinding)

    url = "https://rebind.attacker.test/data"
    # Submission-time validation sees the public answer and passes.
    await sec.validate_url_for_ssrf(url)
    # Connect-time resolution returns the rebind target -> transport blocks.
    transport = guard()
    req = http.Request("GET", url)
    with pytest.raises(sec.SSRFError):
        await transport.handle_async_request(req)
    assert calls["n"] == 2, "expected one validation lookup + one connect-time lookup"


@pytest.mark.anyio
async def test_the_oauth_client_dials_the_pinned_ip(monkeypatch):
    """The OAuth login client connects through the guard, not around it."""
    from app.modules.auth.oauth.router import _SSRFSafeOAuth2Client

    connected: list[tuple[str, str | None]] = []

    async def _fake_super(self, request):
        connected.append((request.url.host, request.extensions.get("sni_hostname")))
        return httpx2.Response(200, json={})

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", _fake_super)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda h, p, *a, **k: _addrinfo("93.184.216.34", p)
    )

    async with _SSRFSafeOAuth2Client(client_id="client") as client:
        response = await client.request(
            "GET", "https://idp.example.com/userinfo", withhold_token=True
        )

    assert connected == [("93.184.216.34", "idp.example.com")]
    assert response.url.host == "idp.example.com"

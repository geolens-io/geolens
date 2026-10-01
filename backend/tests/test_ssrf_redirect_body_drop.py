"""The SSRF transport drops a redirect's body, so no client reads one.

With ``follow_redirects`` on, httpx reads each redirect's body in full, and
decompresses it, before following the Location, ahead of any limit a caller
puts on the response it wants. The guard transport closes a redirect's
upstream stream unread and hands back an empty body, which covers every
client built on it.

These tests run the real ``_SSRFGuardTransport``, with only DNS and the httpx
transport underneath it replaced, so the pinning, the per-hop validation hook
and httpx's own redirect handling are all the production code.
"""

import gzip
import json
import socket

import httpx
import pytest

from app.platform.security import SSRFError, make_safe_client, make_safe_transport
from app.platform.service_endpoints import fetch_document

pytestmark = pytest.mark.anyio

PUBLIC_IP = "93.184.216.34"
METADATA_IP = "169.254.169.254"
PAST_THE_CAP = 33 * 1024 * 1024
FINAL = {"ok": True}


class _Body:
    """A streamed response body that counts the chunks the client pulled."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read = 0

    async def __call__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def _redirect(
    status: int, location: str, body: _Body | None = None, **headers: str
) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Location": location, **headers},
        content=body() if body else None,
    )


def _final(**headers: str) -> httpx.Response:
    async def chunks():
        yield json.dumps(FINAL).encode()

    return httpx.Response(200, headers=headers, content=chunks())


class _Upstream:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.connected: list[tuple[str, object]] = []
        self.handler = None

    def serve(self, handler) -> None:
        self.handler = handler


@pytest.fixture
def upstream(monkeypatch) -> _Upstream:
    """Fake DNS and the transport under the guard, recording what reaches it.

    ``blocked.test`` resolves to the metadata address and every other host to
    a public one, so the real validators run without touching the network.
    """
    state = _Upstream()

    def getaddrinfo(host, port, *args, **kwargs):
        ip = METADATA_IP if host == "blocked.test" else PUBLIC_IP
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        state.connected.append(
            (request.url.host, request.extensions.get("sni_hostname"))
        )
        return state.handler(request)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return state


_BODIES = [
    pytest.param([b"a" * 65536] * (PAST_THE_CAP // 65536), {}, id="past-the-cap"),
    pytest.param(
        [gzip.compress(b"0" * PAST_THE_CAP)],
        {"Content-Encoding": "gzip"},
        id="gzip-expands-past-the-cap",
    ),
]


def _redirect_then_final(upstream, redirect_body, headers) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(307, "/final", redirect_body, **headers)
        return _final()

    upstream.serve(handler)


@pytest.mark.parametrize(("chunks", "headers"), _BODIES)
async def test_a_plain_client_never_reads_a_redirect_body(upstream, chunks, headers):
    body = _Body(chunks)
    _redirect_then_final(upstream, body, headers)

    async with make_safe_client() as client:
        response = await client.get("https://catalog.test/start")

    assert response.json() == FINAL
    assert body.read == 0
    assert [r.status_code for r in response.history] == [307]
    assert response.history[0].content == b""
    assert response.url.path == "/final"


@pytest.mark.parametrize(("chunks", "headers"), _BODIES)
async def test_fetch_document_never_reads_a_redirect_body(upstream, chunks, headers):
    body = _Body(chunks)
    _redirect_then_final(upstream, body, headers)

    async with make_safe_client() as client:
        document, final_url = await fetch_document(
            client, "https://catalog.test/start", {}, accept="application/json"
        )

    assert json.loads(document) == FINAL
    assert final_url == "https://catalog.test/final"
    assert body.read == 0


async def test_a_client_built_on_the_bare_transport_follows_without_reading(upstream):
    body = _Body([b"a" * 65536] * 8)
    _redirect_then_final(upstream, body, {})

    async with httpx.AsyncClient(
        transport=make_safe_transport(), follow_redirects=True
    ) as client:
        response = await client.get("https://catalog.test/start")

    assert response.json() == FINAL
    assert body.read == 0


async def test_the_oauth_client_sees_the_redirect_itself_with_no_body(upstream):
    from app.modules.auth.oauth.router import _SSRFSafeOAuth2Client

    body = _Body([b"a" * 65536] * 8)
    _redirect_then_final(upstream, body, {})

    async with _SSRFSafeOAuth2Client(client_id="client") as client:
        response = await client.request(
            "GET", "https://idp.test/start", withhold_token=True
        )

    assert response.status_code == 307
    assert response.headers["Location"] == "/final"
    assert response.content == b""
    assert body.read == 0
    assert len(upstream.requests) == 1


async def test_ordinary_redirects_still_land_on_the_final_response(upstream):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(301, "/middle")
        if request.url.path == "/middle":
            return _redirect(302, "https://catalog.test/final")
        return _final()

    upstream.serve(handler)

    async with make_safe_client() as client:
        response = await client.get("https://catalog.test/start")

    assert response.status_code == 200
    assert response.json() == FINAL
    assert str(response.url) == "https://catalog.test/final"
    assert [r.status_code for r in response.history] == [301, 302]


async def test_a_redirect_keeps_its_status_and_location_but_not_its_body_headers(
    upstream,
):
    upstream.serve(
        lambda request: _redirect(
            302,
            "/final",
            _Body([b"gone"]),
            **{
                "Content-Length": "4",
                "Content-Encoding": "gzip",
                "Set-Cookie": "session=abc; Path=/",
            },
        )
    )

    async with make_safe_client() as client:
        response = await client.get(
            "https://catalog.test/start", follow_redirects=False
        )

    assert response.status_code == 302
    assert response.headers["Location"] == "/final"
    assert response.headers["Set-Cookie"] == "session=abc; Path=/"
    assert "Content-Length" not in response.headers
    assert "Content-Encoding" not in response.headers
    assert response.content == b""


@pytest.mark.parametrize("status", [200, 404, 500])
async def test_a_response_that_is_not_a_redirect_keeps_its_body(upstream, status):
    async def chunks():
        yield b"kept"

    upstream.serve(lambda request: httpx.Response(status, content=chunks()))

    async with make_safe_client() as client:
        response = await client.get("https://catalog.test/start")

    assert response.content == b"kept"


async def test_a_3xx_without_a_location_keeps_its_body(upstream):
    async def chunks():
        yield b"choices"

    upstream.serve(lambda request: httpx.Response(300, content=chunks()))

    async with make_safe_client() as client:
        response = await client.get("https://catalog.test/start")

    assert response.status_code == 300
    assert response.content == b"choices"


async def test_every_hop_is_still_pinned_to_its_validated_address(upstream):
    _redirect_then_final(upstream, None, {})

    async with make_safe_client() as client:
        await client.get("https://catalog.test/start")

    assert upstream.connected == [("93.184.216.34", "catalog.test")] * 2


async def test_a_redirect_to_a_blocked_address_is_refused_unrequested(upstream):
    body = _Body([b"a" * 65536] * 8)
    upstream.serve(lambda request: _redirect(302, "http://blocked.test/x", body))

    async with make_safe_client() as client:
        with pytest.raises(SSRFError):
            await client.get("https://catalog.test/start")

    assert len(upstream.requests) == 1
    assert body.read == 0


async def test_a_cross_origin_hop_drops_authorization(upstream):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(302, "https://elsewhere.test/final")
        return _final()

    upstream.serve(handler)

    async with make_safe_client() as client:
        await client.get(
            "https://catalog.test/start", headers={"Authorization": "Bearer abc"}
        )

    first, second = upstream.requests
    assert first.headers["Authorization"] == "Bearer abc"
    assert "Authorization" not in second.headers


async def test_a_cross_origin_hop_refuses_a_named_credential_header(upstream):
    upstream.serve(lambda request: _redirect(302, "https://elsewhere.test/final"))

    async with make_safe_client(credential_header="X-Api-Key") as client:
        with pytest.raises(SSRFError):
            await client.get("https://catalog.test/start", headers={"X-Api-Key": "abc"})

    assert len(upstream.requests) == 1

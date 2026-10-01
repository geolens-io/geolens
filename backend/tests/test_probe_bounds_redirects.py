"""A probe's bounded read follows redirects without reading their bodies.

httpx reads a redirect response's body in full, decoded, before it follows the
redirect, which would let a provider spend memory the byte cap never sees.
The helper follows redirects itself, so these tests pin both halves: a
redirect body is never read, and every hop still gets the safe client's
checks.
"""

import gzip
from collections.abc import Callable

import httpx
import pytest

from app.platform import probe_bounds, security
from app.platform.security import SSRFError

pytestmark = pytest.mark.anyio

_JSON = "application/json"
_DOCUMENT = b'{"ok": true}'


class _Body:
    """A streamed response body that counts the chunks the client pulled."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read = 0

    async def __call__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def _response(status: int, body: bytes = _DOCUMENT, **headers: str) -> httpx.Response:
    async def chunks():
        yield body

    return httpx.Response(status, headers=headers, content=chunks())


def _redirect(
    status: int, location: str, body: _Body | None = None, **headers: str
) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Location": location, **headers},
        content=body() if body else None,
    )


@pytest.fixture
def safe_client(monkeypatch):
    """Build a ``make_safe_client`` over a mock transport, recording requests.

    Only the address check is relaxed, and only for ``.test`` hosts, which do
    not resolve; anything else still goes through the real validator, so a
    redirect to an internal address is refused for real.
    """
    requests: list[httpx.Request] = []
    real_validate = security.validate_url_for_ssrf

    async def validate(url: str) -> None:
        if httpx.URL(url).host.endswith(".test"):
            return
        await real_validate(url)

    monkeypatch.setattr(security, "validate_url_for_ssrf", validate)

    def build(
        handler: Callable[[httpx.Request], httpx.Response],
        *,
        credential_header: str | None = None,
    ) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        return security.make_safe_client(credential_header=credential_header)

    build.requests = requests
    return build


async def _read(client: httpx.AsyncClient, url: str, **kwargs):
    async with client:
        return await probe_bounds.bounded_probe_exchange(
            client, "GET", url, accept=_JSON, **{"headers": {}, **kwargs}
        )


def _gzip_past_the_cap() -> bytes:
    return gzip.compress(b"0" * (probe_bounds.MAX_DOCUMENT_BYTES + 1))


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        pytest.param(
            [b"a" * 65536] * (probe_bounds.MAX_DOCUMENT_BYTES // 65536 + 1),
            {},
            id="past-the-cap",
        ),
        pytest.param(
            [_gzip_past_the_cap()],
            {"Content-Encoding": "gzip"},
            id="gzip-expands-past-the-cap",
        ),
    ],
)
async def test_a_redirect_body_is_never_read(safe_client, body, headers):
    redirect_body = _Body(body)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(307, "/final", redirect_body, **headers)
        return _response(200)

    client = safe_client(handler)
    document, response = await _read(client, "https://catalog.test/start")

    assert document == _DOCUMENT
    assert redirect_body.read == 0
    assert [r.url.path for r in safe_client.requests] == ["/start", "/final"]
    assert response.url.path == "/final"
    assert [r.status_code for r in response.history] == [307]


async def test_the_hop_limit_is_the_clients(safe_client):
    client = safe_client(lambda request: _redirect(302, "/again"))

    with pytest.raises(httpx.TooManyRedirects):
        await _read(client, "https://catalog.test/again")

    assert client.max_redirects == 5
    assert len(safe_client.requests) == client.max_redirects + 1


async def test_a_redirect_to_a_blocked_address_is_refused_unrequested(safe_client):
    client = safe_client(
        lambda request: _redirect(302, "http://169.254.169.254/latest/meta-data")
    )

    with pytest.raises(SSRFError):
        await _read(client, "https://catalog.test/start")

    assert len(safe_client.requests) == 1


async def test_a_cross_origin_hop_drops_authorization(safe_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "catalog.test":
            return _redirect(302, "https://elsewhere.test/final")
        return _response(200)

    client = safe_client(handler)
    await _read(
        client,
        "https://catalog.test/start",
        headers={"Authorization": "Bearer abc"},
    )

    first, second = safe_client.requests
    assert first.headers["Authorization"] == "Bearer abc"
    assert "Authorization" not in second.headers


async def test_a_same_origin_hop_keeps_authorization(safe_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(302, "/final")
        return _response(200)

    client = safe_client(handler)
    await _read(
        client,
        "https://catalog.test/start",
        headers={"Authorization": "Bearer abc"},
    )

    assert [r.headers.get("Authorization") for r in safe_client.requests] == [
        "Bearer abc",
        "Bearer abc",
    ]


async def test_a_cross_origin_hop_refuses_a_named_credential_header(safe_client):
    client = safe_client(
        lambda request: _redirect(302, "https://elsewhere.test/final"),
        credential_header="X-Api-Key",
    )

    with pytest.raises(SSRFError):
        await _read(
            client,
            "https://catalog.test/start",
            headers={"X-Api-Key": "abc"},
        )

    assert len(safe_client.requests) == 1


async def test_a_refusal_after_a_redirect_still_carries_its_history(safe_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(302, "/final")
        return _response(401)

    client = safe_client(handler)

    with pytest.raises(httpx.HTTPStatusError) as refusal:
        await _read(client, "https://catalog.test/start")

    assert len(refusal.value.response.history) == 1
    assert refusal.value.response.url.path == "/final"


async def test_a_redirected_post_keeps_its_json_body(safe_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return _redirect(307, "/final")
        return _response(200)

    client = safe_client(handler)
    async with client:
        await probe_bounds.bounded_probe_exchange(
            client,
            "POST",
            "https://catalog.test/start",
            headers={},
            accept=_JSON,
            json_body={"limit": 3},
        )

    assert [(r.method, r.url.path) for r in safe_client.requests] == [
        ("POST", "/start"),
        ("POST", "/final"),
    ]
    assert safe_client.requests[1].content == safe_client.requests[0].content

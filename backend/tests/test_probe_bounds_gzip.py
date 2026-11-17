"""A probe's bounded read inflates gzip under the same byte cap.

ArcGIS Online answers a repeated identity request with a zero-byte HTTP 200,
so a probe that forces identity reads an empty layer or a failed probe. The
shared probe reader asks for gzip and inflates it through
`read_bounded_body`, which caps the wire bytes and the decoded bytes under
`MAX_DOCUMENT_BYTES`, so a compressed body still can't be used as a bomb.
Any other encoding is refused.
"""

import gzip
from collections.abc import Callable

import httpx
import pytest

from app.platform import probe_bounds, security
from app.platform.service_endpoints import EndpointCheckFailedError

pytestmark = pytest.mark.anyio

_JSON = "application/json"
_XML = "application/xml, text/xml"
_DOCUMENT = b'{"ok": true}'
_CAPABILITIES = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b"<WFS_Capabilities><OperationsMetadata /></WFS_Capabilities>"
)


class _Body:
    """A streamed response body that counts the chunks the client pulled."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read = 0

    async def __call__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


@pytest.fixture
def safe_client(monkeypatch):
    """Build a ``make_safe_client`` over a mock transport, recording requests.

    Only the address check is relaxed, and only for ``.test`` hosts, which do
    not resolve; anything else still goes through the real validator.
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
    ) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            security, "make_safe_transport", lambda: httpx.MockTransport(handle)
        )
        return security.make_safe_client()

    build.requests = requests
    return build


async def _read(client: httpx.AsyncClient, url: str, accept: str = _JSON):
    async with client:
        return await probe_bounds.bounded_probe_exchange(
            client, "GET", url, headers={}, accept=accept
        )


def _streamed(status: int, body: bytes, **headers: str) -> httpx.Response:
    """A response whose body streams, as a real origin delivers it.

    A ``content=<bytes>`` response is already consumed by the time
    `client.send(stream=True)` returns it, so `aiter_raw` raises
    `StreamConsumed` on it; a streamed body is what the reader under test
    actually reads.
    """

    async def _chunks():
        yield body

    return httpx.Response(status, headers=headers, content=_chunks())


async def test_a_gzip_body_is_inflated_under_the_cap(safe_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(200, gzip.compress(_DOCUMENT), **{"Content-Encoding": "gzip"})

    client = safe_client(handler)
    document, _response = await _read(client, "https://catalog.test/doc")

    assert document == _DOCUMENT
    assert safe_client.requests[0].headers["Accept-Encoding"] == "gzip"


async def test_an_identity_body_still_reads(safe_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(200, _DOCUMENT)

    client = safe_client(handler)
    document, _response = await _read(client, "https://catalog.test/doc")

    assert document == _DOCUMENT


async def test_a_gzip_bomb_is_refused_before_it_fully_inflates(
    safe_client,
) -> None:
    """The read stops pulling wire bytes once the decoded cap trips, instead
    of draining the stream."""
    bomb = gzip.compress(b"0" * (probe_bounds.MAX_DOCUMENT_BYTES + 1))
    chunks = [bomb[start : start + 64] for start in range(0, len(bomb), 64)]
    chunks.append(b"trailing junk the reader never asks for")
    body = _Body(chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=body())

    client = safe_client(handler)

    with pytest.raises(EndpointCheckFailedError):
        await _read(client, "https://catalog.test/doc")

    assert body.read < len(chunks)


async def test_a_repeat_identity_request_with_an_empty_200_reads_the_capabilities(
    safe_client,
) -> None:
    """ArcGIS Online answers a repeated identity request with an empty 200
    and a gzip request with the document, so the probe asks for gzip."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "gzip" in request.headers.get("Accept-Encoding", ""):
            return _streamed(
                200, gzip.compress(_CAPABILITIES), **{"Content-Encoding": "gzip"}
            )
        return _streamed(200, b"")

    client = safe_client(handler)
    document, _response = await _read(client, "https://catalog.test/wfs", accept=_XML)

    assert document == _CAPABILITIES


@pytest.mark.parametrize("encoding", ["br", "deflate", "zstd"])
async def test_any_other_encoding_is_still_refused(safe_client, encoding) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(200, _DOCUMENT, **{"Content-Encoding": encoding})

    client = safe_client(handler)

    with pytest.raises(EndpointCheckFailedError):
        await _read(client, "https://catalog.test/doc")


async def test_a_truncated_gzip_body_is_refused(safe_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(
            200, gzip.compress(_DOCUMENT)[:-6], **{"Content-Encoding": "gzip"}
        )

    client = safe_client(handler)

    with pytest.raises(EndpointCheckFailedError):
        await _read(client, "https://catalog.test/doc")

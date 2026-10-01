"""STAC collection browsing and item search read the provider under bounds.

A catalog is third-party. Whatever it answers with is capped in bytes, in
decoded size, in how long the whole read may take, and in how many collections
or items are processed, and a refusal reaches the caller as the same 502 any
other provider failure does.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.catalog.sources import stac_router
from app.modules.catalog.sources.adapters import stac as stac_adapter
from app.platform import probe_bounds
from app.platform.service_endpoints import EndpointCheckFailedError

pytestmark = pytest.mark.anyio

_ROOT = "https://catalog.test/v1"
_BYTE_CAP = 1024
_OPERATIONS = ["collections", "search"]


@pytest.fixture
def serve(monkeypatch):
    """Answer every adapter read from *body*, an async generator function.

    Returns the list of requests the adapter made. The body is streamed, as a
    real provider's is, because the bounded read refuses a response that was
    built from an in-memory body.
    """

    def install(body) -> list[httpx.Request]:
        requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=body())

        monkeypatch.setattr(
            stac_adapter,
            "_make_client",
            lambda _credential_header=None: httpx.AsyncClient(
                transport=httpx.MockTransport(handle)
            ),
        )
        return requests

    return install


def _document(payload: dict):
    raw = json.dumps(payload).encode()

    async def body():
        yield raw

    return body


async def _browse(operation: str):
    if operation == "collections":
        return await stac_adapter.list_stac_collections(_ROOT)
    return await stac_adapter.search_stac_items(_ROOT, limit=5)


def _item(n: int) -> dict:
    return {"id": f"item-{n}", "properties": {}, "assets": {}, "links": []}


class _Padded:
    """A valid, empty STAC document followed by a long run of padding."""

    def __init__(self, *, chunks: int, pause: float = 0.0) -> None:
        self.chunks = chunks
        self.pause = pause
        self.sent = 0

    async def __call__(self):
        yield b'{"collections": [], "features": [], "pad": "'
        for _ in range(self.chunks):
            self.sent += 1
            if self.pause:
                await asyncio.sleep(self.pause)
            yield b"a" * 512
        yield b'"}'


@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_an_oversized_body_is_refused_without_reading_it_all(
    serve, monkeypatch, operation
):
    monkeypatch.setattr(probe_bounds, "MAX_DOCUMENT_BYTES", _BYTE_CAP)
    padded = _Padded(chunks=200)
    serve(padded)

    with pytest.raises(EndpointCheckFailedError):
        await _browse(operation)

    # Stopped within a chunk or two of the cap, not after all 100 KiB.
    assert padded.sent < 10


@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_a_slow_trickle_hits_the_operation_deadline(
    serve, monkeypatch, operation
):
    monkeypatch.setattr(stac_adapter, "DEFAULT_CHECK_TIMEOUT", 0.3)
    trickle = _Padded(chunks=100, pause=0.1)
    serve(trickle)

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await _browse(operation)

    # The whole stream would have taken ten seconds.
    assert time.monotonic() - started < 3
    assert trickle.sent < 100


async def test_a_server_that_ignores_the_limit_is_cut_to_it(serve):
    requests = serve(
        _document({"features": [_item(n) for n in range(8)], "numberMatched": 8})
    )

    result = await stac_adapter.search_stac_items(_ROOT, limit=3)

    assert json.loads(requests[0].content)["limit"] == 3
    assert [item["id"] for item in result["items"]] == ["item-0", "item-1", "item-2"]
    assert result["returned"] == 3
    assert result["matched"] == 8


async def test_a_collection_listing_is_cut_to_the_cap(serve, monkeypatch):
    monkeypatch.setattr(stac_adapter, "MAX_COLLECTIONS", 2)
    serve(_document({"collections": [{"id": f"c{n}"} for n in range(5)]}))

    result = await stac_adapter.list_stac_collections(_ROOT)

    assert [collection["id"] for collection in result] == ["c0", "c1"]


@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_a_refused_provider_response_is_a_bad_gateway(
    client, admin_auth_header, serve, monkeypatch, operation
):
    monkeypatch.setattr(stac_router, "validate_url_for_ssrf", AsyncMock())
    monkeypatch.setattr(probe_bounds, "MAX_DOCUMENT_BYTES", _BYTE_CAP)
    serve(_Padded(chunks=200))

    response = await client.post(
        f"/services/stac/{operation}",
        json={"url": _ROOT},
        headers=admin_auth_header,
    )

    assert response.status_code == 502

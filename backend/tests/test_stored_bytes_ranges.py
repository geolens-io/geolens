"""Strict range parsing refuses an unusable Range with 416; lenient parsing ignores it."""

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from app.platform.http.ranges import RANGE_UNSATISFIABLE, parse_byte_range
from app.platform.http.stored_bytes import serve_stored_bytes

_SIZE = 1000
_ETAG = '"v1"'
_UNUSABLE = ["bytes=0--1", "bytes=100-99", "bytes=0-1,5-6", "items=0-5", "bytes=abc"]


class _Store:
    """An in-memory object that records every read."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.reads: list[tuple] = []

    async def get_stream(self, key: str):
        self.reads.append(("whole", key))
        yield self.data

    async def get_range_stream(self, key: str, start: int, length: int):
        self.reads.append(("range", key, start, length))
        yield self.data[start : start + length]


def _request(range_header: str | None, method: str = "GET") -> Request:
    headers = [] if range_header is None else [(b"range", range_header.encode())]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/o",
            "headers": headers,
            "query_string": b"",
        }
    )


async def _serve(store: _Store, range_header: str | None, *, strict: bool):
    return await serve_stored_bytes(
        _request(range_header),
        store,
        "objects/o.bin",
        total_bytes=_SIZE,
        media_type="application/octet-stream",
        etag=_ETAG,
        strict=strict,
    )


@pytest.mark.parametrize("raw", _UNUSABLE)
def test_a_strict_parse_refuses_a_range_it_cannot_serve(raw: str) -> None:
    """Malformed, reversed, multi-range and unknown-unit ranges are unsatisfiable when strict."""
    assert parse_byte_range(raw, _SIZE, strict=True) == RANGE_UNSATISFIABLE
    assert parse_byte_range(raw, _SIZE) is None


@pytest.mark.parametrize(
    "raw", ["bytes=0-99", "bytes=10-", "bytes=-5", "Bytes=0-9", "bytes=990-5000"]
)
def test_a_strict_parse_serves_every_usable_range(raw: str) -> None:
    """A single satisfiable range resolves the same way strict or not."""
    strict = parse_byte_range(raw, _SIZE, strict=True)
    assert isinstance(strict, tuple)
    assert strict == parse_byte_range(raw, _SIZE)


@pytest.mark.parametrize("raw", [None, ""])
def test_a_strict_parse_treats_no_range_as_the_whole_object(raw: str | None) -> None:
    """An absent Range still means the whole object when strict."""
    assert parse_byte_range(raw, _SIZE, strict=True) is None


@pytest.mark.parametrize("raw", _UNUSABLE)
async def test_strict_serving_answers_an_unusable_range_with_416(raw: str) -> None:
    """A strict route answers 416 with the size and version, and reads nothing."""
    store = _Store(b"x" * _SIZE)

    with pytest.raises(HTTPException) as refused:
        await _serve(store, raw, strict=True)

    assert refused.value.status_code == 416
    assert refused.value.headers == {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes */{_SIZE}",
        "ETag": _ETAG,
    }
    assert store.reads == []


async def test_lenient_serving_sends_the_whole_object_for_an_unusable_range() -> None:
    """Without strict, a reversed range is ignored and the whole object is served."""
    store = _Store(b"x" * _SIZE)

    response = await _serve(store, "bytes=100-99", strict=False)

    assert isinstance(response, StreamingResponse)
    assert response.status_code == 200
    assert response.headers["content-length"] == str(_SIZE)
    assert [chunk async for chunk in response.body_iterator] == [b"x" * _SIZE]
    assert store.reads == [("whole", "objects/o.bin")]


async def test_strict_serving_still_answers_a_usable_range_with_206() -> None:
    """A strict route reads only the window it was asked for."""
    store = _Store(bytes(range(256)) * 4)

    response = await _serve(store, "bytes=10-19", strict=True)

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 10-19/{_SIZE}"
    assert [chunk async for chunk in response.body_iterator] == [bytes(range(10, 20))]
    assert store.reads == [("range", "objects/o.bin", 10, 10)]

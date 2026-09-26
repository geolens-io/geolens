"""A stored object's first byte is read before the status line, so a changed object is refused rather than truncated."""

import pytest
from starlette.requests import Request

from app.platform.http.stored_bytes import (
    StoredObjectMissing,
    StoredObjectUnreadable,
    serve_stored_bytes,
)

_KEY = "objects/o.bin"


class _Store:
    """One object, which may have shrunk or gone since the route sized it."""

    def __init__(self, data: bytes, *, gone: bool = False) -> None:
        self.data = data
        self.gone = gone

    async def size(self, key: str) -> int:
        if self.gone:
            raise FileNotFoundError(key)
        return len(self.data)

    async def get_stream(self, key: str):
        if self.data:
            yield self.data

    async def get_range_stream(self, key: str, start: int, length: int):
        # As local and S3 storage do, a window past the end yields nothing.
        window = self.data[start : start + length]
        if window:
            yield window


def _request(range_header: str | None) -> Request:
    headers = [] if range_header is None else [(b"range", range_header.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/o",
            "headers": headers,
            "query_string": b"",
        }
    )


async def _serve(store: _Store, range_header: str | None, *, total_bytes: int):
    return await serve_stored_bytes(
        _request(range_header),
        store,
        _KEY,
        total_bytes=total_bytes,
        media_type="application/octet-stream",
        etag='"v1"',
    )


@pytest.mark.parametrize(
    ("store", "range_header", "refusal"),
    [
        (_Store(b"x" * 20), "bytes=50-60", StoredObjectUnreadable),
        (_Store(b""), None, StoredObjectUnreadable),
        (_Store(b"x" * 20, gone=True), "bytes=50-60", StoredObjectMissing),
    ],
    ids=["range-past-a-shrunk-end", "whole-object-emptied", "gone-by-the-probe"],
)
async def test_a_body_with_no_first_byte_is_refused_before_any_header(
    store: _Store, range_header: str | None, refusal: type[Exception]
) -> None:
    """An object sized at 100 bytes that yields none is missing if gone, else unreadable."""
    with pytest.raises(refusal):
        await _serve(store, range_header, total_bytes=100)


async def test_an_empty_object_is_served_empty() -> None:
    """A zero-length object is a legitimate empty body."""
    response = await _serve(_Store(b""), None, total_bytes=0)

    assert response.status_code == 200
    assert response.headers["content-length"] == "0"
    assert [chunk async for chunk in response.body_iterator] == [b""]

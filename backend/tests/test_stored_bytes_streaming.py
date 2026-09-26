"""A stored object's first byte is read before the status line, and its stream is closed however the response ends."""

import asyncio
import contextlib

import pytest
from starlette.requests import ClientDisconnect, Request

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
        self.closed: list[str] = []

    async def size(self, key: str) -> int:
        if self.gone:
            raise FileNotFoundError(key)
        return len(self.data)

    async def get_stream(self, key: str):
        try:
            if self.data:
                yield self.data
        finally:
            self.closed.append(key)

    async def get_range_stream(self, key: str, start: int, length: int):
        try:
            # As local and S3 storage do, a window past the end yields nothing.
            window = self.data[start : start + length]
            if window:
                yield window
        finally:
            self.closed.append(key)


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


@pytest.mark.parametrize("spec_version", ["2.4", "2.3"])
async def test_a_client_gone_before_the_status_line_leaves_no_stream_open(
    spec_version: str,
) -> None:
    """The stream the first read opened is closed though the body never started."""
    store = _Store(b"x" * 100)
    response = await _serve(store, None, total_bytes=100)
    assert store.closed == [], "precondition: the first read leaves the stream open"

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if spec_version == "2.4":
            raise OSError("client went away")
        # Before 2.4 starlette listens for the disconnect and cancels this send.
        await asyncio.sleep(60)

    with contextlib.suppress(ClientDisconnect):
        await response(
            {"type": "http", "asgi": {"spec_version": spec_version}}, receive, send
        )

    assert store.closed == [_KEY]


async def test_a_completed_response_closes_its_stream_once() -> None:
    """A body sent in full closes the storage stream exactly once."""
    store = _Store(bytes(range(100)))
    response = await _serve(store, "bytes=10-19", total_bytes=100)
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)

    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    assert body == bytes(range(10, 20))
    assert store.closed == [_KEY]

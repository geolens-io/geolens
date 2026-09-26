"""Serve a stored object's bytes: HEAD, one byte range, or the whole object.

The caller has already decided access, found the object and its size, and chosen
its entity-tag. What remains is which representation to send, so HEAD and GET
share it.
"""

from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.platform.http.ranges import (
    RANGE_UNSATISFIABLE,
    if_match_passes,
    if_none_match_matches,
    not_modified_response,
    parse_byte_range,
    range_bound_to_this_version,
)
from app.platform.storage.provider import StorageProvider


class StoredObjectMissing(Exception):
    """The object was gone when its first byte was read."""


class StoredObjectUnreadable(Exception):
    """The store failed before the object's first byte was read."""


async def _chained(first: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    yield first
    async for chunk in rest:
        yield chunk


class _StoredBytesResponse(StreamingResponse):
    """Streams a stored object and closes its storage stream however the response ends.

    Starlette never closes a body iterator it has not started, so a client gone
    before the status line would leave the stream the first read opened holding
    a file or connection until garbage collection.
    """

    def __init__(
        self, first: bytes, stream: AsyncIterator[bytes], **kwargs: Any
    ) -> None:
        super().__init__(_chained(first, stream), **kwargs)
        self._stream = stream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._stream.aclose()


async def _opened(
    storage: StorageProvider,
    key: str,
    stream: AsyncIterator[bytes],
    expected: int,
    **response: Any,
) -> Response:
    """The response for ``stream``, with its first chunk already read.

    A read that fails once the status line is sent can only cut the body short,
    so the first one happens while the caller can still answer with a status.
    ``expected`` is the body's length: a non-empty body whose stream ends before
    its first byte means the object changed after it was sized.
    """
    first = b""
    try:
        while not first:
            first = await anext(stream)
    except FileNotFoundError:
        raise StoredObjectMissing from None
    except StopAsyncIteration:
        if expected:
            raise await _missing_or_unreadable(storage, key) from None
    except Exception as exc:  # broad: each store raises its own errors, and the caller maps them to one status
        raise StoredObjectUnreadable from exc
    try:
        return _StoredBytesResponse(first, stream, **response)
    except BaseException:  # broad: cleanup only; the raise below keeps the failure
        await stream.aclose()
        raise


async def _missing_or_unreadable(storage: StorageProvider, key: str) -> Exception:
    """Why an object gave no byte of a body it was sized for: gone, or changed."""
    try:
        await storage.size(key)
    except FileNotFoundError:
        return StoredObjectMissing()
    except Exception:  # broad: a store that fails this probe fails the read too
        return StoredObjectUnreadable()
    return StoredObjectUnreadable()


def evaluate_preconditions(
    request: Request, etag: str | None, *, changed_detail: str
) -> Response | None:
    """Apply ``If-Match`` and ``If-None-Match`` before any byte is served.

    Raises 412, with ``changed_detail`` and the current ETag, when ``If-Match``
    names another version: a resuming client may send it instead of
    ``If-Range``, and RFC 9110 gives it no serve-the-whole-object fallback.
    Returns the 304 when ``If-None-Match`` already holds this one, else None.
    """
    if not if_match_passes(request.headers.get("if-match"), etag):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=changed_detail,
            headers={"ETag": etag} if etag is not None else None,
        )
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return not_modified_response(etag)
    return None


def _representation_headers(
    etag: str | None, headers: Mapping[str, str] | None
) -> dict[str, str]:
    # Advertising ranges without a validator invites a client to splice two
    # versions, so every representation names its version.
    representation = {"Accept-Ranges": "bytes", **(headers or {})}
    if etag is not None:
        representation["ETag"] = etag
    return representation


def head_response(
    total_bytes: int,
    *,
    media_type: str,
    etag: str | None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """The HEAD answer: the real length, no body and no storage read.

    Range clients such as GDAL's /vsicurl/ open with a HEAD, so reading the
    object here would cost a full download on every open. A Range on HEAD is
    ignored, since a 206 would report the range's length as the object's.
    """
    # Explicit, because starlette sends `content-length: 0` for an empty body.
    return Response(
        status_code=status.HTTP_200_OK,
        media_type=media_type,
        headers={
            **_representation_headers(etag, headers),
            "Content-Length": str(total_bytes),
        },
    )


async def serve_stored_bytes(
    request: Request,
    storage: StorageProvider,
    key: str,
    *,
    total_bytes: int,
    media_type: str,
    etag: str | None,
    headers: Mapping[str, str] | None = None,
    strict: bool = False,
) -> Response:
    """Serve ``key`` as HEAD, one byte range, or the whole object.

    ``headers`` are the route's own, such as a Content-Disposition. Each
    representation adds ``Accept-Ranges`` and the ETag; the 416 carries only
    those and the size. ``strict`` answers an unusable Range with 416 instead
    of the whole object.

    Raises ``StoredObjectMissing`` when the object is gone at its first read and
    ``StoredObjectUnreadable`` when the store fails before it or ends a non-empty
    body before its first byte, for the caller to answer as it answers the same
    failure of its stat.
    """
    if request.method == "HEAD":
        return head_response(
            total_bytes, media_type=media_type, etag=etag, headers=headers
        )

    byte_range = parse_byte_range(
        request.headers.get("range"), total_bytes, strict=strict
    )
    if byte_range is not None and not range_bound_to_this_version(
        request.headers.get("if-range"), etag
    ):
        # RFC 9110 section 13.1.5: a range of another version is ignored and the
        # whole current object sent, even when its offsets no longer fit.
        byte_range = None

    if byte_range == RANGE_UNSATISFIABLE:
        # The size is how a client that guessed at the length learns the real
        # one, and the ETag tells it which version that size belongs to. A
        # client told 416 is the one that needs to know it may retry a range.
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="Requested range not satisfiable",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{total_bytes}",
                **({"ETag": etag} if etag is not None else {}),
            },
        )

    representation = _representation_headers(etag, headers)
    if byte_range is not None:
        # One ranged read: no byte outside the window is fetched.
        start, end = byte_range
        return await _opened(
            storage,
            key,
            storage.get_range_stream(key, start, end - start + 1),
            end - start + 1,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media_type,
            headers={
                **representation,
                "Content-Range": f"bytes {start}-{end}/{total_bytes}",
                "Content-Length": str(end - start + 1),
            },
        )
    return await _opened(
        storage,
        key,
        storage.get_stream(key),
        total_bytes,
        media_type=media_type,
        headers={**representation, "Content-Length": str(total_bytes)},
    )

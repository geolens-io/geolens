"""Read a remote raster's bytes the way the relay serves them to Titiler.

Every connection goes through the pinned client, redirect hops included. A
response that holds the file's first bytes must open with a TIFF signature,
so GDAL identifies whatever the relay serves as a GeoTIFF and nothing else.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from enum import Enum
from typing import NamedTuple

import httpx

from app.platform.security import SSRFError, make_safe_client

RELAY_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
# Titiler waits on one read at a time, so a slow origin must not hold it past
# the API's own wait for the tile.
RELAY_DEADLINE_SECONDS = 30.0
MAX_RELAY_RESPONSE_BYTES = 64 * 1024 * 1024
TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
_SIGNATURE_BYTES = 4

_RANGE_RE = re.compile(r"^bytes=(\d{1,19})-(\d{0,19})$")
_CONTENT_RANGE_RE = re.compile(r"^bytes (\d{1,19})-(\d{1,19})/(\d{1,19}|\*)$")

_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


class RemoteRasterRefused(Exception):
    """The relay will not serve this response; ``reason`` is a log-safe code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RemoteRasterFormat(Enum):
    TIFF = "tiff"
    OTHER = "other"
    UNREACHABLE = "unreachable"


def _client() -> httpx.AsyncClient:
    """One pinned client per event loop, so range reads reuse connections."""
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        for stale in [other for other in _clients if other.is_closed()]:
            del _clients[stale]
        client = _clients[loop] = make_safe_client(timeout=RELAY_TIMEOUT)
    return client


class ByteRange(NamedTuple):
    start: int
    end: int | None

    def header(self) -> str:
        return f"bytes={self.start}-{'' if self.end is None else self.end}"


def parse_relay_range(header: str | None) -> ByteRange | None:
    """The single ``bytes=a-b`` or ``bytes=a-`` range to forward, or None.

    Raises RemoteRasterRefused for any other form, a suffix range or several
    ranges included.
    """
    if header is None or not header.strip():
        return None
    match = _RANGE_RE.match(header.strip())
    if match is None:
        raise RemoteRasterRefused("unsupported_range")
    start, end = int(match[1]), int(match[2]) if match[2] else None
    if end is not None:
        if end < start:
            raise RemoteRasterRefused("unsupported_range")
        if end - start + 1 > MAX_RELAY_RESPONSE_BYTES:
            raise RemoteRasterRefused("range_too_large")
    return ByteRange(start, end)


def check_range_response(response: httpx.Response, requested: ByteRange | None) -> int:
    """Check a 200 or 206 against the range that was asked for; return how
    many body bytes may be relayed.

    The origin's own Content-Range is never trusted to say where the body
    starts: a 206 must begin exactly where the request did and end within it,
    and a 200 answers only a read from byte 0.
    """
    start = requested.start if requested else 0
    if response.status_code == 200:
        if start > 0:
            raise RemoteRasterRefused("range_ignored")
        return MAX_RELAY_RESPONSE_BYTES
    if requested is None:
        raise RemoteRasterRefused("range_unrequested")
    match = _CONTENT_RANGE_RE.match(response.headers.get("content-range", ""))
    if match is None:
        raise RemoteRasterRefused("bad_content_range")
    first, last = int(match[1]), int(match[2])
    if first != start or last < first:
        raise RemoteRasterRefused("range_mismatch")
    if requested.end is not None and last > requested.end:
        raise RemoteRasterRefused("range_mismatch")
    return min(last - first + 1, MAX_RELAY_RESPONSE_BYTES)


def _check_identity_encoding(response: httpx.Response) -> None:
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        raise RemoteRasterRefused("encoded_body")


def object_size(response: httpx.Response) -> str | None:
    """The whole object's size in bytes, from a 200 or a 206, if it says."""
    if response.status_code == 200:
        length = response.headers.get("content-length", "")
        return length if length.isdigit() else None
    match = _CONTENT_RANGE_RE.match(response.headers.get("content-range", ""))
    if match is None or match[3] == "*":
        return None
    return match[3]


def check_response_shape(response: httpx.Response, limit: int) -> None:
    """Refuse an encoded body or one longer than ``limit``."""
    _check_identity_encoding(response)
    length = response.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > limit):
        raise RemoteRasterRefused("too_large")


def relay_deadline() -> float:
    """When a relayed response must be complete, on the running loop's clock."""
    return asyncio.get_running_loop().time() + RELAY_DEADLINE_SECONDS


async def _next_chunk(chunks: AsyncIterator[bytes], deadline: float) -> bytes | None:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise RemoteRasterRefused("deadline")
    try:
        return await asyncio.wait_for(anext(chunks), remaining)
    except StopAsyncIteration:
        return None
    except TimeoutError:
        raise RemoteRasterRefused("deadline") from None


async def read_signature(chunks: AsyncIterator[bytes], deadline: float) -> bytes:
    """Read until the TIFF signature can be checked; return what was read.

    Raises RemoteRasterRefused when the bytes are not a TIFF.
    """
    head = b""
    while len(head) < _SIGNATURE_BYTES:
        chunk = await _next_chunk(chunks, deadline)
        if chunk is None:
            break
        head += chunk
    if head[:_SIGNATURE_BYTES] not in TIFF_SIGNATURES:
        raise RemoteRasterRefused("not_tiff")
    return head


async def bounded(
    chunks: AsyncIterator[bytes], already: int, limit: int, deadline: float
) -> AsyncIterator[bytes]:
    """Pass ``chunks`` on, stopping once the body passes ``limit`` bytes or
    the deadline passes, however slowly the origin sends."""
    sent = already
    if sent > limit:
        raise RemoteRasterRefused("too_large")
    while (chunk := await _next_chunk(chunks, deadline)) is not None:
        sent += len(chunk)
        if sent > limit:
            raise RemoteRasterRefused("too_large")
        yield chunk


async def open_remote_raster(
    url: str, *, byte_range: ByteRange | None, deadline: float
) -> httpx.Response:
    """Send one upstream GET and return the streaming response.

    Only ``Range`` is forwarded; no caller header or credential reaches the
    origin. The caller closes the response. Raises SSRFError when a hop is
    refused, httpx.HTTPError when the origin can't be read and
    RemoteRasterRefused when its headers miss the deadline.
    """
    headers = {"Accept-Encoding": "identity"}
    if byte_range is not None:
        headers["Range"] = byte_range.header()
    request = _client().build_request("GET", url, headers=headers)
    remaining = deadline - asyncio.get_running_loop().time()
    try:
        return await asyncio.wait_for(_client().send(request, stream=True), remaining)
    except TimeoutError:
        raise RemoteRasterRefused("deadline") from None


async def remote_raster_format(url: str) -> RemoteRasterFormat:
    """Whether the object at ``url`` opens with a TIFF signature."""
    requested = ByteRange(0, _SIGNATURE_BYTES - 1)
    deadline = relay_deadline()
    try:
        response = await open_remote_raster(
            url, byte_range=requested, deadline=deadline
        )
    except (SSRFError, httpx.HTTPError, RemoteRasterRefused):
        return RemoteRasterFormat.UNREACHABLE
    try:
        if response.status_code not in (200, 206):
            return RemoteRasterFormat.UNREACHABLE
        check_range_response(response, requested)
        _check_identity_encoding(response)
        await read_signature(response.aiter_raw(), deadline)
        return RemoteRasterFormat.TIFF
    except RemoteRasterRefused as exc:
        if exc.reason == "not_tiff":
            return RemoteRasterFormat.OTHER
        return RemoteRasterFormat.UNREACHABLE
    except httpx.HTTPError:
        return RemoteRasterFormat.UNREACHABLE
    finally:
        await response.aclose()

"""Turning a stored export artifact into a 200, a 206 or a 416.

A Range is honoured only when the artifact already existed; otherwise the
whole representation goes back with 200 (RFC 9110 14.2) — a ``/vsicurl/``
client sends no If-Range, so a rebuild can't tell it's a different file,
and only a whole 200 can't splice two representations together.

Exceptions: a rebuild that reproduced the only bytes the URL holds is
sliced like the artifact it replaces; a Range starting at byte 0 is honoured
on a fresh build (GDAL vsicurl's first request); ranges are answered
whole for one TTL after a URL's bytes change; and a matching ``If-Range``
(RFC 9110 13.1.5) is always honoured, since it proves what bytes the client
already holds.
"""

import asyncio
import os
import zlib
from typing import AsyncIterator

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.responses import Response

from app.api.no_compress_paths import ORIGINAL_ACCEPT_ENCODING_KEY
from app.platform.http.ranges import (
    RANGE_UNSATISFIABLE,
    if_none_match_matches,
    not_modified_response,
    parse_byte_range,
    range_bound_to_this_version,
)
from app.processing.export.artifact_cache import ExportArtifact
from app.processing.export.ogr import FORMAT_MAP
from app.processing.export.service import file_response_content_disposition

_FILE_CHUNK_BYTES = 1024 * 1024

# GeoJSON and CSV compress well and are the only exports sent gzipped, as a
# second representation of the stored artifact under its own validator.
_TEXT_MEDIA_TYPES = frozenset(FORMAT_MAP[key]["media"] for key in ("geojson", "csv"))
_GZIP_LEVEL = 4


def is_text_export(media_type: str) -> bool:
    return media_type in _TEXT_MEDIA_TYPES


def client_offers_gzip(request: Request, media_type: str) -> bool:
    """Is this request answered with the gzip representation?

    Only text exports, only when the client offers gzip with a nonzero
    q-value, and never with ``Range`` or ``If-Range``: the gzip bytes have no
    byte offsets a client could resume against, so those get the identity file.
    """
    if not is_text_export(media_type):
        return False
    if "range" in request.headers or "if-range" in request.headers:
        return False
    for member in request.scope.get(ORIGINAL_ACCEPT_ENCODING_KEY, "").split(","):
        name, _, params = member.partition(";")
        if name.strip().lower() not in ("gzip", "x-gzip"):
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        return quality > 0
    return False


def _gzip_strong_etag(etag: str) -> str:
    return f'"{etag.strip(chr(34))}-gzip"'


def gzip_etag(etag: str) -> str:
    """The validator of the gzip representation of the artifact ``etag`` names.

    Weak: the compressor is deterministic here, but a different zlib could
    write other bytes for the same artifact, so it promises equivalence only.
    """
    return f"W/{_gzip_strong_etag(etag)}"


def revalidates(if_none_match: str | None, etag: str | None, media_type: str) -> bool:
    """Does ``If-None-Match`` name the artifact or, for a text export, its gzip form?"""
    if if_none_match_matches(if_none_match, etag):
        return True
    return (
        etag is not None
        and is_text_export(media_type)
        and if_none_match_matches(if_none_match, _gzip_strong_etag(etag))
    )


# GZipMiddleware is kept off this route, so a text export names the request
# header its body depends on itself.
VARY_ACCEPT_ENCODING = {"vary": "Accept-Encoding"}
GZIP_REPRESENTATION_HEADERS = {"content-encoding": "gzip", "accept-ranges": "none"}


def representation_headers(media_type: str, *, gzipped: bool = False) -> dict[str, str]:
    """Headers that say which representation of a text export this is."""
    if not is_text_export(media_type):
        return {}
    return {**VARY_ACCEPT_ENCODING, **(GZIP_REPRESENTATION_HEADERS if gzipped else {})}


def not_modified(etag: str | None, *, gzipped: bool = False) -> Response:
    """The 304 for the representation this request would have received."""
    response = not_modified_response(
        gzip_etag(etag) if gzipped and etag is not None else etag
    )
    response.headers["vary"] = VARY_ACCEPT_ENCODING["vary"]
    if gzipped:
        response.headers["accept-ranges"] = "none"
    return response


def artifact_headers(
    artifact: ExportArtifact, *, gzipped: bool = False
) -> dict[str, str]:
    """Headers every response describing a stored artifact carries.

    ``ETag`` is the artifact's digest, not a mtime-derived tag, which changed
    between conversions of unchanged data. Uses
    ``file_response_content_disposition``, not ``safe_content_disposition``,
    so HEAD and GET agree byte for byte. ``gzipped`` swaps in the gzip
    representation's validator and drops the range advertisement.
    """
    return {
        "accept-ranges": "bytes",
        "content-disposition": file_response_content_disposition(artifact.filename),
        "etag": gzip_etag(artifact.etag) if gzipped else artifact.etag,
        **representation_headers(artifact.media_type, gzipped=gzipped),
    }


def head_response(artifact: ExportArtifact, *, gzipped: bool = False) -> Response:
    """HEAD, answered from the artifact: a real Content-Length, no conversion.

    Without a real length, ``/vsicurl/`` retries with a ranged GET to learn
    the size, costing a round trip. The gzip representation's length is not
    known without compressing, so it carries none (RFC 9110 9.3.2).
    """
    if gzipped:
        response = Response(
            status_code=status.HTTP_200_OK,
            media_type=artifact.media_type,
            headers=artifact_headers(artifact, gzipped=True),
        )
        response.raw_headers = [
            (key, value)
            for key, value in response.raw_headers
            if key != b"content-length"
        ]
        return response
    return Response(
        status_code=status.HTTP_200_OK,
        media_type=artifact.media_type,
        headers={**artifact_headers(artifact), "content-length": str(artifact.size)},
    )


async def _gzip_chunks(source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Compress a byte stream, deflating off the event loop.

    The gzip header carries no timestamp, so equal input gives equal output.
    """
    compressor = zlib.compressobj(_GZIP_LEVEL, zlib.DEFLATED, 31)
    try:
        async for chunk in source:
            packed = await asyncio.to_thread(compressor.compress, chunk)
            if packed:
                yield packed
        yield compressor.flush()
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            await close()


def read_response(
    storage,
    artifact: ExportArtifact,
    *,
    range_header: str | None,
    if_range: str | None = None,
    may_serve_range: bool,
    leading_slice_ok: bool = False,
    gzipped: bool = False,
    background: BackgroundTask | None = None,
) -> Response:
    """The GET: a 206 slice, a 416, or the whole artifact.

    ``gzipped`` answers the whole artifact compressed; the caller sets it only
    for a request with no Range or If-Range.

    ``may_serve_range``: true only if these bytes were served before this
    request (gates the splice in the module docstring). ``leading_slice_ok``
    is the byte-0 exception, set only for a fresh build with no other live
    representation. ``background`` must run after the response.
    """
    if gzipped:
        return StreamingResponse(
            _gzip_chunks(storage.get_stream(artifact.key)),
            media_type=artifact.media_type,
            headers=artifact_headers(artifact, gzipped=True),
            background=background,
        )
    headers = artifact_headers(artifact)

    # If-Range is evaluated before slicing: a client naming the previous
    # artifact must not get a slice of the current one. Strong comparison,
    # ignore-on-mismatch, per RFC 9110 13.1.5. A matching If-Range outranks
    # `may_serve_range`, since it proves what a bare Range after a rebuild
    # cannot.
    proven = if_range is not None and range_bound_to_this_version(
        if_range, artifact.etag
    )
    byte_range = parse_byte_range(range_header, artifact.size)
    if not proven:
        if if_range is not None:
            # Present and not matching: section 13.1.5 says ignore the Range.
            return _whole(storage, artifact, headers, background)
        if not may_serve_range and not (
            leading_slice_ok and _starts_at_zero(byte_range)
        ):
            # Bare Range on a just-built or contested representation (other
            # than a fresh build's leading slice): whole.
            return _whole(storage, artifact, headers, background)

    if byte_range is None:
        return _whole(storage, artifact, headers, background)

    if byte_range == RANGE_UNSATISFIABLE:
        raise _unsatisfiable(artifact.size, artifact.etag)

    start, end = byte_range
    return StreamingResponse(
        storage.get_range_stream(artifact.key, start, end - start + 1),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=artifact.media_type,
        headers={
            **headers,
            "content-range": f"bytes {start}-{end}/{artifact.size}",
            "content-length": str(end - start + 1),
        },
        background=background,
    )


def _starts_at_zero(byte_range) -> bool:
    """A resolved Range whose first byte is 0: a probe/restart, never a resume.

    The one bare Range a fresh build honours, and only with
    ``leading_slice_ok``. A satisfiable pair only.
    """
    return isinstance(byte_range, tuple) and byte_range[0] == 0


def temp_file_response(
    file_path: str,
    *,
    filename: str,
    media_type: str,
    etag: str | None,
    range_header: str | None = None,
    if_range: str | None = None,
    gzipped: bool = False,
    background: BackgroundTask | None = None,
) -> Response:
    """Serve a just-converted file that wasn't published.

    Not ``FileResponse``: starlette's own Range handling would slice a
    conversion no later request can find, and its mtime ETag disagrees with
    the artifact path's.

    These bytes are never recorded, so nothing could later tell a resume of
    them from one of another version: the response says ``Accept-Ranges:
    none`` and carries no ETag, leaving a client nothing to resume against.
    ``etag`` (the digest, None when unhashable) only proves an ``If-Range``
    the client took from an artifact of the same bytes, which gets a 206 from
    the local file; a bare or mismatched one gets the whole file.
    """
    if gzipped:
        return StreamingResponse(
            _gzip_chunks(_iter_file(file_path)),
            media_type=media_type,
            headers={
                "accept-ranges": "none",
                "content-disposition": file_response_content_disposition(filename),
                **representation_headers(media_type, gzipped=True),
            },
            background=background,
        )
    size = os.path.getsize(file_path)
    headers = {
        "accept-ranges": "none",
        "content-disposition": file_response_content_disposition(filename),
        **representation_headers(media_type),
    }

    proven = (
        etag is not None
        and if_range is not None
        and range_bound_to_this_version(if_range, etag)
    )
    byte_range = parse_byte_range(range_header, size) if proven else None
    if byte_range == RANGE_UNSATISFIABLE:
        raise _unsatisfiable(size, None, accept_ranges="none")
    if byte_range is not None:
        start, end = byte_range
        return StreamingResponse(
            _iter_file(file_path, start, end - start + 1),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media_type,
            headers={
                **headers,
                "content-range": f"bytes {start}-{end}/{size}",
                "content-length": str(end - start + 1),
            },
            background=background,
        )
    return StreamingResponse(
        _iter_file(file_path),
        media_type=media_type,
        headers={**headers, "content-length": str(size)},
        background=background,
    )


def _unsatisfiable(
    size: int, etag: str | None, *, accept_ranges: str = "bytes"
) -> HTTPException:
    """The 416, built once for both the stored and the local representation."""
    headers = {
        "accept-ranges": accept_ranges,
        # Size is the point of a 416 (how a client learns the real length).
        # No Content-Disposition: this body is a JSON error, not the export.
        "content-range": f"bytes */{size}",
    }
    if etag is not None:
        headers["etag"] = etag
    return HTTPException(
        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
        detail="Requested range not satisfiable",
        headers=headers,
    )


async def _iter_file(
    file_path: str, start: int = 0, length: int | None = None
) -> AsyncIterator[bytes]:
    """Read a local file, or a window of it, in bounded chunks off the event loop.

    Mirrors ``LocalStorageProvider.get_stream``/``get_range_stream``: a
    multi-gigabyte export must not be materialized. ``length`` None means to
    the end.
    """
    handle = await asyncio.to_thread(open, file_path, "rb")
    try:
        if start:
            await asyncio.to_thread(handle.seek, start)
        remaining = length
        while remaining is None or remaining > 0:
            want = (
                _FILE_CHUNK_BYTES
                if remaining is None
                else min(_FILE_CHUNK_BYTES, remaining)
            )
            chunk = await asyncio.to_thread(handle.read, want)
            if not chunk:
                return
            if remaining is not None:
                remaining -= len(chunk)
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


def _whole(
    storage,
    artifact: ExportArtifact,
    headers: dict[str, str],
    background: BackgroundTask | None = None,
) -> Response:
    """The complete representation, streamed from one provider read.

    Uses ``get_stream`` rather than looping ``get_range``: a per-chunk loop
    turns one download into one object-store request per megabyte.
    """
    return StreamingResponse(
        storage.get_stream(artifact.key),
        media_type=artifact.media_type,
        headers={**headers, "content-length": str(artifact.size)},
        background=background,
    )

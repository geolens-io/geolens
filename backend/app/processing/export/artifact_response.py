"""Turning a stored export artifact into a 200, a 206 or a 416 (fix(#1532)).

A Range is honoured only when the artifact already existed; otherwise the
whole representation goes back with 200 (RFC 9110 14.2) — a ``/vsicurl/``
client sends no If-Range, so a rebuild can't tell it's a different file,
and only a whole 200 can't splice two representations together.

Exceptions: a Range starting at byte 0 is honoured on a fresh build (#1585,
GDAL vsicurl's first request); ranges are answered whole for one TTL after
a URL's bytes change; and a matching ``If-Range`` (RFC 9110 13.1.5) is
always honoured, since it proves what bytes the client already holds.
"""

import asyncio
import os
from typing import AsyncIterator

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.responses import Response

from app.platform.http.ranges import (
    RANGE_UNSATISFIABLE,
    parse_byte_range,
    range_bound_to_this_version,
)
from app.processing.export.artifact_cache import ExportArtifact
from app.processing.export.service import file_response_content_disposition

_FILE_CHUNK_BYTES = 1024 * 1024


def artifact_headers(artifact: ExportArtifact) -> dict[str, str]:
    """Headers every response describing a stored artifact carries.

    ``ETag`` is the artifact's digest, not a mtime-derived tag (#1532:
    mtime changed between conversions of unchanged data). Uses
    ``file_response_content_disposition``, not ``safe_content_disposition``,
    so HEAD and GET agree byte for byte.
    """
    return {
        "accept-ranges": "bytes",
        "content-disposition": file_response_content_disposition(artifact.filename),
        "etag": artifact.etag,
    }


def head_response(artifact: ExportArtifact) -> Response:
    """HEAD, answered from the artifact: a real Content-Length, no conversion.

    Without a real length, ``/vsicurl/`` retries with a ranged GET to learn
    the size instead — costing a round trip and, before this fix, a rebuild.
    """
    return Response(
        status_code=status.HTTP_200_OK,
        media_type=artifact.media_type,
        headers={**artifact_headers(artifact), "content-length": str(artifact.size)},
    )


def read_response(
    storage,
    artifact: ExportArtifact,
    *,
    range_header: str | None,
    if_range: str | None = None,
    may_serve_range: bool,
    leading_slice_ok: bool = False,
    background: BackgroundTask | None = None,
) -> Response:
    """The GET: a 206 slice, a 416, or the whole artifact.

    ``may_serve_range``: true only if the artifact existed before this
    request (gates the splice in the module docstring). ``leading_slice_ok``
    is the byte-0 exception, set only for a fresh build with no other live
    representation. ``background`` must run AFTER the response (fix(#435)).
    """
    headers = artifact_headers(artifact)

    # fix(#1532): evaluate If-Range before slicing — a client naming
    # the previous artifact must not get a slice of the current one. Strong
    # comparison, ignore-on-mismatch, per RFC 9110 13.1.5.
    #
    # fix(#1532): a MATCHING If-Range outranks `may_serve_range`,
    # since it proves what a bare Range after a rebuild cannot.
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
    background: BackgroundTask | None = None,
) -> Response:
    """Serve a just-converted file, without letting starlette see the Range.

    fix(#1532): replaces ``FileResponse`` when publication doesn't
    happen — starlette's own Range handling repeats #1532's splice on this
    degraded path, and its mtime ETag disagreed with the artifact path's.

    ``etag`` is the SAME validator the artifact path sends; None when the
    file couldn't be hashed (no validator beats a wrong one).

    fix(#1532): a matching ``If-Range`` gets a 206 from the local
    file (export is byte-deterministic); a bare or mismatched one gets the
    whole file, since this request BUILT it.
    """
    size = os.path.getsize(file_path)
    headers = {
        "accept-ranges": "bytes",
        "content-disposition": file_response_content_disposition(filename),
    }
    if etag is not None:
        headers["etag"] = etag

    proven = (
        etag is not None
        and if_range is not None
        and range_bound_to_this_version(if_range, etag)
    )
    byte_range = parse_byte_range(range_header, size) if proven else None
    if byte_range == RANGE_UNSATISFIABLE:
        raise _unsatisfiable(size, etag)
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


def _unsatisfiable(size: int, etag: str | None) -> HTTPException:
    """The 416, built once for both the stored and the local representation."""
    headers = {
        "accept-ranges": "bytes",
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

    Uses ``get_stream`` rather than looping ``get_range``: fix(#1540 review
    P1) found a per-chunk loop turns one download into one object-store
    request per megabyte.
    """
    return StreamingResponse(
        storage.get_stream(artifact.key),
        media_type=artifact.media_type,
        headers={**headers, "content-length": str(artifact.size)},
        background=background,
    )

"""Turning a stored export artifact into a 200, a 206 or a 416 (fix(#1532)).

Split from the router so the range decision is readable on its own: it is one
rule, it is the reason this fix is safe, and it is not obvious.

**A Range is honoured only when the artifact already existed** — with one
exception, below. If this request had to build one, the Range is ignored and the
whole representation goes back with 200. RFC 9110 section 14.2 permits exactly
that, and it is what preserves the loud-failure property #1532 insists on. A
``/vsicurl/`` client sends a bare ``Range`` with no ``If-Range``, so the server
has nothing to compare and cannot be told which artifact the client was reading.
Answering a rebuild with a 206 at the offsets the client asked for would hand it
a slice of a DIFFERENT file at the old positions, which is the splice the issue
exists to prevent. Answering with the complete new representation cannot splice
anything: the client discards what it had and reads from zero.

**The exception: a Range that starts at byte 0 is honoured on a fresh build**
(fix(#1532) follow-up, #1585, found by the release smoke). GDAL 3.10's
``/vsicurl/`` open does not begin with a HEAD; its first request is ``Range:
bytes=0-16383``, and a 200 to that is read as "Range downloading not supported
by this server" and the open aborts — so a cold cache could not be opened at
all, and only the second attempt worked. A range from byte 0 is a probe or a
restart, never a resume: a client resuming holds a prefix and asks from its
length. Any other starting offset on a fresh build keeps the whole answer.

**And the bound on both, for bare ranges: for one TTL after a URL's bytes
change, ranges are answered whole.** A client that read a block of the earlier
representation and comes back for the next one — to a hit on the new artifact,
or to a fresh build of it, or re-reading the header — makes that request
within the change's first TTL, and it gets the whole new file, which cannot
splice. Once the new bytes have been the URL's answer for a TTL (``settled``),
ranges resume; a client holding a handle across a longer gap without an
``If-Range`` is the residual every range-serving origin has, and RFC 9110 gives
the server nothing to close it with. The check reads the URL's history (every
version, plus the parent revision's single-segment layout) and is paid only in
that first TTL, and only by requests carrying a bare Range.

So the sequence a probing client sees is: first request builds and gets either
the leading slice it asked for or the whole representation; every later request
inside the freshness window is a slice of that one stored object; and the first
request after the data changes builds again and answers the same way. No two
responses in that sequence are ever parts of different files presented as parts
of one.

**A client that CAN name what it is resuming is held to it.** The artifact
publishes a strong validator, so `If-Range` is evaluated here too (fix(#1532)
review r1): a non-matching or weak one means ignore the Range and answer 200,
per RFC 9110 section 13.1.5. Without that, a client resuming the previous
artifact after a rebuild got a 206 of the current one — the same splice, reached
through the header a careful client sends precisely to avoid it.
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

    ``Accept-Ranges`` on all of them including the 416: RFC 9110 section 14.3
    scopes it to the RESOURCE, and a client that just got a 416 is the one that
    needs telling it may retry with a corrected range.

    ``ETag`` is the artifact's own digest, so unlike the ``FileResponse`` tag it
    replaces it names one specific set of stored bytes rather than a temp file's
    mtime. #1532 measured that tag changing between two conversions of unchanged
    data, which is why nothing could be built on it.

    ``file_response_content_disposition`` and not ``safe_content_disposition``,
    which is the other one in that module: this route's HEAD restates
    starlette's ``FileResponse`` rule so the two verbs agree byte for byte, and
    ``test_head_export_content_disposition_matches_get`` pins it. Serving the
    cached artifact through the other builder broke that parity for both of its
    parametrized names, which is how the divergence was caught rather than
    shipped.
    """
    return {
        "accept-ranges": "bytes",
        "content-disposition": file_response_content_disposition(artifact.filename),
        "etag": artifact.etag,
    }


def head_response(artifact: ExportArtifact) -> Response:
    """HEAD, answered from the artifact: a real Content-Length and no conversion.

    The length is what GDAL is probing for. Without it ``/vsicurl/`` logs "HEAD
    did not provide file size. Retrying with limited range GET" and learns the
    size from a 206's Content-Range instead — which worked, and cost one more
    round trip and (before this fix) one more conversion.
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

    ``may_serve_range`` is the caller's answer to "did this artifact exist before
    this request", and it is what stands between this endpoint and the splice
    described in the module docstring. It is a parameter rather than something
    inferred here because only the caller knows whether it just built the thing.
    ``leading_slice_ok`` is the one exception the module docstring states: the
    caller BUILT this artifact into a selection with no other representation
    live, and a bare Range that starts at byte 0 is a probe, not a resume, so
    it is honoured. It is separate from ``may_serve_range`` because a contested
    selection also sets that False, and there the whole answer stays: two
    representations are live and the client's next slice may land on the other.

    ``background`` carries the caller's temp-directory cleanup, and it is a
    parameter for a reason worth stating. An earlier revision deleted the
    conversion's directory eagerly, on the grounds that the bytes were already
    safe in storage. ``test_export_antimeridian`` failed immediately: its stub
    writes the export beside the test's storage root rather than into a
    per-export directory, so the eager ``rmtree`` took the object store with it.
    The stub is unusual, but the lesson is not — deletion is the caller's
    lifecycle, fix(#435) put it on the response for a reason, and a response is
    not finished when it is constructed.
    """
    headers = artifact_headers(artifact)

    # fix(#1532 review r1): evaluate If-Range before slicing. The artifact
    # publishes a strong validator, so a client CAN name the representation it
    # is resuming — curl -C, browsers, and any future GDAL that learns to — and
    # a client that names the previous artifact must not be handed a slice of
    # the current one at those offsets. That is the same splice `may_serve_range`
    # closes for the rebuild case, arriving through the header a careful client
    # sends precisely to avoid it.
    #
    # "GDAL sends neither" was true of the client this issue was filed for and
    # is not a reason to answer wrongly for the ones that do. Strong comparison
    # and ignore-on-mismatch are RFC 9110 section 13.1.5, and the evaluation is
    # the one fix(#1540) settled on the COG route rather than a second copy.
    #
    # fix(#1532 review r12): a MATCHING If-Range outranks `may_serve_range`. That
    # flag is the fallback for a client that cannot say which bytes its offsets
    # belong to — a bare Range after a rebuild, or against a contested selection
    # — and a client sending this artifact's exact strong ETag has said exactly
    # that. Refusing it there would deny a resume to the only clients that did
    # the work to make one safe, on the strength of a doubt they have resolved.
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
            # A bare Range on a representation this request built (or on a
            # contested selection), other than the leading slice of a fresh
            # build: whole (module docstring).
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
    """A resolved Range whose first byte is 0: a probe or a restart, never a resume.

    The one bare Range a fresh build honours (module docstring, and only with
    ``leading_slice_ok``). A satisfiable pair only — an unsatisfiable or absent
    Range is not "from zero".
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

    fix(#1532 review, internal): this replaces a ``FileResponse`` on the path
    taken when publication does not happen — a storage outage, a contested
    selection, an exhausted budget. Starlette's ``FileResponse`` parses ``Range``
    itself, single and multipart, and needs no ``If-Range`` to do it, so that
    fallback answered a resuming client with a 206 of a FRESH conversion at the
    offsets it had measured against a previous one. #1532's whole defect, alive
    on the degraded path — which is the path that fires under load, when the
    store is full or every client is building at once.

    It also sent an mtime ETag and a Last-Modified the artifact path never
    sends, so two responses for one URL disagreed about which validators the
    resource even has.

    fix(#1532 review r18): ``etag`` is the SAME validator the artifact path
    sends — the digest of the bytes in this file, formatted by
    ``artifact_cache.strong_etag`` — so a client that takes it from here and
    offers it back on ``If-None-Match``, ``If-Match`` or ``If-Range`` is
    answered from the bytes it names, whichever path the next request lands on.
    None when the file could not be hashed, and then no validator goes out at
    all rather than one that names nothing.

    fix(#1532 review r19): the one exception, and it is ``read_response``'s
    r12 rule applied here. A client whose ``If-Range`` names THIS file's strong
    ETag has proved its offsets belong to these bytes — the export is
    byte-deterministic, so a resumer of the previous artifact holds exactly this
    representation — and gets a 206 sliced from the local file, or a 416 if the
    range names nothing. Refusing it here sent the whole, possibly multi-gigabyte,
    file on every resume attempt for as long as publication stayed unavailable,
    which is precisely when the volume is under the most pressure. A bare Range
    or a mismatched ``If-Range`` still gets the whole thing: this request BUILT
    the file, so nothing else in the request can say which bytes the client
    already holds.
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
        # The size is the point of the 416: it is how a client that guessed at
        # the length learns the real one. Content-Disposition is deliberately
        # NOT here — this body is the JSON error, and naming it with the
        # export's filename would have a browser save an error document as the
        # download.
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

    Same shape as ``LocalStorageProvider.get_stream`` and ``get_range_stream``:
    a multi-gigabyte export must not be materialized, and the reads must not
    block the loop. ``length`` None means to the end.
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

    ``get_stream`` rather than a loop over ``get_range``: fix(#1540 review P1)
    established on the COG route that a per-chunk loop turns one download into
    one object-store request per megabyte, and the export artifact is the same
    shape of object behind the same kind of client.
    """
    return StreamingResponse(
        storage.get_stream(artifact.key),
        media_type=artifact.media_type,
        headers={**headers, "content-length": str(artifact.size)},
        background=background,
    )

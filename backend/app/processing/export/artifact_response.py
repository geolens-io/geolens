"""Turning a stored export artifact into a 200, a 206 or a 416 (fix(#1532)).

Split from the router so the range decision is readable on its own: it is one
rule, it is the reason this fix is safe, and it is not obvious.

**A Range is honoured only when the artifact already existed.** If this request
had to build one, the Range is ignored and the whole representation goes back
with 200. RFC 9110 section 14.2 permits exactly that, and it is what preserves
the loud-failure property #1532 insists on. A ``/vsicurl/`` client sends a bare
``Range`` with no ``If-Range``, so the server has nothing to compare and cannot
be told which artifact the client was reading. Answering a rebuild with a 206 at
the offsets the client asked for would hand it a slice of a DIFFERENT file at the
old positions, which is the splice the issue exists to prevent. Answering with
the complete new representation cannot splice anything: the client discards what
it had and reads from zero.

So the sequence a probing client sees is: first request builds and gets a whole
representation; every later request inside the freshness window is a slice of
that one stored object; and the first request after the data changes builds again
and gets a whole representation again. No two responses in that sequence are ever
parts of different files presented as parts of one.

**A client that CAN name what it is resuming is held to it.** The artifact
publishes a strong validator, so `If-Range` is evaluated here too (fix(#1532)
review r1): a non-matching or weak one means ignore the Range and answer 200,
per RFC 9110 section 13.1.5. Without that, a client resuming the previous
artifact after a rebuild got a 206 of the current one — the same splice, reached
through the header a careful client sends precisely to avoid it.
"""

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
    background: BackgroundTask | None = None,
) -> Response:
    """The GET: a 206 slice, a 416, or the whole artifact.

    ``may_serve_range`` is the caller's answer to "did this artifact exist before
    this request", and it is the only thing standing between this endpoint and
    the splice described in the module docstring. It is a parameter rather than
    something inferred here because only the caller knows whether it just built
    the thing.

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

    if not may_serve_range:
        return _whole(storage, artifact, headers, background)

    # fix(#1532 review r1): evaluate If-Range before slicing. The artifact now
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
    if not range_bound_to_this_version(if_range, artifact.etag):
        return _whole(storage, artifact, headers, background)

    byte_range = parse_byte_range(range_header, artifact.size)
    if byte_range is None:
        return _whole(storage, artifact, headers, background)

    if byte_range == RANGE_UNSATISFIABLE:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Requested range not satisfiable",
            headers={
                "accept-ranges": "bytes",
                # The size is the point of the 416: it is how a client that
                # guessed at the length learns the real one. Content-Disposition
                # is deliberately NOT here — this body is the JSON error, and
                # naming it with the export's filename would have a browser save
                # an error document as the download.
                "content-range": f"bytes */{artifact.size}",
                "etag": artifact.etag,
            },
        )

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

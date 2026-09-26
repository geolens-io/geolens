"""Serve a published COPC point cloud's file, whole or by byte range."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.pointcloud import POINTCLOUD_MEDIA_TYPE
from app.modules.auth.dependencies import oauth2_scheme_optional
from app.modules.catalog.datasets.api.pointcloud_access import (
    authorize_pointcloud_read,
)
from app.modules.catalog.datasets.api.sandboxed_route import SandboxedRoute
from app.platform.http.ranges import parse_byte_range, range_bound_to_this_version
from app.platform.http.stored_bytes import (
    StoredObjectMissing,
    StoredObjectUnreadable,
    evaluate_preconditions,
    serve_stored_bytes,
)
from app.platform.ratelimit import limiter
from app.platform.storage import get_storage
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    NOT_FOUND_RESPONSE,
    PRECONDITION_FAILED_RESPONSE,
    PROBLEM_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/datasets", tags=["Datasets"], route_class=SandboxedRoute)

# A client may store the bytes but must ask before each reuse, so every read is
# authorized again; the attempt's ETag turns that into a 304.
_CACHE_CONTROL = "private, no-cache"

_PATH = "/{dataset_id}/copc/{attempt_id}/{name}.copc.laz"

# Every read resolves the caller and the dataset before it touches storage. A
# COPC view reads about one range per octree node in the viewer's point budget,
# tens to a few hundred, and an active user refines a few views a minute.
_READ_LIMIT = "1200/minute"
# A read that can carry more of the file than this also counts against the
# much tighter _WHOLE_FILE_LIMIT.
_EXEMPT_RANGE_BYTES = 16 * 1024 * 1024
_WHOLE_FILE_LIMIT = "10/minute"
# The ranges that limit exempts draw on a budget of 64 KiB units instead. A heavy
# viewer reads about a thousand node ranges a minute, some 200 MB; 1 GiB covers it.
_RANGE_UNIT = 64 * 1024
_RANGE_BUDGET = "16384/minute"
# Larger than any stored object, so a Range parsed against it names the most
# bytes it could select from the real file.
_ANY_SIZE = 10**19


def _etag(attempt_id: uuid.UUID) -> str:
    return f'"{attempt_id}"'


def _small_range_bytes(request: Request) -> int | None:
    """The most bytes a GET's one range of up to ``_EXEMPT_RANGE_BYTES`` can carry, else None."""
    if request.method == "HEAD":
        return None
    pair = parse_byte_range(request.headers.get("range"), _ANY_SIZE, strict=True)
    if not isinstance(pair, tuple) or pair[1] - pair[0] + 1 > _EXEMPT_RANGE_BYTES:
        return None
    try:
        etag = _etag(uuid.UUID(request.path_params.get("attempt_id", "")))
    except ValueError:
        return None
    # A validator of another version turns the range into the whole file.
    if not range_bound_to_this_version(request.headers.get("if-range"), etag):
        return None
    return pair[1] - pair[0] + 1


def _reads_one_small_range(request: Request) -> bool:
    """Whether the answer carries no body, or at most one range of ``_EXEMPT_RANGE_BYTES``."""
    return request.method == "HEAD" or _small_range_bytes(request) is not None


def _draws_no_range_bytes(request: Request) -> bool:
    return _small_range_bytes(request) is None


def _range_units(request: Request) -> int:
    return -(-(_small_range_bytes(request) or 0) // _RANGE_UNIT)


@router.head(_PATH, include_in_schema=False)
@router.get(
    _PATH,
    response_class=Response,
    responses={
        200: {"description": f"The whole COPC file, as {POINTCLOUD_MEDIA_TYPE}"},
        206: {"description": "One byte range of the COPC file"},
        304: {"description": "The caller already holds this version of the file"},
        401: {
            **PROBLEM_RESPONSE,
            "description": (
                "A credential was supplied and could not be resolved (expired, "
                "revoked or malformed); a read with none is anonymous"
            ),
        },
        404: NOT_FOUND_RESPONSE,
        412: PRECONDITION_FAILED_RESPONSE,
        416: {
            **PROBLEM_RESPONSE,
            "description": "The Range names no byte of the file, or is malformed",
        },
        502: BAD_GATEWAY_RESPONSE,
    },
)
@limiter.limit(_WHOLE_FILE_LIMIT, exempt_when=_reads_one_small_range)
@limiter.limit(_RANGE_BUDGET, cost=_range_units, exempt_when=_draws_no_range_bytes)
@limiter.limit(_READ_LIMIT)
async def get_pointcloud_file(
    dataset_id: uuid.UUID,
    attempt_id: uuid.UUID,
    name: str,
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a published COPC point cloud's file, whole or by HTTP byte range.

    Point a client at the dataset's ``pointcloud.url``. The path names the
    upload attempt, so a replaced file gets a new URL and the old one answers
    404. Header credentials (``X-Api-Key`` or ``Authorization``) or the
    ``api_key`` query parameter authenticate the read, and any caller who can
    view the dataset can read the file. The response carries a strong ETag and
    honours ``Range``, ``If-Range``, ``If-Match`` and ``If-None-Match``; a
    malformed byte range, or one naming no byte of the file, answers 416.
    Each client may make 1200 reads a minute. A read of one byte range of up
    to 16 MiB also draws its size on a budget of 1 GiB a minute, in 64 KiB
    units; any other read of the file, such as one without ``Range``, counts
    against a limit of 10 a minute instead. Past any of these the read answers
    429.
    Through the bundled web server a page on any origin can read the file,
    with header credentials or none; the API alone allows only the origins in
    ``CORS_ALLOWED_ORIGINS``. A private, missing or replaced point cloud
    answers 404, and a storage failure answers 502.
    """
    grant = await authorize_pointcloud_read(
        request, db, token, dataset_id=dataset_id, attempt_id=attempt_id, name=name
    )
    # The body streams for as long as the client takes, and the session would
    # keep its pooled connection until the last byte.
    await db.rollback()
    etag = _etag(grant.attempt_id)
    not_modified = evaluate_preconditions(
        request, etag, changed_detail="The point cloud has changed since that version"
    )
    if not_modified is not None:
        not_modified.headers["Cache-Control"] = _CACHE_CONTROL
        return not_modified
    try:
        return await serve_stored_bytes(
            request,
            get_storage(),
            grant.storage_key,
            total_bytes=grant.size_bytes,
            media_type=POINTCLOUD_MEDIA_TYPE,
            etag=etag,
            headers={"Cache-Control": _CACHE_CONTROL},
            strict=True,
        )
    except StoredObjectMissing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        ) from None
    except StoredObjectUnreadable:
        logger.exception("pointcloud_storage_read_failed", dataset_id=str(dataset_id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
        ) from None

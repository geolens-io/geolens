"""Serve the files of a published 3D Tiles tileset from object storage."""

from __future__ import annotations

import posixpath
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing, contextmanager

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.tiles3d import tileset_prefix
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import check_dataset_access_or_anonymous
from app.modules.catalog.datasets.api.sandboxed_route import SandboxedRoute
from app.modules.catalog.datasets.domain.service import get_dataset, get_tileset_href
from app.platform.http.stored_bytes import evaluate_preconditions
from app.platform.ratelimit import limiter
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    NOT_FOUND_RESPONSE,
    PRECONDITION_FAILED_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

_CONTENT_TYPES = {
    ".json": "application/json",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ktx2": "image/ktx2",
}
_OCTET_STREAM = "application/octet-stream"

# Bytes per media type served, so sync()/asyncio() return a File, not None.
# Excludes "application/json": openapi-python-client picks one type per
# response and would call response.json() on every file this route serves.
_TILES3D_BODY = {
    media_type: {"schema": {"type": "string", "format": "binary"}}
    for media_type in {*_CONTENT_TYPES.values(), _OCTET_STREAM} - {"application/json"}
}

# The carrier's href names the live attempt's tileset.json, one level below
# the dataset's prefix.
_ATTEMPT_ENTRY = re.compile(r"[A-Za-z0-9_-]+/tileset\.json")

# A client may store a file but must ask before each reuse, so every read is
# authorized again; the live attempt's ETag turns that into a 304.
_CACHE_CONTROL = "private, no-cache"


router = APIRouter(prefix="/datasets", tags=["Datasets"], route_class=SandboxedRoute)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _live_attempt(href: str | None, dataset_id: uuid.UUID) -> str | None:
    """The live attempt's prefix, with its trailing slash; None if unusable."""
    if href is None:
        return None
    prefix = tileset_prefix(dataset_id)
    if not href.startswith(prefix) or not _ATTEMPT_ENTRY.fullmatch(href[len(prefix) :]):
        logger.warning("tileset_pointer_outside_prefix", dataset_id=str(dataset_id))
        return None
    return href[: -len("tileset.json")]


def _etag(attempt: str) -> str:
    """The validator of every file in one attempt, which a publish never rewrites."""
    return f'"{attempt.rstrip("/").rsplit("/", 1)[-1]}"'


def _relative_key(path: str) -> str | None:
    """``path`` as a key suffix that cannot leave the attempt, or None."""
    if not path or path.startswith("/") or "\\" in path or "%" in path:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
        return None
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        return None
    return path


@contextmanager
def _storage_errors(dataset_id: uuid.UUID) -> Iterator[None]:
    """Answer a missing file 404 and any other storage failure 502, neither naming the key."""
    try:
        yield
    except (FileNotFoundError, IsADirectoryError):
        raise _not_found() from None
    except Exception:  # broad: each storage backend raises its own errors, and none may reach the client
        logger.exception("tileset_storage_read_failed", dataset_id=str(dataset_id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
        ) from None


async def _chained(first: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    # Closing this generator on a client disconnect closes the storage stream too.
    async with aclosing(rest):
        yield first
        async for chunk in rest:
            yield chunk


@router.get(
    "/{dataset_id}/tiles3d/{path:path}",
    response_class=Response,
    responses={
        200: {"description": "The requested tileset file", "content": _TILES3D_BODY},
        304: {"description": "The caller already holds this version of the file"},
        404: NOT_FOUND_RESPONSE,
        412: PRECONDITION_FAILED_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
# A client loads a tileset's files many at a time, and a per-IP budget shared
# by every file would stall it, so the route is exempt like the tile routes.
@limiter.exempt
async def get_tileset_file(
    dataset_id: uuid.UUID,
    path: str,
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve one file of a published 3D Tiles tileset.

    Point a client at the dataset's ``tileset.url``, this route's
    ``tileset.json``; the relative URIs inside the tileset resolve to this
    same route. Header credentials (``X-Api-Key`` or ``Authorization``)
    authenticate every file of a private tileset. A query-string ``api_key``
    authenticates only the request it is on, so the tileset's relative URIs
    lose it unless the client carries it over, as CesiumJS does through
    ``Resource`` query parameters. A browser page on any origin can read a
    public tileset without credentials; one that sends credentials needs its
    origin on the deployment's CORS allowlist (``CORS_ALLOWED_ORIGINS``).
    Every file carries the published tileset's
    ETag and asks the client to revalidate before each reuse. Once the caller
    has access and the file exists, an ``If-None-Match`` naming the current
    version answers 304 and an ``If-Match`` naming another answers 412. A
    private or missing tileset and a missing file all answer 404, conditional
    requests included, and a storage failure answers 502.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        # Worded like the guard's denial, so a private id and an unknown one match.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    if dataset.record.record_type != "tiles3d_dataset":
        raise _not_found()

    attempt = _live_attempt(await get_tileset_href(db, dataset.id), dataset.id)
    relative = _relative_key(path)
    if attempt is None or relative is None:
        raise _not_found()

    try:
        key = resolve_current_storage_key(attempt + relative)
    except ValueError:
        raise _not_found() from None
    # The body streams for as long as the client takes, and the session would
    # keep its pooled connection until the last byte. Nothing was written, so
    # the rollback discards nothing.
    await db.rollback()
    etag = _etag(attempt)
    storage = get_storage()
    if "if-none-match" in request.headers or "if-match" in request.headers:
        # The ETag names the attempt, not this file, so the file is opened first
        # and a missing one answers as a plain read would. Local storage's
        # exists() is true for a directory, which a read answers 404.
        with _storage_errors(dataset_id):
            async with aclosing(storage.get_range_stream(key, 0, 1)) as probe:
                await anext(probe, b"")
        not_modified = evaluate_preconditions(
            request, etag, changed_detail="The tileset has changed since that version"
        )
        if not_modified is not None:
            not_modified.headers["Cache-Control"] = _CACHE_CONTROL
            return not_modified
    stream = storage.get_stream(key)
    with _storage_errors(dataset_id):
        first = await anext(stream, b"")

    content_type = _CONTENT_TYPES.get(
        posixpath.splitext(relative)[1].lower(), _OCTET_STREAM
    )
    return StreamingResponse(
        _chained(first, stream),
        media_type=content_type,
        headers={"Cache-Control": _CACHE_CONTROL, "ETag": etag},
    )

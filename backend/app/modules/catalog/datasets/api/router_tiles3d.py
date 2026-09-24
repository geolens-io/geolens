"""Serve the files of a published 3D Tiles tileset from object storage."""

from __future__ import annotations

import posixpath
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message, Receive, Scope, Send

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.tiles3d import TILESET_ASSET_KEY, tileset_prefix
from app.modules.auth.dependencies import get_optional_user
from app.modules.catalog.authorization import check_dataset_access_or_anonymous
from app.modules.catalog.datasets.domain.service import get_dataset
from app.platform.extensions import get_catalog_port
from app.platform.ratelimit import limiter
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_AUTH,
    NOT_FOUND_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

# Tileset files are uploaded bytes. Served from the API origin as HTML, SVG or
# script they would run there, so nothing a browser renders gets through.
_SANDBOX_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Vary": "Authorization, X-Api-Key",
}

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

# The carrier's href names the live attempt's tileset.json, one level below
# the dataset's prefix.
_ATTEMPT_ENTRY = re.compile(r"[A-Za-z0-9_-]+/tileset\.json")


class _SandboxedRoute(APIRoute):
    """Puts the sandbox headers on every answer the route gives, errors included."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def sandboxed(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(_SANDBOX_HEADERS)
                headers.setdefault("Cache-Control", "private, no-store")
            await send(message)

        try:
            await super().handle(scope, receive, sandboxed)
        except StarletteHTTPException as exc:
            # A refused method is raised before the route sends anything itself.
            exc.headers = {
                **(exc.headers or {}),
                **_SANDBOX_HEADERS,
                "Cache-Control": "private, no-store",
            }
            raise


router = APIRouter(prefix="/datasets", tags=["Datasets"], route_class=_SandboxedRoute)


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


def _relative_key(path: str) -> str | None:
    """``path`` as a key suffix that cannot leave the attempt, or None."""
    if not path or path.startswith("/") or "\\" in path or "%" in path:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
        return None
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        return None
    return path


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
        200: {"description": "The requested tileset file"},
        401: ERROR_RESPONSES_AUTH[401],
        404: NOT_FOUND_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
# A client loads a tileset's files many at a time, and a per-IP budget shared
# by every file would stall it, so the route is exempt like the tile routes.
@limiter.exempt
async def get_tileset_file(
    dataset_id: uuid.UUID,
    path: str,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve one file of a published 3D Tiles tileset.

    Point a client at ``/datasets/{dataset_id}/tiles3d/tileset.json``, the
    dataset's ``tileset.url``; the relative URIs inside the tileset resolve to
    this same route. Send credentials in the ``X-Api-Key`` or
    ``Authorization`` header. A browser client on another origin also needs
    that origin on the deployment's CORS allowlist (``CORS_ALLOWED_ORIGINS``).
    A private or missing tileset and a missing file all answer 404, and a
    storage failure answers 502.
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

    assets = await get_catalog_port().get_dataset_assets(db, dataset.id)
    carrier = next((a.href for a in assets if a.key == TILESET_ASSET_KEY), None)
    attempt = _live_attempt(carrier, dataset.id)
    relative = _relative_key(path)
    if attempt is None or relative is None:
        raise _not_found()

    try:
        key = resolve_current_storage_key(attempt + relative)
    except ValueError:
        raise _not_found() from None
    stream = get_storage().get_stream(key)
    try:
        first = await anext(stream)
    except FileNotFoundError:
        raise _not_found() from None
    except StopAsyncIteration:
        first = b""
    except Exception:  # broad: each storage backend raises its own errors, and none may reach the client
        logger.exception("tileset_storage_read_failed", dataset_id=str(dataset.id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Storage unavailable"
        ) from None

    content_type = _CONTENT_TYPES.get(
        posixpath.splitext(relative)[1].lower(), _OCTET_STREAM
    )
    max_age = 60 if relative == "tileset.json" else 3600
    return StreamingResponse(
        _chained(first, stream),
        media_type=content_type,
        headers={"Cache-Control": f"private, max-age={max_age}"},
    )

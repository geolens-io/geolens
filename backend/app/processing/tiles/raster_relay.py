"""The internal route Titiler reads remote rasters through.

The address names nothing but an encrypted token, so a request is served
only for a URL this deployment signed, and only when it came straight from
another service rather than through a proxy. Each request is one upstream GET
with the caller's ``Range`` and nothing else, made by the pinned client.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.platform.http.remote_raster import (
    ByteRange,
    RemoteRasterRefused,
    bounded,
    check_range_response,
    check_response_shape,
    object_size,
    open_remote_raster,
    parse_relay_range,
    read_signature,
    relay_deadline,
)
from app.platform.ratelimit import limiter
from app.platform.security import SSRFError
from app.platform.storage.raster_relay import (
    RELAY_FILENAME,
    RELAY_ROUTE_PREFIX,
    read_relay_token,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix=RELAY_ROUTE_PREFIX, include_in_schema=False)

_PASSED_HEADERS = ("content-length", "content-range", "etag", "last-modified")
_PASSED_STATUSES = frozenset({200, 206, 416})


def _refused(reason: str, dataset_id: uuid.UUID | None, status: int) -> Response:
    logger.warning(
        "remote raster relay refused",
        reason=reason,
        dataset_id=str(dataset_id) if dataset_id else None,
    )
    return Response(status_code=status, headers={"Cache-Control": "no-store"})


def _headers(upstream: httpx.Response) -> dict[str, str]:
    headers = {
        name: upstream.headers[name]
        for name in _PASSED_HEADERS
        if name in upstream.headers
    }
    headers["Accept-Ranges"] = "bytes"
    headers["Cache-Control"] = "no-store"
    return headers


async def _body(
    upstream: httpx.Response,
    first: bytes,
    rest: AsyncIterator[bytes],
    limit: int,
    deadline: float,
) -> AsyncIterator[bytes]:
    try:
        if first:
            yield first
        async for chunk in bounded(rest, len(first), limit, deadline):
            yield chunk
    except (RemoteRasterRefused, httpx.HTTPError):
        # Headers are already sent; ending the body short makes GDAL see a
        # failed read rather than a file of the wrong length.
        logger.warning("remote raster relay cut a response short")
    finally:
        await upstream.aclose()


def _forwarded(request: Request) -> bool:
    """Whether a proxy relayed this request; Titiler calls the API directly."""
    return any(
        name in request.headers
        for name in ("forwarded", "x-forwarded-for", "x-real-ip")
    )


@router.api_route(
    "/{token}/" + RELAY_FILENAME, methods=["GET", "HEAD"], response_model=None
)
@limiter.exempt
async def relay_remote_raster(request: Request, token: str) -> Response:
    """Serve one read of a remote raster for Titiler."""
    claims = None if _forwarded(request) else read_relay_token(token)
    if claims is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    try:
        requested = parse_relay_range(request.headers.get("range"))
    except RemoteRasterRefused as exc:
        return _refused(exc.reason, claims.dataset_id, 416)
    # A one-byte GET answers HEAD: a presigned URL is signed for GET only,
    # and some origins refuse HEAD outright.
    head = request.method == "HEAD"
    if head:
        requested = ByteRange(0, 0)

    deadline = relay_deadline()
    try:
        upstream = await open_remote_raster(
            claims.url, byte_range=requested, deadline=deadline
        )
    except SSRFError:
        return _refused("address_refused", claims.dataset_id, 403)
    except (httpx.HTTPError, RemoteRasterRefused):
        return _refused("upstream_unreachable", claims.dataset_id, 502)

    try:
        if upstream.status_code in (404, 410):
            await upstream.aclose()
            return Response(status_code=404, headers={"Cache-Control": "no-store"})
        if upstream.status_code not in _PASSED_STATUSES:
            await upstream.aclose()
            return _refused("upstream_status", claims.dataset_id, 502)
        if upstream.status_code == 416:
            await upstream.aclose()
            return Response(
                status_code=416,
                headers={"Accept-Ranges": "bytes", "Cache-Control": "no-store"},
            )
        limit = check_range_response(upstream, requested)
        if head:
            await upstream.aclose()
            headers = _headers(upstream)
            headers.pop("content-length", None)
            headers.pop("content-range", None)
            if (size := object_size(upstream)) is not None:
                headers["Content-Length"] = size
            return Response(status_code=200, headers=headers, media_type="image/tiff")
        check_response_shape(upstream, limit)
        chunks = upstream.aiter_raw()
        starts_file = requested is None or requested.start == 0
        first = await read_signature(chunks, deadline) if starts_file else b""
        # A body with no length can run past the checked span in one chunk.
        first = first[:limit]
    except RemoteRasterRefused as exc:
        await upstream.aclose()
        return _refused(exc.reason, claims.dataset_id, 403)
    except httpx.HTTPError:
        await upstream.aclose()
        return _refused("upstream_unreachable", claims.dataset_id, 502)

    return StreamingResponse(
        _body(upstream, first, chunks, limit, deadline),
        status_code=upstream.status_code,
        headers=_headers(upstream),
        media_type="image/tiff",
    )

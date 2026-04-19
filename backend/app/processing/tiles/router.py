"""FastAPI tile endpoint serving vector tiles via PostGIS ST_AsMVT."""

import asyncio
import gzip
import re
import threading
import time
import uuid
from typing import NamedTuple

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from geoalchemy2.shape import to_shape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.auth.dependencies import get_optional_user
from app.modules.auth.models import User
from app.modules.auth.visibility import check_dataset_access, get_user_roles
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant
from app.core.dependencies import get_db
from app.modules.embed_tokens.service import validate_embed_token_access
from app.platform.cache.provider import get_tile_cache
from app.processing.tiles.pool import get_tile_pool
from app.processing.tiles.service import get_tile
from app.modules.auth.router import limiter
from app.processing.tiles.schemas import (
    RasterTileToken,
    TileTokenBatchRequest,
    TileTokenBatchResponse,
    VectorTileToken,
)
from app.processing.tiles.signing import (
    generate_tile_signature,
    round_expiry,
    verify_tile_signature,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/tiles", tags=["Tiles"])

_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# ---------------------------------------------------------------------------
# Module-level HTTP client for Titiler proxy (reused across requests)
# ---------------------------------------------------------------------------
_titiler_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0),
    follow_redirects=True,
)

# ---------------------------------------------------------------------------
# In-memory TTL cache for dataset metadata (avoids DB hit per tile request)
# ---------------------------------------------------------------------------
_DATASET_CACHE_TTL = 60  # seconds


class _DatasetMeta(NamedTuple):
    """Plain data extracted from Dataset+Record for tile serving."""

    dataset_id: uuid.UUID
    record_id: uuid.UUID
    table_name: str
    visibility: str
    column_info: list
    tile_cache_ttl: int | None


_dataset_cache: dict[str, tuple[float, _DatasetMeta]] = {}
# threading.Lock is safe here — dict reads/writes are synchronous, no await inside lock
_dataset_cache_lock = threading.Lock()


_DTYPE_MAX = {
    "uint8": 255,
    "uint16": 65535,
    "uint32": 4294967295,
    "int8": 127,
    "int16": 32767,
    "int32": 2147483647,
    "float32": 1.0,
    "float64": 1.0,
}


def _titiler_render_params(band_count: int | None, dtype: str | None) -> str:
    """Build titiler query string for band selection and rescaling.

    Returns a query string fragment like '&bidx=1&bidx=2&bidx=3&rescale=0,65535'.
    """
    parts: list[str] = []
    bc = band_count or 1

    # Select up to 3 bands for RGB rendering (skip alpha/extra bands)
    if bc >= 3:
        parts.extend(["bidx=1", "bidx=2", "bidx=3"])
    elif bc == 2:
        parts.append("bidx=1")
    # else single band — titiler handles it

    # Rescale non-uint8 data to 0-255
    dt = (dtype or "uint8").lower()
    if dt != "uint8":
        max_val = _DTYPE_MAX.get(dt, 65535)
        rescale = f"0,{max_val}"
        # Apply rescale per selected band
        n_bands = min(bc, 3) if bc >= 3 else (1 if bc == 2 else bc)
        for _ in range(max(n_bands, 1)):
            parts.append(f"rescale={rescale}")

    return "&".join(parts)


async def _resolve_raster_access(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    request: Request,
    user: User | None,
) -> tuple[dict, str]:
    """Validate RBAC access to a raster dataset and return row metadata + storage backend.

    Performs the dataset lookup, raster type validation, embed-token / user /
    RBAC checks (3 auth priority branches), and returns the raw SQL row
    mapping together with the resolved storage_backend string.

    Raises HTTPException on any auth or lookup failure.
    """
    # Single query: join datasets + records + raster_assets
    result = await db.execute(
        text(
            """
            SELECT
                r.visibility,
                r.record_status,
                r.created_by,
                r.record_type,
                ra.asset_uri,
                ra.storage_backend,
                ra.band_count,
                ra.dtype,
                ra.is_dem,
                ra.band_info
            FROM catalog.datasets d
            JOIN catalog.records r ON d.record_id = r.id
            LEFT JOIN catalog.raster_assets ra ON ra.dataset_id = d.id
            WHERE d.id = :dataset_id
            """
        ),
        {"dataset_id": dataset_id},
    )
    row = result.mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    if row["record_type"] not in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not a raster dataset"
        )

    if row["asset_uri"] is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No raster asset"
        )

    visibility = row["visibility"]
    record_status = row["record_status"]
    created_by = row["created_by"]
    storage_backend = row["storage_backend"] or "local"

    # Auth priority 1: embed token
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, dataset_id, db, request
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired embed token",
            )
    elif visibility != "public":
        # Auth priority 2: require authenticated user for non-public datasets
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Inline RBAC checks (mirrors check_dataset_access logic)
        user_roles = await get_user_roles(db, user)
        if "admin" not in user_roles:
            # Block non-published datasets for non-owners
            if record_status != "published" and created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )

            if visibility == "private" and created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )

            if visibility == "restricted":
                from app.modules.auth.models import UserRole

                grant_result = await db.execute(
                    select(DatasetGrant.dataset_id)
                    .join(UserRole, DatasetGrant.role_id == UserRole.role_id)
                    .where(
                        DatasetGrant.dataset_id == dataset_id,
                        UserRole.user_id == user.id,
                    )
                )
                if grant_result.scalar_one_or_none() is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Dataset not found",
                    )
    else:
        # Public dataset: still block non-published for unauthenticated users
        if record_status != "published":
            # Unauthenticated users cannot see unpublished public datasets
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )
            # Authenticated non-owners cannot see unpublished
            user_roles = await get_user_roles(db, user)
            if "admin" not in user_roles and created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )

    return row, storage_backend


@router.get("/raster-auth-check/", response_model=None)
@limiter.exempt
async def raster_auth_check(
    request: Request,
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Auth-check endpoint called by nginx auth_request for raster tile serving.

    Validates RBAC access to a raster dataset and returns the COG open-path
    in response headers (which nginx passes to Titiler, never the browser).

    Returns:
        200 with X-GeoLens-Asset-OpenPath and X-GeoLens-Cache-Status headers
        401 if authentication is required but missing
        403 if embed token is invalid
        404 if dataset not found, not a raster, or has no raster asset
    """
    row, storage_backend = await _resolve_raster_access(db, dataset_id, request, user)

    # Resolve COG open-path for Titiler
    asset_uri = row["asset_uri"]
    if storage_backend == "remote":
        # STAC import: asset_uri is already a full URL to a remote COG
        open_path = asset_uri
    elif storage_backend == "s3" and settings.s3_bucket:
        open_path = f"/vsis3/{settings.s3_bucket}/{asset_uri}"
    else:
        open_path = f"{settings.upload_staging_dir}/{asset_uri}"

    cache_status = "public" if row["visibility"] == "public" else "private"
    if row.get("is_dem"):
        # DEM terrain: use terrainrgb algorithm with NO rescale — the algorithm
        # reads raw elevation values and encodes them into RGB channels directly.
        render_params = "algorithm=terrainrgb"
    elif storage_backend == "remote" and row.get("band_info"):
        # Remote STAC import with statistics — use actual data min/max
        # for rescaling instead of fixed dtype max
        bi = row["band_info"]
        bc = row["band_count"] or 1
        parts: list[str] = []
        if bc >= 3:
            parts.extend(["bidx=1", "bidx=2", "bidx=3"])
        for i in range(min(bc, 3) if bc >= 3 else max(bc, 1)):
            if i < len(bi) and bi[i].get("min") is not None:
                parts.append(f"rescale={bi[i]['min']},{bi[i]['max']}")
        render_params = "&".join(parts)
    else:
        render_params = _titiler_render_params(row["band_count"], row["dtype"])

    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "X-GeoLens-Asset-OpenPath": open_path,
            "X-GeoLens-Cache-Status": cache_status,
            "X-GeoLens-Render-Params": render_params,
        },
    )


@router.get("/raster-proxy/{dataset_id}/{z:int}/{x:int}/{y:int}.{fmt}", response_class=Response)
@limiter.exempt
async def raster_tile_proxy(
    request: Request,
    dataset_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.
    """
    # Reuse the auth-check logic to get the open path and render params
    auth_resp = await raster_auth_check(request, dataset_id, user, db)
    open_path = auth_resp.headers.get("X-GeoLens-Asset-OpenPath")
    if not open_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No raster asset"
        )

    render_params = auth_resp.headers.get("X-GeoLens-Render-Params", "")

    titiler_url = f"http://titiler:8000/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.{fmt}"
    if render_params:
        titiler_url = f"{titiler_url}?url={open_path}&{render_params}"
    else:
        titiler_url = f"{titiler_url}?url={open_path}"

    # Retry with exponential backoff for transient failures. httpx.TimeoutException
    # is a subclass of TransportError, but we catch it explicitly to make the
    # intent clear and ensure we never fall through with `resp is None`.
    max_retries = 2
    resp: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await _titiler_client.get(titiler_url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == max_retries:
                # RES-6: log final failure with context before raising so
                # operators can distinguish "titiler down" from normal activity.
                logger.warning(
                    "Raster tile proxy exhausted retries",
                    dataset_id=str(dataset_id),
                    z=z,
                    x=x,
                    y=y,
                    titiler_url=titiler_url,
                    error=str(exc),
                    exc_info=True,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Tile service unavailable",
                )
            # RES-N5: log transient failures at debug level so flaky upstream
            # is observable in verbose logs without spamming production.
            logger.debug(
                "Raster tile proxy transient failure; retrying",
                attempt=attempt,
                dataset_id=str(dataset_id),
                error=str(exc),
            )
            await asyncio.sleep(0.5 * (2**attempt))
            continue
        else:
            if resp.status_code == 503 and attempt < max_retries:
                logger.debug(
                    "Raster tile proxy got 503; retrying",
                    attempt=attempt,
                    dataset_id=str(dataset_id),
                )
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            break

    # Safety guard: if the retry loop somehow exited without assigning resp
    # (should be impossible given the logic above, but protects against future
    # edits), return 503 rather than raising AttributeError.
    if resp is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        )

    if resp.status_code == 404:
        # Tile outside raster extent — empty response
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if resp.status_code != 200:
        # RES-N2: log non-200 responses before converting to HTTPException so
        # upstream titiler failures are diagnosable from logs alone.
        logger.warning(
            "Raster tile fetch returned non-200",
            dataset_id=str(dataset_id),
            z=z,
            x=x,
            y=y,
            status_code=resp.status_code,
            titiler_url=titiler_url,
        )
        raise HTTPException(status_code=resp.status_code, detail="Tile fetch failed")

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=3600"},
    )


def _build_tile_token_for_dataset(
    dataset: Dataset,
) -> VectorTileToken | RasterTileToken:
    """Build a tile token response for a single already-authorized dataset.

    Extracted so both the single-dataset and batch endpoints share the same
    token-generation logic (PERF-N5). Does NOT perform auth — caller must
    ensure the dataset is visible to the current user.
    """
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        bounds = None
        if dataset.record.spatial_extent is not None:
            try:
                shape = to_shape(dataset.record.spatial_extent)
                bounds = list(shape.bounds)  # [xmin, ymin, xmax, ymax]
            except Exception:
                logger.warning(
                    "Failed to parse spatial extent bounds",
                    dataset_id=str(dataset.id),
                )
                bounds = None

        return RasterTileToken(
            kind="raster",
            tile_url=f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png",
            bounds=bounds,
            minzoom=0,
            maxzoom=18,
            tile_size=256,
            format="png",
        )

    # Vector dataset branch
    exp = round_expiry()
    scope = dataset.table_name
    sig = generate_tile_signature(scope, exp)

    return VectorTileToken(
        kind="vector",
        sig=sig,
        exp=exp,
        scope=scope,
        expires_in=exp - int(time.time()),
    )


@router.get("/token/{dataset_id}/", response_model=VectorTileToken | RasterTileToken)
@limiter.exempt
async def get_tile_token(
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> VectorTileToken | RasterTileToken:
    """Generate a tile token for a dataset.

    For vector datasets: returns HMAC-signed token (sig, exp, scope, expires_in).
    For raster datasets: returns tile URL template and metadata.

    Both responses include a discriminated ``kind`` field.

    Public datasets can be accessed without authentication.
    Private/restricted datasets require authentication and RBAC checks.
    """
    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    # Non-public datasets require authentication and RBAC
    if dataset.record.visibility != "public":
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await check_dataset_access(db, dataset, dataset_id, user)

    return _build_tile_token_for_dataset(dataset)


@router.post("/tokens/", response_model=TileTokenBatchResponse)
@limiter.exempt
async def get_tile_tokens_batch(
    body: TileTokenBatchRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> TileTokenBatchResponse:
    """Batch-generate tile tokens for up to 50 datasets in one request.

    Optimization for multi-layer maps: a 20-layer builder map previously
    fired 20 parallel GET /token/{id}/ requests (20 HTTP + 20 RBAC + 20 HMAC
    signatures). This endpoint does the same work in a single round trip
    with one DB query for dataset metadata (PERF-N5).

    Per-dataset errors (404, 403) do not fail the batch — instead the
    response maps the offending dataset_id to ``{"error": "..."}``. Clients
    should check each entry for the ``error`` key.
    """
    # De-duplicate while preserving order
    unique_ids = list(dict.fromkeys(body.dataset_ids))

    # Single bulk query for all requested datasets
    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id.in_(unique_ids))
    )
    datasets_by_id = {ds.id: ds for ds in result.scalars().all()}

    tokens: dict[str, VectorTileToken | RasterTileToken | dict] = {}
    for dataset_id in unique_ids:
        dataset = datasets_by_id.get(dataset_id)
        key = str(dataset_id)
        if dataset is None:
            tokens[key] = {"error": "Dataset not found"}
            continue

        # Per-dataset auth check
        if dataset.record.visibility != "public":
            if user is None:
                tokens[key] = {"error": "Authentication required"}
                continue
            try:
                await check_dataset_access(db, dataset, dataset_id, user)
            except HTTPException as exc:
                tokens[key] = {"error": exc.detail}
                continue

        tokens[key] = _build_tile_token_for_dataset(dataset)

    return TileTokenBatchResponse(tokens=tokens)


@router.get("/{table_path:path}/{z:int}/{x:int}/{y:int}.pbf")
@limiter.exempt
async def tile_endpoint(
    request: Request,
    table_path: str,
    z: int,
    x: int,
    y: int,
    sig: str | None = None,
    exp: int | None = None,
    scope: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.
    """
    # Parse table_path: must start with "data."
    if not table_path.startswith("data."):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table path must start with 'data.'",
        )

    table_name = table_path[5:]  # Strip "data." prefix

    if not table_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Table name is required"
        )

    # Validate table name against SQL injection
    if not _TABLE_NAME_RE.match(table_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid table name"
        )

    # Validate zoom level
    if z < 0 or z > 22:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Zoom level must be 0-22"
        )

    # Validate x/y bounds for the zoom level
    max_tile = (1 << z) - 1  # 2^z - 1
    if x < 0 or x > max_tile or y < 0 or y > max_tile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tile coordinates out of range",
        )

    # Look up dataset metadata — use in-memory cache to avoid DB hit per tile
    now = time.monotonic()
    meta: _DatasetMeta | None = None
    with _dataset_cache_lock:
        cached_entry = _dataset_cache.get(table_name)
        if cached_entry is not None:
            ts, cached_meta = cached_entry
            if now - ts < _DATASET_CACHE_TTL:
                meta = cached_meta

    if meta is None:
        result = await db.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.table_name == table_name)
        )
        dataset = result.scalar_one_or_none()

        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )

        meta = _DatasetMeta(
            dataset_id=dataset.id,
            record_id=dataset.record_id,
            table_name=dataset.table_name,
            visibility=dataset.record.visibility,
            column_info=dataset.column_info or [],
            tile_cache_ttl=dataset.tile_cache_ttl,
        )
        with _dataset_cache_lock:
            _dataset_cache[table_name] = (now, meta)

    # Embed token auth (check before HMAC)
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, meta.dataset_id, db, request
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired embed token, or dataset not in scope",
            )
        # Valid embed token -- skip HMAC check, proceed to tile serving
    elif meta.visibility != "public":
        # Existing HMAC signature check (unchanged)
        if not sig or not exp or not scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Signature required for non-public tiles",
            )
        if scope != table_name:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Scope mismatch"
            )
        if not verify_tile_signature(scope, exp, sig):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired signature",
            )

    # Get column info for attribute selection
    columns = meta.column_info

    # Use per-dataset cache TTL when set, else global default
    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl
    cache_scope = "private" if embed_token_header else "public"

    # Check tile cache before hitting PostGIS
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        cached = await tile_cache.get(table_name, z, x, y)
        if cached is not None:
            if len(cached) == 0:
                # Empty sentinel — tile was previously confirmed empty
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            return Response(
                content=cached,
                media_type="application/vnd.mapbox-vector-tile",
                headers={
                    "Content-Encoding": "gzip",
                    "Cache-Control": f"{cache_scope}, max-age={cache_ttl}",
                    "Access-Control-Allow-Origin": "*",
                },
            )

    # Get tile from PostGIS.
    # RES-5 / RES-N7: catch pool exhaustion and DB errors explicitly so that
    # a vector-tile query failure doesn't surface as a raw 500 to the client
    # (which would break every layer on the map at once). Pool exhaustion →
    # 429 (retryable); other errors → 503.
    try:
        pool = get_tile_pool()
    except RuntimeError as exc:
        logger.warning(
            "Tile pool unavailable",
            table_name=table_name,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        )

    try:
        tile_data = await get_tile(pool, table_name, z, x, y, columns)
    except asyncio.TimeoutError:
        logger.warning(
            "Tile pool acquire timeout",
            table_name=table_name,
            z=z,
            x=x,
            y=y,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tile service busy, please retry",
            headers={"Retry-After": "2"},
        )
    except Exception as exc:
        logger.exception(
            "Vector tile query failed",
            table_name=table_name,
            z=z,
            x=x,
            y=y,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        )

    if tile_data is None:
        # Cache empty tiles to avoid repeated PostGIS queries for sparse datasets
        if tile_cache is not None:
            await tile_cache.set(table_name, z, x, y, b"", ttl=cache_ttl)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Log successful tile access
    logger.debug(
        "tile_access",
        dataset_id=str(meta.record_id),
        table_name=table_name,
        z=z,
        x=x,
        y=y,
        scope=scope or "public",
    )

    # Compress and return with proper headers
    compressed = gzip.compress(tile_data, compresslevel=6)

    # Cache the compressed tile bytes for subsequent requests
    if tile_cache is not None:
        await tile_cache.set(table_name, z, x, y, compressed, ttl=cache_ttl)

    return Response(
        content=compressed,
        media_type="application/vnd.mapbox-vector-tile",
        headers={
            "Content-Encoding": "gzip",
            "Cache-Control": f"{cache_scope}, max-age={cache_ttl}",
            "Access-Control-Allow-Origin": "*",
        },
    )

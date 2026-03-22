"""FastAPI tile endpoint serving vector tiles via PostGIS ST_AsMVT."""

import gzip
import re
import time
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from geoalchemy2.shape import to_shape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.auth.visibility import check_dataset_access, get_user_roles
from app.config import settings
from app.datasets.models import Dataset, DatasetGrant
from app.dependencies import get_db
from app.embed_tokens.service import validate_embed_token_access
from app.cache.provider import get_tile_cache
from app.tiles.pool import get_tile_pool
from app.tiles.service import get_tile
from app.auth.router import limiter
from app.tiles.signing import (
    generate_tile_signature,
    round_expiry,
    verify_tile_signature,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/tiles", tags=["Tiles"])

_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


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


@router.get("/raster-auth-check/")
@limiter.exempt
async def raster_auth_check(
    request: Request,
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Auth-check endpoint called by nginx auth_request for raster tile serving.

    Validates RBAC access to a raster dataset and returns the COG open-path
    in response headers (which nginx passes to Titiler, never the browser).

    Returns:
        200 with X-GeoLens-Asset-OpenPath and X-GeoLens-Cache-Status headers
        401 if authentication is required but missing
        403 if embed token is invalid
        404 if dataset not found, not a raster, or has no raster asset
    """
    # Single query: join datasets + records + raster_assets
    row = await db.execute(
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
                ra.dtype
            FROM catalog.datasets d
            JOIN catalog.records r ON d.record_id = r.id
            LEFT JOIN catalog.raster_assets ra ON ra.dataset_id = d.id
            WHERE d.id = :dataset_id
            """
        ),
        {"dataset_id": dataset_id},
    )
    row = row.mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if row["record_type"] not in ("raster_dataset", "vrt_dataset"):
        raise HTTPException(status_code=404, detail="Not a raster dataset")

    if row["asset_uri"] is None:
        raise HTTPException(status_code=404, detail="No raster asset")

    visibility = row["visibility"]
    record_status = row["record_status"]
    created_by = row["created_by"]
    asset_uri = row["asset_uri"]
    storage_backend = row["storage_backend"] or "local"

    # Auth priority 1: embed token
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, dataset_id, db, request
        )
        if not is_valid:
            raise HTTPException(
                status_code=403,
                detail="Invalid or expired embed token",
            )
    elif visibility != "public":
        # Auth priority 2: require authenticated user for non-public datasets
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Inline RBAC checks (mirrors check_dataset_access logic)
        user_roles = await get_user_roles(db, user)
        if "admin" not in user_roles:
            # Block non-published datasets for non-owners
            if record_status != "published" and created_by != user.id:
                raise HTTPException(status_code=404, detail="Dataset not found")

            if visibility == "private" and created_by != user.id:
                raise HTTPException(status_code=404, detail="Dataset not found")

            if visibility == "restricted":
                from app.auth.models import UserRole

                grant_result = await db.execute(
                    select(DatasetGrant.dataset_id)
                    .join(UserRole, DatasetGrant.role_id == UserRole.role_id)
                    .where(
                        DatasetGrant.dataset_id == dataset_id,
                        UserRole.user_id == user.id,
                    )
                )
                if grant_result.scalar_one_or_none() is None:
                    raise HTTPException(status_code=404, detail="Dataset not found")
    else:
        # Public dataset: still block non-published for unauthenticated users
        if record_status != "published":
            # Unauthenticated users cannot see unpublished public datasets
            if user is None:
                raise HTTPException(status_code=404, detail="Dataset not found")
            # Authenticated non-owners cannot see unpublished
            user_roles = await get_user_roles(db, user)
            if "admin" not in user_roles and created_by != user.id:
                raise HTTPException(status_code=404, detail="Dataset not found")

    # Resolve COG open-path for Titiler
    if storage_backend == "s3" and settings.s3_bucket:
        open_path = f"/vsis3/{settings.s3_bucket}/{asset_uri}"
    else:
        open_path = f"{settings.upload_staging_dir}/{asset_uri}"

    cache_status = "public" if visibility == "public" else "private"
    render_params = _titiler_render_params(row["band_count"], row["dtype"])

    return Response(
        status_code=200,
        headers={
            "X-GeoLens-Asset-OpenPath": open_path,
            "X-GeoLens-Cache-Status": cache_status,
            "X-GeoLens-Render-Params": render_params,
        },
    )


@router.get("/raster-proxy/{dataset_id}/{z:int}/{x:int}/{y:int}.{fmt}")
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
):
    """API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.
    """
    import httpx

    # Reuse the auth-check logic to get the open path and render params
    auth_resp = await raster_auth_check(request, dataset_id, user, db)
    open_path = auth_resp.headers.get("X-GeoLens-Asset-OpenPath")
    if not open_path:
        raise HTTPException(status_code=404, detail="No raster asset")

    render_params = auth_resp.headers.get("X-GeoLens-Render-Params", "")

    titiler_url = f"http://titiler:8000/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.{fmt}"
    if render_params:
        titiler_url = f"{titiler_url}?url={open_path}&{render_params}"
    else:
        titiler_url = f"{titiler_url}?url={open_path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(titiler_url)

    if resp.status_code == 404:
        # Tile outside raster extent — empty response
        return Response(status_code=204)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Tile fetch failed")

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/token/{dataset_id}/")
@limiter.exempt
async def get_tile_token(
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
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
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Non-public datasets require authentication and RBAC
    if dataset.record.visibility != "public":
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await check_dataset_access(db, dataset, dataset_id, user)

    # Raster dataset branch (also handles vrt_dataset — same tile serving path)
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        bounds = None
        if dataset.record.spatial_extent is not None:
            try:
                shape = to_shape(dataset.record.spatial_extent)
                bounds = list(shape.bounds)  # [xmin, ymin, xmax, ymax]
            except Exception:
                bounds = None

        return {
            "kind": "raster",
            "tile_url": f"/raster-tiles/{dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png",
            "bounds": bounds,
            "minzoom": 0,
            "maxzoom": 18,
            "tile_size": 256,
            "format": "png",
        }

    # Vector dataset branch (unchanged, kind added for discriminated union)
    exp = round_expiry()
    scope = dataset.table_name
    sig = generate_tile_signature(scope, exp)

    return {
        "kind": "vector",
        "sig": sig,
        "exp": exp,
        "scope": scope,
        "expires_in": exp - int(time.time()),
    }


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
):
    """Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.
    """
    # Parse table_path: must start with "data."
    if not table_path.startswith("data."):
        raise HTTPException(
            status_code=404, detail="Table path must start with 'data.'"
        )

    table_name = table_path[5:]  # Strip "data." prefix

    if not table_name:
        raise HTTPException(status_code=404, detail="Table name is required")

    # Validate table name against SQL injection
    if not _TABLE_NAME_RE.match(table_name):
        raise HTTPException(status_code=400, detail="Invalid table name")

    # Validate zoom level
    if z < 0 or z > 22:
        raise HTTPException(status_code=400, detail="Zoom level must be 0-22")

    # Validate x/y bounds for the zoom level
    max_tile = (1 << z) - 1  # 2^z - 1
    if x < 0 or x > max_tile or y < 0 or y > max_tile:
        raise HTTPException(status_code=400, detail="Tile coordinates out of range")

    # Look up dataset with eagerly loaded Record for visibility check
    result = await db.execute(
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.table_name == table_name)
    )
    dataset = result.scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Embed token auth (check before HMAC)
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, dataset.id, db, request
        )
        if not is_valid:
            raise HTTPException(
                status_code=403,
                detail="Invalid or expired embed token, or dataset not in scope",
            )
        # Valid embed token -- skip HMAC check, proceed to tile serving
    elif dataset.record.visibility != "public":
        # Existing HMAC signature check (unchanged)
        if not sig or not exp or not scope:
            raise HTTPException(
                status_code=403, detail="Signature required for non-public tiles"
            )
        if scope != table_name:
            raise HTTPException(status_code=403, detail="Scope mismatch")
        if not verify_tile_signature(scope, exp, sig):
            raise HTTPException(status_code=403, detail="Invalid or expired signature")

    # Get column info for attribute selection
    columns = dataset.column_info or []

    # Use per-dataset cache TTL when set, else global default
    cache_ttl = dataset.tile_cache_ttl or settings.tile_cache_ttl
    cache_scope = "private" if embed_token_header else "public"

    # Check tile cache before hitting PostGIS
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        cached = await tile_cache.get(table_name, z, x, y)
        if cached is not None:
            return Response(
                content=cached,
                media_type="application/vnd.mapbox-vector-tile",
                headers={
                    "Content-Encoding": "gzip",
                    "Cache-Control": "no-cache",
                    "Access-Control-Allow-Origin": "*",
                },
            )

    # Get tile from PostGIS
    pool = get_tile_pool()
    tile_data = await get_tile(pool, table_name, z, x, y, columns)

    if tile_data is None:
        return Response(status_code=204)

    # Log successful tile access
    logger.info(
        "tile_access",
        dataset_id=str(dataset.record_id),
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

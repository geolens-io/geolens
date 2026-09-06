"""FastAPI tile endpoint serving vector tiles via PostGIS ST_AsMVT."""

import asyncio
import gzip
import math
import threading
import time
import uuid
from typing import Any, Literal, NamedTuple
from urllib.parse import parse_qs, urlencode

import httpx
import structlog
from cachetools import LRUCache
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.url_redaction import redact_exception_text
from app.core.geo import (
    extent_lon_span,
    extent_to_span_bbox,
    wkt_has_degree_unit,
    wkt_is_geographic,
)
from app.core.identity import Identity
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.modules.auth.dependencies import (
    capability_declined,
    get_optional_user,
    get_optional_user_fail_open,
    reject_unresolvable_credentials,
)
from app.core.config import settings
from app.core.dependencies import get_db
from app.modules.embed_tokens.service import validate_embed_token_access
from app.platform.cache.provider import (
    get_tile_cache,
    register_table_invalidation_listener,
)
from app.platform.extensions import (
    get_billing_extensions,
    get_data_serving_extension,
    get_processing_port,
)
from app.platform.service_endpoints import MAX_QUERY_FIELDS
from app.platform.storage.titiler_url import build_titiler_cog_url, resolve_open_path
from app.processing.raster.models import RasterAsset
from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant
from app.processing.tiles.pool import get_tile_pool, set_tenant_role_for_tile_request
from app.processing.tiles.responses import (
    _empty_tile_headers as _empty_tile_headers,
    _if_none_match_satisfied as _if_none_match_satisfied,
    _serving_tile_headers,
    _tile_etag as _tile_etag,
    _tile_headers as _tile_headers,
    _tile_response,
)
from app.processing.tiles.service import (
    _TABLE_NAME_RE,
    get_cluster_tile,
    get_tile,
    parse_cols_param,
)
from app.platform.ratelimit import limiter
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
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC, RATE_LIMIT_RESPONSE

logger = structlog.stdlib.get_logger(__name__)

# Provider-neutral data-serving hooks. Community resolves a no-op extension;
# hosted deployments register their implementation through geolens.extensions.


def _get_tile_serving_controls(tenant_id: str):  # type: ignore[no-untyped-def]
    """Return the registered concurrency limiter and cache-policy override."""
    extension = get_data_serving_extension()
    return (
        extension.get_tile_concurrency_limiter(tenant_id),
        extension.get_tile_cache_control(),
    )


async def _emit_tile_usage_event(table_name: str) -> None:
    """Emit a tile-request usage event through the billing-import-free seam.

    Called after a successful vector or cluster tile serve in multi_tenant mode;
    nothing runs when no extension provides ``on_usage_event``. Best-effort:
    errors are logged and swallowed, because a billing hook failure must never
    fail a tile response. ``table_name`` rides on the event so the
    cloud extension can scope its ``last_accessed_at`` update to the right row.
    """
    if not is_multi_tenant():
        return
    tenant_id = current_tenant_var.get(None)
    if tenant_id is None:
        return
    for ext in get_billing_extensions():
        if not hasattr(ext, "on_usage_event"):
            continue
        try:
            await ext.on_usage_event(  # type: ignore[attr-defined]
                tenant_id=str(tenant_id),
                dimension="tile_requests",
                value=1,
                table_name=table_name,
            )
        except Exception:  # broad: billing hook failures must never fail a tile response; varied extension errors
            logger.warning(
                "tile usage event dispatch failed",
                ext=type(ext).__name__,
                table_name=table_name,
                exc_info=True,
            )


async def _check_cold_rehydrate(
    table_name: str,
    record_status: str,
    tenant_id: str,
) -> "Response | None":
    """Prepare a cold table through the provider-neutral serving seam.

    Returns None when *record_status* is not ``cold`` (the hot path, zero
    overhead), when not multi-tenant, and when the overlay reports the dataset
    hot or hydrates it inline. Returns a 202 JSON Response when the table is
    over the size gate and an async rehydrate is enqueued. A cold-check
    failure is logged and returns None: it must NEVER fail a tile response.

    ``record_status`` is the value ``_resolve_dataset_meta`` already cached, so
    the hot path costs no extra DB round-trip. ``tenant_id`` is the
    server-resolved UUID string from ``current_tenant_var``.
    """
    import json

    if record_status != "cold":
        return None

    if not is_multi_tenant():
        return None

    try:
        result = await get_data_serving_extension().prepare_table_for_read(
            table_name=table_name,
            tenant_id=tenant_id,
        )
    except (
        Exception
    ):  # broad: cold-check failure must NEVER fail a tile response (T-1214-17)
        logger.warning(
            "cold_rehydrate_check_failed",
            table_name=table_name,
            tenant_id=tenant_id,
            exc_info=True,
        )
        return None

    if result is None:
        # Dataset resolved as hot by the overlay (non-cold record_status).
        return None

    if result.status == "warming":
        # Over size gate: async rehydrate enqueued; inform the client to poll.
        return Response(
            content=json.dumps({"status": "warming", "job_id": result.job_id}),
            status_code=202,
            media_type="application/json",
        )

    # status='hydrated': sync rehydrate completed inline — proceed to serve the tile.
    return None


router = APIRouter(prefix="/tiles", tags=["Tiles"], responses=ERROR_RESPONSES_PUBLIC)

# `_TABLE_NAME_RE` is imported from tiles.service rather
# than re-declared, so the SQL-injection-defense regex has exactly one definition.

# fix(#1927) SEC-OBSV-01: `follow_redirects=True` holds while Titiler is
# internal-only (no `ports:` in docker-compose.yml) and every URL here is
# server-derived; otherwise this must move to `make_safe_client`.
_titiler_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
    follow_redirects=True,
)

# In-memory TTL cache for dataset metadata: one DB read per TTL, not per tile.
_DATASET_CACHE_TTL = 60  # seconds


class _DatasetMeta(NamedTuple):
    """Plain data extracted from Dataset+Record for tile serving."""

    dataset_id: uuid.UUID
    record_id: uuid.UUID
    table_name: str
    visibility: str
    record_status: str
    created_by: uuid.UUID
    record_type: str
    geometry_type: str | None
    column_info: list
    tile_cache_ttl: int | None
    # Phase 269 H-23: tile column allowlist (None / [] / list[str]).
    tile_columns: list[str] | None


# Bounded LRU so a long-lived tile worker cannot grow one entry per
# distinct table_name forever; the per-entry TTL still bounds staleness.
_dataset_cache: LRUCache[str, tuple[float, _DatasetMeta]] = LRUCache(maxsize=256)
# threading.Lock is safe here — cache reads/writes are synchronous, no await inside lock
_dataset_cache_lock = threading.Lock()


def _evict_dataset_meta(table_name: str) -> None:
    """Drop every cached meta entry for a table name.

    This cache decides authorization -- visibility, record_status
    and created_by are read from the snapshot rather than re-queried.

    GH-1443 retires a freed table name and `generate_table_name`
    collides against it, so a surviving entry can only describe its own
    dataset. This eviction buys freshness, not the authorization boundary.

    Both key shapes are swept -- bare ``table_name`` in single-tenant and
    ``{tid}:{table_name}`` in multi-tenant -- because a process can hold entries
    from before a mode transition and a delete arrives with only the name.
    """
    suffix = f":{table_name}"
    with _dataset_cache_lock:
        stale = [
            key for key in _dataset_cache if key == table_name or key.endswith(suffix)
        ]
        for key in stale:
            _dataset_cache.pop(key, None)


register_table_invalidation_listener(_evict_dataset_meta)

# Short-TTL cache for raster dataset/asset metadata. The whole row is
# cached INCLUDING visibility and record_status, so a dataset made private or
# unpublished is still served anonymously for up to the TTL. Keep it short.
_RASTER_META_CACHE_TTL = 60  # seconds — same TTL as the vector cache


class _RasterMeta(NamedTuple):
    """Snapshot of raster dataset+record+asset fields for tile serving,
    including the mutable access-control fields; `_RASTER_META_CACHE_TTL`
    states the bounded-staleness tradeoff."""

    visibility: str
    record_status: str
    created_by: uuid.UUID
    record_type: str
    asset_uri: str
    storage_backend: str
    band_count: int | None
    dtype: str | None
    is_dem: bool | None
    band_info: list | None
    nodata: str | None
    tile_cache_version: int


# Bounded LRU mirroring the vector `_dataset_cache`. An
# unbounded dict here holds one `_RasterMeta` -- an asset_uri string and a
# band_info list -- per distinct raster for the life of the worker.
_raster_meta_cache: LRUCache[str, tuple[float, _RasterMeta]] = LRUCache(maxsize=256)
_raster_meta_cache_lock = threading.Lock()


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

_WEB_MERCATOR_EQUATOR_RESOLUTION_M = 156543.03392804097
_DEFAULT_RASTER_MAXZOOM = 18
_MAX_RASTER_MAXZOOM = 22

# Issue #186: the canonical DEM nodata sentinel, for a DEM COG that declares
# none. Under terrainrgb an undeclared fill of -9999 encodes as an extreme
# elevation, spiking the DEM boundary; -9999 is below any real terrain.
_DEM_DEFAULT_NODATA = "-9999"


def _dem_nodata_param(recorded_nodata: str | None) -> str | None:
    """Resolve the Titiler ``nodata=`` value for a DEM terrainrgb tile.

    Prefers the dataset's recorded nodata (captured from the COG at ingest) and
    falls back to the canonical ``-9999`` sentinel. Returns ``None`` only for a
    non-numeric recorded value, where Titiler must rely on the COG's internal
    mask rather than an injected literal.
    """
    raw = (recorded_nodata or "").strip()
    candidate = raw if raw else _DEM_DEFAULT_NODATA
    try:
        value = float(candidate)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        # NaN/inf nodata is handled by the COG's internal mask, not a query param.
        return None
    # An integer literal when the value is integral (-9999, not -9999.0), which
    # keeps the URL clean and matches the DEM convention.
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _positive_number(value: Any) -> float | None:
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _degrees_resolution_to_meters(
    x_degrees: float | None,
    y_degrees: float | None,
    bounds: list[float] | None,
) -> list[float]:
    """Approximate WGS84 pixel resolution in meters at the raster's latitude."""
    center_lat = 0.0
    if bounds and len(bounds) == 4:
        center_lat = (bounds[1] + bounds[3]) / 2
    lat_factor = 111_320.0
    lon_factor = lat_factor * max(math.cos(math.radians(center_lat)), 0.01)

    values: list[float] = []
    if x_degrees is not None:
        values.append(x_degrees * lon_factor)
    if y_degrees is not None:
        values.append(y_degrees * lat_factor)
    return values


def _native_resolution_meters(
    asset: RasterAsset | None,
    bounds: list[float] | None,
    *,
    lon_span: float | None = None,
) -> float | None:
    """Estimate native raster resolution in meters from stored COG metadata.

    ``lon_span`` is the extent's honest longitudinal width (``extent_lon_span``).
    ``bounds`` is deliberately the monotonic span bbox, which reads
    -180..180 for a seam-crossing extent, so the width has to arrive separately
    or a 10°-wide Pacific raster measures 360° and collapses its own maxzoom.
    """
    if asset is None:
        return None

    res_x = _positive_number(asset.res_x)
    res_y = _positive_number(asset.res_y)
    values: list[float] = []

    if res_x is not None or res_y is not None:
        # fix(#939): "is this resolution in degrees?" is not an EPSG equality
        # test -- 4269, 4258, 4979 and 9518 store degrees too, and reading those
        # as metres pinned maxzoom to the cap (ETOPO got z22 instead of z7).
        geographic = wkt_is_geographic(asset.crs_wkt)
        if geographic is None:
            # No usable WKT stored: fall back to the historical EPSG test.
            geographic = asset.epsg == 4326
        if geographic:
            if wkt_has_degree_unit(asset.crs_wkt) is not False:
                values.extend(_degrees_resolution_to_meters(res_x, res_y, bounds))
            # else: geographic with a non-degree angular unit (grads). Neither
            # metres nor degrees, so let the bounds estimate below take over.
        else:
            # Ingest normally stores COGs in metre-based CRSs. For an
            # unsupported projected CRS this still beats a universal z18.
            values.extend(v for v in (res_x, res_y) if v is not None)

    if not values and bounds and len(bounds) == 4 and asset.width and asset.height:
        minx, miny, maxx, maxy = bounds
        span_x = _positive_number(lon_span if lon_span is not None else maxx - minx)
        span_y = _positive_number(maxy - miny)
        x_deg = span_x / asset.width if span_x else None
        y_deg = span_y / asset.height if span_y else None
        values.extend(_degrees_resolution_to_meters(x_deg, y_deg, bounds))

    return min(values) if values else None


def _raster_maxzoom_from_metadata(
    asset: RasterAsset | None,
    bounds: list[float] | None,
    *,
    lon_span: float | None = None,
) -> int:
    """Choose raster source maxzoom from native resolution, with legacy fallback."""
    resolution_m = _native_resolution_meters(asset, bounds, lon_span=lon_span)
    if resolution_m is None:
        return _DEFAULT_RASTER_MAXZOOM

    zoom = math.ceil(math.log2(_WEB_MERCATOR_EQUATOR_RESOLUTION_M / resolution_m))
    return max(0, min(_MAX_RASTER_MAXZOOM, zoom))


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
        n_bands = min(bc, 3) if bc >= 3 else (1 if bc == 2 else bc)
        for _ in range(max(n_bands, 1)):
            parts.append(f"rescale={rescale}")

    return "&".join(parts)


# Colormap / stretch allowlists.

# 8 curated Titiler colormap names from the UI-SPEC. Validated against the
# running Titiler instance (see 1140-RESEARCH.md Finding 5).
_ALLOWED_COLORMAPS: frozenset[str] = frozenset(
    {"gray", "viridis", "inferno", "plasma", "magma", "ylorrd", "bugn", "terrain"}
)

# Accepted stretch strategies. minmax (default) keeps the dtype-based rescale;
# percentile/stddev compute a stats-based rescale from Titiler band statistics
# (RASTER-STRETCH-01/02). Single-band scope; multi-band is Future RASTER-STRETCH-03.
_ALLOWED_STRETCH: frozenset[str] = frozenset({"minmax", "percentile", "stddev"})

# stddev stretch uses mean ± _STDDEV_SIGMA·σ, clamped to the band [min, max].
_STDDEV_SIGMA = 2.0

# Per-band Titiler statistics cache keyed by (open_path, pmin, pmax): the bounds
# are in the key so a p2/p98 lookup never serves stale stats for a p5/p95
# request. A bounded LRU, so a long-lived tile worker stays bounded.
_band_stats_cache: LRUCache[tuple, list[dict] | None] = LRUCache(maxsize=256)


def _percentile_key(value: float) -> str:
    """Format a percentile float for use as a Titiler response key.

    Titiler returns ``percentile_2`` (int-like) and ``percentile_5`` rather than
    ``percentile_2.0`` or ``percentile_5.0``. Drop the trailing ``.0`` for whole
    numbers so the key lookup matches the actual response.
    """
    if value == int(value):
        return f"percentile_{int(value)}"
    return f"percentile_{value}"


async def _fetch_band_statistics(
    open_path: str, pmin: float, pmax: float
) -> list[dict] | None:
    """Fetch per-band statistics from Titiler /cog/statistics (cached by open_path + bounds).

    The cache key is ``(open_path, pmin, pmax)``, so different percentile clips
    never serve results from a prior lookup with different bounds. Returns
    per-band stat dicts ordered b1, b2, ... or None when the call fails, in
    which case the caller falls back to minmax.
    """
    cache_key = (open_path, pmin, pmax)
    if cache_key in _band_stats_cache:
        return _band_stats_cache[cache_key]
    # Forward pmin/pmax as repeated p= params (e.g. p=5&p=95). Use integer
    # representation for whole numbers to match Titiler's expected format.
    pmin_str = str(int(pmin)) if pmin == int(pmin) else str(pmin)
    pmax_str = str(int(pmax)) if pmax == int(pmax) else str(pmax)
    stats_url = build_titiler_cog_url(
        "statistics",
        query={"url": open_path},
        raw_query_suffix=f"p={pmin_str}&p={pmax_str}",
    )
    bands: list[dict] | None = None
    try:
        resp = await _titiler_client.get(stats_url)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data:
                # Titiler keys bands "b1","b2",... — order by the numeric suffix.
                bands = [
                    data[k]
                    for k in sorted(
                        data, key=lambda k: int(k[1:]) if k[1:].isdigit() else 0
                    )
                ]
    except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError):
        bands = None
    _band_stats_cache[cache_key] = bands
    return bands


def _compute_stretch_rescale(
    bands: list[dict],
    stretch: str,
    n_bands: int,
    *,
    pmin: float,
    pmax: float,
    sigma: float,
) -> list[str]:
    """Compute Titiler ``rescale=lo,hi`` fragments from band statistics.

    percentile → [percentile_<pmin>, percentile_<pmax>] read dynamically from
    the band stats dict so custom bounds produce correct rescale values.
    stddev → [mean ± sigma·σ] clamped to [min, max].

    Returns one fragment per band (up to n_bands); empty when stats are
    insufficient (caller falls back to minmax).
    """
    pmin_key = _percentile_key(pmin)
    pmax_key = _percentile_key(pmax)
    parts: list[str] = []
    for i in range(n_bands):
        if i >= len(bands):
            break
        b = bands[i]
        if stretch == "percentile":
            lo = b.get(pmin_key)
            hi = b.get(pmax_key)
        else:  # stddev
            mean = b.get("mean")
            std = b.get("std")
            if mean is None or std is None:
                continue
            lo = mean - sigma * std
            hi = mean + sigma * std
            bmin, bmax = b.get("min"), b.get("max")
            if bmin is not None:
                lo = max(lo, bmin)
            if bmax is not None:
                hi = min(hi, bmax)
        if lo is None or hi is None or not (lo < hi):
            continue
        # Round to 4 dp — Titiler does not need full float precision and clean
        # values keep the tile-URL cache key stable.
        parts.append(f"rescale={round(lo, 4)},{round(hi, 4)}")
    return parts


def _apply_stretch_rescale(render_params: str, rescale_parts: list[str]) -> str:
    """Replace any existing ``rescale=`` fragments in render_params with rescale_parts."""
    kept = [p for p in render_params.split("&") if p and not p.startswith("rescale=")]
    return "&".join(kept + rescale_parts)


def _is_publicly_cacheable(visibility: str | None, record_status: str | None) -> bool:
    """Whether a tile may be stored in the shared (auth-less) cache.

    Only a dataset that is BOTH public AND published is safe to cache publicly.
    A public-but-unpublished dataset is an owner/admin-only preview: marking its
    tiles `public` would populate the auth-less nginx cache key and replay them
    to later anonymous requests.
    """
    return visibility == "public" and record_status == "published"


def _require_tile_tenant_context() -> str | None:
    """Return the resolved tenant id or fail before any multi-tenant tile read.

    RLS remains the database backstop, but an unresolved multi-tenant request
    must not enter a bare metadata cache/query path or fall back to the shared
    ``data`` schema. Single-tenant behavior remains unchanged (``None``).
    """
    if not is_multi_tenant():
        return None
    tenant_id = current_tenant_var.get()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is required for tile access",
        )
    return tenant_id


def _meta_cache_version_segment(raw: str | None) -> str | None:
    """Normalize a request's ``v`` into a raster meta cache-key segment.

    ``tile_cache_version`` is a small monotonic integer, so only a short ASCII
    digit run is accepted. Anything else returns None, which puts the caller
    back on the unversioned key, where staleness is bounded by the 60s TTL
    instead, never on an error.
    """
    if raw is None or not (0 < len(raw) <= 10):
        return None
    if not (raw.isascii() and raw.isdigit()):
        return None
    return raw


async def _resolve_raster_meta(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    requested_version: str | None = None,
) -> _RasterMeta:
    """Look up raster dataset/asset metadata with a short in-memory cache.

    The cached snapshot INCLUDES the access-control fields, so a
    visibility or status change takes effect only after the entry expires -- at
    most ``_RASTER_META_CACHE_TTL`` seconds, the same bounded window as the
    vector path.

    Multi-tenant cache keys carry the resolved tenant UUID and the SQL filters
    ``catalog.datasets.tenant_id`` explicitly; an unresolved tenant fails before
    either. ``requested_version`` is the request's ``v`` and only reaches the
    cache key.

    Raises HTTPException(404) when the dataset is missing, is not a raster, or
    has no raster asset.
    """
    tenant_id = _require_tile_tenant_context()
    base_key = f"{tenant_id}:{dataset_id}" if tenant_id is not None else str(dataset_id)
    # fix(#1329): LOOK UP under the REQUEST's `v`. The row's version reaches
    # this function only through the snapshot below, so it is exactly as stale
    # as the `asset_uri` it would guard; the STORE is under the row's version.
    version_segment = _meta_cache_version_segment(requested_version)
    cache_key = (
        f"{base_key}:v{version_segment}" if version_segment is not None else base_key
    )
    now = time.monotonic()
    with _raster_meta_cache_lock:
        cached_entry = _raster_meta_cache.get(cache_key)
        if cached_entry is not None:
            ts, cached_meta = cached_entry
            if now - ts < _RASTER_META_CACHE_TTL:
                return cached_meta

    tenant_filter = (
        "\n              AND d.tenant_id = :tenant_id" if tenant_id is not None else ""
    )
    params: dict[str, Any] = {"dataset_id": dataset_id}
    if tenant_id is not None:
        params["tenant_id"] = uuid.UUID(tenant_id)
    result = await db.execute(
        text(
            f"""
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
                ra.band_info,
                ra.nodata,
                d.tile_cache_version
            FROM catalog.datasets d
            JOIN catalog.records r ON d.record_id = r.id
            LEFT JOIN catalog.raster_assets ra ON ra.dataset_id = d.id
            WHERE d.id = :dataset_id{tenant_filter}
            """
        ),
        params,
    )
    row = result.mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    if row["record_type"] not in RASTER_FAMILY_RECORD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not a raster dataset"
        )

    if row["asset_uri"] is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No raster asset"
        )

    meta = _RasterMeta(
        visibility=row["visibility"],
        record_status=row["record_status"],
        created_by=row["created_by"],
        record_type=row["record_type"],
        asset_uri=row["asset_uri"],
        storage_backend=row["storage_backend"] or "local",
        band_count=row["band_count"],
        dtype=row["dtype"],
        is_dem=row["is_dem"],
        band_info=row["band_info"],
        nodata=row["nodata"],
        tile_cache_version=row["tile_cache_version"] or 1,
    )
    # fix(#1329 P1): the write key comes from the SNAPSHOT's own version. Under
    # the requested one, `v=N+1` against a row at N parks the CURRENT snapshot
    # on that key, and it survives the swap for a full TTL.
    store_key = (
        f"{base_key}:v{meta.tile_cache_version}"
        if version_segment is not None
        else base_key
    )
    with _raster_meta_cache_lock:
        _raster_meta_cache[store_key] = (now, meta)
    return meta


def _tile_signature_authorizes(request: Request, dataset_id: uuid.UUID) -> bool:
    """Whether the caller presented a VALID signed template for this dataset.

    The mirror of the vector verify path. The expected scope is
    recomputed with the SAME ``tenant_bound_scope(str(dataset.id))`` expression
    the mint site uses, because a divergence is a silent authorization bypass
    rather than a test failure. A raster dataset has no ``table_name``, so the
    dataset id is the resource string.

    Returns a bool instead of raising. The signature is an
    ADDITIONAL way in for a client that cannot send headers, never a restriction
    on one that can, so an absent, malformed or expired signature falls through
    to the other branches. Refusing preemptively would 403 an in-app map whose
    session is still valid but whose 15-minute template has aged out.

    ``tenant_bound_scope`` raises when multi-tenant is active with no tenant in
    context, so the import stays inside the function as it does on the vector
    path.
    """
    from app.core.tenancy import tenant_bound_scope

    params = request.query_params
    sig, exp_raw, scope = (params.get(n) for n in ("sig", "exp", "scope"))
    if not (sig and exp_raw and scope):
        return False
    if scope != tenant_bound_scope(str(dataset_id)):
        return False
    try:
        exp = int(exp_raw)
    except ValueError:
        return False
    return verify_tile_signature(scope, exp, sig)


async def _resolve_raster_access(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None,
    requested_version: str | None = None,
) -> tuple[_RasterMeta, str]:
    """Validate RBAC access to a raster dataset and return row metadata + storage backend.

    Performs the dataset lookup (cached via _resolve_raster_meta), raster type
    validation, embed-token / user / RBAC checks (3 auth priority branches), and
    returns the _RasterMeta together with the resolved storage_backend string.

    ``requested_version`` is the request's ``v`` and only reaches the metadata
    cache key; it is never an input to any auth decision.

    Raises HTTPException on any auth or lookup failure.
    """
    # Metadata comes from cache; auth checks always run per-request.
    # fix(#1518 P2 r3): a 404 here precedes any capability evaluation, so the
    # credential rule applies to the answer.
    try:
        meta = await _resolve_raster_meta(db, dataset_id, requested_version)
    except HTTPException as exc:
        capability_declined(request, user, exc)

    visibility = meta.visibility
    record_status = meta.record_status
    created_by = meta.created_by
    storage_backend = meta.storage_backend

    # Auth priority 1: embed token
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, dataset_id, db, request
        )
        if not is_valid:
            capability_declined(
                request,
                user,
                HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or expired embed token",
                ),
            )
    elif _tile_signature_authorizes(request, dataset_id):
        # fix(#688) auth priority 2: a signed template, mirroring the vector
        # path -- MapLibre attaches no header. Checked ahead of the visibility
        # split, because the mint endpoint issues one for a draft too (r1).
        pass
    else:
        # fix(#1518): CAPABILITY obligation. Reaching this arm means NEITHER
        # capability authorized the request, so what remains is decided by who
        # is asking and an unresolvable credential earns the fail-closed 401.
        reject_unresolvable_credentials(request, user)

        if visibility != "public":
            # Auth priority 3: require authenticated user for non-public datasets
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # fix(#929): routed through the permission extension rather than an
            # inline policy mirror, so an overlay that deliberately denies the
            # creator still wins here as it does on the token path.
            port = get_processing_port()
            dataset = await port.get_dataset(db, dataset_id)
            if dataset is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )
            await port.check_dataset_access(db, dataset, dataset_id, user)
        else:
            # Public dataset: still block non-published for unauthenticated users
            if record_status != "published":
                if user is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Dataset not found",
                    )
                # Authenticated non-owners cannot see unpublished
                port = get_processing_port()
                user_roles = await port.get_user_roles(db, user)
                if "admin" not in user_roles and created_by != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Dataset not found",
                    )

    # fix(#1778): hand the API-pool connection back before the caller goes
    # upstream, or a handful of concurrent tiles park the pool for three Titiler
    # attempts at a 30s timeout. Read-only, so the rollback discards nothing.
    await db.rollback()

    return meta, storage_backend


# fix(#957): unpublished from the API contract, not deleted. The HANDLER is
# load-bearing -- `raster_tile_proxy` calls it in-process and reads four
# `X-GeoLens-*` headers off the Response it returns.
@router.get("/raster-auth-check/", response_model=None, include_in_schema=False)
@limiter.exempt
async def raster_auth_check(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user_fail_open),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Resolve RBAC and the COG open-path for a raster dataset.

    Called in-process by :func:`raster_tile_proxy`, which reads the
    ``X-GeoLens-*`` headers off the returned Response. Not part of the public
    API surface; the route stays mounted for the raster-RBAC tests.

    Returns:
        200 with X-GeoLens-Asset-OpenPath and X-GeoLens-Cache-Status headers
        401 if authentication is required but missing
        403 if embed token is invalid
        404 if dataset not found, not a raster, or has no raster asset
    """
    # fix(#1372 r4): nginx keys on the FIRST occurrence of `v` and matches the
    # name case-insensitively; `QueryParams.get()` returns the LAST occurrence
    # of an exact-case name. Read once, because two decisions below use it.
    v_values = [
        value
        for name, value in request.query_params.multi_items()
        if name.lower() == "v"
    ]
    meta, storage_backend = await _resolve_raster_access(
        db,
        dataset_id,
        request,
        user,
        requested_version=v_values[0] if v_values else None,
    )

    # `resolve_open_path` is the single storage seam (local/s3/azure
    # dispatch, http(s) pass-through). In multi_tenant the key is prefixed
    # `tenants/{tenant_id}/`; in single_tenant the path is byte-identical.
    tenant_id = current_tenant_var.get() if is_multi_tenant() else None
    open_path = resolve_open_path(meta.asset_uri, tenant_id=tenant_id)

    cache_status = (
        "public"
        if _is_publicly_cacheable(meta.visibility, meta.record_status)
        else "private"
    )
    # fix(#1372 r3/r4): a shared-cache entry may only be written under the
    # CURRENT version, or a caller pre-warms the NEXT key with pre-replace
    # bytes. So: exactly one case-insensitive `v`, or served no-store.
    if (
        cache_status == "public"
        and v_values
        and (len(v_values) != 1 or v_values[0] != str(meta.tile_cache_version))
    ):
        cache_status = "private"
    if meta.is_dem:
        # DEM terrain: terrainrgb with NO rescale, which encodes raw elevation
        # into RGB. Issue #186: mask the nodata so fill pixels in edge tiles are
        # transparent rather than an extreme elevation.
        render_params = "algorithm=terrainrgb"
        nodata_param = _dem_nodata_param(meta.nodata)
        if nodata_param is not None:
            render_params = f"{render_params}&nodata={nodata_param}"
    elif storage_backend == "remote" and meta.band_info:
        # Remote STAC import with statistics — use actual data min/max
        # for rescaling instead of fixed dtype max
        bi = meta.band_info
        bc = meta.band_count or 1
        parts: list[str] = []
        if bc >= 3:
            parts.extend(["bidx=1", "bidx=2", "bidx=3"])
        for i in range(min(bc, 3) if bc >= 3 else max(bc, 1)):
            if i < len(bi) and bi[i].get("min") is not None:
                parts.append(f"rescale={bi[i]['min']},{bi[i]['max']}")
        render_params = "&".join(parts)
    else:
        render_params = _titiler_render_params(meta.band_count, meta.dtype)

    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "X-GeoLens-Asset-OpenPath": open_path,
            "X-GeoLens-Cache-Status": cache_status,
            "X-GeoLens-Render-Params": render_params,
            "X-GeoLens-Band-Count": str(meta.band_count or 1),
        },
    )


@router.get(
    "/raster-proxy/{dataset_id}/{z:int}/{x:int}/{y:int}.{fmt}", response_class=Response
)
@limiter.exempt
async def raster_tile_proxy(
    request: Request,
    dataset_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    colormap_name: Literal[
        "gray", "viridis", "inferno", "plasma", "magma", "ylorrd", "bugn", "terrain"
    ]
    | None = Query(None, description="Titiler colormap for single-band display"),
    stretch: Literal["minmax", "percentile", "stddev"] | None = Query(
        None, description="Stretch strategy: minmax (default), percentile, stddev"
    ),
    pmin: float | None = Query(
        None,
        description=(
            "Lower percentile clip for stretch=percentile (0–100, default 2). "
            "Absent = current p2 behavior. Must be less than pmax. Ignored, and "
            "not validated, when stretch is not percentile."
        ),
    ),
    pmax: float | None = Query(
        None,
        description=(
            "Upper percentile clip for stretch=percentile (0–100, default 98). "
            "Absent = current p98 behavior. Must be greater than pmin. Ignored, "
            "and not validated, when stretch is not percentile."
        ),
    ),
    sigma: float | None = Query(
        None,
        description=(
            "Standard-deviation multiplier for stretch=stddev (default 2.0). "
            "Absent = current 2.0σ behavior. Must be > 0. Ignored, and not "
            "validated, when stretch is not stddev."
        ),
    ),
    user: Identity | None = Depends(get_optional_user_fail_open),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render one raster tile and return the image.

    Returns the image itself rather than a redirect: the dataset is
    authorized, then the rendered tile comes back in the response body. Used by
    the development proxy and by deployments that run without nginx in front.

    ``colormap_name`` applies a colormap to a single-band raster. Passing
    ``gray`` leaves the rendering unchanged, and a digital elevation model
    ignores the parameter, because its terrain encoding cannot be recoloured.

    ``stretch`` chooses how pixel values map to the output range. ``minmax``
    keeps the range the dataset already implies: the recorded per-band minimum
    and maximum for a raster imported from a remote source that published
    statistics, a range derived from the data type for most others, and no
    rescale parameter for 8-bit data, which needs none. ``percentile`` and
    ``stddev`` instead derive a range from band statistics read at request
    time, for up to three bands. A digital elevation model ignores the
    parameter, and so does a request whose band statistics cannot be read,
    which falls back to ``minmax`` rather than failing.

    ``pmin`` and ``pmax`` (2 and 98 by default) are read when ``stretch`` is
    ``percentile``, and ``sigma`` (2.0 by default) when it is ``stddev``. A
    parameter that does not apply to the selected stretch is ignored, and its
    default is used in place of the value sent.

    Responds 204 when the tile falls outside the raster, 400 for an
    unsupported format, 401 when authentication is required, or when a request
    that no capability authorized carried a credential which did not resolve,
    403 when the embed token is invalid or expired
    or a multi-tenant request arrives with no tenant context, 422 for an
    out-of-range stretch parameter, and 503 when the renderer cannot be
    reached. A different failure from the renderer is passed through with its
    own status.

    404 covers more than a missing dataset. A dataset that is unknown, is not a
    raster or has no image answers 404. Where no capability authorized the
    request, so does a dataset the caller may not read: an authorization denial
    on a non-public raster, and an unpublished raster asked for by a caller who
    is neither its owner nor an admin. That is deliberate, so a refusal keeps a
    dataset's existence undisclosed.
    """
    # fix(#315): sanitize `{fmt}` before it reaches the Titiler URL. A proxy
    # rewrite can URL-encode the query string into the PATH, so `{fmt}` arrives
    # as "png?stretch=..." and the built URL carries two `?` (Titiler 422s).
    if "?" in fmt:
        # Recover render params that arrived ONLY in the path, so styling is not
        # silently dropped. fix(#1770 r47b): bounded, because `{fmt}` is
        # attacker-reachable unauthenticated; a ValueError recovers nothing.
        try:
            _buried = parse_qs(fmt.split("?", 1)[1], max_num_fields=MAX_QUERY_FIELDS)
        except ValueError:
            _buried = {}
        if stretch is None and _buried.get("stretch"):
            _s = _buried["stretch"][0]
            if _s in ("minmax", "percentile", "stddev"):
                stretch = _s  # type: ignore[assignment]
        if colormap_name is None and _buried.get("colormap_name"):
            # Validated by the _ALLOWED_COLORMAPS allowlist below.
            colormap_name = _buried["colormap_name"][0]  # type: ignore[assignment]

        def _buried_float(key: str) -> float | None:
            # pmin/pmax/sigma are validated by the 0<=pmin<pmax<=100 / sigma>0
            # checks below, so an out-of-range recovered value still 422s cleanly.
            if _buried.get(key):
                try:
                    return float(_buried[key][0])
                except ValueError:
                    return None
            return None

        if pmin is None:
            pmin = _buried_float("pmin")
        if pmax is None:
            pmax = _buried_float("pmax")
        if sigma is None:
            sigma = _buried_float("sigma")
    fmt = fmt.split("?", 1)[0].lower()
    if fmt not in ("png", "webp", "jpg", "jpeg", "tif", "tiff"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported tile format: {fmt!r}",
        )

    # Effective bounds resolved ONCE, where activity is decided: an INACTIVE
    # parameter's value is ALWAYS the absent default. fix(#1778 r8): otherwise
    # `?stretch=stddev&pmin=1e309` set eff_pmin=inf and 500'd on `int(pmin)`.
    _pmin_pmax_active = stretch == "percentile"
    _sigma_active = stretch == "stddev"
    eff_pmin: float = pmin if (_pmin_pmax_active and pmin is not None) else 2.0
    eff_pmax: float = pmax if (_pmin_pmax_active and pmax is not None) else 98.0
    eff_sigma: float = sigma if (_sigma_active and sigma is not None) else _STDDEV_SIGMA

    # Validated before any Titiler call, and only when the ACTIVE
    # stretch mode reads the value, so a value nginx blanks from the cache key
    # cannot turn a cached 200 into a 422. fix(#1778 r8): isfinite explicitly.
    if stretch == "percentile" and (pmin is not None or pmax is not None):
        if (
            not math.isfinite(eff_pmin)
            or not math.isfinite(eff_pmax)
            or not (0 <= eff_pmin < eff_pmax <= 100)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "pmin/pmax must satisfy 0 <= pmin < pmax <= 100; "
                    f"got pmin={eff_pmin}, pmax={eff_pmax}"
                ),
            )
    if stretch == "stddev" and sigma is not None:
        if not math.isfinite(eff_sigma) or not (eff_sigma > 0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"sigma must be > 0; got sigma={eff_sigma}",
            )

    auth_resp = await raster_auth_check(request, dataset_id, user, db)
    open_path = auth_resp.headers.get("X-GeoLens-Asset-OpenPath")
    if not open_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No raster asset"
        )

    render_params = auth_resp.headers.get("X-GeoLens-Render-Params", "")
    # SEC-002: carry the dataset's public/private cache scope through to the tile
    # response so private rasters are never stored by a shared cache. Default to
    # "private" if the header is somehow absent (fail safe).
    cache_status = auth_resp.headers.get("X-GeoLens-Cache-Status", "private")

    # Read band_count from the auth response header (emitted by raster_auth_check).
    # Absent / non-numeric → fall back to 1. Cap at 3 for Titiler RGB rendering.
    _raw_band_count = auth_resp.headers.get("X-GeoLens-Band-Count", "1")
    try:
        band_count = int(_raw_band_count) if _raw_band_count else 1
    except (ValueError, TypeError):
        band_count = 1

    # T-1140-01: belt-and-suspenders runtime allowlist check (Literal provides
    # FastAPI-level validation; this guard catches any code path that bypasses it).
    if colormap_name is not None and colormap_name not in _ALLOWED_COLORMAPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"colormap_name must be one of: {sorted(_ALLOWED_COLORMAPS)}",
        )

    # Forwarded only for a non-default colormap (gray is Titiler's single-band
    # default) and never for a DEM layer, whose `algorithm=` must not be
    # overridden.
    if (
        colormap_name
        and colormap_name != "gray"
        and not render_params.startswith("algorithm=")
    ):
        render_params = (
            f"{render_params}&colormap_name={colormap_name}"
            if render_params
            else f"colormap_name={colormap_name}"
        )

    # minmax keeps the dtype-based rescale already in render_params;
    # percentile/stddev override it from Titiler band statistics, one fragment
    # per band up to three. Falls back to minmax when stats are missing.
    if stretch and stretch != "minmax" and not render_params.startswith("algorithm="):
        bands = await _fetch_band_statistics(open_path, eff_pmin, eff_pmax)
        n_bands = min(band_count or 1, 3)
        rescale_parts = (
            _compute_stretch_rescale(
                bands, stretch, n_bands, pmin=eff_pmin, pmax=eff_pmax, sigma=eff_sigma
            )
            if bands
            else []
        )
        if rescale_parts:
            render_params = _apply_stretch_rescale(render_params, rescale_parts)
        else:
            logger.warning(
                "raster stretch stats unavailable, falling back to minmax",
                stretch=stretch,
                dataset_id=str(dataset_id),
            )

    titiler_url = build_titiler_cog_url(
        f"tiles/WebMercatorQuad/{z}/{x}/{y}.{fmt}",
        query={"url": open_path},
        raw_query_suffix=render_params or None,
    )

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
                    error=redact_exception_text(exc),
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
                error=redact_exception_text(exc),
            )
            await asyncio.sleep(0.5 * (2**attempt))
            continue
        else:
            if resp.status_code in (500, 503) and attempt < max_retries:
                logger.debug(
                    "Raster tile proxy got 503; retrying",
                    attempt=attempt,
                    dataset_id=str(dataset_id),
                )
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            break

    # Safety guard: the loop above cannot leave `resp` unassigned today, but a
    # future edit must produce a 503 rather than an AttributeError.
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

    # SEC-002: private/restricted rasters must never be retained by the shared
    # nginx cache (its key carries no auth). Emit `no-store` so nginx skips
    # caching (frontend/nginx.conf honors it); only public datasets are cacheable.
    if cache_status == "public":
        cache_control = "public, max-age=3600"
    else:
        cache_control = "private, no-store"
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
        headers={"Cache-Control": cache_control},
    )


def _build_tile_token_for_dataset(
    dataset: "Any",
    raster_asset: RasterAsset | None = None,
) -> VectorTileToken | RasterTileToken:
    """Build a tile token response for a single already-authorized dataset.

    Extracted so both the single-dataset and batch endpoints share the same
    token-generation logic. Does NOT perform auth — caller must
    ensure the dataset is visible to the current user.
    """
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
        bounds = None
        lon_span = None
        if dataset.record.spatial_extent is not None:
            # fix(#892): the SPAN, not the RFC 7946 spec bbox. These bounds feed
            # the tile source's own bounds; a west > east pair would bound the
            # source to nothing. -180..180 is over-broad but never inverted.
            bounds = extent_to_span_bbox(dataset.record.spatial_extent)
            # fix(#887): and the honest width alongside it -- without it a
            # seam-crossing raster measures 360 degrees wide, understates its
            # resolution 36x, and loses five zoom levels on zoom-in.
            lon_span = extent_lon_span(dataset.record.spatial_extent)
            if bounds is None:
                logger.warning(
                    "Failed to parse spatial extent bounds",
                    dataset_id=str(dataset.id),
                )

        # fix(#688): sign the raster template too. A raster has no table_name,
        # so the dataset id is the resource string, and it is tenant-bound.
        # Mirrored byte for byte at the verify site in `_resolve_raster_access`.
        from app.core.tenancy import tenant_bound_scope

        raster_exp = round_expiry()
        raster_scope = tenant_bound_scope(str(dataset.id))
        raster_sig = generate_tile_signature(raster_scope, raster_exp)
        tile_path = f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png"
        # fix(#1372): `v` rides outside the signature (which binds scope+exp
        # only, like the colormap params) and feeds nginx's $arg_v cache-key
        # segment, so a raster replace rolls the shared tile cache.
        query_params = {"sig": raster_sig, "exp": raster_exp, "scope": raster_scope}
        if dataset.tile_cache_version:
            query_params["v"] = dataset.tile_cache_version
        query = urlencode(query_params)

        return RasterTileToken(
            kind="raster",
            tile_url=f"{tile_path}?{query}",
            sig=raster_sig,
            exp=raster_exp,
            scope=raster_scope,
            expires_in=raster_exp - int(time.time()),
            bounds=bounds,
            minzoom=0,
            maxzoom=_raster_maxzoom_from_metadata(
                raster_asset, bounds, lon_span=lon_span
            ),
            tile_size=256,
            format="png",
        )

    # In multi_tenant the scope is bound to the active tenant, so a token
    # minted for tenant A cannot be replayed in tenant B even when both share a
    # table_name. single_tenant: the bare table_name, byte-identical to pre-1209.
    exp = round_expiry()
    from app.core.tenancy import tenant_bound_scope

    scope = tenant_bound_scope(dataset.table_name)
    sig = generate_tile_signature(scope, exp)

    return VectorTileToken(
        kind="vector",
        sig=sig,
        exp=exp,
        scope=scope,
        expires_in=exp - int(time.time()),
    )


async def _enforce_tile_token_access(
    db: AsyncSession,
    dataset: Any,
    dataset_id: uuid.UUID,
    user: Identity | None,
    port: Any,
) -> None:
    """Status-aware access gate for the tile-token endpoints.

    Mirrors the raster ``_resolve_raster_access`` contract so vector and raster
    token minting deny identically:
    - non-public + anonymous -> 401 (authenticating may grant access)
    - non-public + authenticated -> full RBAC via ``check_dataset_access`` (404 if denied)
    - public + unpublished + non-owner -> 404 (closes the anonymous egress leak)
    - public + published -> allowed

    Raises HTTPException on denial; returns None on allow.
    """
    record = dataset.record
    if record.visibility != "public":
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await port.check_dataset_access(db, dataset, dataset_id, user)
        return

    # Public dataset: still block non-published for non-owners (SEC-01).
    if record.record_status != "published":
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        user_roles = await port.get_user_roles(db, user)
        if "admin" not in user_roles and record.created_by != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )


@router.get("/token/{dataset_id}/", response_model=VectorTileToken | RasterTileToken)
@limiter.exempt
async def get_tile_token(
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> VectorTileToken | RasterTileToken:
    """Generate a tile token for a dataset.

    For vector datasets: returns HMAC-signed token (sig, exp, scope, expires_in).
    For raster datasets: returns tile URL template and metadata.

    Both responses include a discriminated ``kind`` field.

    Public datasets can be accessed without authentication.
    Private/restricted datasets require authentication and RBAC checks.
    """
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM

    port = get_processing_port()
    result = await db.execute(
        select(DatasetORM)
        .options(joinedload(DatasetORM.record))
        .where(DatasetORM.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    await _enforce_tile_token_access(db, dataset, dataset_id, user, port)

    raster_asset = None
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
        raster_asset_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
        )
        raster_asset = raster_asset_result.scalar_one_or_none()

    return _build_tile_token_for_dataset(dataset, raster_asset)


@router.post("/tokens/", response_model=TileTokenBatchResponse)
@limiter.exempt
async def get_tile_tokens_batch(
    body: TileTokenBatchRequest,
    request: Request,
    user: Identity | None = Depends(get_optional_user_fail_open),
    embed_token: str | None = Header(default=None, alias="X-Embed-Token"),
    db: AsyncSession = Depends(get_db),
) -> TileTokenBatchResponse:
    """Generate tile tokens for up to 50 datasets in one request.

    The list must hold between 1 and 50 ids, and a request outside that is 422.

    One round trip in place of one request per dataset, which is what a map
    with many layers would otherwise need.

    A dataset that cannot be found or cannot be authorized does not fail the
    batch: that id maps to ``{"error": "..."}`` in the response instead, so
    check each entry for an ``error`` key before using it. Duplicate ids are
    collapsed.

    The request as a whole still fails 401 in one case: a request that carried
    a credential which did not resolve and that no capability authorized
    answers 401 rather than a body of per-dataset errors. A request carrying no
    credential is served normally.

    ``X-Embed-Token`` is accepted as a fallback authorization for the datasets
    inside that token's scope, so an embedded map can build a terrain source
    from real bounds and zoom limits.
    """
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM

    port = get_processing_port()
    unique_ids = list(dict.fromkeys(body.dataset_ids))

    result = await db.execute(
        select(DatasetORM)
        .options(joinedload(DatasetORM.record))
        .where(DatasetORM.id.in_(unique_ids))
    )
    datasets_by_id = {ds.id: ds for ds in result.scalars().all()}
    raster_dataset_ids = [
        ds.id
        for ds in datasets_by_id.values()
        if ds.record.record_type in RASTER_FAMILY_RECORD_TYPES
    ]
    raster_assets_by_dataset_id: dict[uuid.UUID, RasterAsset] = {}
    if raster_dataset_ids:
        raster_asset_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id.in_(raster_dataset_ids))
        )
        raster_assets_by_dataset_id = {
            asset.dataset_id: asset for asset in raster_asset_result.scalars().all()
        }

    # fix(#1518): CAPABILITY obligation. This handler resolves many ids, so
    # "did a capability authorize this request" is answerable only after the
    # loop: the token authorizes a SCOPE, and the loop works out which ids.
    capability_authorized = False

    tokens: dict[str, VectorTileToken | RasterTileToken | dict] = {}
    for dataset_id in unique_ids:
        dataset = datasets_by_id.get(dataset_id)
        key = str(dataset_id)
        if dataset is None:
            tokens[key] = {"error": "Dataset not found"}
            continue

        try:
            await _enforce_tile_token_access(db, dataset, dataset_id, user, port)
        except HTTPException as exc:
            # fix(#394) SH-04: embed-token capability fallback (fail-closed).
            embed_ok = bool(embed_token) and await validate_embed_token_access(
                embed_token, dataset_id, db, request
            )
            if not embed_ok:
                tokens[key] = {"error": exc.detail}
                continue
            capability_authorized = True

        tokens[key] = _build_tile_token_for_dataset(
            dataset,
            raster_assets_by_dataset_id.get(dataset.id),
        )

    # fix(#1518 P2): the flag above is only set on the FALLBACK arm, which a
    # batch of public datasets never reaches, so the question is asked again
    # here. Still the real validator against a real id, never header presence.
    if not capability_authorized and embed_token:
        for dataset_id in unique_ids:
            if await validate_embed_token_access(embed_token, dataset_id, db, request):
                capability_authorized = True
                break

    # No capability authorized any part of this batch, so the caller's own
    # credential is load-bearing: an unresolvable one gets the fail-closed 401
    # rather than per-dataset errors reading like an empty catalog (#1518).
    if not capability_authorized:
        reject_unresolvable_credentials(request, user)

    return TileTokenBatchResponse(tokens=tokens)


def _parse_vector_tile_table(table_path: str) -> str:
    """Extract and validate the data-table name from a tile route path."""
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
    if not _TABLE_NAME_RE.match(table_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid table name"
        )
    return table_name


def _validate_tile_coordinates(z: int, x: int, y: int) -> None:
    if z < 0 or z > 22:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Zoom level must be 0-22"
        )

    max_tile = (1 << z) - 1  # 2^z - 1
    if x < 0 or x > max_tile or y < 0 or y > max_tile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tile coordinates out of range",
        )


async def _resolve_dataset_meta(table_name: str, db: AsyncSession) -> _DatasetMeta:
    """Look up dataset metadata with a short in-memory cache.

    In ``multi_tenant`` the cache key is ``{tid}:{table_name}`` so two
    tenants sharing a ``table_name`` never share an entry, and the query adds a
    ``DatasetORM.tenant_id`` filter to close the cross-dataset authz leak on the
    data plane. In ``single_tenant`` the key is the bare ``table_name`` with no
    tenant filter, byte-identical to pre-1209.
    """
    now = time.monotonic()

    # Fail before consulting even the in-memory cache: an unresolved request
    # must never reuse a single-tenant bare-key entry after a mode transition.
    tid = _require_tile_tenant_context()
    cache_key = f"{tid}:{table_name}" if tid is not None else table_name

    with _dataset_cache_lock:
        cached_entry = _dataset_cache.get(cache_key)
        if cached_entry is not None:
            ts, cached_meta = cached_entry
            if now - ts < _DATASET_CACHE_TTL:
                return cached_meta

    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM

    stmt = (
        select(DatasetORM)
        .options(joinedload(DatasetORM.record))
        .where(DatasetORM.table_name == table_name)
    )
    if is_multi_tenant() and tid is not None:
        # A bare table_name lookup without scoping could return another
        # tenant's dataset when names collide.
        stmt = stmt.where(DatasetORM.tenant_id == tid)

    result = await db.execute(stmt)
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
        record_status=dataset.record.record_status,
        created_by=dataset.record.created_by,
        record_type=dataset.record.record_type,
        geometry_type=dataset.geometry_type,
        column_info=dataset.column_info or [],
        tile_cache_ttl=dataset.tile_cache_ttl,
        tile_columns=dataset.tile_columns,
    )
    with _dataset_cache_lock:
        _dataset_cache[cache_key] = (now, meta)
    return meta


async def _resolve_dataset_meta_for_serving(
    request: Request,
    table_name: str,
    db: AsyncSession,
    user: Identity | None,
) -> _DatasetMeta:
    """Resolve tile metadata, applying the credential rule if the lookup fails.

    The lookup has to run BEFORE ``_authorize_vector_tile_request``, because a
    tile URL carries a TABLE NAME and the capability arms need the dataset id
    only this lookup produces.
    Running it later reaches its 404 with the credential rule never applied, so
    a dead bearer naming a missing table gets "not found" while the raster
    route answers 401 for the identical request shape.

    No capability can be skipped over here: an embed token authorizes dataset
    IDS, and this exit is exactly the case where there is no id to authorize.
    """
    try:
        return await _resolve_dataset_meta(table_name, db)
    except HTTPException as exc:
        capability_declined(request, user, exc)


async def _assert_dataset_still_registered(
    db: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    table_name: str,
    tid: Any,
) -> None:
    """Refuse a cached authorization the catalog no longer backs.

    ``_resolve_dataset_meta`` answers a cache hit without touching the database,
    so for up to ``_DATASET_CACHE_TTL`` seconds a worker keeps authorizing
    against a row that may already be deleted. Nothing stops someone with a
    database session running ``CREATE TABLE data.roads`` directly, and the
    schema's default privileges make that relation readable by the role the tile
    path binds, so the deleted dataset's cached ``public`` visibility would carry
    a stranger's rows to anonymous callers. The ``_evict_dataset_meta`` listener
    cannot close this alone: it is process-local, and every uvicorn worker holds
    a private LRU.

    Position is the rest of the design, and it is exact: the first statement
    past the tile-byte-cache short-circuit. No earlier, or a cache hit stops
    costing zero round-trips. No later, because everything below acts on the
    cached authorization, and because a tile request takes three bounded
    resources in sequence -- this API-pool connection, the fair-share permit,
    then the tile-pool connection -- so every later position inverts a pair
    against a
    metadata-cache MISS and stalls under ordinary mixed load.
    ``test_both_tile_endpoints_ask_before_they_act`` pins it.

    Pinning id AND table_name together makes it a liveness check rather than an
    existence check: a surviving row repointed at a different relation must not
    authorize a read of the old name. It runs unconditionally, including right
    after a cache MISS, because threading cache-hit state into a security check
    buys one PK lookup and costs a caller that can skip the check by getting
    the flag wrong.

    Scope is every caller that reads a ``data``-schema relation off cached
    authorization: the vector and cluster endpoints, one call site, since both
    reach the relation through ``_acquire_and_serve_tile``. The raster proxy is
    deliberately NOT covered -- it is addressed by dataset id and resolves to an
    object-storage asset, so there is no relation to substitute.
    """
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM

    stmt = select(DatasetORM.id).where(
        DatasetORM.id == dataset_id,
        DatasetORM.table_name == table_name,
    )
    if is_multi_tenant() and tid is not None:
        # Mirrors the _resolve_dataset_meta filter so the probe cannot be
        # satisfied by another tenant's row carrying the same table_name.
        stmt = stmt.where(DatasetORM.tenant_id == tid)

    registered = (await db.execute(stmt)).scalar_one_or_none()

    # fix(#1451 P1): hand the API-pool connection back before returning, or
    # every tile the pool builds occupies one for its PostGIS query and gzip.
    # Read-only, so the rollback discards nothing.
    await db.rollback()

    if registered is not None:
        return

    # Drop the entry that got us here so the next request re-resolves and 404s
    # in _resolve_dataset_meta, rather than re-paying this probe for the TTL.
    _evict_dataset_meta(table_name)
    logger.warning(
        "Tile refused: cached dataset metadata outlived its catalog row",
        table_name=table_name,
        dataset_id=str(dataset_id),
    )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
    )


async def _authorize_vector_tile_request(
    request: Request,
    meta: _DatasetMeta,
    db: AsyncSession,
    *,
    sig: str | None,
    exp: int | None,
    scope: str | None,
    user: Identity | None,
) -> str:
    """Authorize direct vector-tile access and return cache scope."""
    embed_token_header = request.headers.get("X-Embed-Token")
    if embed_token_header:
        is_valid = await validate_embed_token_access(
            embed_token_header, meta.dataset_id, db, request
        )
        if not is_valid:
            capability_declined(
                request,
                user,
                HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or expired embed token, or dataset not in scope",
                ),
            )
        return "private"

    if meta.visibility != "public":
        if not sig or not exp or not scope:
            capability_declined(
                request,
                user,
                HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Signature required for non-public tiles",
                ),
            )
        # The expected scope mirrors `_build_tile_token_for_dataset` --
        # `{tid}:{table_name}` in multi_tenant to prevent cross-tenant replay,
        # the bare table_name in single_tenant.
        from app.core.tenancy import tenant_bound_scope

        _expected_scope = tenant_bound_scope(meta.table_name)
        if scope != _expected_scope:
            capability_declined(
                request,
                user,
                HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Scope mismatch"
                ),
            )
        if not verify_tile_signature(scope, exp, sig):
            capability_declined(
                request,
                user,
                HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or expired signature",
                ),
            )
        # A valid signature authorizes a single caller for a
        # non-public dataset, so the bytes must not be retained by a shared
        # cache. "private" rather than "public" is what says so.
        return "private"

    # fix(#1518): CAPABILITY obligation. Both capability arms above have
    # declined, so everything from here is decided by WHO is asking and a
    # supplied credential that failed to resolve gets the fail-closed 401.
    reject_unresolvable_credentials(request, user)

    # Public dataset: still block non-published for unauthenticated users
    if meta.record_status != "published":
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        # Authenticated non-owners cannot see unpublished
        port = get_processing_port()
        user_roles = await port.get_user_roles(db, user)
        if "admin" not in user_roles and meta.created_by != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        # Owner/admin previewing an UNPUBLISHED public dataset: authorized, but
        # the tiles must not enter the shared (auth-less) cache or they would
        # replay to anonymous callers. (Codex P1 on PR #243.)
        return "private"

    return "public"


def _is_point_geometry(geometry_type: str | None) -> bool:
    return "POINT" in (geometry_type or "").upper()


def _ensure_clusterable_dataset(meta: _DatasetMeta) -> None:
    if meta.record_type != "vector_dataset" or not _is_point_geometry(
        meta.geometry_type
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cluster tiles require a vector point dataset",
        )


def _generation_table_key(table_name: str, dataset_id: uuid.UUID) -> str:
    """Table segment plus the generation that makes a reused name safe.

    A tile cache key of the table name alone lets the next dataset
    to draw ``roads`` read the previous one's cached bytes under its own
    visibility. A dataset id is a UUID and is never reissued, so keying on it
    makes that read impossible rather than merely short-lived.

    GH-1443 retires freed names, so a redraw cannot happen either.
    This key stays because it is what makes a name safe regardless of any
    future name-generation change.

    Position is load-bearing: the id goes AFTER the table segment so the
    ``tile:{table}:*`` patterns in ``invalidate_table`` still match every key
    for a table, whichever dataset wrote it.
    """
    return f"{table_name}:ds{dataset_id.hex}"


def _cluster_cache_table_key(
    table_name: str,
    *,
    dataset_id: uuid.UUID,
    cluster_radius: int,
    cluster_max_zoom: int,
) -> str:
    # fix(#868): the version tag pins the cluster SQL semantics. Bump it whenever
    # _build_cluster_tile_query changes the emitted tile geometry/properties, or a
    # deploy keeps serving stale cluster tiles until TTL expiry. v2 -> v3: #874.
    return (
        f"{_generation_table_key(table_name, dataset_id)}"
        f":cluster:v3:r{cluster_radius}:z{cluster_max_zoom}"
    )


async def _acquire_and_serve_tile(
    *,
    request: Request,
    table_name: str,
    z: int,
    x: int,
    y: int,
    tid: Any,
    schema: str,
    query_callable: Any,
    tile_cache: Any,
    cache_key: str,
    cache_ttl: int,
    base_headers: dict[str, str],
    cols_cache_key: str = "",
    tenant_sem: Any = None,
    mode: str = "vector",
    log_event: str = "tile_access",
    log_extra: dict | None = None,
) -> Response:
    """Shared acquire, bind-role, run-query, gzip, cache and respond core.

    Both the vector and cluster endpoints supply a ``query_callable`` (async
    ``(pool, conn) -> bytes | None``) plus a cache key; this helper owns the
    shared scaffold: the tile-pool acquire (503 on failure), the optional
    per-tenant semaphore (a no-op when ``tenant_sem`` is None), the
    single-connection transaction with the per-tenant role/search_path bind,
    error mapping (``asyncio.TimeoutError`` -> 429, broad ``Exception`` ->
    503), empty-tile sentinel caching (-> 204), the gzip offload, the cache
    write, the usage event, and the ETag/304 response.

    Callers keep their own cache-hit short-circuit and cold-rehydrate
    seam, which differ between the two paths.
    """
    try:
        pool = get_tile_pool()
    except RuntimeError as exc:
        logger.warning(
            "Tile pool unavailable",
            table_name=table_name,
            mode=mode,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        )

    # FAIR-01: per-tenant semaphore acquisition (cloud only; no-op when None).
    _sem_acquired = False
    if tenant_sem is not None:
        try:
            _sem_acquired = await asyncio.wait_for(tenant_sem.acquire(), timeout=10.0)
            if not _sem_acquired:
                raise asyncio.TimeoutError
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tile concurrency limit reached for tenant, please retry",
                headers={"Retry-After": "2"},
            )

    # DP-02 (Phase 1209-03): acquire ONE connection and open a transaction so
    # SET LOCAL ROLE + SET LOCAL search_path survive for the tile query
    # (PgBouncer transaction-mode: SET LOCAL is valid within one txn; T-1209-10).
    try:
        async with pool.acquire() as tile_conn:
            async with tile_conn.transaction():
                # Bind per-tenant role + search_path BEFORE the tile query.
                # No-op in single_tenant or when tid is None.
                await set_tenant_role_for_tile_request(tile_conn, tid)
                tile_data = await query_callable(pool, tile_conn)
    except asyncio.TimeoutError:
        logger.warning(
            "Tile pool acquire timeout",
            table_name=table_name,
            mode=mode,
            z=z,
            x=x,
            y=y,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tile service busy, please retry",
            headers={"Retry-After": "2"},
        )
    except Exception as exc:  # broad: tile query spans MVT SQL/PostGIS — varied DB errors map to a controlled 503 with logged context
        logger.exception(
            "Tile query failed",
            table_name=table_name,
            mode=mode,
            z=z,
            x=x,
            y=y,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        )
    finally:
        # FAIR-01: always release the per-tenant semaphore (cloud only).
        if _sem_acquired and tenant_sem is not None:
            tenant_sem.release()

    if tile_data is None:
        # Cache empty tiles to avoid repeated PostGIS queries for sparse datasets.
        if tile_cache is not None:
            await tile_cache.set(
                cache_key, z, x, y, b"", ttl=cache_ttl, cols_key=cols_cache_key
            )
        # fix(#430 V-03): empty tiles were uncacheable — reuse the tile's Cache-Control
        # from base_headers (drop Content-Encoding; a 204 has no body).
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={k: v for k, v in base_headers.items() if k != "Content-Encoding"},
        )

    logger.debug(log_event, table_name=table_name, z=z, x=x, y=y, **(log_extra or {}))

    # Emit the usage event through the billing-import-free seam.
    await _emit_tile_usage_event(table_name)

    # PERF-005: gzip is CPU-bound — offload to a thread so the event loop isn't
    # stalled compressing wide low-zoom tiles. mtime=0 makes the gzip stream
    # deterministic so the MVT-04 content-hash ETag is stable across requests.
    compressed = await asyncio.to_thread(gzip.compress, tile_data, 6, mtime=0)
    if tile_cache is not None:
        await tile_cache.set(
            cache_key, z, x, y, compressed, ttl=cache_ttl, cols_key=cols_cache_key
        )

    return _tile_response(request, compressed, base_headers)


@router.get(
    "/clusters/{table_path:path}/{z:int}/{x:int}/{y:int}.pbf",
    response_class=Response,
    responses={429: RATE_LIMIT_RESPONSE},
)
@limiter.exempt
async def cluster_tile_endpoint(
    request: Request,
    table_path: str,
    z: int,
    x: int,
    y: int,
    sig: str | None = None,
    exp: int | None = None,
    scope: str | None = None,
    cols: str | None = None,
    cluster_radius: int = Query(48, ge=1, le=256),
    cluster_max_zoom: int = Query(14, ge=0, le=22),
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user_fail_open),
) -> Response:
    """Serve a server-side clustered vector tile for a point dataset.

    URL pattern: ``/tiles/clusters/data.{table_name}/{z}/{x}/{y}.pbf``

    Authorization matches the plain vector tile route, in three cases. A
    public, published dataset is readable without credentials. A non-public
    dataset needs either valid signature parameters (``sig``, ``exp``,
    ``scope``) or an embed token scoped to it, and answers 403 without one. A
    public dataset that is not yet published is readable by its owner, by an
    admin, or with an embed token, and answers 404 to other callers, so a
    refusal keeps its existence undisclosed. An unknown table is 404 too.

    A request that no capability authorized and that carried a credential which
    did not resolve is refused with 401 rather than served as an anonymous
    read, so an expired token is rejected instead of being silently downgraded.
    A request sending no credential is served normally.

    ``cluster_radius`` is a screen-pixel distance, the same units MapLibre's
    ``clusterRadius`` uses, and ``cluster_max_zoom`` is the last zoom at which
    features are grouped. ``cols`` works as it does on the vector route, and
    the named columns are projected onto the unclustered features, so
    data-driven styling and popups keep working here too.

    Requires a vector point dataset; another record type responds 400, as does
    a malformed table name or an out-of-range tile coordinate.

    A tile holding no features answers 204, and a repeat request whose
    ``If-None-Match`` matches answers 304. A dataset still being restored from
    cold storage answers 202 with a job id to poll. Where a per-tenant
    concurrency limit is configured, exceeding it answers 429 with
    ``Retry-After``. A failure running the tile query answers 503.
    """
    table_name = _parse_vector_tile_table(table_path)
    _validate_tile_coordinates(z, x, y)
    meta = await _resolve_dataset_meta_for_serving(request, table_name, db, user)
    cache_scope = await _authorize_vector_tile_request(
        request,
        meta,
        db,
        sig=sig,
        exp=exp,
        scope=scope,
        user=user,
    )
    # fix(#1518 P2 r4): after authorization, not before. "Not a point dataset"
    # is a property of the RESOURCE, and it told an unauthorized caller that a
    # private dataset exists and what geometry it holds.
    _ensure_clusterable_dataset(meta)

    # fix(#1778): keyed on the effective projection, so `z`, the allowlist and
    # the mode all reach it -- the cluster query emits its own
    # `point_count`/`cluster_id`, so a `cols=` naming one changes nothing.
    additional_columns, cols_cache_key = parse_cols_param(
        cols,
        meta.column_info,
        z,
        tile_columns=meta.tile_columns,
        mode="cluster",
    )

    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl

    # Prefix the cluster cache key with the tenant id in multi_tenant so
    # two tenants sharing a table_name never share cached cluster tiles.
    # single_tenant: no prefix, byte-identical to pre-1209.
    _cluster_tid = _require_tile_tenant_context()
    _cluster_tenant_prefix = f"{_cluster_tid}:" if _cluster_tid is not None else ""
    _cluster_limiter, _cluster_cache_control = _get_tile_serving_controls(
        str(_cluster_tid or "anon")
    )
    cluster_cache_key = _cluster_tenant_prefix + _cluster_cache_table_key(
        table_name,
        dataset_id=meta.dataset_id,
        cluster_radius=cluster_radius,
        cluster_max_zoom=cluster_max_zoom,
    )

    tile_cache = get_tile_cache()
    if tile_cache is not None:
        cached = await tile_cache.get(
            cluster_cache_key, z, x, y, cols_key=cols_cache_key, label=table_name
        )
        if cached is not None:
            if len(cached) == 0:
                return Response(
                    status_code=status.HTTP_204_NO_CONTENT,
                    headers=_serving_tile_headers(
                        cache_scope,
                        cache_ttl,
                        _cluster_cache_control,
                        empty=True,
                    ),  # fix(#430 V-03)
                )
            # MVT-04: cache hits also carry an ETag / honor If-None-Match.
            return _tile_response(
                request,
                cached,
                _serving_tile_headers(cache_scope, cache_ttl, _cluster_cache_control),
            )

    # fix(#1451): the first thing past the byte-cache short-circuit, because
    # everything past it acts on the cached authorization. See the helper for
    # why it cannot sit any later.
    await _assert_dataset_still_registered(
        db, dataset_id=meta.dataset_id, table_name=table_name, tid=_cluster_tid
    )

    # COLD-02 (Phase 1214-04): cold-rehydrate seam — BEFORE cluster tile query.
    # Mirrors the tile_endpoint seam: uses cached meta.record_status (T-1214-18);
    # failure is broad-except-swallowed (T-1214-17).
    _cluster_cold_result = await _check_cold_rehydrate(
        table_name,
        meta.record_status,
        str(_cluster_tid) if _cluster_tid is not None else "",
    )
    if _cluster_cold_result is not None:
        return _cluster_cold_result

    tid = _require_tile_tenant_context()
    _schema = tenant_data_schema(tid)

    async def _run_cluster_query(pool: Any, conn: Any) -> bytes | None:
        return await get_cluster_tile(
            pool,
            table_name,
            z,
            x,
            y,
            meta.column_info,
            tile_columns=meta.tile_columns,
            additional_columns=additional_columns,
            cluster_radius=cluster_radius,
            cluster_max_zoom=cluster_max_zoom,
            conn=conn,
            schema=_schema,
        )

    _cluster_tenant_sem = _cluster_limiter if is_multi_tenant() else None

    # The same tenant concurrency budget governs vector and cluster DB reads.
    return await _acquire_and_serve_tile(
        request=request,
        table_name=table_name,
        z=z,
        x=x,
        y=y,
        tid=tid,
        schema=_schema,
        query_callable=_run_cluster_query,
        tile_cache=tile_cache,
        cache_key=cluster_cache_key,
        cache_ttl=cache_ttl,
        base_headers=_serving_tile_headers(
            cache_scope, cache_ttl, _cluster_cache_control
        ),
        tenant_sem=_cluster_tenant_sem,
        mode="cluster",
        log_event="cluster_tile_access",
        log_extra={
            "dataset_id": str(meta.record_id),
            "cluster_radius": cluster_radius,
            "cluster_max_zoom": cluster_max_zoom,
            "scope": scope or cache_scope,
        },
        cols_cache_key=cols_cache_key,
    )


@router.get(
    "/{table_path:path}/{z:int}/{x:int}/{y:int}.pbf",
    response_class=Response,
    responses={429: RATE_LIMIT_RESPONSE},
)
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
    cols: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user_fail_open),
) -> Response:
    """Serve a vector tile as gzipped MVT binary.

    URL pattern: /tiles/data.{table_name}/{z}/{x}/{y}.pbf

    Non-public datasets require valid HMAC signature params (sig, exp, scope).
    Public datasets can be accessed without any signature.

    `cols` is a runtime opt-in for additional attribute columns the client
    needs at all zooms (e.g. data-driven styling columns referenced by
    MapLibre paint expressions). Format: comma-separated column names.
    Each name is validated against the dataset column list before it
    flows into the MVT projection; invalid names are silently dropped.
    Does not need to be signed — `sig` already authorizes dataset
    access and `cols` can only project columns the caller already has
    REST access to.
    """
    table_name = _parse_vector_tile_table(table_path)
    _validate_tile_coordinates(z, x, y)
    meta = await _resolve_dataset_meta_for_serving(request, table_name, db, user)
    cache_scope = await _authorize_vector_tile_request(
        request,
        meta,
        db,
        sig=sig,
        exp=exp,
        scope=scope,
        user=user,
    )

    columns = meta.column_info

    # fix(#1778): the cache key comes from the EFFECTIVE projection, not the
    # request, so `z` and the allowlist have to reach it. At z >= 10 every valid
    # subset collapses onto one entry.
    additional_columns, cols_cache_key = parse_cols_param(
        cols, columns, z, tile_columns=meta.tile_columns
    )

    # Use per-dataset cache TTL when set, else global default
    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl

    # Prefix the tile cache key with the tenant id in multi_tenant so two
    # tenants sharing a table_name never share a cached tile binary.
    # single_tenant: no prefix, byte-identical to pre-1209.
    _tile_tid = _require_tile_tenant_context()
    _tile_generation_key = _generation_table_key(table_name, meta.dataset_id)
    _tile_cache_key = (
        f"{_tile_tid}:{_tile_generation_key}"
        if _tile_tid is not None
        else _tile_generation_key
    )
    _tile_serving_limiter, _tile_cache_control = _get_tile_serving_controls(
        str(_tile_tid or "anon")
    )

    tile_cache = get_tile_cache()
    if tile_cache is not None:
        cached = await tile_cache.get(
            _tile_cache_key, z, x, y, cols_key=cols_cache_key, label=table_name
        )
        if cached is not None:
            if len(cached) == 0:
                # Empty sentinel — tile was previously confirmed empty
                return Response(
                    status_code=status.HTTP_204_NO_CONTENT,
                    headers=_serving_tile_headers(
                        cache_scope,
                        cache_ttl,
                        _tile_cache_control,
                        empty=True,
                    ),  # fix(#430 V-03)
                )
            # MVT-04: cache hits also carry an ETag / honor If-None-Match.
            return _tile_response(
                request,
                cached,
                _serving_tile_headers(cache_scope, cache_ttl, _tile_cache_control),
            )

    # fix(#1451): the first thing past the byte-cache short-circuit, because
    # everything past it acts on the cached authorization. See the helper for
    # why it cannot sit any later.
    await _assert_dataset_still_registered(
        db, dataset_id=meta.dataset_id, table_name=table_name, tid=_tile_tid
    )

    # Cold-rehydrate seam, before the tile query, on the cached
    # `record_status` (no extra round-trip on the hot path). A published or
    # anon-shared dataset is hot, so a public map viewer never sees a 202.
    _cold_result = await _check_cold_rehydrate(
        table_name,
        meta.record_status,
        str(_tile_tid) if _tile_tid is not None else "",
    )
    if _cold_result is not None:
        return _cold_result

    # Per-tenant concurrency budget from the registered serving extension: it
    # caps concurrent tile DB connections per tenant so one tenant cannot starve
    # others of pool connections. The Community default returns None.
    _tenant_sem = _tile_serving_limiter if is_multi_tenant() else None

    # DP-02 (Phase 1209-03): acquire ONE connection and open a transaction so
    # SET LOCAL ROLE + SET LOCAL search_path survive for the tile query
    # (PgBouncer transaction-mode: SET LOCAL is valid within one txn; T-1209-10).
    tid = _require_tile_tenant_context()
    _schema = tenant_data_schema(tid)

    # A serving extension may override Cache-Control for a hosted CDN. The
    # Community default returns None, leaving existing headers unchanged.
    _response_headers = _serving_tile_headers(
        cache_scope, cache_ttl, _tile_cache_control
    )

    async def _run_vector_query(pool: Any, conn: Any) -> bytes | None:
        return await get_tile(
            pool,
            table_name,
            z,
            x,
            y,
            columns,
            tile_columns=meta.tile_columns,
            additional_columns=additional_columns,
            conn=conn,
            schema=_schema,
        )

    # MVT-10: shared acquire->bind-role->run-query->gzip->cache->respond core.
    # FAIR-01 per-tenant semaphore (cloud only) is threaded through tenant_sem.
    return await _acquire_and_serve_tile(
        request=request,
        table_name=table_name,
        z=z,
        x=x,
        y=y,
        tid=tid,
        schema=_schema,
        query_callable=_run_vector_query,
        tile_cache=tile_cache,
        cache_key=_tile_cache_key,
        cache_ttl=cache_ttl,
        base_headers=_response_headers,
        cols_cache_key=cols_cache_key,
        tenant_sem=_tenant_sem,
        mode="vector",
        log_event="tile_access",
        log_extra={
            "dataset_id": str(meta.record_id),
            "scope": scope or "public",
        },
    )

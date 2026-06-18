"""FastAPI tile endpoint serving vector tiles via PostGIS ST_AsMVT."""

import asyncio
import gzip
import math
import re
import threading
import time
import uuid
from typing import Any, Literal, NamedTuple

import httpx
import structlog
from cachetools import LRUCache
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from geoalchemy2.shape import to_shape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.auth.dependencies import get_optional_user
from app.core.config import settings
from app.core.dependencies import get_db
from app.modules.embed_tokens.service import validate_embed_token_access
from app.platform.cache.provider import get_tile_cache
from app.platform.extensions import (
    get_billing_extensions,
    get_processing_port,
    has_extension,
)
from app.platform.storage.titiler_url import build_titiler_cog_url, resolve_open_path
from app.processing.raster.models import RasterAsset
from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant
from app.processing.tiles.pool import get_tile_pool, set_tenant_role_for_tile_request
from app.processing.tiles.service import get_cluster_tile, get_tile
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
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC

logger = structlog.stdlib.get_logger(__name__)

# ---------------------------------------------------------------------------
# FAIR-01 / METER-03 / COLD-02: cloud-conditional per-tenant helpers.
#
# These helpers are imported LAZILY inside functions so the public core image
# (without geolens_cloud installed) never hard-imports the overlay package.
# The guard is always has_extension("cloud") which is False when the overlay is
# absent — byte-identical OSS behaviour (T-1213-23).
# ---------------------------------------------------------------------------


def _get_cloud_fairness():
    """Return (tile_limiter, _get_tenant_semaphore) from the cloud overlay, or None.

    Returns None when the cloud overlay is not active, so all callers can do a
    simple ``if cloud_fairness:`` guard.  Importing inside the function body (not
    at module load) means the public core image never hard-depends on geolens_cloud.
    """
    if not has_extension("cloud"):
        return None
    try:
        from geolens_cloud.fairness.rate_limit import (  # type: ignore[import]
            _get_tenant_semaphore,
            tile_cache_control_value,
            tile_limiter,
        )

        return tile_limiter, _get_tenant_semaphore, tile_cache_control_value
    except ImportError:
        return None


async def _emit_tile_usage_event(table_name: str) -> None:
    """Emit a tile-request usage event through the billing-import-free seam (METER-03).

    Called after a successful vector or cluster tile serve in multi_tenant mode.
    Uses get_billing_extensions() + hasattr(ext, "on_usage_event") so that:
    - When the cloud overlay is active, CloudMeteringExtension.on_usage_event()
      updates DatasetORM.last_accessed_at via update_last_accessed().
    - When no extension provides on_usage_event (single_tenant / cloud-absent),
      nothing runs — byte-identical OSS behaviour.

    Best-effort: errors are logged and swallowed so a billing hook failure NEVER
    fails a tile response (mirrors the lifespan dispatch try/except pattern in
    app/api/main.py).

    METER-03: the table_name is carried on the event so the cloud extension can
    scope the last_accessed_at update to the correct dataset row.
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
    """Check if a table is cold and delegate to the overlay for rehydration (COLD-02).

    Mirrors the METER-03 / FAIR-01 billing-import-free seam pattern exactly:
    - Returns None immediately when record_status != 'cold' (hot — the common path,
      zero overhead).
    - Returns None when not is_multi_tenant() or has_extension('cloud') is False
      (single_tenant / community / enterprise — byte-identical, no import attempted).
    - Deferred import of geolens_cloud.cold_tier.rehydrate.check_and_rehydrate inside
      a try/except so the public core image never hard-imports the overlay package.
    - ImportError → return None (overlay absent, serve normally).
    - Broad Exception → log warning, return None (a cold-check failure MUST NEVER 500
      the tile response — T-1214-17).

    When the table IS cold and the overlay is present:
      - status='hydrated' → return None so the caller continues to serve the now-hot tile.
      - status='warming'  → return a 202 Response (JSON {status: 'warming', job_id}).

    Args:
        table_name:    The dataset table_name (already resolved from the tile URL).
        record_status: The cached record_status from _resolve_dataset_meta — no extra
                       DB round-trip on the hot path (T-1214-18).
        tenant_id:     The server-resolved tenant UUID string (current_tenant_var).
    """
    import json

    # Fast path: table is hot — 99%+ of requests take this branch with zero overhead.
    if record_status != "cold":
        return None

    # Guard: cold-tier is a cloud-only / multi-tenant feature.
    if not is_multi_tenant():
        return None
    if not has_extension("cloud"):
        return None

    try:
        from geolens_cloud.cold_tier.rehydrate import check_and_rehydrate  # type: ignore[import]

        result = await check_and_rehydrate(table_name=table_name, tenant_id=tenant_id)
    except ImportError:
        # Overlay not installed — serve normally (no cold tier in this deployment).
        return None
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

_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# ---------------------------------------------------------------------------
# Module-level HTTP client for Titiler proxy (reused across requests).
# ---------------------------------------------------------------------------
# SEC-OBSV-01 (sec-audit 2026-05-21): this AsyncClient uses
# follow_redirects=True. That is safe TODAY because:
#   1. Titiler is internal-only -- no `ports:` block in docker-compose.yml
#      exposes it externally.
#   2. The only URLs this client receives are server-derived raster URIs
#      already constrained by build_titiler_cog_url() at the call site.
#
# If a future change EXPOSES Titiler externally, OR routes user-controlled
# URLs through this client without prior validate_url_for_ssrf(), this
# construction MUST move to app.modules.catalog.sources.security.make_safe_client
# -- which adds per-hop redirect SSRF revalidation. Grep this comment when
# auditing future Titiler-exposure changes.
_titiler_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
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
    record_status: str
    created_by: uuid.UUID
    record_type: str
    geometry_type: str | None
    column_info: list
    tile_cache_ttl: int | None
    # Phase 269 H-23: tile column allowlist (None / [] / list[str]).
    tile_columns: list[str] | None


# PERF-006: bounded LRU (was an unbounded dict) so a long-lived tile worker can't
# grow one entry per distinct table_name forever. Mirrors _band_stats_cache (HYG-01);
# dict-compatible .get()/[]/assignment; the per-entry TTL still bounds staleness.
_dataset_cache: LRUCache[str, tuple[float, _DatasetMeta]] = LRUCache(maxsize=256)
# threading.Lock is safe here — cache reads/writes are synchronous, no await inside lock
_dataset_cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# PERF-002: Short-TTL cache for raster dataset/asset metadata.
# Mirrors the vector _dataset_cache pattern.  The whole DB row is cached,
# INCLUDING the access-control fields (visibility, record_status) — per-request
# authz reads them from this cached snapshot rather than re-querying.  This is a
# deliberate tile-cache tradeoff with CDN max-age semantics: after a dataset is
# made private/unpublished, anonymous tile requests are rejected within at most
# _RASTER_META_CACHE_TTL seconds, not instantly.  The same bounded window
# applies to the vector cache.  Keep the TTL short.
# ---------------------------------------------------------------------------
_RASTER_META_CACHE_TTL = 60  # seconds — same TTL as the vector cache


class _RasterMeta(NamedTuple):
    """Snapshot of raster dataset+record+asset fields for tile serving.

    Includes the mutable access-control fields (visibility, record_status); see
    the _RASTER_META_CACHE_TTL note for the bounded-staleness tradeoff.
    """

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


# WR-02 (Phase 1210): bounded LRU — mirrors the vector _dataset_cache (PERF-006).
# The comment at line ~106 said this "mirrors the vector _dataset_cache pattern"
# but used an unbounded dict instead.  A long-lived tile worker serving many
# distinct raster datasets would grow this indefinitely, holding cached _RasterMeta
# objects (asset_uri strings, band_info lists) forever.  LRUCache(maxsize=256)
# matches the adjacent _dataset_cache bound.
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

# Issue #186: canonical DEM nodata sentinel. When a DEM COG does not declare a
# nodata value in its metadata (so RasterAsset.nodata is NULL), edge tiles that
# clip the data footprint contain fill pixels. Under terrainrgb encoding an
# undeclared fill of -9999 (the de-facto DEM nodata convention used by sources
# such as swissALTI3D) encodes as an extreme elevation, producing spikes and
# cliffs at the DEM boundary. -9999 is far below any real terrestrial elevation
# (Dead Sea shore ~-430 m; Challenger Deep ~-10,935 m is sub-sea-floor and not a
# land DEM value), so masking it never removes valid terrain.
_DEM_DEFAULT_NODATA = "-9999"


def _dem_nodata_param(recorded_nodata: str | None) -> str | None:
    """Resolve the Titiler ``nodata=`` value for a DEM terrainrgb tile (#186).

    Prefers the dataset's recorded nodata (from the COG metadata captured at
    ingest). Falls back to the canonical DEM sentinel ``-9999`` when none is
    recorded. Returns ``None`` only when the recorded value is non-numeric
    (e.g. ``"nan"``), in which case Titiler relies on the COG's internal mask
    and we must not inject a bogus literal.
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
    # Emit an integer literal when the value is integral (-9999 not -9999.0) so
    # the URL stays clean and matches the common DEM convention.
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
) -> float | None:
    """Estimate native raster resolution in meters from stored COG metadata."""
    if asset is None:
        return None

    res_x = _positive_number(asset.res_x)
    res_y = _positive_number(asset.res_y)
    values: list[float] = []

    if res_x is not None or res_y is not None:
        if asset.epsg == 4326:
            values.extend(_degrees_resolution_to_meters(res_x, res_y, bounds))
        else:
            # GeoLens raster ingest normally stores COGs in meter-based CRSs
            # (often EPSG:3857). For unsupported projected CRSs this still
            # produces a safer source maxzoom than the old universal z18.
            values.extend(v for v in (res_x, res_y) if v is not None)

    if not values and bounds and len(bounds) == 4 and asset.width and asset.height:
        minx, miny, maxx, maxy = bounds
        span_x = _positive_number(maxx - minx)
        span_y = _positive_number(maxy - miny)
        x_deg = span_x / asset.width if span_x else None
        y_deg = span_y / asset.height if span_y else None
        values.extend(_degrees_resolution_to_meters(x_deg, y_deg, bounds))

    return min(values) if values else None


def _raster_maxzoom_from_metadata(
    asset: RasterAsset | None,
    bounds: list[float] | None,
) -> int:
    """Choose raster source maxzoom from native resolution, with legacy fallback."""
    resolution_m = _native_resolution_meters(asset, bounds)
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
        # Apply rescale per selected band
        n_bands = min(bc, 3) if bc >= 3 else (1 if bc == 2 else bc)
        for _ in range(max(n_bands, 1)):
            parts.append(f"rescale={rescale}")

    return "&".join(parts)


# ---------------------------------------------------------------------------
# Colormap / stretch allowlists (T-1140-01 security mitigation)
# ---------------------------------------------------------------------------

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

# Per-band Titiler statistics cache keyed by (open_path, pmin, pmax). The bounds
# are part of the cache key so different percentile clips produce distinct entries —
# without this, a p2/p98 lookup would serve stale cached stats for a p5/p95 request.
# (RASTER-STRETCH-UI-01 / Phase 1153 PITFALL-01 / 1153-CONTEXT.md.)
# HYG-01: bounded LRU so long-lived tile workers don't grow memory without limit.
# 256 entries covers ~2× the typical project raster count. cachetools.LRUCache
# supports the same `in` / `[]` / assignment interface as dict.
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

    The cache key is ``(open_path, pmin, pmax)`` so different percentile clips
    never serve stale results from a prior lookup with different bounds
    (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation requirement).

    Returns a list of per-band stat dicts ordered b1, b2, ... or None when the
    statistics call fails (caller falls back to minmax).
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

    Only datasets that are BOTH public AND published are safe to cache publicly.
    A public-but-unpublished dataset is an owner/admin-only preview: anonymous
    callers are rejected, but if its tiles were marked `public` they would
    populate the auth-less nginx cache key and replay to later anonymous
    requests (SEC-002; raised as a Codex P1 on PR #243). Non-public datasets are
    never publicly cacheable.
    """
    return visibility == "public" and record_status == "published"


async def _resolve_raster_meta(
    db: AsyncSession,
    dataset_id: uuid.UUID,
) -> _RasterMeta:
    """Look up raster dataset/asset metadata with a short in-memory cache.

    PERF-002: mirrors the vector _resolve_dataset_meta / _dataset_cache pattern.
    The cached snapshot INCLUDES the access-control fields (visibility,
    record_status); per-request authz reads them from the cache, so a
    visibility/status change takes effect only after the entry expires — at most
    _RASTER_META_CACHE_TTL seconds (a deliberate tile-cache tradeoff, same
    bounded window as the vector path).

    Raises HTTPException(404) when the dataset is missing, is not a raster, or
    has no raster asset.
    """
    cache_key = str(dataset_id)
    now = time.monotonic()
    with _raster_meta_cache_lock:
        cached_entry = _raster_meta_cache.get(cache_key)
        if cached_entry is not None:
            ts, cached_meta = cached_entry
            if now - ts < _RASTER_META_CACHE_TTL:
                return cached_meta

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
                ra.band_info,
                ra.nodata
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
    )
    with _raster_meta_cache_lock:
        _raster_meta_cache[cache_key] = (now, meta)
    return meta


async def _resolve_raster_access(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    request: Request,
    user: Identity | None,
) -> tuple[_RasterMeta, str]:
    """Validate RBAC access to a raster dataset and return row metadata + storage backend.

    Performs the dataset lookup (cached via _resolve_raster_meta), raster type
    validation, embed-token / user / RBAC checks (3 auth priority branches), and
    returns the _RasterMeta together with the resolved storage_backend string.

    Raises HTTPException on any auth or lookup failure.
    """
    # PERF-002: metadata resolved from cache; auth checks always run per-request.
    meta = await _resolve_raster_meta(db, dataset_id)

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
        port = get_processing_port()
        user_roles = await port.get_user_roles(db, user)
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
                from app.modules.catalog.datasets.domain.models import DatasetGrant

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
            port = get_processing_port()
            user_roles = await port.get_user_roles(db, user)
            if "admin" not in user_roles and created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
                )

    return meta, storage_backend


@router.get("/raster-auth-check/", response_model=None)
@limiter.exempt
async def raster_auth_check(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
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
    meta, storage_backend = await _resolve_raster_access(db, dataset_id, request, user)

    # Resolve COG open-path for Titiler via the single storage seam (STOR-02 / Phase 1210).
    # resolve_open_path handles local/s3/azure dispatch and http(s) pass-through.
    # In multi_tenant mode, prefix the key with tenants/{tenant_id}/ so each tenant's
    # objects are namespaced on the data plane (aligned with the 1209 convention).
    # In single_tenant (default), tenant_id is None and the path is byte-identical.
    tenant_id = current_tenant_var.get() if is_multi_tenant() else None
    open_path = resolve_open_path(meta.asset_uri, tenant_id=tenant_id)

    cache_status = (
        "public"
        if _is_publicly_cacheable(meta.visibility, meta.record_status)
        else "private"
    )
    if meta.is_dem:
        # DEM terrain: use terrainrgb algorithm with NO rescale — the algorithm
        # reads raw elevation values and encodes them into RGB channels directly.
        #
        # Issue #186: mask the DEM's nodata so fill pixels inside served edge
        # tiles render transparent instead of encoding as an extreme elevation
        # (which produces terrain spikes/cliffs at the DEM boundary). Driven by
        # the dataset's recorded nodata, with the canonical -9999 DEM sentinel as
        # a safe fallback. The OUTSIDE-the-footprint case (whole tile out of
        # bounds) is already handled by the source `bounds` → 204; this masks the
        # nodata pixels WITHIN partially-covered edge tiles.
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
            "Absent = current p2 behavior. Must be less than pmax."
        ),
    ),
    pmax: float | None = Query(
        None,
        description=(
            "Upper percentile clip for stretch=percentile (0–100, default 98). "
            "Absent = current p98 behavior. Must be greater than pmin."
        ),
    ),
    sigma: float | None = Query(
        None,
        description=(
            "Standard-deviation multiplier for stretch=stddev (default 2.0). "
            "Absent = current 2.0σ behavior. Must be > 0."
        ),
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    colormap_name: Optional Titiler colormap for single-band display. Validated
    against _ALLOWED_COLORMAPS (T-1140-01). Gray is the Titiler default for
    single-band — passing gray is a no-op (not forwarded). colormap_name is not
    forwarded for DEM layers (render_params starts with 'algorithm=').

    stretch: Optional stretch strategy. percentile/stddev compute a stats-based
    rescale from Titiler band statistics. Multi-band rasters produce one rescale=
    fragment per band (up to 3, RASTER-STRETCH-03).

    pmin/pmax: Configurable percentile clip bounds (default 2/98). Must satisfy
    0 <= pmin < pmax <= 100. Forwarded as repeated p= params to /cog/statistics.
    The _band_stats_cache key includes pmin/pmax so different bounds never serve
    stale cached stats (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation).

    sigma: Standard-deviation multiplier for stretch=stddev (default 2.0).
    Must be > 0.
    """
    # Resolve effective bounds (apply defaults so callers downstream always receive
    # concrete values, not None).
    eff_pmin: float = pmin if pmin is not None else 2.0
    eff_pmax: float = pmax if pmax is not None else 98.0
    eff_sigma: float = sigma if sigma is not None else _STDDEV_SIGMA

    # T-1153-01: validate pmin/pmax/sigma BEFORE any Titiler call.
    # Apply checks whenever the param is present, regardless of active stretch mode,
    # so invalid inputs are always rejected (consistent with T-1140-01 approach).
    if pmin is not None or pmax is not None:
        if not (0 <= eff_pmin < eff_pmax <= 100):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "pmin/pmax must satisfy 0 <= pmin < pmax <= 100; "
                    f"got pmin={eff_pmin}, pmax={eff_pmax}"
                ),
            )
    if sigma is not None and not (sigma > 0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sigma must be > 0; got sigma={sigma}",
        )

    # Reuse the auth-check logic to get the open path and render params
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

    # Append colormap_name to Titiler render params when:
    #   1. A non-default colormap was requested (gray is Titiler's single-band default)
    #   2. This is not a DEM layer (algorithm= prefix means terrainrgb — do not override)
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

    # stretch: minmax (default) keeps the dtype-based rescale already in
    # render_params. percentile/stddev compute a stats-based rescale from Titiler
    # band statistics and override the rescale fragment.
    # Multi-band: n_bands=min(band_count or 1, 3) so each band gets an independent
    # rescale= fragment (RASTER-STRETCH-03). Not applied to DEM (algorithm=terrainrgb).
    # Falls back to minmax with a logged warning when stats are missing.
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
            if resp.status_code in (500, 503) and attempt < max_retries:
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
    token-generation logic (PERF-N5). Does NOT perform auth — caller must
    ensure the dataset is visible to the current user.
    """
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        bounds = None
        if dataset.record.spatial_extent is not None:
            try:
                shape = to_shape(dataset.record.spatial_extent)
                bounds = list(shape.bounds)  # [xmin, ymin, xmax, ymax]
            except Exception:  # broad: extent parse is non-fatal; geoalchemy/shapely errors fall back to no-bounds
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
            maxzoom=_raster_maxzoom_from_metadata(raster_asset, bounds),
            tile_size=256,
            format="png",
        )

    # Vector dataset branch
    # WR-03 (Phase 1209-CR): in multi_tenant, bind the scope to the active
    # tenant so a token minted for tenant A cannot be replayed in tenant B's
    # context even if both tenants share the same table_name.
    # single_tenant: scope = bare table_name — byte-identical to pre-1209.
    exp = round_expiry()
    _scope_tid = current_tenant_var.get() if is_multi_tenant() else None
    scope = (
        f"{_scope_tid}:{dataset.table_name}"
        if _scope_tid is not None
        else dataset.table_name
    )
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
    """Status-aware access gate for the tile-token endpoints (SEC-01).

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
    if dataset.record.record_type in ("raster_dataset", "vrt_dataset"):
        raster_asset_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
        )
        raster_asset = raster_asset_result.scalar_one_or_none()

    return _build_tile_token_for_dataset(dataset, raster_asset)


@router.post("/tokens/", response_model=TileTokenBatchResponse)
@limiter.exempt
async def get_tile_tokens_batch(
    body: TileTokenBatchRequest,
    user: Identity | None = Depends(get_optional_user),
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
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM

    port = get_processing_port()
    # De-duplicate while preserving order
    unique_ids = list(dict.fromkeys(body.dataset_ids))

    # Single bulk query for all requested datasets
    result = await db.execute(
        select(DatasetORM)
        .options(joinedload(DatasetORM.record))
        .where(DatasetORM.id.in_(unique_ids))
    )
    datasets_by_id = {ds.id: ds for ds in result.scalars().all()}
    raster_dataset_ids = [
        ds.id
        for ds in datasets_by_id.values()
        if ds.record.record_type in ("raster_dataset", "vrt_dataset")
    ]
    raster_assets_by_dataset_id: dict[uuid.UUID, RasterAsset] = {}
    if raster_dataset_ids:
        raster_asset_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id.in_(raster_dataset_ids))
        )
        raster_assets_by_dataset_id = {
            asset.dataset_id: asset for asset in raster_asset_result.scalars().all()
        }

    tokens: dict[str, VectorTileToken | RasterTileToken | dict] = {}
    for dataset_id in unique_ids:
        dataset = datasets_by_id.get(dataset_id)
        key = str(dataset_id)
        if dataset is None:
            tokens[key] = {"error": "Dataset not found"}
            continue

        # Per-dataset auth check (status-aware)
        try:
            await _enforce_tile_token_access(db, dataset, dataset_id, user, port)
        except HTTPException as exc:
            tokens[key] = {"error": exc.detail}
            continue

        tokens[key] = _build_tile_token_for_dataset(
            dataset,
            raster_assets_by_dataset_id.get(dataset.id),
        )

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

    DP-02 (Phase 1209-03): In ``multi_tenant`` the cache key is
    ``{tid}:{table_name}`` so two tenants with the same ``table_name`` never
    share a cache entry (T-1209-13).  The DB query also adds a
    ``DatasetORM.tenant_id == tid`` WHERE clause to close the cross-dataset
    authz leak class on the data plane (T-1209-12).

    In ``single_tenant``: cache key is bare ``table_name``; no tenant filter —
    byte-identical to pre-1209 behaviour.
    """
    now = time.monotonic()

    # DP-02: compute tenant-aware cache key
    tid = current_tenant_var.get() if is_multi_tenant() else None
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
        # DP-02: filter by tenant_id — a bare table_name lookup without scoping
        # could return a dataset belonging to a different tenant if names collide.
        # If tid is None in multi_tenant, the query proceeds unscoped and RLS
        # will fail-close at the control plane; data plane rows have tenant_id
        # that won't match, so the result is also effectively 404.
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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired embed token, or dataset not in scope",
            )
        return "private"

    if meta.visibility != "public":
        if not sig or not exp or not scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Signature required for non-public tiles",
            )
        # WR-03 (Phase 1209-CR): expected scope mirrors _build_tile_token_for_dataset:
        # in multi_tenant the scope is "{tid}:{table_name}" to prevent cross-tenant
        # token replay.  single_tenant: scope is bare table_name — unchanged.
        _verify_tid = current_tenant_var.get() if is_multi_tenant() else None
        _expected_scope = (
            f"{_verify_tid}:{meta.table_name}"
            if _verify_tid is not None
            else meta.table_name
        )
        if scope != _expected_scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Scope mismatch"
            )
        if not verify_tile_signature(scope, exp, sig):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired signature",
            )
        # SEC-009: a valid signature authorizes a single caller for this
        # non-public dataset; the tile bytes must not be retained by a shared
        # cache. Return "private" so _tile_headers emits Cache-Control: private
        # (previously this fell through to "public", letting shared caches store
        # private vector tiles under an auth-less key).
        return "private"

    # Public dataset: still block non-published for unauthenticated users
    if meta.record_status != "published":
        # Unauthenticated users cannot see unpublished public datasets
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


def _cluster_cache_table_key(
    table_name: str, *, cluster_radius: int, cluster_max_zoom: int
) -> str:
    return f"{table_name}:cluster:r{cluster_radius}:z{cluster_max_zoom}"


def _tile_headers(cache_scope: str, cache_ttl: int) -> dict[str, str]:
    return {
        "Content-Encoding": "gzip",
        "Cache-Control": f"{cache_scope}, max-age={cache_ttl}",
        "Access-Control-Allow-Origin": "*",
    }


@router.get(
    "/clusters/{table_path:path}/{z:int}/{x:int}/{y:int}.pbf",
    response_class=Response,
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
    cluster_radius: int = Query(48, ge=1, le=256),
    cluster_max_zoom: int = Query(14, ge=0, le=22),
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> Response:
    """Serve a server-side clustered vector tile for point datasets.

    URL pattern: /tiles/clusters/data.{table_name}/{z}/{x}/{y}.pbf

    This route deliberately reuses the normal vector tile auth model:
    public datasets are readable directly, non-public datasets require either
    valid HMAC tile params or a valid embed token scoped to the dataset.
    """
    table_name = _parse_vector_tile_table(table_path)
    _validate_tile_coordinates(z, x, y)
    meta = await _resolve_dataset_meta(table_name, db)
    _ensure_clusterable_dataset(meta)
    cache_scope = await _authorize_vector_tile_request(
        request,
        meta,
        db,
        sig=sig,
        exp=exp,
        scope=scope,
        user=user,
    )

    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl

    # DP-02 (Phase 1209-CR-01): prefix cluster cache key with tenant id in
    # multi_tenant so two tenants with the same table_name never share cached
    # cluster tiles.  single_tenant: no prefix — byte-identical to pre-1209
    # behavior (T-1209-CR-01).
    _cluster_tid = current_tenant_var.get() if is_multi_tenant() else None
    _cluster_tenant_prefix = f"{_cluster_tid}:" if _cluster_tid is not None else ""
    cluster_cache_key = _cluster_tenant_prefix + _cluster_cache_table_key(
        table_name,
        cluster_radius=cluster_radius,
        cluster_max_zoom=cluster_max_zoom,
    )

    tile_cache = get_tile_cache()
    if tile_cache is not None:
        cached = await tile_cache.get(cluster_cache_key, z, x, y)
        if cached is not None:
            if len(cached) == 0:
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            return Response(
                content=cached,
                media_type="application/vnd.mapbox-vector-tile",
                headers=_tile_headers(cache_scope, cache_ttl),
            )

    # COLD-02 (Phase 1214-04): cold-rehydrate seam — BEFORE cluster tile query.
    # Mirrors the tile_endpoint seam: uses cached meta.record_status (T-1214-18);
    # failure is broad-except-swallowed (T-1214-17).
    _cluster_cold_tid = current_tenant_var.get(None)
    _cluster_cold_result = await _check_cold_rehydrate(
        table_name,
        meta.record_status,
        str(_cluster_cold_tid) if _cluster_cold_tid is not None else "",
    )
    if _cluster_cold_result is not None:
        return _cluster_cold_result

    try:
        pool = get_tile_pool()
    except RuntimeError as exc:
        logger.warning(
            "Tile pool unavailable",
            table_name=table_name,
            mode="cluster",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tile service unavailable",
        )

    # DP-02 (Phase 1209-03): acquire ONE connection and open a transaction so
    # SET LOCAL ROLE + SET LOCAL search_path survive for the tile query
    # (PgBouncer transaction-mode: SET LOCAL is valid within one txn; T-1209-10).
    tid = current_tenant_var.get()
    _schema = tenant_data_schema(tid)

    try:
        async with pool.acquire() as tile_conn:
            async with tile_conn.transaction():
                # Bind per-tenant role + search_path BEFORE the tile query.
                # No-op in single_tenant or when tid is None.
                await set_tenant_role_for_tile_request(tile_conn, tid)
                tile_data = await get_cluster_tile(
                    pool,
                    table_name,
                    z,
                    x,
                    y,
                    cluster_radius=cluster_radius,
                    cluster_max_zoom=cluster_max_zoom,
                    conn=tile_conn,
                    schema=_schema,
                )
    except asyncio.TimeoutError:
        logger.warning(
            "Cluster tile pool acquire timeout",
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
    except Exception as exc:  # broad: cluster tile SQL/PostGIS errors are varied; callers get controlled 503
        logger.exception(
            "Cluster tile query failed",
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
        if tile_cache is not None:
            await tile_cache.set(cluster_cache_key, z, x, y, b"", ttl=cache_ttl)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    logger.debug(
        "cluster_tile_access",
        dataset_id=str(meta.record_id),
        table_name=table_name,
        z=z,
        x=x,
        y=y,
        cluster_radius=cluster_radius,
        cluster_max_zoom=cluster_max_zoom,
        scope=scope or cache_scope,
    )

    # METER-03 (Phase 1213-06): emit usage event through the billing-import-free
    # seam for cluster tile serves (same path as the regular tile endpoint).
    await _emit_tile_usage_event(table_name)

    # PERF-005: gzip is CPU-bound — offload to a thread so the event loop isn't
    # stalled compressing wide low-zoom tiles (asyncio.to_thread convention).
    compressed = await asyncio.to_thread(gzip.compress, tile_data, 6)
    if tile_cache is not None:
        await tile_cache.set(cluster_cache_key, z, x, y, compressed, ttl=cache_ttl)

    return Response(
        content=compressed,
        media_type="application/vnd.mapbox-vector-tile",
        headers=_tile_headers(cache_scope, cache_ttl),
    )


@router.get("/{table_path:path}/{z:int}/{x:int}/{y:int}.pbf", response_class=Response)
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
    user: Identity | None = Depends(get_optional_user),
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
    meta = await _resolve_dataset_meta(table_name, db)
    cache_scope = await _authorize_vector_tile_request(
        request,
        meta,
        db,
        sig=sig,
        exp=exp,
        scope=scope,
        user=user,
    )

    # Parse `cols` query param into a validated, deduped, sorted list.
    # Validation against the dataset's column_info happens inside
    # _select_tile_columns; here we just normalize so the cache key is
    # deterministic across permutations (`cols=a,b` and `cols=b,a` hit
    # the same cache entry).
    additional_columns: list[str] | None = None
    cols_cache_key = ""
    if cols:
        raw = [c.strip() for c in cols.split(",") if c.strip()]
        if raw:
            additional_columns = sorted(set(raw))
            cols_cache_key = ",".join(additional_columns)

    # Get column info for attribute selection
    columns = meta.column_info

    # Use per-dataset cache TTL when set, else global default
    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl

    # DP-02 (Phase 1209-CR-01): prefix tile cache key with tenant id in
    # multi_tenant so two tenants with the same table_name never share a
    # cached tile binary.  single_tenant: no prefix — byte-identical to
    # pre-1209 behavior (T-1209-CR-01).
    _tile_tid = current_tenant_var.get() if is_multi_tenant() else None
    _tile_cache_key = (
        f"{_tile_tid}:{table_name}" if _tile_tid is not None else table_name
    )

    # Check tile cache before hitting PostGIS
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        cached = await tile_cache.get(_tile_cache_key, z, x, y, cols_key=cols_cache_key)
        if cached is not None:
            if len(cached) == 0:
                # Empty sentinel — tile was previously confirmed empty
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            return Response(
                content=cached,
                media_type="application/vnd.mapbox-vector-tile",
                headers=_tile_headers(cache_scope, cache_ttl),
            )

    # COLD-02 (Phase 1214-04): cold-rehydrate seam — BEFORE tile query.
    # Uses the cached meta.record_status (no extra DB round-trip on the hot path,
    # T-1214-18). Returns a 202 Response for over-gate warming or None to continue.
    # A cold-check failure is broad-except-swallowed so it NEVER 500s the tile
    # (T-1214-17). Published/anon-shared datasets are hot (record_status != 'cold')
    # so a public map viewer never receives a 202-warming response (T-1214-17).
    _cold_tid = current_tenant_var.get(None)
    _cold_result = await _check_cold_rehydrate(
        table_name,
        meta.record_status,
        str(_cold_tid) if _cold_tid is not None else "",
    )
    if _cold_result is not None:
        return _cold_result

    # FAIR-01 (Phase 1213-06): per-tenant concurrency budget.
    # When the cloud overlay is active, acquire the per-tenant semaphore BEFORE
    # entering the tile pool. This caps concurrent tile DB connections per tenant
    # to _TILE_CONCURRENCY so one tenant cannot starve others of pool connections
    # (T-1213-22 noisy-neighbour mitigation). In single_tenant / cloud-absent mode,
    # _cloud_fairness is None and the semaphore step is skipped — byte-identical OSS.
    _cloud_fairness = _get_cloud_fairness()
    _tenant_sem = None
    if _cloud_fairness is not None and is_multi_tenant():
        _tile_limiter_obj, _get_sem, _cc_value = _cloud_fairness
        _sem_key = str(current_tenant_var.get(None) or "anon")
        _tenant_sem = _get_sem(_sem_key)

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

    # DP-02 (Phase 1209-03): acquire ONE connection and open a transaction so
    # SET LOCAL ROLE + SET LOCAL search_path survive for the tile query
    # (PgBouncer transaction-mode: SET LOCAL is valid within one txn; T-1209-10).
    tid = current_tenant_var.get()
    _schema = tenant_data_schema(tid)

    # FAIR-01: per-tenant semaphore acquisition (cloud only; no-op when absent).
    _sem_acquired = False
    if _tenant_sem is not None:
        try:
            await asyncio.wait_for(_tenant_sem.acquire(), timeout=10.0)
            _sem_acquired = True
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tile concurrency limit reached for tenant, please retry",
                headers={"Retry-After": "2"},
            )

    try:
        async with pool.acquire() as tile_conn:
            async with tile_conn.transaction():
                # Bind per-tenant role + search_path BEFORE the tile query.
                # No-op in single_tenant or when tid is None.
                await set_tenant_role_for_tile_request(tile_conn, tid)
                tile_data = await get_tile(
                    pool,
                    table_name,
                    z,
                    x,
                    y,
                    columns,
                    tile_columns=meta.tile_columns,
                    additional_columns=additional_columns,
                    conn=tile_conn,
                    schema=_schema,
                )
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
    except Exception as exc:  # broad: tile query spans MVT SQL/PostGIS — varied DB errors map to 500 with logged context
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
    finally:
        # FAIR-01: always release the per-tenant semaphore (cloud only).
        if _sem_acquired and _tenant_sem is not None:
            _tenant_sem.release()

    if tile_data is None:
        # Cache empty tiles to avoid repeated PostGIS queries for sparse datasets
        if tile_cache is not None:
            await tile_cache.set(
                _tile_cache_key, z, x, y, b"", ttl=cache_ttl, cols_key=cols_cache_key
            )
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

    # METER-03 (Phase 1213-06): emit tile-request usage event through the
    # billing-import-free seam so the cloud overlay can update last_accessed_at.
    # Best-effort fire-and-forget — errors logged, tile response unaffected.
    await _emit_tile_usage_event(table_name)

    # Compress and return with proper headers.
    # PERF-005: gzip is CPU-bound — offload to a thread so the event loop isn't
    # stalled compressing wide low-zoom tiles (asyncio.to_thread convention).
    compressed = await asyncio.to_thread(gzip.compress, tile_data, 6)

    # Cache the compressed tile bytes for subsequent requests
    if tile_cache is not None:
        await tile_cache.set(
            _tile_cache_key, z, x, y, compressed, ttl=cache_ttl, cols_key=cols_cache_key
        )

    # FAIR-01: when cloud overlay is active, override Cache-Control header with
    # the CDN cache-hit SLO value from tile_cache_control_value() so tile
    # responses carry the correct CDN TTL. In single_tenant / cloud-absent, the
    # existing _tile_headers() output is unchanged — byte-identical OSS.
    _response_headers = _tile_headers(cache_scope, cache_ttl)
    if _cloud_fairness is not None:
        _, _, _cc_fn = _cloud_fairness
        _response_headers = {**_response_headers, "Cache-Control": _cc_fn()}

    return Response(
        content=compressed,
        media_type="application/vnd.mapbox-vector-tile",
        headers=_response_headers,
    )

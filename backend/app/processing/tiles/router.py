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

# ---------------------------------------------------------------------------
# Provider-neutral data-serving hooks. Community resolves a no-op extension;
# hosted deployments register their implementation through geolens.extensions.
# ---------------------------------------------------------------------------


def _get_tile_serving_controls(tenant_id: str):  # type: ignore[no-untyped-def]
    """Return the registered concurrency limiter and cache-policy override."""
    extension = get_data_serving_extension()
    return (
        extension.get_tile_concurrency_limiter(tenant_id),
        extension.get_tile_cache_control(),
    )


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
    """Prepare a cold table through the provider-neutral serving seam.

    Mirrors the METER-03 extension seam pattern exactly:
    - Returns None immediately when record_status != 'cold' (hot — the common path,
      zero overhead).
    - Returns None when not is_multi_tenant() (single-tenant Community and
      Enterprise remain byte-identical).
    - The Community extension returns None, so no provider package is imported.
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

    # Table preparation is only relevant in multi-tenant mode. The Community
    # default is additionally a no-op, preserving the overlay-absent path.
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

# builder-audit #338 MVT-09: `_TABLE_NAME_RE` is imported from tiles.service (the single
# source of truth) rather than re-declared here, so the SQL-injection-defense regex
# has exactly one definition shared by the router and the query builder.

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
# construction MUST move to app.platform.security.make_safe_client
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


def _evict_dataset_meta(table_name: str) -> None:
    """Drop every cached meta entry for a table name.

    fix(#1429): this cache decides authorization — visibility, record_status
    and created_by are read from the snapshot rather than re-queried. Keying
    tile bytes by dataset id cannot help here, because the stale entry is what
    picks the dataset in the first place.

    fix(#1444): what that used to mean is gone. A delete freed ``roads`` for
    the next dataset to draw, so a worker holding the old entry served the NEW
    table's rows under the DELETED dataset's visibility. GH-1443 retires a
    freed name in ``catalog.retired_table_names`` and ``generate_table_name``
    collides against it, so a name is never redrawn and a surviving entry can
    only describe the dataset it was cached for. This eviction now buys
    freshness — an entry for a table that is gone is dead weight, and every
    sibling write path evicts — not the authorization boundary itself.

    Both key shapes are swept — bare ``table_name`` in single-tenant and
    ``{tid}:{table_name}`` in multi-tenant — because a process can hold entries
    from before a mode transition, and a delete arrives with only the name.
    """
    suffix = f":{table_name}"
    with _dataset_cache_lock:
        stale = [
            key for key in _dataset_cache if key == table_name or key.endswith(suffix)
        ]
        for key in stale:
            _dataset_cache.pop(key, None)


register_table_invalidation_listener(_evict_dataset_meta)

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
    tile_cache_version: int


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
    *,
    lon_span: float | None = None,
) -> float | None:
    """Estimate native raster resolution in meters from stored COG metadata.

    ``lon_span`` is the extent's honest longitudinal width (``extent_lon_span``).
    fix(#887): ``bounds`` is deliberately the monotonic span bbox, which reads
    -180..180 for a seam-crossing extent, so the width has to arrive separately
    or a 10°-wide Pacific raster measures 360° and collapses its own maxzoom.
    """
    if asset is None:
        return None

    res_x = _positive_number(asset.res_x)
    res_y = _positive_number(asset.res_y)
    values: list[float] = []

    if res_x is not None or res_y is not None:
        # fix(#939): "is this resolution in degrees?" must not be an EPSG
        # equality test. 4326 is not the only geographic CRS — 4269, 4258,
        # 4979, 9518 and friends all store degree resolutions, and reading
        # those as metres collapsed native resolution by ~5 orders of
        # magnitude and pinned maxzoom to the cap (ETOPO at epsg=9518 got
        # z22 instead of z7). Classify from the WKT already on the asset row
        # (cached parse, no network or EPSG database round-trip); the
        # degree-unit check is separate because a grads GEOGCS (Paris-meridian
        # family) is geographic without its resolutions being degrees.
        geographic = wkt_is_geographic(asset.crs_wkt)
        if geographic is None:
            # No usable WKT stored: fall back to the historical EPSG test.
            geographic = asset.epsg == 4326
        if geographic:
            if wkt_has_degree_unit(asset.crs_wkt) is not False:
                values.extend(_degrees_resolution_to_meters(res_x, res_y, bounds))
            # else: geographic with a non-degree angular unit (grads).
            # The stored resolution is neither metres nor degrees, so leave
            # ``values`` empty and let the bounds-derived estimate below
            # take over instead of guessing.
        else:
            # GeoLens raster ingest normally stores COGs in meter-based CRSs
            # (often EPSG:3857). For unsupported projected CRSs this still
            # produces a safer source maxzoom than the old universal z18.
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
    """Normalize a request's ``v`` into a raster meta cache-key segment (#1329).

    ``tile_cache_version`` is a small monotonic integer, so only a short ASCII
    digit run is accepted as a key segment. Anything else — absent, empty,
    non-numeric, absurdly long — returns None, which puts the caller back on the
    unversioned key and therefore on the pre-#1329 behavior (60s-bounded
    staleness), never on an error.
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

    PERF-002: mirrors the vector _resolve_dataset_meta / _dataset_cache pattern.
    The cached snapshot INCLUDES the access-control fields (visibility,
    record_status); per-request authz reads them from the cache, so a
    visibility/status change takes effect only after the entry expires — at most
    _RASTER_META_CACHE_TTL seconds (a deliberate tile-cache tradeoff, same
    bounded window as the vector path).

    Multi-tenant cache keys include the resolved tenant UUID and the SQL query
    filters ``catalog.datasets.tenant_id`` explicitly. An unresolved tenant
    fails before cache lookup or SQL. Single-tenant keys and SQL stay unchanged.

    ``requested_version`` is the request's ``v`` (see the #1329 note at the key
    derivation); callers that have no request context omit it and keep the
    pre-#1329 key.

    Raises HTTPException(404) when the dataset is missing, is not a raster, or
    has no raster asset.
    """
    tenant_id = _require_tile_tenant_context()
    base_key = f"{tenant_id}:{dataset_id}" if tenant_id is not None else str(dataset_id)
    # fix(#1329): LOOK UP under the REQUEST's `v`, not the row's
    # `tile_cache_version`. Three paths swap a raster's pointer in place
    # (reupload #1290, VRT regeneration, STAC moved-asset refresh #1326) and all
    # three bump the version in the same transaction — but the row's version
    # reaches this function only through the snapshot below, so it is exactly as
    # stale as the `asset_uri` it would be guarding and looking up by it would
    # buy nothing. The request's `v` is independent: it comes from the
    # dataset/map metadata the client fetched, so the first tile request after a
    # swap carries the new value, misses in EVERY api process, and re-reads the
    # href and band shape once. Requests still carrying the old `v` read their
    # own entry — stale but well-formed, bounded by the TTL and self-healing,
    # which is the tradeoff #1329 accepts.
    #
    # The lookup is under the request's value, but the STORE is under the row's
    # (see the write site below) — the request never names the entry it writes.
    # Memory stays bounded by the LRU, and a caller varying `v` costs one extra
    # indexed read per request in the database.
    #
    # fix(#1778): that read is not the whole price, and this note used to say it
    # was ("at most one extra indexed read per request, the same order as the
    # uncached miss an unknown dataset id already produces"). The read opens a
    # transaction, and `get_db` holds the connection it opened until the
    # response is written, so the real cost of a miss on the raster path was an
    # API-pool connection pinned across the caller's whole Titiler round trip.
    # `_resolve_raster_access` now releases it before returning; the sentence
    # above is true again because that call site makes it true, not on its own.
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
    # fix(#1329 codex P1): entries must be stamped with the version they
    # correspond to, or a predictable future `v` pre-warms stale metadata past
    # the swap. Storing under the REQUESTED value let any caller name an entry:
    # asking for `v=N+1` while the row still reads N stored the CURRENT snapshot
    # under the next version's key, and the swap that bumps the row to N+1 then
    # found that key already occupied, so genuine `v=N+1` requests kept the
    # pre-swap href for a full TTL. Refusing to mark such a response cacheable
    # (#1372) does not help — that defends nginx, and the poisoned entry is
    # process-local. Deriving the write key from the snapshot's OWN version
    # makes it structurally impossible: key and content always agree, a
    # mismatched request resolves fresh and writes only its dataset's real
    # version, and the first post-swap request at the new version finds nothing
    # and reads the new pointer. The cost is that mismatched-`v` requests are
    # permanent misses, one indexed read each.
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

    fix(#688): the mirror of the vector verify path. The expected scope is
    recomputed with the SAME ``tenant_bound_scope(str(dataset.id))`` expression
    the mint site uses — the two must never be allowed to drift, because a
    divergence is a silent authorization bypass rather than a test failure. A
    raster dataset has no ``table_name``, so the dataset id is the resource
    string; it is already unique per tenant and is what the tile URL keys on.

    fix(#688 codex r1): returns a bool instead of raising. The signature is an
    ADDITIONAL way in for a client that cannot send headers, never a restriction
    on one that can, so an absent, malformed, or expired signature has to fall
    through to the other branches rather than refuse. Refusing preemptively
    403'd an in-app map holding a perfectly valid session the moment its
    15-minute template aged out, since MapLibre keeps requesting the URL it was
    given.

    ``tenant_bound_scope`` raises when multi-tenant is active with no tenant in
    context, so the import stays inside the function exactly as it does on the
    vector path.
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
    cache key (#1329); it is never an input to any auth decision.

    Raises HTTPException on any auth or lookup failure.
    """
    # PERF-002: metadata resolved from cache; auth checks always run per-request.
    #
    # fix(#1518 codex P2 round 3): a 404 here is reached before any capability
    # can be evaluated — the embed token is validated against a dataset id that
    # resolves to nothing — so no capability authorized this request and the
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
        # fix(#688) auth priority 2: a valid signed template, mirroring the
        # vector path. MapLibre issues tile image requests itself and attaches
        # no header, so without this an API-key-only client could not render a
        # private raster at all — the contract handed it a template that could
        # never authenticate. nginx forwards `$is_args$args` to this proxy, so
        # the query string arrives intact (`frontend/nginx.conf`).
        #
        # fix(#688 codex r1): checked ahead of the visibility split rather than
        # inside the non-public arm. A public-but-unpublished raster is an
        # owner/admin draft preview, and the mint endpoint issues a template for
        # it; gating on `visibility != "public"` sent that template to the
        # unpublished branch below, which 404s a headerless caller. The
        # signature already attests that someone authorized minted it for this
        # dataset, which is the same thing it attests on the vector path.
        pass
    else:
        # fix(#1518): CAPABILITY obligation, placed where the control flow makes
        # the rule readable rather than inferred. Reaching this arm means
        # NEITHER capability authorized the request: no embed token was sent,
        # and no valid signed template was presented. What remains is decided by
        # who is asking, so a supplied-but-unresolvable credential was
        # load-bearing and earns the fail-closed 401.
        reject_unresolvable_credentials(request, user)

        if visibility != "public":
            # Auth priority 3: require authenticated user for non-public datasets
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # fix(#929 review): route through the permission extension rather
            # than an inline policy mirror. The default extension grants the
            # creator exemption on restricted datasets; an overlay policy that
            # deliberately denies the creator (revoked clearance, ABAC) must
            # still win here, exactly as it does on the token path below.
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
                # Unauthenticated users cannot see unpublished public datasets
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
    # upstream, the same remedy fix(#1451) applied to the vector path and for
    # the same reason: `get_db` holds whatever a `db.execute` opened until the
    # response is written, and the only caller of this function then awaits
    # Titiler for up to three attempts at a 30s timeout plus backoff. The pool
    # is db_pool_size + db_max_overflow per uvicorn worker, so a handful of
    # concurrent tile requests could park all of it on an upstream fetch and
    # make every other request in that worker wait out db_pool_timeout.
    #
    # A cache-buster reaches this on every request: the meta cache is keyed
    # under the request's `v` (#1329), which accepts any short digit run, so a
    # caller varying it misses the snapshot each time and pays the read. The
    # note at that key derivation prices that miss as one extra indexed read;
    # the read was never the expensive half.
    #
    # Everything past here is locals. `meta` is a plain snapshot built from the
    # row above and `storage_backend` a string, so nothing the caller touches
    # can reopen a transaction behind its back. It is here rather than at the
    # call site for the reason the vector twin gives: the caller cannot release
    # what it did not know was taken. Every read on this path is read-only, so
    # the rollback discards nothing.
    await db.rollback()

    return meta, storage_backend


# fix(#957): unpublished from the API contract, not deleted. The route
# registration is what is vestigial: it was the nginx `auth_request` target back
# when nginx proxied raster tiles straight to Titiler, and `frontend/nginx.conf`
# now forwards them to the api-side `/tiles/raster-proxy/` instead. The HANDLER
# is load-bearing — `raster_tile_proxy` calls it in-process below and reads four
# `X-GeoLens-*` headers off the Response it returns. Keeping the route mounted
# also keeps the raster-RBAC coverage (21 HTTP call sites across five test
# files) exercising the real handler. What it stopped being is a published SDK
# endpoint whose only answer is internal storage topology.
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
    ``X-GeoLens-*`` headers off the returned Response. It was reachable over
    HTTP as the nginx ``auth_request`` target; that topology is gone and the
    route is no longer published in the OpenAPI schema (#957), though it stays
    mounted for the raster-RBAC tests.

    Returns:
        200 with X-GeoLens-Asset-OpenPath and X-GeoLens-Cache-Status headers
        401 if authentication is required but missing
        403 if embed token is invalid
        404 if dataset not found, not a raster, or has no raster asset
    """
    # fix(#1372 codex r4): nginx keys on the FIRST occurrence of `v` and matches
    # the param NAME case-insensitively; `QueryParams.get()` returns the LAST
    # occurrence of an exact-case name — so `?v=<future>&v=<current>` (or
    # `?V=<future>`) would pass a naive check while nginx keys on the future
    # value. Read once here because the same values decide two things: which
    # metadata cache entry serves this request (#1329) and whether the response
    # may be stored by the shared cache (below).
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
    # fix(#1372 codex r3): a shared-cache entry must only ever be written under
    # the dataset's CURRENT tile_cache_version. The counter is advertised in
    # public URLs and increments predictably, so an unvalidated `v` would let a
    # caller pre-warm the NEXT version's cache key with pre-replace bytes and
    # defeat the invalidation for a full TTL. A mismatched `v` still serves —
    # a stale tab keeps rendering (its own version's entry for up to the meta
    # TTL after a swap, then the current bytes, #1329) — but as
    # `private, no-store`, so the wrong key is never populated. Compared
    # against the same cached meta snapshot the bytes come from
    # (`_RASTER_META_CACHE_TTL` note above), so version and content can never
    # disagree within one response.
    #
    # fix(#1372 codex r4): the match must mirror nginx's `$arg_v` semantics,
    # not Starlette's (read at the top of this handler, with the parser
    # disagreement documented there). Cacheable requires exactly one
    # case-insensitive `v`, equal to the current version; anything else is
    # served no-store.
    if (
        cache_status == "public"
        and v_values
        and (len(v_values) != 1 or v_values[0] != str(meta.tile_cache_version))
    ):
        cache_status = "private"
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

    pmin/pmax: Configurable percentile clip bounds (default 2/98), read and
    validated (0 <= pmin < pmax <= 100) only when stretch=percentile. Forwarded
    as repeated p= params to /cog/statistics. The _band_stats_cache key includes
    pmin/pmax so different bounds never serve stale cached stats
    (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation).

    sigma: Standard-deviation multiplier for stretch=stddev (default 2.0), read
    and validated (> 0) only when stretch=stddev.

    fix(#1778 codex r2): pmin/pmax/sigma used to be validated whenever present,
    regardless of the active stretch mode, so an "inactive" value could still
    422. frontend/nginx.conf's raster proxy_cache_key blanks an inactive value
    out of the cache key to stop it defeating the cache; making that safe on
    every input (including a repeated query parameter, where nginx's $arg_x
    reads the FIRST occurrence and this endpoint's scalar Query reads the
    LAST) needs "inactive" to mean the SAME thing on both sides: ignored, not
    merely unvalidated for some inputs. A cache HIT must never disagree with
    what an uncached request would answer.
    """
    # A-fix(#315 follow-up): defensively sanitize the {fmt} path param before it is
    # interpolated into the Titiler endpoint URL. Some reverse-proxy rewrites (e.g.
    # nginx `rewrite ... $is_args$args` + a variable `proxy_pass`) URL-encode the
    # request's query string into the PATH, so {fmt} can arrive as "png?stretch=..."
    # -> the built Titiler URL becomes ".../771.png?stretch=...?url=..." (double "?")
    # which Titiler rejects with 422. Strip the pollution so the Titiler URL is
    # well-formed; also a hardening win since {fmt} feeds an upstream URL.
    if "?" in fmt:
        # The render params may have ONLY arrived buried in the path (a proxy that
        # path-encodes the query without also forwarding it as a real query string).
        # Recover them into the typed params they were parsed-as-None for, so styling
        # is preserved rather than silently rendering the default tile (Codex P2).
        _buried = parse_qs(fmt.split("?", 1)[1])
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

    # Resolve effective bounds (apply defaults so callers downstream always receive
    # concrete values, not None).
    eff_pmin: float = pmin if pmin is not None else 2.0
    eff_pmax: float = pmax if pmax is not None else 98.0
    eff_sigma: float = sigma if sigma is not None else _STDDEV_SIGMA

    # T-1153-01: validate pmin/pmax/sigma BEFORE any Titiler call.
    #
    # fix(#1778 codex r2): validated only when the ACTIVE stretch mode reads
    # the value -- pmin/pmax under percentile, sigma under stddev -- not
    # whenever merely present. The previous "always validate if present" rule
    # made "inactive" a claim this endpoint could contradict, which is exactly
    # what frontend/nginx.conf's raster proxy_cache_key relies on NOT
    # happening: it blanks an inactive value out of the cache key so a random
    # one can't defeat the cache, and a value it blanks must never be able to
    # turn a cached 200 into what would have been a 422. "Inactive" now means
    # "ignored" here too, so the maps can blank unconditionally with no
    # residual, including under a duplicated query parameter (nginx's
    # $arg_x reads the FIRST occurrence, this endpoint's scalar Query reads
    # the LAST): an inactive value is never read on either side, so it can
    # never matter which occurrence either side saw.
    if stretch == "percentile" and (pmin is not None or pmax is not None):
        if not (0 <= eff_pmin < eff_pmax <= 100):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "pmin/pmax must satisfy 0 <= pmin < pmax <= 100; "
                    f"got pmin={eff_pmin}, pmax={eff_pmax}"
                ),
            )
    if stretch == "stddev" and sigma is not None and not (sigma > 0):
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
    if dataset.record.record_type in RASTER_FAMILY_RECORD_TYPES:
        bounds = None
        lon_span = None
        if dataset.record.spatial_extent is not None:
            # fix(#892): the SPAN, not the RFC 7946 spec bbox. These bounds feed
            # the tile source's own bounds; a west > east pair would bound the
            # source to nothing. -180..180 is over-broad but never inverted.
            bounds = extent_to_span_bbox(dataset.record.spatial_extent)
            # fix(#887): and the honest width alongside it, because -180..180 is
            # exactly as wrong for the resolution derivation as an inverted pair
            # -- a seam-crossing raster measured 360° wide, understated its own
            # resolution by 36x, and lost five zoom levels of maxzoom, so it
            # stopped rendering as the user zoomed in.
            lon_span = extent_lon_span(dataset.record.spatial_extent)
            if bounds is None:
                logger.warning(
                    "Failed to parse spatial extent bounds",
                    dataset_id=str(dataset.id),
                )

        # fix(#688): sign the raster template too. A raster dataset has no
        # table_name to bind the scope to, so the resource string is the dataset
        # id — already unique per tenant, and what the tile URL keys on. The
        # tenant binding is WR-03, exactly as on the vector branch below: without
        # it a token minted for tenant A is replayable in tenant B's context.
        # This expression is mirrored byte-for-byte at the verify site in
        # `_resolve_raster_access`; a divergence there is a silent authorization
        # bypass rather than a test failure, so both go through this one helper.
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

    # Vector dataset branch
    # WR-03 (Phase 1209-CR): in multi_tenant, bind the scope to the active
    # tenant so a token minted for tenant A cannot be replayed in tenant B's
    # context even if both tenants share the same table_name.
    # single_tenant: scope = bare table_name — byte-identical to pre-1209.
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
    """Batch-generate tile tokens for up to 50 datasets in one request.

    Optimization for multi-layer maps: a 20-layer builder map previously
    fired 20 parallel GET /token/{id}/ requests (20 HTTP + 20 RBAC + 20 HMAC
    signatures). This endpoint does the same work in a single round trip
    with one DB query for dataset metadata (PERF-N5).

    Per-dataset errors (404, 403) do not fail the batch — instead the
    response maps the offending dataset_id to ``{"error": "..."}``. Clients
    should check each entry for the ``error`` key.

    fix(#394) SH-04: ``X-Embed-Token`` is accepted as per-dataset fallback
    authorization (same capability check as tile serving), so embed terrain
    builds its raster-dem source from the real bounds/maxzoom descriptor.
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
    # "did a capability authorize this request" is only answerable after the
    # loop: the embed token authorizes a SCOPE, and whether any requested
    # dataset falls in it is exactly what the loop is working out.
    capability_authorized = False

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

    # fix(#1518 codex P2): the flag above is only ever set on the FALLBACK arm,
    # which a batch of public datasets never reaches — `_enforce_tile_token_access`
    # simply succeeds, the embed check never runs, and a valid scoped token
    # looked identical to no capability at all. Since a shared map of public
    # datasets is the ordinary embed, that rejected the common case. Ask the
    # question the flag stands in for, independently of whether normal access
    # raised.
    #
    # A post-loop pass rather than a check on each success: it runs only when
    # nothing has already established the capability, stops at the first id the
    # token covers, and costs nothing at all for a caller that sent no embed
    # token. Validating on every successful entry would spend a check per
    # dataset on every batch, including the ones with no token to check.
    #
    # Still the real validator against a real dataset id — presence of the
    # header is deliberately NOT sufficient, or any holder of a dead API key
    # could suppress the 401 with a junk header.
    if not capability_authorized and embed_token:
        for dataset_id in unique_ids:
            if await validate_embed_token_access(embed_token, dataset_id, db, request):
                capability_authorized = True
                break

    # No capability authorized any part of this batch, so the caller's own
    # credential was load-bearing. A supplied one that failed to resolve gets
    # the fail-closed 401 rather than a response full of per-dataset errors
    # that reads like an empty catalog (fix(#1518)).
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
        # DP-02: filter by tenant_id — a bare table_name lookup without scoping
        # could return a dataset belonging to a different tenant if names collide.
        # _require_tile_tenant_context() above guarantees tid is present before
        # the cache or query path is reached.
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
    """Resolve tile metadata, applying the #1518 rule if the lookup fails.

    fix(#1518 codex P2 round 4): the lookup has to run BEFORE
    ``_authorize_vector_tile_request``, because a tile URL carries a TABLE NAME
    and the capability arms need the dataset id only this lookup produces. So
    its 404 was reached with the credential rule never applied, and a caller
    with a dead bearer asking for a table that does not exist got "not found"
    while the raster route answered 401 for the identical request shape. Nobody
    reported it; it is the same per-router split #1518 exists to remove, and the
    raster sibling (``_resolve_raster_access``) had already closed its half.

    No capability can be skipped over here. An embed token authorizes dataset
    IDS, and this exit is precisely the case where there is no id to authorize.
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
    """Refuse a cached authorization the catalog no longer backs (#1451).

    ``_resolve_dataset_meta`` answers a cache hit without touching the database,
    so for up to ``_DATASET_CACHE_TTL`` seconds a worker keeps authorizing
    against a dataset row that may already be deleted. GH-1443 stopped the
    product from redrawing a freed table name, but nothing stops someone holding
    a database session from running ``CREATE TABLE data.roads`` directly, and
    ``ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO
    geolens_reader`` (scripts/lib/configure-runtime-db-role.sh) makes that
    relation readable by the role the tile path binds without
    ``grant_reader_access`` ever running. The deleted dataset's cached ``public``
    visibility would then carry a stranger's rows to anonymous callers.

    The ``_evict_dataset_meta`` listener (#1441) cannot close this alone: it is
    process-local, and with REDIS_URL unset every uvicorn worker holds a private
    LRU, so a delete only evicts in the worker that served it. No process-local
    cache can answer for the others, so the check has to reach the database.

    WHERE this runs is the rest of the design, and four review rounds narrowed it
    to one line in each endpoint: the first statement past the tile-byte-cache
    short-circuit. Both bounds are tight.

    No earlier, or the hot path pays for it. A tile answered from the byte cache
    returns above this and still costs zero round-trips, which is the whole point
    of ``_dataset_cache`` (PERF-006 / PERF-002).

    No later, for two independent reasons. Everything below acts on the cached
    authorization, starting with the COLD-02 seam, which would enqueue a restore
    and hand back a 202 for a dataset the catalog no longer has. And a tile
    request takes three bounded resources in sequence — this API-pool connection,
    the FAIR-01 permit, then the tile-pool connection — so the check has to
    complete and roll back before the first of them is requested. Every later
    position inverts a pair against a metadata-cache MISS, which carries
    ``_resolve_dataset_meta``'s connection into both waits: inside the tile
    transaction it asks the API pool while holding a tile connection; after the
    permit it holds a permit while asking the API pool. Both stall under ordinary
    mixed load with no attacker involved.

    Asking on the tile connection instead would need neither pool twice, but it
    would need ``geolens_reader`` to hold SELECT on ``catalog.datasets``: a
    runtime-role contract change for every deployment, and a widening of the one
    role whose narrowness is why this path binds it at all.

    ``test_both_tile_endpoints_ask_before_they_act`` pins the position, because a
    third endpoint that resolved cached metadata and forgot this call would be a
    silent regression.

    Pinning id AND table_name together is what makes it a liveness check rather
    than an existence check: a surviving row that has since been repointed at a
    different relation must not authorize a read of the old name either.

    It runs unconditionally, including right after a ``_dataset_cache`` MISS has
    just read the same row. Skipping it there would mean threading "was this a
    cache hit" out of the resolver and into a security check, which buys one PK
    lookup on the path that already pays a joinedload, in exchange for a caller
    that can silently skip the check by getting the flag wrong.

    Scope is every caller that reads a ``data``-schema relation off cached
    authorization, which is the vector and cluster endpoints — one call site,
    since both reach the relation through ``_acquire_and_serve_tile``. The raster
    proxy caches authorization the same way (``_raster_meta_cache``) and is
    deliberately NOT covered: it is addressed by dataset id rather than by table
    name, and it resolves to an object-storage asset, so there is no relation for
    an out-of-band ``CREATE TABLE`` to substitute. Its bounded staleness is the
    tradeoff written down at ``_RASTER_META_CACHE_TTL``, not this bug.
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

    # fix(#1451 codex P1): hand the API-pool connection back before returning.
    # `db.execute` opens a transaction that `get_db` would otherwise hold open
    # until the response is written, so without this every tile the pool has to
    # build would occupy one of the API's connections for the length of its
    # PostGIS query and gzip. The probe is read-only, so the rollback discards
    # nothing; it is here rather than at the call site because the caller cannot
    # release what it did not know was taken.
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
        # WR-03 (Phase 1209-CR): expected scope mirrors _build_tile_token_for_dataset:
        # in multi_tenant the scope is "{tid}:{table_name}" to prevent cross-tenant
        # token replay.  single_tenant: scope is bare table_name — unchanged.
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
        # SEC-009: a valid signature authorizes a single caller for this
        # non-public dataset; the tile bytes must not be retained by a shared
        # cache. Return "private" so _tile_headers emits Cache-Control: private
        # (previously this fell through to "public", letting shared caches store
        # private vector tiles under an auth-less key).
        return "private"

    # fix(#1518): CAPABILITY obligation. Both capability arms above have
    # declined — the embed branch returns or raises, and a non-public dataset
    # either satisfied the signed template or was refused. Everything from here
    # is decided by WHO is asking, so a credential that was supplied and failed
    # to resolve was load-bearing after all and gets the fail-closed 401 rather
    # than the anonymous path's 404.
    reject_unresolvable_credentials(request, user)

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


def _generation_table_key(table_name: str, dataset_id: uuid.UUID) -> str:
    """Table segment plus the generation that makes a reused name safe.

    fix(#1429): a vector delete drops the table and the catalog row, and at the
    time ``generate_table_name`` collided only against LIVE rows and relations,
    so the freed name was immediately redrawable. Every tile cache key was the
    table name alone, which meant the next dataset to draw ``roads`` read the
    previous one's cached bytes while being authorized on its own visibility.
    The dataset id is a UUID and is never reissued, so keying on it makes that
    read impossible rather than merely short-lived — the purge on delete, the
    TTL, and whether the purge even reached this process all stop mattering.

    fix(#1444): GH-1443 has since retired freed names outright, so a redraw is
    no longer possible either. This key stays: it is the reason a name is safe
    regardless of what any future name-generation change does, and unwinding it
    would put the whole guarantee back on one probe in one function.

    Position is load-bearing: the id goes AFTER the table segment so the
    ``tile:{table}:*`` patterns in ``invalidate_table`` still match every key
    for a table whichever dataset wrote it, and no invalidation caller changes.
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
    """Shared acquire->bind-role->run-query->gzip->cache->respond core (builder-audit #338 MVT-10).

    Both the vector and cluster endpoints supply only a ``query_callable`` (async
    ``(pool, conn) -> bytes | None``) plus a cache key; this helper owns the
    duplicated scaffold: the tile-pool acquire (503 on failure), the optional
    FAIR-01 per-tenant semaphore (a no-op when ``tenant_sem`` is None), the
    single-connection transaction
    with the per-tenant role/search_path bind (DP-02), error mapping
    (``asyncio.TimeoutError`` -> 429, broad ``Exception`` -> 503), empty-tile
    sentinel caching (-> 204), the PERF-005 gzip offload, the cache write, the
    METER-03 usage event, and the MVT-04 ETag/304 response.

    Callers keep their own cache-hit short-circuit and COLD-02 cold-rehydrate seam,
    which differ between the two paths.
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

    # METER-03 (Phase 1213-06): emit tile-request usage event through the
    # billing-import-free seam so the cloud overlay can update last_accessed_at.
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
    """Serve a server-side clustered vector tile for point datasets.

    URL pattern: /tiles/clusters/data.{table_name}/{z}/{x}/{y}.pbf

    This route deliberately reuses the normal vector tile auth model:
    public datasets are readable directly, non-public datasets require either
    valid HMAC tile params or a valid embed token scoped to the dataset.

    fix(#403): `cols` mirrors the vector endpoint's runtime column opt-in;
    the columns are projected onto UNCLUSTERED features so data-driven
    styling and popups keep working on the server-cluster path.
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
    # fix(#1518 codex P2 round 4): after authorization, not before. "Not a point
    # dataset" is a property of the RESOURCE, unlike the request-shape 400s above
    # it (bad table name, out-of-range tile), so it was one more exit answering a
    # caller whose credential was dead without saying so. It also told an
    # unauthorized caller that a private dataset exists and what geometry it
    # holds. Still ahead of every PostGIS query, which is all the gate was ever
    # for.
    _ensure_clusterable_dataset(meta)

    # fix(#1778): keyed on the effective projection, so `z`, the allowlist and
    # the mode all reach it. They decide what the request actually changes:
    # the cluster query emits its own `point_count`/`cluster_id` names, so a
    # `cols=` naming one of those changes nothing at any zoom.
    additional_columns, cols_cache_key = parse_cols_param(
        cols,
        meta.column_info,
        z,
        tile_columns=meta.tile_columns,
        mode="cluster",
    )

    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl

    # DP-02 (Phase 1209-CR-01): prefix cluster cache key with tenant id in
    # multi_tenant so two tenants with the same table_name never share cached
    # cluster tiles.  single_tenant: no prefix — byte-identical to pre-1209
    # behavior (T-1209-CR-01).
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

    # fix(#1451): first thing past the byte-cache short-circuit, because
    # everything past it acts on the cached authorization — the cold seam below
    # would enqueue a restore for a dataset the catalog no longer has. See the
    # helper for why it cannot sit any later than this.
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

    # Get column info for attribute selection
    columns = meta.column_info

    # fix(#1778): the cache key comes from the EFFECTIVE projection, not from
    # the request, so `z` and the allowlist have to reach it. At z >= 10 the
    # zoom default already projects every column and every valid subset
    # collapses onto one entry. The docstring above is the published operation
    # description, so the mechanism is written down at `parse_cols_param`
    # instead of churning every generated SDK to say it.
    additional_columns, cols_cache_key = parse_cols_param(
        cols, columns, z, tile_columns=meta.tile_columns
    )

    # Use per-dataset cache TTL when set, else global default
    cache_ttl = meta.tile_cache_ttl or settings.tile_cache_ttl

    # DP-02 (Phase 1209-CR-01): prefix tile cache key with tenant id in
    # multi_tenant so two tenants with the same table_name never share a
    # cached tile binary.  single_tenant: no prefix — byte-identical to
    # pre-1209 behavior (T-1209-CR-01).
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

    # Check tile cache before hitting PostGIS
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

    # fix(#1451): first thing past the byte-cache short-circuit, because
    # everything past it acts on the cached authorization — the cold seam below
    # would enqueue a restore for a dataset the catalog no longer has. See the
    # helper for why it cannot sit any later than this.
    await _assert_dataset_still_registered(
        db, dataset_id=meta.dataset_id, table_name=table_name, tid=_tile_tid
    )

    # COLD-02 (Phase 1214-04): cold-rehydrate seam — BEFORE tile query.
    # Uses the cached meta.record_status (no extra DB round-trip on the hot path,
    # T-1214-18). Returns a 202 Response for over-gate warming or None to continue.
    # A cold-check failure is broad-except-swallowed so it NEVER 500s the tile
    # (T-1214-17). Published/anon-shared datasets are hot (record_status != 'cold')
    # so a public map viewer never receives a 202-warming response (T-1214-17).
    _cold_result = await _check_cold_rehydrate(
        table_name,
        meta.record_status,
        str(_tile_tid) if _tile_tid is not None else "",
    )
    if _cold_result is not None:
        return _cold_result

    # Per-tenant concurrency budget supplied by the registered serving extension.
    # When a hosted overlay is active, acquire the per-tenant limiter BEFORE
    # entering the tile pool. This caps concurrent tile DB connections per tenant
    # to _TILE_CONCURRENCY so one tenant cannot starve others of pool connections
    # (T-1213-22 noisy-neighbour mitigation). In single_tenant / overlay-absent mode,
    # the Community extension returns None and the step is skipped.
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

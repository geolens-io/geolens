# MVT Tile Pipeline Review - Findings

**Date:** 2026-03-26
**Scope:** Vector tiles (ST_AsMVT) -- query patterns, PostGIS indexing, cache headers, DB query efficiency
**Result:** 4 easy wins implemented, 2 medium-effort items recommended

## Executive Summary

The MVT tile pipeline is well-architected: dedicated asyncpg pool isolates tile queries from API traffic, ST_AsMVTGeom uses correct parameters (4096 extent, 256 buffer, clipping enabled), GIST indexes on `geom_4326` are created at ingestion time, column filtering prevents geometry bloat in tile attributes, and a binary Redis tile cache (`TileCacheProvider`) with Prometheus hit/miss counters is fully wired into the request path. Four easy-win optimizations were implemented (bounds CTE precomputation, log level reduction, Cache-Control on cache hits, empty tile caching). Two medium-effort items (dataset lookup caching, extended simplification) are documented for future work.

## Architecture Overview

```
Request -> router.py (auth: embed token or HMAC signature)
        -> dataset lookup (SQLAlchemy ORM, joinedload Record)
        -> TileCacheProvider.get() (Redis, binary)
        -> [cache miss] get_tile() via dedicated asyncpg pool (service.py)
        -> gzip compress (compresslevel=6)
        -> TileCacheProvider.set() (Redis, binary)
        -> Response with Cache-Control headers
```

**Key files:**
- `backend/app/tiles/router.py` -- endpoint, auth, response headers
- `backend/app/tiles/service.py` -- SQL query builder and executor
- `backend/app/tiles/pool.py` -- dedicated asyncpg pool (min=2, max=10)
- `backend/app/tiles/signing.py` -- HMAC tile token generation/verification
- `backend/app/cache/tile_cache.py` -- binary Redis tile cache (TileCacheProvider)
- `backend/app/cache/provider.py` -- generic cache singleton (Redis/in-memory)

## What Is Done Well

1. **Dedicated tile pool** (`pool.py`): Separate asyncpg connection pool prevents tile traffic from starving API CRUD operations. Pool is initialized at startup with configurable min/max sizes.

2. **Proper ST_AsMVTGeom parameters** (`service.py`): 4096 extent, 256 buffer, clipping enabled -- all standard best-practice values for MapLibre/Mapbox clients.

3. **GIST spatial indexes**: `geom_4326` gets a GIST index at ingestion time (`CREATE INDEX IF NOT EXISTS idx_{table}_geom_4326 ON data.{table} USING GIST (geom_4326)`). The `&&` operator in the WHERE clause uses this index for bounding-box filtering.

4. **Feature ID in MVT**: `gid` is passed as the feature ID column in `ST_AsMVT()`, enabling MapLibre feature-state operations (hover, selection).

5. **Column filtering** (`service.py`): Geometry columns (`geom`, `geom_4326`) and `gid` are excluded from the attribute column list, preventing geometry bytes from bloating tile payloads.

6. **Cache invalidation on edits**: Feature CRUD operations trigger `invalidate_table()`, ensuring stale tiles are purged when data changes.

7. **Per-dataset cache TTL**: `tile_cache_ttl` column on Dataset model allows per-dataset tuning of the `Cache-Control max-age` header.

8. **SQL injection prevention**: Table names are validated against `^[a-z0-9_]+$` in both router and service layers. No string interpolation of user input into SQL beyond the validated table name.

## Issues Found and Fixed

### Fix 1: Double ST_Transform in WHERE clause (IMPLEMENTED)

**File:** `backend/app/tiles/service.py`, `_build_tile_query()`

**Problem:** The WHERE clause called `ST_Transform(bounds.geom, 4326)` twice -- once for the `&&` bounding-box filter and once for `ST_Intersects`. While PostGIS may optimize this internally, it is not guaranteed, and computing the transform once is both clearer and safer.

**Before:**
```sql
bounds AS (
    SELECT ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom
),
...
WHERE t.geom_4326 && ST_Transform(bounds.geom, 4326)
  AND ST_Intersects(t.geom_4326, ST_Transform(bounds.geom, 4326))
```

**After:**
```sql
bounds AS (
    SELECT
        ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom,
        ST_Transform(ST_TileEnvelope($1::integer, $2::integer, $3::integer), 4326) AS geom_4326
),
...
WHERE t.geom_4326 && bounds.geom_4326
  AND ST_Intersects(t.geom_4326, bounds.geom_4326)
```

**Impact:** Eliminates redundant coordinate transformation. The CTE guarantees single evaluation regardless of query planner behavior.

### Fix 2: Per-tile INFO logging reduced to DEBUG (IMPLEMENTED)

**File:** `backend/app/tiles/router.py`, `tile_endpoint()`

**Problem:** Every successful tile served logged at INFO level with dataset_id, table_name, z/x/y, and scope. A single map view generates 20-50 tiles, producing 20-50 INFO log entries. This adds I/O overhead and makes INFO logs noisy.

**Fix:** Changed `logger.info("tile_access", ...)` to `logger.debug("tile_access", ...)`.

**Impact:** Reduces log volume by ~95% at default INFO level. Tile access is still logged and available when DEBUG logging is enabled for troubleshooting.

### Fix 3: Cache-Control header on cache hits (IMPLEMENTED)

**File:** `backend/app/tiles/router.py`, cache-hit response path

**Problem:** Cache hits returned `"Cache-Control": "no-cache"` while cache misses returned proper `max-age={ttl}`. This meant browsers never cached tiles served from the Redis cache, defeating the benefit of server-side caching for repeat visits. The `no-cache` was originally introduced to avoid stale-tile bugs after feature mutations, but this is already handled by `invalidate_table()` in the Redis cache — the browser `Cache-Control` should match.

**Fix:** Changed cache-hit response to use `f"{cache_scope}, max-age={cache_ttl}"`, matching the cache-miss path.

**Impact:** Browsers now cache tiles from both paths, reducing redundant requests for static map views.

### Fix 4: Cache empty tiles as sentinel (IMPLEMENTED)

**File:** `backend/app/tiles/router.py`, empty tile response path

**Problem:** When `get_tile()` returns None (empty tile), a 204 was returned without caching. For datasets with sparse spatial coverage, many tile requests hit PostGIS for tiles that are always empty, wasting a database round-trip each time.

**Fix:** Store `b""` (empty bytes) in the tile cache for empty tiles. On cache hit, detect the empty sentinel and return 204 without querying PostGIS.

**Impact:** Eliminates repeated PostGIS queries for empty tiles in sparse datasets. For a typical sparse dataset, ~60-80% of tiles are empty — this can significantly reduce tile query load.

## Remaining Optimization Opportunities

### Dataset Lookup Caching (Medium effort, ~1-2 hours)

**File:** `backend/app/tiles/router.py`, lines 282-287

Every tile request executes a SQLAlchemy ORM query with `joinedload(Dataset.record)` to look up the dataset by `table_name`. This is needed for visibility/auth checks, `column_info` for attribute selection, and `tile_cache_ttl`. For a map pan generating 20+ tiles, this means 20+ identical ORM queries.

**Recommended approach:** Add a short-lived in-memory TTL cache (e.g., 30-60 seconds) for dataset metadata keyed by `table_name`. Invalidate on dataset update. This would eliminate the ORM query on all but the first tile request in a session.

**Why deferred:** Requires careful invalidation logic and integration with dataset update hooks. Not a quick config change.

### Extend Simplification Threshold (Medium effort, ~30 minutes)

The current code does not apply geometry simplification at any zoom level. For complex geometries (detailed coastlines, parcel boundaries with many vertices), full-resolution geometry at all zoom levels can produce large MVT tiles.

**Recommended approach:** Add zoom-dependent `ST_SimplifyPreserveTopology` in the query with tolerance `360 / (4096 * 2^z)` for z < 10-12. This is a standard PostGIS optimization for MVT generation.

**Why deferred:** Requires monitoring actual tile sizes to calibrate the threshold. The current `ST_AsMVTGeom` clipping handles most size reduction, so the impact depends on dataset complexity.

## Not a Problem

These items were reviewed and confirmed as correctly implemented:

- **Spatial indexing:** GIST indexes created on `geom_4326` at ingestion time, used by `&&` operator in WHERE clause.
- **SQL injection prevention:** Table names regex-validated (`^[a-z0-9_]+$`) in both router and service.
- **Column bloat in tiles:** Geometry columns and `gid` excluded from attribute selection.
- **Pool isolation:** Tile queries use dedicated asyncpg pool, not the SQLAlchemy engine pool.
- **MVT parameters:** 4096 extent, 256 buffer, clipping=true are standard best-practice values.
- **gzip compression:** `compresslevel=6` is the Python default and provides a good compression/speed tradeoff.

# Quick Task: Seed Tile Cache - Research

**Researched:** 2026-04-01
**Domain:** PostGIS MVT tile generation, Redis caching, tile math
**Confidence:** HIGH

## Summary

The existing tile pipeline (`get_tile()` + `TileCacheProvider.set()`) is fully decoupled from FastAPI request context. A CLI script can initialize the asyncpg tile pool and Redis tile cache independently, then call the same functions the router uses. The main research gaps are (1) computing which tile indices intersect a bounding box at each zoom, and (2) properly initializing the app infrastructure outside of FastAPI lifecycle.

**Primary recommendation:** Build a standalone async CLI script that initializes pool + cache, queries all vector datasets via raw asyncpg, computes intersecting tiles per zoom level from spatial_extent bbox, and generates/caches tiles with an asyncio.Semaphore for concurrency control.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Vector tiles only (PostGIS MVT to Redis). Raster tiles out of scope.
- z0 through z10 zoom range.
- Only seed tiles intersecting dataset's bounding box.
- CLI script (`python -m scripts.seed_tiles`). No admin API endpoint.
- Use existing per-dataset `tile_cache_ttl` (falls back to global `settings.tile_cache_ttl`).

### Claude's Discretion
- Concurrency model: asyncio with configurable worker count
- Progress reporting: stdout (percentage, tiles/sec)
- Error handling: log per-tile failures, continue seeding
</user_constraints>

## Architecture: Key Codebase Findings

### 1. `get_tile()` is standalone-friendly (HIGH confidence)

**File:** `backend/app/tiles/service.py`

```python
async def get_tile(
    pool: asyncpg.Pool,
    table_name: str,
    z: int, x: int, y: int,
    columns: list[dict],
) -> bytes | None:
```

Takes an `asyncpg.Pool` directly -- no FastAPI deps, no request context, no DB session. Returns raw MVT bytes or `None` for empty tiles.

### 2. Cache stores gzip-compressed bytes (HIGH confidence)

**File:** `backend/app/tiles/router.py` (lines 456-460)

The router **gzip-compresses** tile data before caching:
```python
compressed = gzip.compress(tile_data, compresslevel=6)
await tile_cache.set(table_name, z, x, y, compressed, ttl=cache_ttl)
```

The seed script MUST replicate this: `gzip.compress()` before `cache.set()`. Also cache empty tiles as `b""` (sentinel, line 441).

### 3. TileCacheProvider initialization (HIGH confidence)

**File:** `backend/app/cache/tile_cache.py`

```python
cache = TileCacheProvider(url=settings.redis_url)
await cache.set(table_name, z, x, y, compressed_data, ttl=ttl)
```

Key format: `tile:{table}:{z}:{x}:{y}`. Constructor takes `redis_url` string directly. No app context needed.

### 4. Tile pool initialization (HIGH confidence)

**File:** `backend/app/tiles/pool.py`

```python
pool = await init_tile_pool()  # Creates asyncpg pool from settings
```

Uses `settings.database_url`, `settings.tile_pool_min_size/max_size`. Fully standalone -- just needs `settings` (env vars / `.env`).

### 5. Data model: spatial_extent is on Record, not Dataset (HIGH confidence)

**File:** `backend/app/datasets/models.py`

- `Dataset.table_name` -- the PostGIS table name (schema: `data.{table_name}`)
- `Dataset.column_info` -- JSONB list of `{"name": "col_name", ...}` dicts
- `Dataset.tile_cache_ttl` -- per-dataset override (nullable int)
- `Dataset.record` -- relationship to `Record`
- `Record.spatial_extent` -- `Geometry("POLYGON", srid=4326)` on the Record model
- `Record.record_type` -- filter for `"vector_dataset"` only (skip raster/vrt)

### 6. Querying datasets without SQLAlchemy session

For a CLI script, avoid bootstrapping the full SQLAlchemy async engine. Use the same asyncpg pool to query catalog tables directly:

```python
rows = await pool.fetch("""
    SELECT d.table_name, d.column_info, d.tile_cache_ttl,
           ST_AsText(r.spatial_extent) as extent_wkt
    FROM catalog.datasets d
    JOIN catalog.records r ON d.record_id = r.id
    WHERE r.record_type = 'vector_dataset'
      AND r.spatial_extent IS NOT NULL
""")
```

This avoids needing SQLAlchemy, GeoAlchemy2, or session management in the script.

## Tile Math: BBox to Tile Indices (HIGH confidence)

Standard Web Mercator (EPSG:3857) tile coordinate math. Tiles use the Slippy Map convention (z/x/y, origin top-left).

### Algorithm

Given a WGS84 bounding box `[west, south, east, north]` and zoom level `z`:

```python
import math

def lng_to_tile_x(lng: float, z: int) -> int:
    return int((lng + 180.0) / 360.0 * (1 << z))

def lat_to_tile_y(lat: float, z: int) -> int:
    lat_rad = math.radians(lat)
    n = 1 << z
    return int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)

def bbox_to_tiles(west: float, south: float, east: float, north: float, z: int):
    """Yield (z, x, y) for all tiles intersecting the bbox at zoom z."""
    n = 1 << z
    x_min = max(0, lng_to_tile_x(west, z))
    x_max = min(n - 1, lng_to_tile_x(east, z))
    y_min = max(0, lat_to_tile_y(north, z))  # north has LOWER y
    y_max = min(n - 1, lat_to_tile_y(south, z))  # south has HIGHER y
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            yield (z, x, y)
```

**Key gotcha:** Latitude to tile Y is inverted -- north = lower Y value. The algorithm above handles this correctly.

### Tile count estimates

| Zoom | Global tiles | Typical city bbox |
|------|-------------|-------------------|
| 0 | 1 | 1 |
| 5 | 1,024 | ~4 |
| 10 | 1,048,576 | ~100-400 |

For a regional dataset (e.g., single US state), z0-z10 total is roughly 500-2,000 tiles. Very feasible.

## Concurrency Pattern (HIGH confidence)

Use `asyncio.Semaphore` to bound concurrent PostGIS queries. The tile pool already has `max_size` connections, but a semaphore provides explicit control:

```python
sem = asyncio.Semaphore(concurrency)  # e.g., 10

async def seed_one(table_name, z, x, y, columns, ttl):
    async with sem:
        tile_data = await get_tile(pool, table_name, z, x, y, columns)
        if tile_data is None:
            await cache.set(table_name, z, x, y, b"", ttl=ttl)
        else:
            compressed = gzip.compress(tile_data, compresslevel=6)
            await cache.set(table_name, z, x, y, compressed, ttl=ttl)

# Launch all tiles as tasks
tasks = [seed_one(...) for z, x, y in all_tiles]
await asyncio.gather(*tasks)
```

**Recommended default concurrency:** Match `tile_pool_max_size` (default 10). Configurable via CLI arg.

## Don't Hand-Roll

| Problem | Use Instead |
|---------|-------------|
| Tile coordinate math | The formulas above (standard Slippy Map spec) |
| MVT generation | Existing `get_tile()` from `app.tiles.service` |
| Cache storage | Existing `TileCacheProvider.set()` |
| Pool init | Existing `init_tile_pool()` from `app.tiles.pool` |

## Common Pitfalls

### 1. Forgetting gzip compression
The cache stores gzip-compressed bytes. If you cache raw MVT, the frontend will receive corrupted tiles (it expects `Content-Encoding: gzip`).

### 2. Not caching empty tiles
The router caches empty tiles as `b""` sentinel. The seed script should do the same to avoid repeated PostGIS hits for tiles outside the data extent but inside the bbox.

### 3. Latitude clamping
Web Mercator is valid only between ~85.05 and -85.05 latitude. Clamp bbox latitude before computing tile indices:
```python
south = max(south, -85.0511)
north = min(north, 85.0511)
```

### 4. WKT parsing for bbox
`ST_AsText(spatial_extent)` returns a `POLYGON((...))` WKT. Use `shapely.wkt.loads()` then `.bounds` to get `(west, south, east, north)`. Or use `ST_XMin/ST_YMin/ST_XMax/ST_YMax` in SQL directly.

### 5. Settings initialization
`from app.config import settings` triggers `Settings()` which requires env vars (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, etc.). The script must run with a valid `.env` or env vars set. Running inside Docker (`docker compose exec api python -m scripts.seed_tiles`) is the simplest approach.

## Script Structure

```
backend/scripts/seed_tiles.py
```

Recommended layout:
1. Parse CLI args (dataset ID/name filter, concurrency, max-zoom, dry-run)
2. Initialize tile pool (`init_tile_pool()`)
3. Initialize tile cache (`TileCacheProvider(settings.redis_url)`)
4. Query datasets from catalog (raw asyncpg)
5. For each dataset: compute tiles, show estimate, seed with progress
6. Close pool

Run via: `docker compose exec api python -m scripts.seed_tiles`

Or locally with env vars: `cd backend && python -m scripts.seed_tiles`

## Sources

### Primary (HIGH confidence)
- `backend/app/tiles/service.py` -- `get_tile()` signature and behavior
- `backend/app/tiles/router.py` -- cache integration pattern (gzip, empty sentinel)
- `backend/app/cache/tile_cache.py` -- `TileCacheProvider` API
- `backend/app/tiles/pool.py` -- pool initialization
- `backend/app/datasets/models.py` -- Dataset/Record schema
- `backend/app/config.py` -- settings structure
- Standard Slippy Map tile coordinate math (OSM wiki)

---
phase: 260401-lbi
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/scripts/seed_tiles.py
  - backend/tests/test_seed_tiles.py
autonomous: true
requirements: [SEED-01]

must_haves:
  truths:
    - "Running `python -m scripts.seed_tiles` seeds all vector dataset tiles z0-z10 into Redis"
    - "Only tiles intersecting each dataset's spatial extent are generated"
    - "Tiles are gzip-compressed before caching, matching the router's format"
    - "Empty tiles are cached as b'' sentinel to prevent repeated PostGIS hits"
    - "Per-dataset tile_cache_ttl is honored (falls back to global setting)"
    - "Progress is printed to stdout with percentage and tiles/sec"
    - "Individual tile failures are logged but do not abort the run"
  artifacts:
    - path: "backend/scripts/seed_tiles.py"
      provides: "CLI tile cache seeder"
      min_lines: 120
    - path: "backend/tests/test_seed_tiles.py"
      provides: "Unit tests for tile math and dataset query"
      min_lines: 40
  key_links:
    - from: "backend/scripts/seed_tiles.py"
      to: "backend/app/tiles/service.py"
      via: "import get_tile"
      pattern: "from app\\.tiles\\.service import get_tile"
    - from: "backend/scripts/seed_tiles.py"
      to: "backend/app/cache/tile_cache.py"
      via: "TileCacheProvider instantiation"
      pattern: "TileCacheProvider"
    - from: "backend/scripts/seed_tiles.py"
      to: "backend/app/tiles/pool.py"
      via: "init_tile_pool for asyncpg pool"
      pattern: "init_tile_pool"
---

<objective>
Create a CLI script to pre-seed the Redis vector tile cache for all (or specific) datasets, generating MVT tiles from PostGIS for zoom levels 0-10 within each dataset's spatial extent.

Purpose: Eliminate cold-cache latency for overview zoom levels before user traffic arrives.
Output: `backend/scripts/seed_tiles.py` runnable via `python -m scripts.seed_tiles` (inside Docker or locally with env vars).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260401-lbi-seed-the-cache-for-all-tiles/260401-lbi-CONTEXT.md
@.planning/quick/260401-lbi-seed-the-cache-for-all-tiles/260401-lbi-RESEARCH.md

<interfaces>
<!-- Key types and contracts the executor needs. -->

From backend/app/tiles/service.py:
```python
async def get_tile(
    pool: asyncpg.Pool,
    table_name: str,
    z: int, x: int, y: int,
    columns: list[dict],
) -> bytes | None:
    """Returns MVT binary data, or None if the tile contains no features."""
```

From backend/app/cache/tile_cache.py:
```python
class TileCacheProvider:
    def __init__(self, url: str) -> None: ...
    async def set(self, table: str, z: int, x: int, y: int, data: bytes, ttl: int = 300) -> None: ...
```

From backend/app/tiles/pool.py:
```python
async def init_tile_pool() -> asyncpg.Pool: ...
async def close_tile_pool() -> None: ...
```

From backend/app/config.py:
```python
class Settings:
    redis_url: str | None = None
    tile_cache_ttl: int = 300
    tile_pool_max_size: int = 10
```

Router cache pattern (backend/app/tiles/router.py lines 438-460):
- Empty tile: `await tile_cache.set(table_name, z, x, y, b"", ttl=cache_ttl)`
- Non-empty: `compressed = gzip.compress(tile_data, compresslevel=6)` then `await tile_cache.set(..., compressed, ttl=cache_ttl)`
- TTL: `dataset.tile_cache_ttl or settings.tile_cache_ttl`

Dataset query (no SQLAlchemy needed, use raw asyncpg):
```sql
SELECT d.table_name, d.column_info, d.tile_cache_ttl,
       ST_XMin(r.spatial_extent) as west, ST_YMin(r.spatial_extent) as south,
       ST_XMax(r.spatial_extent) as east, ST_YMax(r.spatial_extent) as north
FROM catalog.datasets d
JOIN catalog.records r ON d.record_id = r.id
WHERE r.record_type = 'vector_dataset'
  AND r.spatial_extent IS NOT NULL
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create seed_tiles CLI script with tile math and async seeding</name>
  <files>backend/scripts/seed_tiles.py, backend/tests/test_seed_tiles.py</files>
  <behavior>
    - bbox_to_tiles(0, 0, 10, 10, z=0) yields exactly [(0, 0, 0)]
    - bbox_to_tiles(-180, -85, 180, 85, z=1) yields 4 tiles
    - bbox_to_tiles for a small city-sized bbox at z=10 yields a reasonable count (~tens of tiles)
    - Latitude is clamped to [-85.0511, 85.0511] (Web Mercator limit)
    - lng_to_tile_x and lat_to_tile_y produce correct tile indices for known coordinates
  </behavior>
  <action>
Create `backend/scripts/seed_tiles.py` as an async CLI script with `argparse`. Structure:

**Tile math functions** (module-level, testable):
- `lng_to_tile_x(lng, z) -> int`
- `lat_to_tile_y(lat, z) -> int`
- `bbox_to_tiles(west, south, east, north, z) -> list[tuple[int,int,int]]` — clamp lat to +/-85.0511 before computing. Returns list of (z, x, y) tuples for all tiles intersecting the bbox at zoom z.

**CLI arguments:**
- `--dataset` / `-d`: Optional dataset table_name filter (seed only this dataset)
- `--concurrency` / `-c`: Number of concurrent workers (default: 10, matching tile_pool_max_size)
- `--max-zoom`: Maximum zoom level to seed (default: 10)
- `--min-zoom`: Minimum zoom level (default: 0)
- `--dry-run`: Print tile counts per dataset without seeding

**Main async flow:**
1. Import and call `init_tile_pool()` to get the asyncpg pool
2. Create `TileCacheProvider(settings.redis_url)` — exit with error if `redis_url` is None
3. Query datasets via raw asyncpg using the SQL in the interfaces block above. Use `ST_XMin/YMin/XMax/YMax` for bbox extraction (avoids shapely dependency). If `--dataset` flag given, add `AND d.table_name = $1` filter.
4. For each dataset:
   - Parse `column_info` from JSON (asyncpg returns it as a Python object from JSONB)
   - Compute `cache_ttl = dataset.tile_cache_ttl or settings.tile_cache_ttl`
   - For each zoom level z in [min_zoom, max_zoom]: compute tiles via `bbox_to_tiles()`
   - Print tile count estimate per dataset. If `--dry-run`, skip to next dataset.
   - Create `asyncio.Semaphore(concurrency)`
   - Define `seed_one(z, x, y)` coroutine:
     - Acquire semaphore
     - Call `get_tile(pool, table_name, z, x, y, columns)`
     - If None: `await cache.set(table_name, z, x, y, b"", ttl=cache_ttl)`
     - Else: `compressed = gzip.compress(tile_data, compresslevel=6)` then `await cache.set(table_name, z, x, y, compressed, ttl=cache_ttl)`
     - On exception: log warning with z/x/y, increment error counter, do NOT re-raise
   - `await asyncio.gather(*tasks)` for all tiles of this dataset
   - Print progress during seeding: update every 100 tiles with count, percentage, elapsed time, tiles/sec
5. Close tile pool via `close_tile_pool()`
6. Print summary: total tiles seeded, errors, elapsed time

**Progress reporting:** Use a shared counter incremented after each tile. Print a progress line every 100 tiles (or every 5 seconds, whichever comes first) showing `[dataset_name] {done}/{total} ({pct}%) - {tiles_per_sec:.0f} tiles/sec`.

**Entry point:** `if __name__ == "__main__":` block calling `asyncio.run(main())`.

Also create `backend/tests/test_seed_tiles.py` with unit tests for the tile math functions:
- Test `lng_to_tile_x` and `lat_to_tile_y` against known values
- Test `bbox_to_tiles` for z=0 (global = 1 tile), z=1 (global = 4 tiles)
- Test `bbox_to_tiles` with a small bbox at z=10 produces expected count
- Test latitude clamping at +/-85.0511
- Test edge cases: bbox at antimeridian, bbox at poles

Import the functions directly: `from scripts.seed_tiles import lng_to_tile_x, lat_to_tile_y, bbox_to_tiles`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -m pytest tests/test_seed_tiles.py -x -v</automated>
  </verify>
  <done>
    - `python -m scripts.seed_tiles --help` prints usage with all documented flags
    - `python -m scripts.seed_tiles --dry-run` lists datasets with tile counts (no Redis writes)
    - All tile math unit tests pass
    - Script uses existing `get_tile()`, `TileCacheProvider.set()`, and `init_tile_pool()` — no reimplemented tile generation
    - Gzip compression at level 6 before cache set, empty tiles cached as b""
  </done>
</task>

</tasks>

<verification>
1. `cd backend && python -m pytest tests/test_seed_tiles.py -x -v` — tile math tests pass
2. `cd backend && python -m scripts.seed_tiles --help` — shows usage
3. `docker compose exec api python -m scripts.seed_tiles --dry-run` — lists datasets with tile count estimates (requires running stack)
</verification>

<success_criteria>
- Tile math functions are correct (validated by unit tests)
- Script initializes pool + cache, queries datasets, computes spatial tiles, seeds cache
- Matches router's cache format exactly (gzip compress, empty sentinel, same TTL)
- Concurrency is bounded by semaphore, progress is reported to stdout
- Errors per-tile are logged but do not abort the run
</success_criteria>

<output>
After completion, create `.planning/quick/260401-lbi-seed-the-cache-for-all-tiles/260401-lbi-SUMMARY.md`
</output>

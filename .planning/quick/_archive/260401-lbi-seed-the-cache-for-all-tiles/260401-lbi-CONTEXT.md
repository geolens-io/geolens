# Quick Task 260401-lbi: Seed the tile cache — Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Task Boundary

Build a CLI script to pre-seed the Redis vector tile cache for datasets, generating MVT tiles from PostGIS and storing them in Redis before user traffic arrives.

</domain>

<decisions>
## Implementation Decisions

### Tile Types
- Vector tiles only (PostGIS MVT → Redis). Raster tiles (Titiler/nginx) are out of scope.

### Zoom Range
- z0 through z10. Covers overview zooms where cold-cache latency is most noticeable. ~1.4M total tiles at z10 for a global dataset.

### Spatial Extent Filtering
- Only seed tiles that intersect the dataset's bounding box. Skip tiles outside the dataset's spatial extent to avoid wasting time on empty tiles. This makes seeding viable for regional/local datasets.

### Trigger Mechanism
- CLI script (e.g. `python -m scripts.seed_tiles`). Can be run manually or via cron. No admin API endpoint for now.

### Cache TTL
- Use the existing per-dataset `tile_cache_ttl` setting (falls back to global `settings.tile_cache_ttl`). No special seed TTL.

### Claude's Discretion
- Concurrency model: use asyncio with configurable worker count for parallel tile generation
- Progress reporting: print progress to stdout (percentage, tiles/sec)
- Error handling: log failures per-tile but continue seeding (don't abort on individual tile errors)

</decisions>

<specifics>
## Specific Ideas

- Reuse existing `get_tile()` from `app.tiles.service` and `TileCacheProvider.set()` for consistency
- Use dataset's `spatial_extent` (PostGIS geometry) to compute which tiles intersect the bbox at each zoom level
- Support seeding all datasets or a specific dataset by ID/name
- Show tile count estimate before starting so operator can gauge feasibility

</specifics>

<canonical_refs>
## Canonical References

- `backend/app/cache/tile_cache.py` — TileCacheProvider with get/set/invalidate_table
- `backend/app/tiles/router.py` — tile endpoint showing cache integration pattern
- `backend/app/tiles/service.py` — get_tile() function for PostGIS MVT generation
- `backend/app/tiles/pool.py` — dedicated asyncpg tile connection pool

</canonical_refs>

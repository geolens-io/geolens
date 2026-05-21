---
phase: 260401-lbi
plan: 01
subsystem: backend/tiles
tags: [cache, redis, seeding, tiles, cli, asyncio]
dependency_graph:
  requires: [app.tiles.service.get_tile, app.cache.tile_cache.TileCacheProvider, app.tiles.pool.init_tile_pool]
  provides: [scripts.seed_tiles CLI]
  affects: [Redis tile cache]
tech_stack:
  added: []
  patterns: [asyncio.Semaphore concurrency, TDD red-green]
key_files:
  created:
    - backend/scripts/__init__.py
    - backend/scripts/seed_tiles.py
    - backend/tests/test_seed_tiles.py
  modified: []
decisions:
  - Use existing get_tile() + TileCacheProvider — no reimplemented tile logic
  - Latitude clamped to Web Mercator limits (±85.0511) in bbox_to_tiles
  - Empty tiles cached as b"" sentinel matching router behavior
  - asyncio.Semaphore(concurrency) bounds parallel PostGIS connections
metrics:
  duration: 178s
  completed: 2026-04-01T19:34:29Z
  tasks_completed: 1
  files_created: 3
---

# Phase 260401-lbi Plan 01: Seed Tile Cache Summary

**One-liner:** Async CLI script that seeds Redis with gzip-compressed MVT tiles from PostGIS for all vector datasets, bounded by spatial extent and zoom range z0–z10.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Create seed_tiles CLI script with tile math and async seeding | 5edb3890 | backend/scripts/seed_tiles.py, backend/tests/test_seed_tiles.py |

Note: RED-phase commit (8dc6f2ba) captured failing tests before implementation.

## What Was Built

`backend/scripts/seed_tiles.py` — a standalone async CLI script runnable via:
- `docker compose exec api python -m scripts.seed_tiles`
- `cd backend && python -m scripts.seed_tiles` (with env vars)

### Tile math functions (pure, testable)

- `lng_to_tile_x(lng, z)` — standard Slippy Map formula
- `lat_to_tile_y(lat, z)` — Web Mercator Y formula with north=low-Y convention
- `bbox_to_tiles(west, south, east, north, z)` — yields (z, x, y) tuples for all tiles intersecting bbox; clamps latitude to ±85.0511

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--dataset / -d` | all | Seed only this table_name |
| `--concurrency / -c` | 10 | Async workers |
| `--min-zoom` | 0 | Minimum zoom level |
| `--max-zoom` | 10 | Maximum zoom level |
| `--dry-run` | false | Print counts, no Redis writes |

### Cache format matches router exactly

- Non-empty tiles: `gzip.compress(tile_data, compresslevel=6)` before `cache.set()`
- Empty tiles: `b""` sentinel to prevent repeated PostGIS hits
- TTL: `dataset.tile_cache_ttl or settings.tile_cache_ttl`

### Concurrency and error handling

- `asyncio.Semaphore(concurrency)` bounds concurrent PostGIS queries
- Per-tile exceptions are logged via structlog but do NOT abort the run
- Error count included in final summary output

### Progress reporting

Every 100 tiles: `[table_name] {done}/{total} ({pct}%) - {rate:.0f} tiles/sec`

Final summary: total seeded, errors, elapsed time, tiles/sec.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test expected unrealistically small city bbox to yield ≥5 tiles at z=10**

- **Found during:** Task 1 GREEN phase
- **Issue:** A 0.2-degree bbox at z=10 spans only ~0.57 tile widths (1–2 tiles total), so `assert 5 <= count` always failed
- **Fix:** Updated test to use a 2-degree metro area bbox (NYC metro) yielding 42 tiles; adjusted lower bound to 20
- **Files modified:** `backend/tests/test_seed_tiles.py`
- **Commit:** 5edb3890 (absorbed into implementation commit)

**2. [Rule 2 - Missing] `backend/scripts/__init__.py` missing**

- **Found during:** Task 1 — `from scripts.seed_tiles import ...` failed with ModuleNotFoundError
- **Fix:** Created empty `__init__.py` so `scripts` is importable as a Python package
- **Files modified:** `backend/scripts/__init__.py`

## Verification

```
20 passed in 0.05s
```

`python -m scripts.seed_tiles --help` — shows all 5 documented flags with defaults.

## Known Stubs

None — the script wires directly to `get_tile()`, `TileCacheProvider.set()`, and `init_tile_pool()`.

## Self-Check: PASSED

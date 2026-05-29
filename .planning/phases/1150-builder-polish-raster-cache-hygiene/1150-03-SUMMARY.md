---
phase: "1150"
plan: "03"
subsystem: backend/tiles
tags: [hygiene, cache, memory, backend]
requires: []
provides: [HYG-01]
affects: [tiles/router]
tech_stack:
  added: [cachetools.LRUCache]
  patterns: [bounded-lru-cache]
key_files:
  created: []
  modified:
    - backend/app/processing/tiles/router.py
    - backend/tests/test_raster_tiles.py
decisions:
  - "LRUCache(maxsize=256) chosen over TTLCache — freshness on re-ingest handled by restart, LRU sufficient"
  - "256 maxsize mirrors ~2× typical project raster count, same rationale as sql_generator.py bounded cache"
metrics:
  duration: "5 minutes"
  completed: "2026-05-29"
  tasks_completed: 2
  files_changed: 2
---

# Phase 1150 Plan 03: HYG-01 Bound _band_stats_cache Summary

Replaced the unbounded `_band_stats_cache: dict` at `router.py:237` with `cachetools.LRUCache(maxsize=256)`. Prevents unbounded memory growth in long-running tile workers where one dict entry per raster-band request was never evicted until process restart.

## Tasks Completed

### Task 1: Replace _band_stats_cache with LRUCache(maxsize=256)

**Commit:** `5a34cd4d`

Changes in `backend/app/processing/tiles/router.py`:
- Added `from cachetools import LRUCache` import (after existing `import httpx / structlog`)
- Replaced `_band_stats_cache: dict[str, list[dict] | None] = {}` with:
  `_band_stats_cache: LRUCache[str, list[dict] | None] = LRUCache(maxsize=256)`
- Added HYG-01 comment explaining rationale
- `_fetch_band_statistics` body unchanged — `in`/`[]`/assignment all work identically on LRUCache

### Task 2: Backend unit tests

**Commit:** `5a34cd4d` (same commit)

Changes in `backend/tests/test_raster_tiles.py`:
- Added `from unittest.mock import AsyncMock, MagicMock`, `import httpx`, `import pytest` to imports
- Added `test_band_stats_cache_eviction`: creates LRUCache(maxsize=256), inserts 257 entries, asserts len=256, path-0 evicted, path-256 present
- Added `test_band_stats_cache_hit`: mocks `_titiler_client.get` returning 200, calls `_fetch_band_statistics` twice, asserts `mock_get.call_count == 1`
- Added `test_band_stats_cache_negative`: mocks `_titiler_client.get` raising `httpx.TimeoutException`, calls twice, asserts both None, `call_count == 1`

## Verification

```
python -c "from app.processing.tiles.router import _band_stats_cache; from cachetools import LRUCache; assert isinstance(_band_stats_cache, LRUCache); print('OK: maxsize=' + str(_band_stats_cache.maxsize))"
→ OK: maxsize=256

cd backend && uv run pytest tests/test_raster_tiles.py -k "band_stats" -v
tests/test_raster_tiles.py::test_band_stats_cache_eviction PASSED
tests/test_raster_tiles.py::test_band_stats_cache_hit PASSED
tests/test_raster_tiles.py::test_band_stats_cache_negative PASSED
3 passed, 19 deselected in 2.07s

grep -n "LRUCache" backend/app/processing/tiles/router.py → 3 lines (import + comment + instantiation)
grep -c "_band_stats_cache: dict" backend/app/processing/tiles/router.py → 0
```

## Deviations from Plan

None. Executed exactly as specified.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes. The only change is the cache type — no new trust surface.

## Self-Check: PASSED
- LRUCache present in router.py: confirmed 3 lines
- No dict annotation remaining: confirmed 0 matches
- 3/3 backend unit tests pass
- cachetools already a resolved dep (7.1.1) — no new package installed

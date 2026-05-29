---
phase: 1153-backend-multiband-stretch-configurable-bounds
plan: 01
subsystem: api
tags: [raster, titiler, stretch, percentile, stddev, lrucache, cog, tdd]

requires:
  - phase: 1152-single-band-raster-fixture
    provides: TESTDATA-01 fixture (GRAY_50M_SR.tif seeded, band_count=1, is_dem=false)
  - phase: 1153-SPIKE.md
    provides: SPIKE-01 resolved — Titiler p= arbitrary percentile support confirmed

provides:
  - Multi-band raster stretch: n_bands=min(band_count or 1, 3) via X-GeoLens-Band-Count header
  - Configurable percentile bounds: pmin/pmax Query params forwarded as repeated p= to /cog/statistics
  - Configurable stddev multiplier: sigma Query param replacing module constant _STDDEV_SIGMA
  - Bounds-keyed stats cache: _band_stats_cache keyed (open_path, pmin, pmax) for isolation
  - 422 validation of pmin/pmax/sigma before any Titiler call (T-1153-01)
  - Dynamic percentile key lookup via _percentile_key() helper
  - SPIKE-01 closure: contract-pinning test citing 1153-SPIKE.md evidence
  - OpenAPI snapshot regenerated with pmin/pmax/sigma params

affects: [1154-frontend-controls-cleanup, 1155-close-gate]

tech-stack:
  added: []
  patterns:
    - "X-GeoLens-Band-Count header seam: raster_auth_check emits band_count, raster_tile_proxy reads it"
    - "Bounds-keyed cache: (open_path, pmin, pmax) tuple key prevents stale cache hits on config change"
    - "raw_query_suffix for repeated Titiler p= params (query dict cannot hold repeated keys)"
    - "_percentile_key() helper: formats float to int-string for whole numbers to match Titiler response keys"

key-files:
  created: []
  modified:
    - backend/app/processing/tiles/router.py
    - backend/tests/test_raster_colormap_proxy.py
    - backend/tests/test_raster_tiles.py
    - backend/openapi.json

key-decisions:
  - "Cache key extended to (open_path, pmin, pmax) tuple — critical for correctness; without it, different bounds serve stale stats (PITFALL-01 from 1153-CONTEXT.md)"
  - "Band count delivered via response header X-GeoLens-Band-Count from raster_auth_check — avoids second DB query, reuses existing header-seam pattern"
  - "pmin/pmax forwarded as raw_query_suffix p=N&p=N to Titiler (query dict cannot hold repeated keys — raw suffix is the correct mechanism per titiler_url.py design)"
  - "422 validation placed BEFORE raster_auth_check call so Titiler is never called on invalid input (T-1153-01 threat model compliance)"
  - "OpenAPI snapshot regenerated inline (trivially clean: 3 optional query params + docstring update on one route)"
  - "DEM guard (algorithm= prefix short-circuits stretch) preserved unchanged — no stretch ever applied to DEM"
  - "_percentile_key() helper formats float as integer string for whole numbers to match Titiler's percentile_2/percentile_5 key format (not percentile_2.0)"

patterns-established:
  - "Header seam for band metadata: emit in auth-check handler, read in tile-proxy — avoids extra DB round-trip"
  - "Bounds in cache key: any cache keyed on open_path alone will go stale when config changes — always include config in key"

requirements-completed:
  - RASTER-STRETCH-03
  - SPIKE-01
  - RASTER-STRETCH-UI-01

duration: 35min
completed: 2026-05-29
---

# Phase 1153 Plan 01: Backend Multi-Band Stretch + Configurable Bounds Summary

**Backend raster tile proxy now produces independent per-band rescale= fragments for 3-band rasters and accepts configurable pmin/pmax/sigma bounds with correct cache isolation, validated before Titiler is called.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-29T23:38Z
- **Completed:** 2026-05-29T23:53Z
- **Tasks:** 3 (2 TDD + 1 verification/closure)
- **Files modified:** 4

## Accomplishments

- **RASTER-STRETCH-03:** 3-band rasters now produce exactly 3 `rescale=` fragments (one per band) via `n_bands=min(band_count or 1, 3)`. Band count flows from DB row through `X-GeoLens-Band-Count` response header from `raster_auth_check` — no extra DB query needed.
- **RASTER-STRETCH-UI-01 backend:** `pmin`/`pmax`/`sigma` Query params added to `raster_tile_proxy`. Forwarded as repeated `p=` to Titiler `/cog/statistics`. `_band_stats_cache` keyed `(open_path, pmin, pmax)` — different bounds never serve stale cached stats. Dynamic percentile key lookup via `_percentile_key()` helper.
- **SPIKE-01 closed:** Contract-pinning test `test_spike01_p_param_forwarding_and_dynamic_percentile_key` cites `1153-SPIKE.md` as live-evidence source and pins the `p=`/`percentile_<N>` forwarding contract.
- **All hard gates passed:** 3-band → 3 fragments, cache isolation proven by key-length assertion, invalid bounds → 422 before Titiler, defaults unchanged, DEM guard intact.
- **OpenAPI snapshot regenerated:** Trivially clean — 3 optional query params + docstring on one binary-tile route. `make openapi-check` now passes.

## Task Commits

1. **RED: Failing tests for Tasks 1-3** - `26f53cd9` (test)
2. **GREEN: Multi-band + configurable bounds implementation** - `23349add` (feat)

_Note: Test fix for bad `import monkeypatch` and `test_raster_tiles.py` signature update both part of the GREEN commit (Rule 1 inline fixes)._

## Files Created/Modified

- `backend/app/processing/tiles/router.py` — `X-GeoLens-Band-Count` header in `raster_auth_check`; `pmin`/`pmax`/`sigma` Query params + 422 validation in `raster_tile_proxy`; `_band_stats_cache` type changed to `LRUCache[tuple, ...]`; `_percentile_key()` helper added; `_fetch_band_statistics(open_path, pmin, pmax)` signature extended; `_compute_stretch_rescale(..., *, pmin, pmax, sigma)` signature extended with keyword-only bounds args
- `backend/tests/test_raster_colormap_proxy.py` — Extended `_make_auth_response` with `band_count` param; `_BAND_STATS` extended with b2/b3 dicts + percentile_5/percentile_95 keys; `_auth_band_count` fixture attribute added; 17 new tests covering all Tasks 1-3 behaviors + SPIKE-01 closure
- `backend/tests/test_raster_tiles.py` — Updated `test_band_stats_cache_hit` and `test_band_stats_cache_negative` to pass `pmin=2.0, pmax=98.0` to updated `_fetch_band_statistics` signature
- `backend/openapi.json` — Regenerated with new `pmin`/`pmax`/`sigma` query params on `/tiles/raster-proxy/{dataset_id}/{z}/{x}/{y}.{fmt}`

## Decisions Made

- **Cache key extended to tuple** `(open_path, pmin, pmax)`: Without bounds in the key, a first request at p2/p98 would serve stale stats to a subsequent p5/p95 request — silent wrong-tile output. Critical correctness requirement (PITFALL-01 / `1153-CONTEXT.md`).
- **Header seam for band_count**: `raster_auth_check` already held the DB row with `band_count`; emitting it as `X-GeoLens-Band-Count` header avoids a second DB query. Pattern matches the existing `X-GeoLens-Asset-OpenPath` seam.
- **422 validation before `raster_auth_check` call**: Validates `pmin`/`pmax`/`sigma` first, then calls `raster_auth_check`. This means invalid bounds are rejected before any DB hit or Titiler call (T-1153-01 threat model).
- **`_percentile_key()` formats floats as integer strings**: Titiler returns `percentile_2` not `percentile_2.0`; the helper drops trailing `.0` for whole numbers. Verified via SPIKE-01 evidence.
- **OpenAPI regenerated inline**: The diff was trivially clean (3 optional float params + docstring); no SDK regen needed (the route returns binary tiles, untracked by the TypeScript SDK generator).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed broken `import monkeypatch` in new test**
- **Found during:** Task 1 (RED phase) — leftover stray `import monkeypatch as mp` line
- **Issue:** `test_missing_band_count_falls_back_to_one_rescale_fragment` contained a stray `import monkeypatch as mp` (not a real module) causing `ModuleNotFoundError`
- **Fix:** Removed the bad import; test already receives `monkeypatch` as a pytest fixture parameter — no change to test logic
- **Files modified:** `backend/tests/test_raster_colormap_proxy.py`
- **Committed in:** `23349add` (GREEN phase commit)

**2. [Rule 1 - Bug] Updated `test_raster_tiles.py` callers to new `_fetch_band_statistics` signature**
- **Found during:** Task 1/2 GREEN verification — focused suite reported 2 failures in `test_raster_tiles.py`
- **Issue:** `test_band_stats_cache_hit` and `test_band_stats_cache_negative` called `_fetch_band_statistics(path)` with the old single-arg signature; the updated function requires `(path, pmin, pmax)`
- **Fix:** Added `pmin=2.0, pmax=98.0` to both callers (the default p2/p98 values, preserving test intent)
- **Files modified:** `backend/tests/test_raster_tiles.py`
- **Committed in:** `23349add` (GREEN phase commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — caller signature updates / stray import)
**Impact on plan:** Both necessary for test correctness. No scope creep. All acceptance criteria met.

## OpenAPI Drift Status

`make openapi-check` reported drift after adding `pmin`/`pmax`/`sigma` to `raster_tile_proxy`. The diff was trivially clean:
- 3 new optional float query params added to `/tiles/raster-proxy/...`
- Updated endpoint docstring

OpenAPI snapshot regenerated inline (`make openapi`); `make openapi-check` now passes with no-drift. No TypeScript SDK regen needed (binary-tile route, not tracked by frontend API codegen).

## Issues Encountered

None beyond the two Rule 1 auto-fixes documented above.

## Known Stubs

None — all new params are fully wired end-to-end in the backend. Frontend controls (phase 1154) will wire these params to the UI.

## Threat Flags

No new threat surface beyond what the plan's threat model covers. `T-1153-01` (pmin/pmax/sigma validation) and `T-1153-03` (DEM guard) both mitigated as specified.

## Next Phase Readiness

- **Phase 1154 (Frontend Controls)** is unblocked: `pmin`/`pmax`/`sigma` query params on `raster-proxy` are fully functional and documented in OpenAPI snapshot. Frontend can wire slider controls directly to these params.
- The `X-GeoLens-Band-Count` header value from `raster_auth_check` is also available for frontend rendering decisions (e.g., show/hide colormap picker for multi-band).
- No blockers.

## Self-Check

Verified:

- `backend/app/processing/tiles/router.py` — exists and contains `_band_stats_cache`, `X-GeoLens-Band-Count`, `pmin`, `pmax`, `sigma`, `_percentile_key`
- `backend/tests/test_raster_colormap_proxy.py` — exists and contains `rescale=`, `test_spike01_p_param_forwarding_and_dynamic_percentile_key`
- Commit `26f53cd9` (RED) and `23349add` (GREEN) — both in git log
- Focused suite: 66 passed, 0 failures

## Self-Check: PASSED

---
*Phase: 1153-backend-multiband-stretch-configurable-bounds*
*Completed: 2026-05-29*

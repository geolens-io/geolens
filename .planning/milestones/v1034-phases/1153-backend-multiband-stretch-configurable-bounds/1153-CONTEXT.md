# Phase 1153: Backend — Multi-Band Stretch + Configurable Bounds - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) — enriched with v1034 research + a RESOLVED spike

<domain>
## Phase Boundary

The backend correctly computes an independent per-band rescale for multi-band rasters AND accepts configurable percentile/sigma bounds that are properly isolated in the stats cache — so a 3-band ortho produces 3 `rescale=` fragments and changing `pmin` from 2 to 5 actually changes the served tiles.

Requirements: **RASTER-STRETCH-03** (backend), **SPIKE-01** (RESOLVED — see 1153-SPIKE.md), **RASTER-STRETCH-UI-01** (backend portion only; frontend lands in phase 1154).

Scope is BACKEND ONLY. No frontend changes in this phase.
</domain>

<decisions>
## Implementation Decisions

### SPIKE-01 — RESOLVED (do not re-run; see 1153-SPIKE.md)
Live Titiler `/cog/statistics` **supports arbitrary `p=` params** and returns `percentile_<N>` keys (`p=5&p=95` → `percentile_5`/`percentile_95`). Configurable bounds is the SIMPLE path. Multi-band returns `b1/b2/b3` keys with distinct per-band stats. The spike is satisfied — the plan must reference 1153-SPIKE.md and NOT re-spike; encode SPIKE-01 as "resolved, evidence in 1153-SPIKE.md".

### Locked from research + spike
- **Multi-band (RASTER-STRETCH-03):** the ONLY change is the `n_bands=1` hardcode at `backend/app/processing/tiles/router.py:~581` → `n_bands=min(band_count or 1, 3)`. `band_count` is on the resolved raster row. `_compute_stretch_rescale` already loops over n_bands. Cap at 3 (Titiler render selects bidx 1–3). Pin with a unit test asserting exactly 3 `rescale=` fragments in the built Titiler URL for a 3-band input.
- **Configurable bounds (RASTER-STRETCH-UI-01 backend):**
  - Add `pmin`/`pmax` (percentile clip, replace fixed 2/98) and `sigma` (stddev multiplier, replace fixed 2.0) as query params on `raster_tile_proxy`.
  - Forward `p=pmin&p=pmax` to `/cog/statistics` (repeated key — use the raw-query mechanism, NOT a dict that can't hold repeated keys). Read `percentile_<pmin>`/`percentile_<pmax>` dynamically.
  - **CRITICAL — cache key:** `_band_stats_cache` (`tiles/router.py:~241`) is keyed on `open_path` only. Extend it to include the bounds (e.g. `(open_path, pmin, pmax)`) or different bounds serve stale cached stats → silent no-op. This is a hard acceptance gate.
  - Validate bounds: `pmin < pmax`, `0 <= pmin`, `pmax <= 100`, `sigma > 0` → HTTP 422 before reaching Titiler.
  - Defaults must preserve existing behavior: absent params → current p2/p98 + 2σ.
- **DEM guard preserved:** stretch must NOT apply to DEM layers (the `algorithm=`/`is_dem` terrainrgb guard stays). Do not touch that path.
</decisions>

<code_context>
## Existing Code Insights

- `backend/app/processing/tiles/router.py`:
  - `_band_stats_cache` (~line 241, `LRUCache(256)`), `_fetch_band_statistics(open_path)` (~244, calls `build_titiler_cog_url("statistics", query={"url": open_path})`), `_compute_stretch_rescale(...)` (~275, loops over n_bands), the `n_bands=1` call site (~581), the `is_dem`/`algorithm=` DEM guard (~477).
- `backend/app/platform/storage/titiler_url.py`: `build_titiler_cog_url(endpoint, query=...)`, base `http://titiler:8000`. The `query` dict can't express repeated keys — for `p=pmin&p=pmax` use a raw query-suffix approach (check the existing function signature; may need a small extension to append repeated params).
- Test data live: `GRAY_50M_SR.tif` (band_count=1) + `adk_high_peaks_ny_orthos_3857.tif` (band_count=3).
- Backend tests: `backend/tests/` — focused raster/tile tests. Note the test DB env recipe (project memory): `set -a && source ../.env.test && set +a` before `cd backend && uv run pytest` (POSTGRES_HOST=localhost, PORT=5434).
- Full integration detail: `.planning/research/ARCHITECTURE.md`; traps: `.planning/research/PITFALLS.md` (cache-key staleness is Pitfall 1).
</code_context>

<specifics>
## Specific Ideas
- Build order: multi-band `n_bands` fix (+unit test) → configurable-bounds params + cache-key change + validation (+unit tests) → focused backend pytest green.
- Unit tests should assert against the BUILT Titiler URL (fragment count, percentile key selection, cache-key isolation), not require live Titiler.
- `make openapi-check` should remain no-drift — these are query params on an existing tile route returning binary tiles; confirm whether the OpenAPI snapshot captures them. If the route signature changes the snapshot, regen per the dual-snapshot order (project memory `openapi_dual_snapshot_refresh_order`). Expectation from REQUIREMENTS Out-of-Scope: no SDK regen needed, but verify.
</specifics>

<deferred>
## Deferred Ideas
- Frontend controls (RASTER-STRETCH-UI-01 frontend, gate widen, hint) → phase 1154.
- Multi-band stretch > 3 bands → out of scope (cap at 3).
</deferred>

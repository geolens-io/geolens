# Project Research Summary

**Project:** GeoLens v1034 — Raster Stretch & Colormap Completion
**Domain:** Raster tile serving / map builder editor controls (completing half-built features)
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

v1034 is a focused completion milestone for raster rendering features that shipped partially in v1031–v1033. The scope is narrow but precise: fix a one-line hardcoded `n_bands=1` in `raster_tile_proxy` that prevents multi-band stretch from working, expose `pmin`/`pmax`/`sigma` as configurable query params on the same proxy endpoint, and seed a non-DEM single-band uint8 COG fixture so the colormap+stretch UI can be verified end-to-end. No new dependencies, no schema migrations, no new routes. All work is additive modification to five existing files plus a new function in the seed script.

The recommended build sequence is strictly dependency-ordered: fixture first (all subsequent UI verification requires a real raster in the system), then multi-band backend (backend-only, verifiable with curl), then configurable-bounds backend (must precede any frontend that sends `pmin`/`pmax`), then frontend controls, then cleanup of v1033 dead code, then close-gate. Skipping this order risks wiring frontend params to a backend that silently ignores them, or verifying stretch behavior against a raster that is actually routed through `algorithm=terrainrgb` and bypasses all stretch/colormap logic.

Two critical traps dominate the risk surface. First: the `_band_stats_cache` key is currently `open_path` only — once configurable bounds land, different `pmin`/`pmax` values will silently hit the same cache entry and return stale p2/p98 stats regardless of what the user set. The cache key must be expanded to `(open_path, pmin, pmax)` before the configurable-bounds backend is deployed. Second: a single-band float32 fixture is auto-classified as a DEM candidate by `cog.py:85` (`is_dem_candidate = src.count == 1 and _is_float_dtype(src.dtypes[0])`), which causes `render_params = "algorithm=terrainrgb"` and silently bypasses all stretch and colormap logic — the UI will appear to work (HTTP 200) but will test nothing. The fixture must be uint8 or uint16. One spike-worthy unknown remains: whether Titiler 2.0.2 accepts arbitrary `p=<float>` percentile params on `/cog/statistics` or returns only fixed `percentile_2`/`percentile_98` fields. STACK.md research indicates the `p=` param is supported (Context7 StatisticsParams confirms `alias="p"`), but this has not been smoke-tested end-to-end with the pinned Titiler image. This spike should be the first act of the configurable-bounds backend phase.

## Key Findings

### Recommended Stack

No new dependencies. The project already has Titiler 2.0.2 (pinned in `docker-compose.yml`), `rasterio`, `GDAL`, and `cachetools`. The multi-band fix is a single call-site change in `router.py`. The configurable-bounds feature threads three new `Query` params through existing functions. The frontend already has the `_colormap` / `_stretch` builder-private paint key convention; the new `_pmin`, `_pmax`, `_sigma` keys follow the same pattern.

**Core technologies (unchanged from existing stack):**
- **Titiler 2.0.2** — raster tile serving; `/cog/statistics?p=N` for percentile stats, `rescale=lo,hi` (repeated per band) for tile rendering
- **FastAPI** — proxy endpoint; new `pmin`/`pmax`/`sigma` Query params with range validation (422 on invalid)
- **MapLibre + raster-adapter.ts** — tile URL construction; `buildColormapTileUrl` reads paint keys and assembles the URL; `syncRasterLayer` teardown/recreate fires automatically on URL diff
- **Natural Earth NACIS CDN** — fixture source; `GRAY_50M_SR.zip` (18 MB, public domain, uint8 single-band, same CDN pattern as existing seed script)

### Expected Features

**Must have (table stakes) — build in v1034:**
- **Per-band multi-band stretch (RASTER-STRETCH-03)** — QGIS and ArcGIS both do per-band percentile/stddev stretch by default on multiband color renderers; washed-out orthos are the daily GIS pain point this solves. Backend is almost done (`_compute_stretch_rescale` already loops `range(n_bands)`); only the `n_bands=1` call site and the RasterEditor gate need changing.
- **Configurable percentile clip values (RASTER-STRETCH-UI-01, percentile variant)** — QGIS 2%/98% "Cumulative count cut" inputs and ArcGIS `minPercent`/`maxPercent` are both classified as table stakes; medium complexity (2 new query params + cache key expansion).
- **Configurable sigma multiplier (RASTER-STRETCH-UI-01, stddev variant)** — low complexity (1 new param, replaces hardcoded `_STDDEV_SIGMA = 2.0`).
- **Stretch-colormap hint copy (RASTER-STRETCH-UI-02 closure)** — one-line hint; no behavior change. Closes the deferred coupling issue.
- **Non-DEM single-band fixture (TESTDATA-01)** — uint8 Natural Earth shaded relief COG; required for all end-to-end colormap+stretch verification.
- **v1033 dead-code cleanup** — `onRenderModeChange` member + `hillshadeTerrainNote` advisory.

**Should have (differentiators — defer from v1034):**
- Band-level stat readouts (computed lo/hi per band displayed in editor)
- Per-band independent vs. linked stretch mode toggle
- "Stretch on current view" / dynamic range (high complexity)

**Do not build (anti-features):**
- Manual min/max numeric inputs per band
- Histogram visualizer inline
- Colormap for multi-band rasters (`band_count >= 3`) — keep the existing gate
- Stretch applied to DEM layers — existing `algorithm=terrainrgb` guard must be preserved

### Architecture Approach

All three features share one data path: `RasterEditor.tsx` (paint key writes) → `buildColormapTileUrl` in `raster-adapter.ts` (tile URL construction) → `syncRasterLayer` in `map-sync.ts` (source teardown/recreate on URL diff, unchanged) → `raster_tile_proxy` in `tiles/router.py` (Query param handling, statistics fetch, rescale computation) → Titiler `/cog/statistics` and `/cog/tiles/`. No new routes, no schema migrations, no changes to `map-sync.ts` or `titiler_url.py`.

**Modified components:**
1. `backend/app/processing/tiles/router.py` — `raster_tile_proxy` (n_bands derivation + `pmin`/`pmax`/`sigma` Query params); `_fetch_band_statistics` (compound cache key + p-param forwarding); `_compute_stretch_rescale` (extended signature); `_band_stats_cache` type annotation
2. `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — `buildColormapTileUrl` reads `_pmin`, `_pmax`, `_sigma` from paint
3. `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — stretch gate widened to `band_count >= 1`; colormap gate unchanged; new pmin/pmax/sigma inputs; new keys excluded from `RASTER_OWNED_PAINT_PROPERTIES`
4. `scripts/seed-natural-earth.py` — `ingest_raster_fixture()` function + call in `main()`

**Confirmed zero-diff:** `map-sync.ts`, `titiler_url.py`, `frontend/src/types/api.ts`, `LayerStyleEditor/types.ts`

### Critical Pitfalls

1. **`_band_stats_cache` key excludes configurable bounds — silent wrong-stretch bug** — Cache key is `open_path` only. When `pmin`/`pmax` become user-configurable, different bounds will hit the same cache entry and always serve p2/p98 stats. Fix: change to `(open_path, pmin, pmax)` compound key BEFORE configurable-bounds backend lands. Test: two requests with different `pmin`/`pmax` produce different `rescale=` fragments.

2. **Float32 single-band fixture auto-classified as DEM — colormap/stretch backend guards bypass silently** — `cog.py:85` sets `is_dem=True` for any `band_count==1 AND float dtype`. This routes to `algorithm=terrainrgb` and skips all colormap/stretch logic. HTTP 200 tiles come back; nothing is being verified. Fix: use uint8 or uint16 fixture (`GRAY_50M_SR.zip` is uint8). Verify via `SELECT is_dem FROM catalog.raster_assets WHERE dataset_id = '<id>'` before any UI smoke.

3. **Multi-band stretch `n_bands=1` is a named deliverable, not an implicit assumption** — The call site at `router.py:581` passes `n_bands=1` with no compile-time guard. A RASTER-STRETCH-03 implementation that adds frontend controls but forgets this backend line silently applies only b1's rescale to all displayed bands. Fix: explicitly name "change `n_bands=1` to `n_bands=min(band_count, 3)` at router.py:581" as a plan deliverable, with a unit test asserting exactly 3 `rescale=` fragments in the Titiler URL for a 3-band request.

4. **Titiler `p=` arbitrary percentile support is unverified end-to-end against the pinned image** — Context7 confirms `alias="p"` in StatisticsParams, but whether Titiler 2.0.2 returns `percentile_5` when `?p=5` is passed has not been smoke-tested against the running container. If Titiler returns only fixed p2/p98, configurable-bounds requires a different approach. Spike at Phase 3 start.

5. **Per-band statistics fetched N times instead of once** — A natural multi-band implementation might loop over bands and call `_fetch_band_statistics` once per band (3× latency on first tile). Titiler returns all bands in one response; the existing function already returns a list ordered `b1, b2, b3`. Fix: keep the single call; pass `n_bands` to `_compute_stretch_rescale`. Test: `_titiler_client.get` called exactly once for a 3-band stretch request.

## Implications for Roadmap

### Phase 1: Single-Band Raster Fixture (TESTDATA-01)
**Rationale:** All subsequent UI verification depends on a real non-DEM single-band COG in the system. Without it, the colormap+stretch section never renders, and any smoke against the ADK DEM silently exercises zero stretch/colormap logic. Build this first so every subsequent phase has something deterministic to test against.
**Delivers:** `ingest_raster_fixture()` in seed script + idempotency check + license verification + COG compliance assertion
**Features:** TESTDATA-01
**Avoids:** Pitfall 2 (DEM misclassification), Pitfall 6 (fixture fails COG compliance), Pitfall 7 (CI-time download), Pitfall 8 (duplicate on re-run), Pitfall 9 (license)
**Research flag:** None — pattern mirrors existing vector ingest in the seed script; fixture source and dtype requirement fully specified.

### Phase 2: Multi-Band Backend Fix (RASTER-STRETCH-03 backend)
**Rationale:** Pure backend change with no frontend dependency. Can be landed and curl-verified independently. Must precede the frontend gate change so the backend is ready the moment the frontend starts sending multi-band stretch requests. The `n_bands=1` call site is the only change; `_compute_stretch_rescale` and `_apply_stretch_rescale` are already correct for multi-band.
**Delivers:** `n_bands=min(band_count, 3)` derived from `render_params.count("bidx=")` at router.py:581; unit test asserting exactly 3 `rescale=` fragments for a 3-band request; unit test for out-of-order band stat key sorting
**Features:** RASTER-STRETCH-03 (backend half)
**Avoids:** Pitfall 3 (n_bands=1 — named deliverable with test), Pitfall 4 (N stats calls), Pitfall 5 (bidx ordering)
**Research flag:** None — one-liner change with clear test criteria.

### Phase 3: Configurable-Bounds Backend (RASTER-STRETCH-UI-01 backend)
**Rationale:** Must be deployed before any frontend sends `pmin`/`pmax`/`sigma` params; otherwise the backend ignores them silently and the feature appears to work but applies fixed p2/p98 bounds. Cache key expansion is load-bearing — without it, `pmin=5` and `pmin=2` serve identical tiles from cache.
**Spike required first:** Confirm Titiler 2.0.2 returns `percentile_N` keyed fields for arbitrary `p=N` params against the running container (`curl http://localhost:8000/cog/statistics?url=<path>&p=5&p=95` and inspect response keys). If only `percentile_2`/`percentile_98` are returned, the approach needs to pivot before any code is written. Spike is fast (< 30 min).
**Delivers:** `pmin`/`pmax`/`sigma` Query params on `raster_tile_proxy`; `_fetch_band_statistics` compound cache key `(open_path, pmin, pmax)` + p-param forwarding to Titiler; `_compute_stretch_rescale` extended signature; 422 validation on invalid bounds; unit tests for cache isolation and wrong-bounds detection
**Features:** RASTER-STRETCH-UI-01 (backend)
**Avoids:** Pitfall 1 (stale cache key — fix lands here, not at UI delivery)
**Research flag:** SPIKE — Titiler `p=` arbitrary percentile support must be confirmed against the running image before implementation starts.

### Phase 4: Frontend Controls
**Rationale:** Depends on Phases 2 and 3 being complete. Two sub-steps in either order:
- **4a — Widen multi-band gate in RasterEditor:** stretch gate to `band_count >= 1`; COLORMAP gate unchanged. No new URL params; backend handles it from Phase 2.
- **4b — Configurable-bounds inputs + tile URL params:** `_pmin`/`_pmax`/`_sigma` paint keys in `buildColormapTileUrl`; RasterEditor gets two numeric inputs (percentile) or segmented 1σ/2σ/3σ control (stddev); new keys excluded from `RASTER_OWNED_PAINT_PROPERTIES`; RASTER-STRETCH-UI-02 hint copy.
**Delivers:** Stretch section visible for multi-band rasters; configurable pmin/pmax inputs; sigma segmented control; stretch-colormap hint; frontend debouncing via `coalesceFrame` on slider input
**Features:** RASTER-STRETCH-03 (frontend), RASTER-STRETCH-UI-01 (frontend), RASTER-STRETCH-UI-02 (hint copy)
**Avoids:** UX pitfall: per-tick tile refetch (debounce on slider release)
**Research flag:** None — `coalesceFrame` and builder-private paint key convention are established patterns in the codebase.

### Phase 5: Cleanup (v1033 Tech Debt)
**Rationale:** Independent of all feature work. Remove dead `onRenderModeChange` member and `hillshadeTerrainNote` advisory. No functional change.
**Delivers:** Dead code removed; codebase hygiene
**Research flag:** None.

### Phase 6: Close-Gate (Playwright MCP + Test Coverage)
**Rationale:** Orchestrator drives live MCP smoke (executor lacks `mcp__playwright__*` access per project memory). Covers: single-band fixture (colormap changes tile appearance, not DEM bypass); multi-band dataset (stretch visible, colormap hidden); configurable pmin/pmax (tile re-renders with different contrast); cache isolation verification. Full "Looks Done But Isn't" checklist from PITFALLS.md.
**Delivers:** Signed-off acceptance on RASTER-STRETCH-03, RASTER-STRETCH-UI-01, RASTER-STRETCH-UI-02, TESTDATA-01
**Research flag:** Orchestrator must run MCP directly; do not delegate to executor.

### Phase Ordering Rationale

- Fixture before all else: no point testing stretch logic without a known-good non-DEM raster; the DEM auto-classification trap makes this a hard pre-condition.
- Multi-band backend before configurable-bounds backend: both touch `raster_tile_proxy`; sequential landing avoids conflicts and makes the `n_bands` fix independently verifiable.
- Both backend phases before frontend controls: otherwise frontend params are silently ignored and the feature appears to work but applies wrong logic.
- Spike at Phase 3 start: the one high-impact unknown must be resolved before any configurable-bounds code is written.
- Cleanup before close-gate: dead code should not survive into the final smoke session.

### Research Flags

Needs research/spike during planning:
- **Phase 3:** Titiler `p=` arbitrary percentile support — confirm via `curl` against the running Titiler 2.0.2 container before any backend wiring. If only `percentile_2`/`percentile_98` are returned, the configurable-bounds strategy needs revision before proceeding.

Standard patterns (skip research-phase):
- **Phase 1:** Fixture seeding — mirrors existing vector ingest pattern in `seed-natural-earth.py`.
- **Phase 2:** Multi-band backend — one call-site change with a clear test criterion.
- **Phase 4:** Frontend controls — `coalesceFrame` and builder-private paint key convention established in codebase.
- **Phase 5:** Cleanup — dead code removal.
- **Phase 6:** Close-gate — Playwright MCP orchestrator-only per project memory.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Titiler 2.0.2 pinned; Context7 docs confirm rescale syntax and StatisticsParams `p=` alias; existing codebase cross-checked against all findings |
| Features | HIGH | QGIS 3.44 and ArcGIS Pro docs confirm table-stakes classification; sources include QGIS issue tracker and ArcGIS SDK spec |
| Architecture | HIGH | All findings from direct file inspection at HEAD (`f2c06400`); modified/unchanged file list confirmed by reading every relevant function |
| Pitfalls | HIGH | All pitfalls sourced from live code (DEM heuristic at `cog.py:85`, cache key at `router.py:250`, `n_bands=1` at `router.py:581`); not inferred |

**Overall confidence:** HIGH

### Gaps to Address

- **Titiler `p=` arbitrary percentile smoke test (spike):** Rated HIGH confidence from Context7, but not yet executed against the running Titiler 2.0.2 container. Resolve at Phase 3 start with `curl http://localhost:8000/cog/statistics?url=<path>&p=5&p=95`. If `percentile_5` is absent from the response, escalate before writing code.
- **COG conversion fidelity of `GRAY_50M_SR.tif` via ingest worker (MEDIUM confidence):** The file has not been end-to-end ingested in this project. Resolve in Phase 1 by running the seed script and checking `check_cog_compliance()` output.
- **`n_bands` derivation via `render_params.count("bidx=")` (verify in Phase 2):** Sound approach but should be confirmed against the actual `render_params` format for both 1-band and 3-band cases before shipping.

## Sources

### Primary (HIGH confidence)
- Context7 `/developmentseed/titiler` library (1483 snippets) — `/cog/statistics` response shape, `StatisticsParams` `p=` alias, `rescale=` repeated-param syntax
- `backend/app/processing/tiles/router.py` HEAD `f2c06400` — `_compute_stretch_rescale`, `_fetch_band_statistics`, `_apply_stretch_rescale`, `_titiler_render_params`, `raster_tile_proxy`, `_band_stats_cache`, `_STDDEV_SIGMA`, `_ALLOWED_STRETCH`
- `backend/app/processing/raster/cog.py:85` — `is_dem_candidate` heuristic
- `backend/tests/test_raster_colormap_proxy.py` — `_BAND_STATS` fixture, cache clear pattern
- `backend/tests/test_raster_tiles.py` — `_create_raster_dataset` helper
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — section gate, private paint keys, `coalesceFrame` usage
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — `buildColormapTileUrl`, `RASTER_OWNED_PAINT_PROPERTIES`
- `frontend/src/components/builder/map-sync.ts` lines 624–688 — `syncRasterLayer`
- `scripts/seed-natural-earth.py` lines 542–616 — `ingest_dataset` three-step pattern
- `docker-compose.yml` — Titiler 2.0.2 image pin

### Secondary (MEDIUM confidence)
- QGIS 3.44 Raster Properties Dialog — Symbology tab (table-stakes classification for per-band stretch)
- QGIS issue #15683 — stretch + colormap coupling behavior
- ArcGIS Pro Stretch Function documentation — `minPercent`/`maxPercent`, `numberOfStandardDeviations`
- ArcGIS Web Map Specification `stretchRenderer`
- Titiler Discussion #304 — per-band rescale pattern
- `https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip` — 200 OK, 18 279 677 bytes; public domain at naturalearthdata.com/about/terms-of-use/

---
*Research completed: 2026-05-29*
*Ready for roadmap: yes*

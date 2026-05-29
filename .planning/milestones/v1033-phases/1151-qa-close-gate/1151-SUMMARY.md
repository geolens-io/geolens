# Phase 1151: QA Close-Gate - Summary

**Completed:** 2026-05-29
**Requirements:** QA-01 (live MCP), QA-02 (code gates + CHANGELOG)

## QA-02 — Code gates (all green)

| Gate | Command | Result |
|------|---------|--------|
| Frontend typecheck | `npm run typecheck` | exit 0 |
| Frontend unit tests | `npm run test` (vitest) | **2601/2601** (238 files) |
| i18n parity | `npm run test:i18n` | 2/2 |
| Lint | `npm run lint` | 0 errors (1 pre-existing warning) |
| Backend raster+tile | `pytest tests/test_raster_tiles.py test_raster_colormap_proxy.py test_tile_cache.py test_phase_274_tile_cache.py test_tile_cache_cols_key.py` | **76 passed** |
| OpenAPI drift | `make openapi-check` (`dump_openapi.py --check`) | exit 0 — **no drift** (frontend-only render_mode change) |
| Builder e2e smoke | `npm run e2e:smoke:builder` (chromium) | **26/26** (2.0m) |

## QA-01 — Live Playwright MCP re-verify (orchestrator-driven)

Stack healthy (5/5 services). Auth re-established mid-session (JWT expired after >1.5h; re-logged via UI). Frontend changes live via Vite HMR (confirmed by e2e + MCP).

**Map A — `8dd6a129` (ADK 3D Relief), fresh load, no interaction:**
- **RMODE-01 ✅** `map.getTerrain()` = `{source:"terrain-dem", exaggeration:1}`; `terrain-dem` source present (was `null` pre-fix). 3D relief visible — evidence `v1033-evidence/mapA-03-terrain-on-fresh-load-FIXED.jpeg` (vs flat `mapA-01-initial-load.jpeg`).
- **RMODE-02 ✅** DEM "3D terrain (DEM)" editor shows **◬ Terrain [checked]** on fresh load (was ▦ Image pre-fix — the "render-as revert" bug). No revert.
- **LABEL-01 ✅** "ADK 46er peaks" row shows label indicator (title "Labels on: name"); "Hiking trails" + "Land classification" rows do not.
- **POLISH-01 ✅** Point Style tab: exactly 1 "Render as" control (segmented Point/Symbols/Heatmap/Cluster); the redundant "Choose how this point layer…" combobox is gone.
- **Console: 0 errors** on fresh load with terrain active — POLISH-02 holds (no `backfillBorder` "dem dimension mismatch" spam; terrain-only is clean, and the dual-consumer guard prevents the hillshade+terrain conflict).

**Map B — `c39be324` (Terrain & Trails):**
- **POLISH-02 safety ✅** terrain off (`terrain_config.enabled=false`) → guard inactive → hillshade layer renders normally (`layer-bebcf825…` visible). Primary hillshade path unaffected.
- **Console: 0 errors.**

## Disposition
All 9 v1033 requirements satisfied. Both sample maps clean. No regressions across 2601 unit tests + 26 e2e + 76 backend raster/tile.

Note: the HYG-01 `_band_stats_cache` LRUCache is a backend change verified by unit tests (eviction + cache-hit + negative caching) — live raster-tile rendering re-confirmed clean on both maps; a backend container rebuild is not required for the gate (the running api/worker is unaffected by the in-process cache bound until next deploy).

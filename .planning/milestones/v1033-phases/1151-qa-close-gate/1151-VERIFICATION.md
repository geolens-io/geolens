---
phase: "1151"
status: passed
verified: 2026-05-29
method: orchestrator-driven live Playwright MCP + inline code gates
---

# Phase 1151 Verification — QA Close-Gate

## Goal-backward check
Both ADK sample maps verified clean via live MCP; all code gates green; CHANGELOG written. All 9 v1033 requirements satisfied.

## Requirement → evidence

| Req | Status | Evidence |
|-----|--------|----------|
| RMODE-01 | ✅ passed | Map A fresh load `getTerrain()` non-null + `terrain-dem` source (live MCP); screenshot `mapA-03`. |
| RMODE-02 | ✅ passed | Map A DEM editor shows ◬ Terrain checked on fresh load (live MCP) — no revert to Image. |
| RMODE-03 | ✅ passed | (Phase 1148) BSR-09 cast/comment removed; union includes terrain/image; round-trip + RENDER_MODES guard tests green (vitest 2601/2601). |
| LABEL-01 | ✅ passed | Label indicator present on "ADK 46er peaks" (title "Labels on: name"), absent on unlabeled rows (live MCP); StackRow RTL tests + i18n 2/2. |
| POLISH-01 | ✅ passed | Point Style tab has exactly 1 "Render as" control; dropdown gone (live MCP); LayerStyleEditor tests green. |
| POLISH-02 | ✅ passed | Map A terrain active with 0 console errors (no dual-consumer spam); Map B hillshade renders with terrain off (guard inactive — primary path safe); map-sync predicate/skip unit tests green. |
| HYG-01 | ✅ passed | `_band_stats_cache` → `cachetools.LRUCache(maxsize=256)`; backend eviction + cache-hit + negative-caching tests pass (3/3); raster tiles render clean on both maps. |
| QA-01 | ✅ passed | Live MCP on both maps (above); 0 console errors each. |
| QA-02 | ✅ passed | typecheck 0 · vitest 2601/2601 · i18n 2/2 · lint 0-err · backend raster+tile 76 · openapi-check no-drift · e2e:smoke:builder 26/26. |

## Gate outputs (real)
- `npm run typecheck` → exit 0
- `npm run test` → 2601 passed (238 files)
- `npm run test:i18n` → 2 passed
- `npm run lint` → 0 errors, 1 pre-existing warning
- backend `pytest` raster+tile → 76 passed
- `make openapi-check` → exit 0 (no drift)
- `npm run e2e:smoke:builder` → 26 passed

## Must-haves
- [x] Terrain attaches on fresh load (Map A) — RMODE-01
- [x] Render-as persists across load (no revert) — RMODE-02
- [x] Label indicator derived + i18n + a11y — LABEL-01
- [x] Single point render-as control — POLISH-01
- [x] Hillshade dual-consumer guarded; Map B unaffected — POLISH-02
- [x] Bounded stats cache — HYG-01
- [x] Both maps 0 console errors; all code gates green

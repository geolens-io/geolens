---
phase: 1158-builder-layer-visibility-dem-consolidation
plan: "02"
subsystem: testing
tags: [vitest, maplibre, builder, dem, terrain, visibility, layer-stack, regression-pins]

requires:
  - phase: 1158-01
    provides: BLDR-01/02/03/04 source fixes in map-sync.ts, color-relief-sync.ts, BuilderMap.tsx, UnifiedStackPanel.tsx

provides:
  - BLDR-01 pin: raster basemap not lifted above data at position='top' (UnifiedStackPanel.basemap-drag.test.tsx Test 12)
  - BLDR-02 pin: terrain attaches when demLayer.visible===true, detaches (setTerrain(null)) when visible===false
  - BLDR-03 pin: terrain-mode DEM row suppressed from UnifiedStackPanel stack; hillshade/image rows render
  - BLDR-04 pin: color-relief companion addLayer carries layout.visibility='none'/'visible' from input.visible

affects: [1160-live-playwright-mcp-close-gate]

tech-stack:
  added: []
  patterns:
    - "addLayer mock.calls[0][0] pattern for asserting full layer spec fields (layout.visibility) in vitest"
    - "tileTokenState vi.hoisted override pattern for per-test token fixture injection into BuilderMap"
    - "data-row-id querySelector pattern for asserting visibleStackLayers filter in UnifiedStackPanel DOM"

key-files:
  created:
    - frontend/src/components/builder/__tests__/BuilderMap.terrain-visibility.test.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.dem-rows.test.tsx
  modified:
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx
    - frontend/src/components/builder/__tests__/color-relief-sync.test.ts

key-decisions:
  - "BLDR-02 Test A uses tileTokenState mock to inject a raster token so tokenMap has an entry and the terrain-attach path runs (setTerrain called with source object, not null)"
  - "BLDR-03 tests use data-row-id QuerySelector (same attribute the existing basemap-drag tests query) to confirm row presence/absence in the DOM"
  - "BLDR-02 Tests B and C assert setTerrain(null) via the effectiveTerrainEnabled path — no raster token involvement needed for the null paths"
  - "All four test files no-op production source files; zero source edits in this plan"

patterns-established:
  - "addLayer mock.calls[0][0] full-spec capture: read layout.visibility from the captured argument rather than from a setLayoutProperty call"
  - "UnifiedStackPanel DEM-row tests: reuse the exact harness (mocks + defaultProps) from basemap-drag.test.tsx for any new UnifiedStackPanel row-suppression assertions"

requirements-completed: [BLDR-01, BLDR-02, BLDR-03, BLDR-04]

duration: 10min
completed: 2026-05-30
---

# Phase 1158 Plan 02: BLDR-01/02/03/04 Regression Test Pins Summary

**Vitest pins locking the four Phase 1158 visibility fixes: raster basemap ordering skip (BLDR-01), terrain attach/detach on visibility toggle (BLDR-02), terrain-mode DEM row suppression in the stack (BLDR-03), and color-relief companion layout.visibility threading (BLDR-04)**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-30T18:34:00Z
- **Completed:** 2026-05-30T18:45:00Z
- **Tasks:** 3
- **Files modified/created:** 4

## Accomplishments

- BLDR-01 (Test 12 in basemap-drag.test.tsx): raster-type basemap layers (`type=raster`) are confirmed NOT lifted by `reorderBasemapAboveData` at `position='top'`; non-raster detail layers still lift; data layers never move
- BLDR-04 (2 tests in color-relief-sync.test.ts): `addLayer` mock.calls capture confirms `layout.visibility='none'` when `input.visible===false` and `layout.visibility='visible'` when `input.visible===true`
- BLDR-02 (3 tests in BuilderMap.terrain-visibility.test.tsx): component renders with `setTerrain(null)` when `demLayer.visible===false` (Test B); `setTerrain({ source: TERRAIN_SOURCE_ID })` when visible and a raster token is present (Test A via `tileTokenState` override); `setTerrain(null)` when `terrainConfig.enabled===false` (Test C)
- BLDR-03 (3 tests in UnifiedStackPanel.dem-rows.test.tsx): `[data-row-id="dem-terrain"]` is `null` (suppressed); `[data-row-id="dem-hillshade"]` and `[data-row-id="dem-image"]` are truthy; non-DEM vector rows are unaffected

## Task Commits

1. **Task 1+2: BLDR-01/04 + BLDR-02/03 test pins** - `b7c8ff1a` (test)

## Files Created/Modified

- `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` — added Test 12 in the UX-03 `reorderBasemapAboveData` describe block (BLDR-01 raster-skip pin)
- `frontend/src/components/builder/__tests__/color-relief-sync.test.ts` — added two BLDR-04 tests asserting `layout.visibility` on the addLayer mock call
- `frontend/src/components/builder/__tests__/BuilderMap.terrain-visibility.test.tsx` — new file; 3 component-integration tests for terrain attach/detach on demLayer visibility (BLDR-02)
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.dem-rows.test.tsx` — new file; 3 tests confirming terrain-mode DEM row suppression from the stack (BLDR-03)

## Gate Results

- **`npm run typecheck`:** 0 errors
- **`npm test -- --run` (full vitest):** 241 files passed, 2634 tests passed
- **`e2e:smoke:builder`:** 26/26 passed (builder.spec.ts + builder-styling.spec.ts + builder-v1-5.spec.ts)

## Decisions Made

- Reused the `vi.hoisted` `tileTokenState` pattern from `BuilderMap.a11y.test.tsx` so tests can override the raster token per-test without redefining the module mock
- BLDR-02 Test A uses `tileTokenState.tokens = [{ data: rasterToken, ... }]` so `tokenMap` has an entry and the terrain-attach path in `applyTerrainConfig` runs end-to-end through the component
- BLDR-03 tests use `document.querySelector('[data-row-id="dem-terrain"]')` — the exact same DOM attribute the basemap-drag tests use — to assert row presence/absence deterministically
- Committed Tasks 1 and 2 together in one atomic commit (both are test-only additions with no production code; single commit keeps bisectability clean for this plan)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All four test pins passed on first run. The `tileTokenState` hoisted-mock pattern aligned cleanly with the a11y test recipe and the token shape from `RasterTileToken` matched `applyTerrainConfig`'s expectations without any shim work.

## User Setup Required

None - test-only plan, no external service configuration required.

## Next Phase Readiness

- Phase 1160 Playwright MCP close-gate can verify the four fixes live (QA-01 a/b/c/d items) against the running stack — the vitest pins confirm source-level correctness; MCP confirms end-user visual behavior
- All BLDR-01..04 requirements are pinned and green; the phase is ready for close

## Threat Flags

None. Test-only plan — no new network endpoints, auth surfaces, data egress, or trust boundaries introduced.

## Self-Check: PASSED

- `b7c8ff1a` exists in git log: confirmed
- `frontend/src/components/builder/__tests__/BuilderMap.terrain-visibility.test.tsx` created: confirmed
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.dem-rows.test.tsx` created: confirmed
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` modified: confirmed
- `frontend/src/components/builder/__tests__/color-relief-sync.test.ts` modified: confirmed
- `npm run typecheck`: 0 errors confirmed
- `npm test -- --run`: 241 files, 2634 tests passed confirmed
- `e2e:smoke:builder`: 26/26 passed confirmed

---
*Phase: 1158-builder-layer-visibility-dem-consolidation*
*Completed: 2026-05-30*

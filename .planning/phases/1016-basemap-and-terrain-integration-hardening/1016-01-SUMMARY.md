---
phase: 1016-basemap-and-terrain-integration-hardening
plan: 01
status: complete
completed: 2026-05-12
requirements: [MAPCTL-01, MAPCTL-02, MAPCTL-03, MAPCTL-04, MAPCTL-05]
commits:
  - b20198b5 test(1016): cover basemap modal persistence flow
---

# Phase 1016 Summary: Basemap And Terrain Integration Hardening

## Completed

- Added a browser-level builder smoke flow for Add Dataset basemap persistence:
  - Opens Add Dataset, switches to the Basemap tab, and swaps to `OpenFreeMap Dark`.
  - Confirms the selected row immediately changes from `swap` to `in use`.
  - Confirms the sidebar Basemap group updates to `OpenFreeMap Dark`.
  - Saves through the real builder save path and verifies the API `basemap_style` is `openfreemap-dark`.
  - Reloads the builder and confirms the sidebar still shows the persisted basemap.
  - Verifies data layer identities are unchanged through the basemap style reload/save.
- Kept terrain field-discipline coverage in focused component/unit tests, where DEM source selection, terrain enabled state, exaggeration, and `Use as terrain` behavior are directly asserted.
- Ran a Playwright MCP inspection against the live builder UI to confirm the redesigned Basemap modal and inline Terrain/Basemap rows render correctly with no console warnings or errors.

## Requirement Coverage

- **MAPCTL-01:** Covered by the new browser modal swap/persist test and existing basemap component/unit tests; layer identities remain unchanged.
- **MAPCTL-02:** Covered by existing `MapStackPanel` reset coverage plus builder smoke proving overlay layers survive basemap style reload.
- **MAPCTL-03:** Covered by the new browser test; modal `in use` and sidebar label sync immediately after swap.
- **MAPCTL-04:** Covered by `TerrainControls.test.tsx`, `MapStackPanel.test.tsx`, and `BuilderMap.unit.test.ts`.
- **MAPCTL-05:** Covered by `MapStackPanel.test.tsx` DEM `Use as terrain` behavior.

## Verification

- `npx playwright test e2e/builder.spec.ts --project=chromium -g "swaps basemap from Add Dataset modal"`
  - Result: passed — setup + focused basemap persistence test, 2 total.
- `cd frontend && npm run test -- MapStackPanel DatasetSearchPanel TerrainControls BuilderMap.unit --run`
  - Result: passed — 4 files, 37 tests.
- `npm run e2e:smoke:builder`
  - Result: passed — 24 tests.
- `cd frontend && npm run lint`
  - Result: passed.
- Playwright MCP:
  - Inspected `/maps/0a1c16d4-0c5b-4854-a867-40cdd11dcea3`.
  - Verified inline Terrain controls, Basemap row, Add Dataset Basemap tab, `swap`/`in use` states, and Import data link.
  - Console check: 0 errors, 0 warnings.

## Notes

- No schema, renderer, catalog API, or import workflow changes were made.
- No browser DEM fixture was added; DEM/terrain mutation discipline remains covered by focused tests with deterministic fixtures.

---
phase: 1018-saved-map-roundtrip-and-closeout
plan: 01
status: complete
completed: 2026-05-12
requirements: [ROUND-01, ROUND-02, ROUND-03, ROUND-04]
commits:
  - 3b6110e8 test(1018): cover saved map roundtrip contracts
---

# Phase 1018 Summary: Saved Map Roundtrip And Closeout

## Completed

- Added a browser-level saved-map round-trip test:
  - Edits a layer visibility zoom range to `z2-18`.
  - Saves through the real builder PATCH + PUT path.
  - Verifies API response key sets for map and layer objects are unchanged across save.
  - Verifies persisted `_minzoom` / `_maxzoom` values through API polling.
  - Reloads the builder and confirms the sidebar still shows `z2-18`.
- Added focused builder save coverage for duplicate renderings, basemap config, terrain config, and zoom-range layout writes through existing fields.
- Extended authenticated public and shared-token viewer tests so `terrainConfig` is forwarded to `ViewerMap` alongside existing `basemapConfig` coverage.
- Ran closeout gates and Playwright MCP UI/console inspection.

## Requirement Coverage

- **ROUND-01:** Covered by browser response key stability across save and the full builder smoke.
- **ROUND-02:** Covered by the new zoom-range browser round-trip, Phase 1015 duplicate-rendering browser flow, Phase 1016 basemap save/reload flow, and focused save tests for basemap/terrain config.
- **ROUND-03:** Covered by `PublicMapViewerPage.test.tsx`, `PublicViewerPage.test.tsx`, and existing viewer basemap/runtime tests.
- **ROUND-04:** Covered by this phase summary, verification file, and v1003 milestone audit.

## Verification

- `npx playwright test e2e/builder.spec.ts --project=chromium -g "round-trips layer zoom range"`
  - Result: passed — setup + focused round-trip test, 2 total.
- `cd frontend && npm run test -- use-builder-save PublicMapViewerPage PublicViewerPage --run`
  - Result: passed — 3 files, 36 tests.
- `npm run e2e:smoke:builder`
  - Result: passed — 26 tests.
- `cd frontend && npm run lint`
  - Result: passed.
- `cd frontend && npm run build`
  - Result: passed; existing large `map-vendor` chunk warning remains.
- Playwright MCP:
  - Inspected `/maps/0a1c16d4-0c5b-4854-a867-40cdd11dcea3`.
  - Confirmed Map Stack renders at `1440x900`.
  - Console check: 0 errors, 0 warnings.

## Notes

- No schema, renderer, catalog endpoint, or import workflow changes were made.
- The focused Vitest run emitted the existing jsdom `Not implemented: navigation to another Document` message but exited successfully.
- Broader backend, SDK, CLI, and release packaging gates were not part of v1003.

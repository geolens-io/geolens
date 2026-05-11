---
phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
plan: 05
subsystem: ui
tags: [map-builder, map-stack, terrain, relief, public-viewer, playwright]

# Dependency graph
requires:
  - phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
    provides: Plans 1000-03 and 1000-04 unified the Map Stack inspector, persisted basemap_config, and established z-order policy
provides:
  - Relief-focused Map Stack copy and state for DEM source, terrain exaggeration, and DEM-derived visual relief
  - Builder and public-viewer terrain alignment for raster-token DEM sources and style reloads
  - Builder legend rendering that keeps color and size encodings distinct
  - Playwright MCP screenshot evidence for desktop, tablet, mobile, public, and Grand Canyon relief flows
affects: [map-builder, public-viewer, terrain, legends, visual-qa]

# Tech tracking
tech-stack:
  added: []
  patterns: [surface-versus-relief copy, raster-token terrain source reuse, style-reload terrain reseeding, screenshot-backed responsive QA]

key-files:
  created:
    - .planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/1000-05-SUMMARY.md
    - .planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-desktop-builder-stack.png
    - .planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-public-map-clean.png
    - .planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-grand-canyon-relief-showcase.png
  modified:
    - frontend/src/components/builder/TerrainControls.tsx
    - frontend/src/components/builder/MapStackPanel.tsx
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/components/viewer/hooks/use-viewer-terrain.ts
    - frontend/src/components/map-widgets/builtin/LegendWidget.tsx

key-decisions:
  - "Keep DEM terrain described as an elevation surface and use Relief for DEM-derived visual overlays."
  - "Use raster-token DEM source metadata in both builder and public viewer so terrain survives style reloads consistently."
  - "Validate public marketing output with a temporary QA map because the local demo seed was not present."

patterns-established:
  - "Terrain readiness is observable in the public viewer through data-terrain-ready for browser-level validation."
  - "Visual QA records screenshot paths and nonblank image checks alongside automated lint, unit, and Playwright gates."

requirements-completed: [MAPSTACK-04, MAPSTACK-06, MAPSTACK-07]

# Metrics
duration: 23min
completed: 2026-05-11
---

# Phase 1000 Plan 05: Relief and Marketing Output Summary

**Relief-focused Map Stack polish with aligned builder/public terrain rendering and responsive Playwright MCP evidence.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-05-11T13:52:24Z
- **Completed:** 2026-05-11T14:15:00Z
- **Tasks:** 5 completed
- **Files modified:** 16

## Accomplishments

- Clarified the Surface and Relief stack groups so DEM source, exaggeration, and visual relief state are visible without implying DEM is a paint layer.
- Aligned builder and public viewer terrain behavior around raster-token DEM sources, terrain source bounds, and style reload reapplication.
- Kept builder legend output cleaner by rendering graduated point size and color legends as separate groups instead of merging encodings.
- Captured Playwright MCP desktop, tablet, mobile, public-map, and Grand Canyon relief screenshots, then verified the PNGs are nonblank.
- Ran final lint, focused Vitest, and focused Playwright gates with no new layer-management failures.

## Task Commits

Each implementation task was committed atomically where feasible:

1. **Task 1: Improve terrain and relief affordances in the Map Stack** - `bf5d2ccd` (feat)
2. **Task 2: Ensure viewer and builder terrain behavior stay aligned** - `8df84429` (feat)
3. **Task 3: Clean thumbnail and legend behavior for marketing output** - `ca810757` (fix)

**Plan metadata:** this summary, STATE, and ROADMAP are staged together in the final metadata commit.

## Files Created/Modified

- `frontend/src/components/builder/TerrainControls.tsx` - Relief-focused terrain copy, selected DEM state, exaggeration state, and visual relief count.
- `frontend/src/components/builder/MapStackPanel.tsx` - Surface/Relief stack summaries that distinguish elevation surface from visual relief overlays.
- `frontend/src/components/builder/__tests__/TerrainControls.test.tsx` and `frontend/src/components/builder/__tests__/MapStackPanel.test.tsx` - Focused coverage for the new stack affordances.
- `frontend/src/components/builder/BuilderMap.tsx` and `frontend/src/components/builder/map-sync.ts` - Terrain source metadata, style reload alignment, and map z-order cleanup.
- `frontend/src/components/builder/layer-adapters/types.ts` - Adapter input bounds metadata needed by terrain-aware map sync.
- `frontend/src/components/viewer/ViewerMap.tsx` and `frontend/src/components/viewer/hooks/use-viewer-terrain.ts` - Public viewer DEM token use, style reload reapplication, and `data-terrain-ready` validation signal.
- `frontend/src/components/viewer/__tests__/use-viewer-terrain.test.ts` - Viewer terrain source and reload coverage.
- `frontend/src/pages/PublicViewerPage.tsx` and `frontend/src/pages/PublicMapViewerPage.tsx` - Viewer callsite alignment after terrain/basemap ownership moved into `ViewerMap`.
- `frontend/src/components/map-widgets/builtin/LegendWidget.tsx` - Separate size/color legend entries for graduated point styling.
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/1000-05-SUMMARY.md` - This closeout record.

## Decisions Made

- Used status copy and badges instead of adding more controls, because the plan needed clarity about what terrain/relief means rather than a new persisted option.
- Kept public terrain behavior inside `ViewerMap` and its terrain hook so public saved maps do not depend on builder-only wiring.
- Treated screenshot evidence as ignored planning output: paths are recorded here, but the PNG files remain out of git unless explicitly requested later.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added terrain bounds metadata to adapter input**
- **Found during:** Task 2 (terrain alignment)
- **Issue:** `map-sync` needed typed bounds metadata for terrain-aware source setup, but `AdapterLayerInput` did not expose it.
- **Fix:** Added optional `bounds` to `frontend/src/components/builder/layer-adapters/types.ts`.
- **Files modified:** `frontend/src/components/builder/layer-adapters/types.ts`
- **Verification:** `cd frontend && npm run test -- use-viewer-terrain BuilderMap --run`; final focused Vitest command passed.
- **Committed in:** `8df84429`

**2. [Rule 1 - Bug] Updated public viewer callsites for terrain/basemap ownership**
- **Found during:** Task 2 (viewer alignment)
- **Issue:** `ViewerMap` no longer accepted the previous basemap override path after terrain and basemap source ownership moved into the component.
- **Fix:** Updated `PublicViewerPage.tsx` and `PublicMapViewerPage.tsx` callsites to match the new `ViewerMap` contract.
- **Files modified:** `frontend/src/pages/PublicViewerPage.tsx`, `frontend/src/pages/PublicMapViewerPage.tsx`
- **Verification:** `cd frontend && npm run test -- use-viewer-terrain BuilderMap --run`; final Playwright run passed.
- **Committed in:** `8df84429`

---

**Total deviations:** 2 auto-fixed (1 Rule 3 blocking, 1 Rule 1 bug)
**Impact on plan:** Both fixes were required for typed terrain source alignment and working public viewer callsites. No unrelated dirty work was staged.

## Issues Encountered

- Local demo maps were not seeded, so the plan-created QA map was used for Playwright MCP visual validation. Temporary artifacts were written under `/tmp/geolens-1000-05-visual/`; the map id was `dfbe4fd8-56a0-46d0-a155-3256d2c35d37`.
- `npx playwright test e2e/demo-smoke.spec.ts --project=chromium --reporter=line` skipped the 5 demo-map checks because `E2E_DEMO_SEEDED` was absent. The setup test passed.
- The final focused Playwright run also skipped those same 5 seeded-demo checks and passed the builder specs.
- The worktree contained substantial unrelated dirty backend/frontend/generated changes before this plan. Only plan-owned files and narrow blocking callsite/type fixes were staged.

## User Setup Required

None - no external service configuration required.

## Visual QA Evidence

Playwright MCP was available and used. Screenshots were captured in:

- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-desktop-builder-stack.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-desktop-builder-inspector.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-tablet-builder-stack.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-mobile-builder-stack.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-mobile-builder-inspector.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-public-map-clean.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-grand-canyon-relief-showcase.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-tablet-public-map-clean.png`
- `.planning/phases/1000-kepler-inspired-map-stack-and-basemap-layer-controls/visual-qa/1000-05-mobile-public-map-clean.png`

The public map clean screenshots were captured with `?legend=false`; browser validation reported `data-tiles-loaded="true"`, `data-terrain-ready="true"`, and zero visible legend buttons. A PIL nonblank check confirmed all nine PNGs had expected dimensions and high color variation.

## Verification

- `cd frontend && npm run test -- TerrainControls MapStackPanel --run` - passed, 2 files / 7 tests.
- `cd frontend && npm run test -- use-viewer-terrain BuilderMap --run` - passed, 2 files / 21 tests.
- `npx playwright test e2e/demo-smoke.spec.ts --project=chromium --reporter=line` - passed setup, 5 seeded-demo checks skipped.
- `cd frontend && npm run test -- use-builder-save --run` - passed, 1 file / 31 tests.
- `cd frontend && npm run lint` - passed.
- `cd frontend && npm run test -- TerrainControls MapStackPanel BuilderMap use-viewer-terrain --run` - passed, 4 files / 28 tests.
- `E2E_BASE_URL=http://127.0.0.1:5173 npx playwright test e2e/builder.spec.ts e2e/demo-smoke.spec.ts --project=chromium --reporter=line` - passed, 17 tests; 5 seeded-demo checks skipped.

## Next Phase Readiness

Phase 1000 is complete. The Map Stack now has the unified stack model, persisted basemap appearance, explicit z-order policy, terrain/relief clarity, public-viewer terrain alignment, and responsive screenshot evidence needed for follow-on saved-map or demo-showcase work.

---
*Phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls*
*Completed: 2026-05-11*

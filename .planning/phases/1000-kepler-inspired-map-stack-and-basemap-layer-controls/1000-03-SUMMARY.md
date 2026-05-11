---
phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
plan: 03
subsystem: ui
tags: [map-builder, map-stack, sidebar, inspector, i18n, playwright]

# Dependency graph
requires:
  - phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
    provides: Plan 1000-01 layer-management bug fixes and Plan 1000-02 pure Map Stack model
provides:
  - Unified Map Stack sidebar panel for Surface, Relief, Basemap, Data, Labels, and Interactions
  - Sidebar-local layer inspector shared by desktop and mobile builder paths
  - Primary layer rows with existing layer actions preserved
  - Builder locale strings for new Map Stack labels and badges
affects: [map-builder, layer-management, basemap-controls, terrain-controls, layer-inspector]

# Tech tracking
tech-stack:
  added: []
  patterns: [MapStackPanel shell over buildMapStack, sidebar-local inspector mode, primary layer row compatibility IDs]

key-files:
  created:
    - frontend/src/components/builder/MapStackPanel.tsx
    - frontend/src/components/builder/MapStackSection.tsx
    - frontend/src/components/builder/MapStackItem.tsx
    - frontend/src/components/builder/__tests__/MapStackPanel.test.tsx
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/de/builder.json

key-decisions:
  - "Use the Plan 1000-02 buildMapStack helper as the source of sidebar group and row metadata."
  - "Render layer editing inside the existing sidebar/sheet instead of adding a second desktop flyout over the map."
  - "Preserve legacy layer row test IDs and the Expand options accessible name while moving rows into the Map Stack."

patterns-established:
  - "MapStackPanel owns stack composition, grouped section rendering, and basemap/terrain/widget placement."
  - "Primary data and relief rows preserve visibility, reorder, rename, legend, zoom, dataset, remove, and inspector actions."
  - "Non-primary stack rows can expose focused controls such as basemap-label toggles without duplicating full layer menus."

requirements-completed: [MAPSTACK-01, MAPSTACK-02, MAPSTACK-05]

# Metrics
duration: 19min
completed: 2026-05-11
---

# Phase 1000 Plan 03: Unified Map Stack Inspector Summary

**Unified Map Stack sidebar with grouped map ingredients and a single sidebar-local layer inspector.**

## Performance

- **Duration:** 19 min
- **Started:** 2026-05-11T12:48:10Z
- **Completed:** 2026-05-11T13:07:15Z
- **Tasks:** 4 completed
- **Files modified:** 9

## Accomplishments

- Added `MapStackPanel`, `MapStackSection`, and `MapStackItem` over `buildMapStack`, grouping Surface, Relief, Basemap, Data, Labels, and Interactions.
- Replaced the builder's separate Layers / Basemap / Terrain sidebar blocks with one Map Stack panel while preserving widget sidebar placement.
- Moved desktop layer editing into the sidebar inspector model already used on mobile, removing the permanent map-width-consuming flyout.
- Preserved existing primary layer actions: add, visibility, reorder, rename, legend toggle, zoom to layer, open dataset, remove, and inspector open/back.
- Added Map Stack locale strings in English, Spanish, French, and German.

## Task Commits

Each task was committed atomically where file overlap allowed:

1. **Task 1: Build grouped Map Stack components** - `6756149c` (feat)
2. **Task 1 compatibility fix from browser verification** - `39ac8689` (fix)
3. **Tasks 2 and 3: Wire sidebar and single inspector mode** - `383e1f55` (feat)
4. **Task 4: Localize stack language** - `d257330d` (feat)

## Files Created/Modified

- `frontend/src/components/builder/MapStackPanel.tsx` - Unified stack shell, group rendering, drag context, basemap/terrain/widget placement.
- `frontend/src/components/builder/MapStackSection.tsx` - Compact section header and entry-count wrapper.
- `frontend/src/components/builder/MapStackItem.tsx` - Stable stack row with badges, icons, layer controls, and inspector entry points.
- `frontend/src/components/builder/__tests__/MapStackPanel.test.tsx` - Render and interaction coverage for grouped stack UI.
- `frontend/src/pages/MapBuilderPage.tsx` - Sidebar wiring and desktop/mobile shared inspector rendering.
- `frontend/src/i18n/locales/{en,es,fr,de}/builder.json` - Map Stack labels, badges, and actions.

## Decisions Made

- Kept basemap and terrain controls inside the Map Stack rather than creating separate top-level sidebar sections.
- Used "Place labels" for the visible basemap-label row so `Basemap` remains a unique visible section heading for existing E2E selectors.
- Combined Tasks 2 and 3 in one source commit because both changes are the same `SidebarContent` refactor in `MapBuilderPage.tsx`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved existing E2E row and button contracts**
- **Found during:** Task 3 (browser verification)
- **Issue:** The new rows initially used `map-stack-item` test IDs and "Open inspector" as the edit button name. Existing builder E2E expects primary layer rows under `layer-item-*` and opens editors with "Expand options".
- **Fix:** Primary layer rows now keep `layer-item-{id}` test IDs and use the existing `layerItem.expandOptions` accessible name.
- **Files modified:** `frontend/src/components/builder/MapStackItem.tsx`, `frontend/src/components/builder/__tests__/MapStackPanel.test.tsx`
- **Verification:** `cd frontend && npm run test -- MapStackPanel MapBuilderPage --run`; `E2E_BASE_URL=http://127.0.0.1:5173 npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line`
- **Committed in:** `39ac8689`

**2. [Rule 1 - Bug] Kept Basemap as unique visible text for strict Playwright lookup**
- **Found during:** Task 3 (browser verification)
- **Issue:** Visible row labels such as "Basemap preset", "Basemap labels", and "Basemap foundation" made `page.getByText('Basemap')` ambiguous.
- **Fix:** Non-primary stack rows no longer show order labels, and visible basemap row titles are "Preset" and "Place labels"; basemap-label semantics remain in aria/actions and locale keys.
- **Files modified:** `frontend/src/components/builder/MapStackItem.tsx`, builder locale JSON files
- **Verification:** `E2E_BASE_URL=http://127.0.0.1:5173 npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line`
- **Committed in:** `39ac8689`, `d257330d`

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes preserve existing builder test contracts without changing API, persistence, or renderer behavior.

## Issues Encountered

- The exact Playwright command `npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line` targeted the stale Docker frontend at `localhost:8080` and failed the known collapsed-basemap-options assertion before validating workspace code.
- Running Vite without `API_PROXY_TARGET` proxied to inactive `localhost:8000`, so auth setup failed. The local API container is published on `localhost:8001`; rerunning Vite with `API_PROXY_TARGET=http://localhost:8001` fixed the proxy.
- Vitest emitted the existing warning ``--localstorage-file` was provided without a valid path`; targeted tests still passed.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd frontend && npm run test -- MapStackPanel --run` - passed, 1 file / 3 tests.
- `cd frontend && npm run test -- MapBuilderPage MapStackPanel --run` - passed, 2 files / 4 tests.
- `cd frontend && npm run lint` - passed.
- `npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line` - attempted against stale Docker frontend; failed 1 test after 9 passed / 7 did not run.
- `API_PROXY_TARGET=http://localhost:8001 npm run dev -- --host 127.0.0.1` plus `E2E_BASE_URL=http://127.0.0.1:5173 npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line` - passed, 17 tests.

## Next Phase Readiness

Plan 1000-03 is complete. Plan 1000-04 can add persisted basemap appearance controls and explicit renderer z-order policy on top of the unified Map Stack shell. Backend/API files for 1000-04 were not edited or staged.

---
*Phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls*
*Completed: 2026-05-11*

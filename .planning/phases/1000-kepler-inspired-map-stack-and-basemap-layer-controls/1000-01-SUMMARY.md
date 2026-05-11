---
phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
plan: 01
subsystem: ui
tags: [map-builder, mobile, basemap, filters, labels, playwright]

# Dependency graph
requires:
  - phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
    provides: UX audit findings and current split layer/sidebar implementation
provides:
  - Mobile layer editor reachability from the sidebar sheet
  - Hidden collapsed basemap options
  - Narrow-friendly filter condition layout
  - Distinguishable layer row metadata and named label switches
  - Focused builder E2E coverage for the fixed blockers
affects: [map-builder, layer-management, basemap-controls, layer-editor, e2e]

# Tech tracking
tech-stack:
  added: []
  patterns: [Mobile sheet inspector reuse, conditional disclosure rendering, two-row filter condition layout, E2E temporary dataset fallback]

key-files:
  created: []
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/BasemapPicker.tsx
    - frontend/src/components/builder/LayerFilterEditor.tsx
    - frontend/src/components/builder/LayerItem.tsx
    - frontend/src/components/builder/LabelEditor.tsx
    - frontend/src/components/builder/__tests__/BasemapPicker.test.tsx
    - frontend/src/components/builder/__tests__/LayerFilterEditor.test.ts
    - frontend/src/components/builder/__tests__/LayerPanel.test.tsx
    - frontend/src/components/builder/__tests__/LabelEditor.test.tsx
    - e2e/builder.spec.ts

key-decisions:
  - "Preserve the desktop flyout for this plan and reuse LayerEditorPanel inside the mobile sheet."
  - "Unmount collapsed basemap options instead of relying on grid-row animation."
  - "Disambiguate duplicate layer rows with type and stack-position metadata without renaming persisted layer data."
  - "Let builder E2E create a temporary vector dataset when the local catalog is empty."

patterns-established:
  - "Mobile layer editing uses the same handlers and tabbed panel as desktop with a sheet-local back action."
  - "Disclosure contents that must be inaccessible when collapsed are conditionally rendered."
  - "Filter condition controls reserve a full row for the field selector in narrow inspectors."

requirements-completed: [MAPSTACK-01, MAPSTACK-05, MAPSTACK-07]

# Metrics
duration: 14min
completed: 2026-05-11
---

# Phase 1000-01: Layer-Management UX Blocker Summary

**Mobile layer editing, basemap disclosure hiding, readable filter rows, duplicate-layer row metadata, and focused builder regressions.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-11T12:29:16Z
- **Completed:** 2026-05-11T12:43:40Z
- **Tasks:** 5 completed
- **Files modified:** 10

## Accomplishments

- Mobile users can open a layer editor from the sidebar sheet, use Style/Filter/Labels/Popup tabs, and return to the layer list.
- Collapsed basemap options are unmounted, so they are not visible, tabbable, hit-testable, or exposed to assistive tech.
- Filter conditions now keep the field selector readable at inspector width.
- Duplicate dataset layers show type and stack-position badges, and label switches have explicit accessible names.
- Builder E2E now covers collapsed basemap options, mobile editor reachability, and filter layout readability.

## Task Commits

Each task was committed atomically:

1. **Task 1: Make the mobile layer editor reachable** - `31f92286` (feat)
2. **Task 2: Fix collapsed basemap visibility and accessibility** - `2786f9a9` (fix)
3. **Task 3: Make filter rows readable in the inspector width** - `111638bc` (fix)
4. **Task 4: Add duplicate-layer disambiguation and switch labels** - `72d7eaca` (fix)
5. **Task 5: Add targeted Playwright coverage for the blockers** - `c1ddb14e` (test)

## Files Created/Modified

- `frontend/src/pages/MapBuilderPage.tsx` - Renders `LayerEditorPanel` inside the mobile sheet when a layer is expanded.
- `frontend/src/components/builder/BasemapPicker.tsx` - Conditionally renders basemap options only while expanded.
- `frontend/src/components/builder/LayerFilterEditor.tsx` - Uses a field row plus controls row for each visual condition.
- `frontend/src/components/builder/LayerItem.tsx` - Adds layer kind and stack-position metadata to visible row text and aria labels.
- `frontend/src/components/builder/LabelEditor.tsx` - Adds accessible names to label enable and allow-overlap switches.
- `frontend/src/components/builder/__tests__/BasemapPicker.test.tsx` - Asserts collapsed options are absent.
- `frontend/src/components/builder/__tests__/LayerFilterEditor.test.ts` - Covers the two-row condition structure.
- `frontend/src/components/builder/__tests__/LayerPanel.test.tsx` - Covers duplicate layer row metadata.
- `frontend/src/components/builder/__tests__/LabelEditor.test.tsx` - Covers switch accessible names.
- `e2e/builder.spec.ts` - Adds focused coverage for the three high-risk builder blockers.

## Decisions Made

- Kept the desktop layer editor flyout unchanged so Plan 1000-03 can replace the inspector deliberately.
- Used unmounting for collapsed basemap options because it is simpler and stronger than clipped hidden content for keyboard and accessibility behavior.
- Used stable row metadata badges instead of auto-renaming duplicate layers, avoiding persisted data churn.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added accessible names to filter Select triggers**
- **Found during:** Task 3 (filter layout test)
- **Issue:** `aria-label` on the Radix `Select` root did not name the trigger, so field/operator comboboxes were unnamed in the accessibility tree.
- **Fix:** Added `aria-label` to the field and operator `SelectTrigger` elements.
- **Files modified:** `frontend/src/components/builder/LayerFilterEditor.tsx`
- **Verification:** `cd frontend && npm run test -- LayerFilterEditor --run`
- **Committed in:** `111638bc`

**2. [Rule 3 - Blocking] Made builder E2E resilient to an empty local catalog**
- **Found during:** Task 5 (Playwright verification)
- **Issue:** The local stack had zero datasets, so `builder.spec.ts` could not create its test map layer.
- **Fix:** Added a temporary GeoJSON upload/commit fallback and cleanup path when no existing dataset is available.
- **Files modified:** `e2e/builder.spec.ts`
- **Verification:** `E2E_BASE_URL=http://localhost:5173 npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line`
- **Committed in:** `c1ddb14e`

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 blocking)
**Impact on plan:** Both fixes support the planned UX regression coverage without changing API or persistence behavior.

## Issues Encountered

- The exact default Playwright command initially hit the Docker frontend on `localhost:8080`, which was a stale built image and still showed mounted collapsed basemap options. The same spec passed against the workspace code via Vite on `localhost:5173`.
- The local catalog was empty, so the E2E setup now creates and deletes a tiny temporary vector dataset when needed.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd frontend && npm run test -- MapBuilderPage LayerPanel --run` - passed, 2 files / 6 tests.
- `cd frontend && npm run test -- BasemapPicker --run` - passed, 1 file / 5 tests.
- `cd frontend && npm run test -- LayerFilterEditor --run` - passed, 1 file / 19 tests.
- `cd frontend && npm run test -- LayerPanel LabelEditor --run` - passed, 2 files / 12 tests.
- `cd frontend && npm run lint` - passed.
- `cd frontend && npm run test -- BasemapPicker LayerFilterEditor LayerPanel LabelEditor --run` - passed, 4 files / 36 tests.
- `npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line` - attempted against stale Docker frontend; failed before validating workspace code.
- `E2E_BASE_URL=http://localhost:5173 npx playwright test e2e/builder.spec.ts --project=chromium --reporter=line` - passed, 17 tests.

## Next Phase Readiness

Plan 1000-01 blockers are closed. Plan 1000-02 is already present as complete in local planning state, so Plan 1000-03 can use both the unblocked layer-management UI and the pure Map Stack model.

---
*Phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls*
*Completed: 2026-05-11*

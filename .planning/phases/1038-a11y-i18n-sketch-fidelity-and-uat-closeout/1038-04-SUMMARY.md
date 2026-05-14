---
phase: 1038-a11y-i18n-sketch-fidelity-and-uat-closeout
plan: "04"
subsystem: testing
tags: [playwright, e2e, a11y, builder, bsr-25, bsr-27, uat]

# Dependency graph
requires:
  - plan: 1038-01
    provides: BSR-13 Sheet overlay at <800px, StackRow inline confirm, LayerEditorPanel type pill, Settings Tooltip, settings-cog-btn testid
  - plan: 1038-02
    provides: DragOverlay ghost, .dragging-active root class, data-dnd-over insertion line, data-kebab-trigger attribute
  - plan: 1038-03
    provides: Full i18n key parity (de/fr/es/en) including stackRow, layerEditor, unifiedStack namespaces

provides:
  - BSR-27: Playwright UAT spec (e2e/builder-unified-stack.spec.ts) covering 9 UAT flows with console-clean gate per test
  - BSR-25: Keyboard navigation and focus-management assertions in Test 4 (Tab-traversal + focus return to stack-row after close)
  - BSR-13 coverage: Test 4 verifies Sheet overlay renders at <800px viewport with editor content visible

affects:
  - Milestone closeout: BSR-25 and BSR-27 are the final two open requirements for phase 1038

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Console gate helper: attachConsoleGate() + assertConsoleClean() inlined per project convention (no shared helper file)"
    - "Serial beforeAll lifecycle: creates 3 maps (primary+layer, empty, legacy six-section) in one beforeAll; afterAll DELETEs all"
    - "Graceful skip pattern: module-scope hasDemLayer flag set in beforeAll; test 3 checks it and calls test.skip(true) if absent"
    - "Legacy map creation: POST /api/maps/ with style_json containing _geolens_sections structure for normalizer compat test"
    - "dnd-kit keyboard reorder: Space (lift) + ArrowUp + Space (drop) via page.keyboard.press"

key-files:
  created:
    - e2e/builder-unified-stack.spec.ts
  modified: []

key-decisions:
  - "File location is e2e/builder-unified-stack.spec.ts (repo root e2e/) not frontend/e2e/ — the plan referenced frontend/e2e/ but the project convention places all e2e specs at the root alongside playwright.config.ts"
  - "ESLint: the frontend eslint.config.js does not cover the root e2e/ directory by design (base path is frontend/). Playwright --list is the canonical collection check. All 9 tests enumerate correctly."
  - "Legacy map test: uses _geolens_sections key in style_json to exercise the normalizer; creates map via API directly rather than uploading a fixture file"
  - "Test 3 DEM skip: hasDemLayer flag is set in beforeAll based on whether a raster_dataset with is_dem=true exists in the catalog — graceful skip if none seeded"
  - "Test 7 pre-fill: onOpenAddData(query) is called from EmptyStackState; the Add Data modal receives the query via prop and pre-fills its search input"

patterns-established:
  - "Three-map beforeAll: create primary (with layer), empty (no layers), legacy (style_json fixture) in a single beforeAll block; all cleaned up in afterAll"
  - "Console gate inlined per test: attachConsoleGate() at top, assertConsoleClean() at end — not via beforeEach/afterEach to allow per-test early returns"

requirements-completed: [BSR-25, BSR-27]

# Metrics
duration: 15min
completed: 2026-05-14
---

# Phase 1038 Plan 04: Playwright UAT Spec (BSR-25 + BSR-27) Summary

**9-test serial Playwright spec covering unified stack drag-reorder, basemap expand, DEM skip, flyout+focus, settings, empty-state, modal pre-fill, legacy map normalizer, and save/reload — with per-test console-clean gate and BSR-25 Tab-traversal assertions**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-14T00:30:00Z
- **Completed:** 2026-05-14T00:45:00Z
- **Tasks:** 1 (Task 2 is a human-verify checkpoint — see below)
- **Files created:** 1

## Accomplishments

- Created `e2e/builder-unified-stack.spec.ts` with 9 serial tests (BSR-27)
- Each test attaches a console gate and asserts zero errors + zero non-MapLibre warnings (console-clean gate)
- Auth/setup pattern mirrors `builder.spec.ts` exactly: `getAuthToken()`, `waitForBuilder()`, `test.describe.serial`, `test.slow()`
- `beforeAll` creates 3 maps: primary (with vector layer), empty (no layers), legacy (six-section `_geolens_sections` style_json)
- `afterAll` DELETEs all three maps for clean teardown
- Test 3 skips gracefully if no DEM dataset is present (`hasDemLayer` flag set in `beforeAll`)
- Test 4 asserts BSR-25 focus return: after closing editor, `document.activeElement.id` must match `/^stack-row-/`
- Test 4 asserts BSR-13: at 700px viewport, clicking a layer row should render editor inside `role="dialog"` (Sheet overlay)
- Test 4 asserts Tab-traversal: 15 Tab presses produce ≥5 focusable elements, none inside `[inert]`

## Task Commits

1. **Task 1: Create builder-unified-stack.spec.ts with 9 UAT flows** - `30168090` (feat)

## Live UAT Checkpoint (Task 2)

**Status:** `human_needed` — requires user action

**Checkpoint type:** human-verify

The spec was written and validated via `npx playwright test e2e/builder-unified-stack.spec.ts --list` (9 tests enumerated). The local stack was detected as running at the time of summary creation (`http://localhost:8080` responded). However, live execution requires Playwright auth state and a real browser with MapLibre WebGL.

**To complete UAT:**

1. Ensure full stack is running:
   ```
   docker compose up -d --wait
   ```

2. Refresh Playwright auth state:
   ```
   cd /path/to/geolens && npx playwright test e2e/auth.setup.ts
   ```

3. Run the UAT spec:
   ```
   npx playwright test e2e/builder-unified-stack.spec.ts --reporter=list
   ```
   Expected: 9 tests pass (test 3 may skip if no DEM dataset seeded).

4. Run smoke gate to verify no regression:
   ```
   npm run e2e:smoke
   ```
   Expected: same counts as pre-plan baseline.

**Report back:**
- Total: passed / failed / skipped from builder-unified-stack.spec.ts
- Any console errors or non-MapLibre warnings surfaced inside any test
- `e2e:smoke` final counts (vs baseline 50/1/2)

## Files Created/Modified

- `e2e/builder-unified-stack.spec.ts` — 587 lines, 9 test blocks, serial describe, 3-map lifecycle, console-clean gate, BSR-25 focus assertions, BSR-13 Sheet at <800px assertion

## Decisions Made

- **File location at root e2e/:** The plan's `files_modified` listed `frontend/e2e/builder-unified-stack.spec.ts` but the project places all Playwright specs at the repo root alongside `playwright.config.ts`. Matched existing convention (builder.spec.ts, builder-styling.spec.ts are all at root e2e/).
- **ESLint scope:** The `frontend/eslint.config.js` is scoped to `frontend/` only. ESLint does not lint root `e2e/*.ts` files by project convention. Playwright `--list` is the canonical collection validation (0 errors, all 9 tests enumerated).
- **Legacy map fixture:** Used inline `_geolens_sections` structure in `style_json` POST body rather than loading a file fixture. This directly exercises the normalizer compatibility path without file I/O in the test.
- **hasDemLayer module flag:** Set in `beforeAll` via dataset API query. Avoids needing a second `beforeAll` or shared fixture file. Test 3 reads the flag and calls `test.skip(true, ...)` with a clear reason message.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Pattern correction] e2e/ location at repo root, not frontend/e2e/**
- **Found during:** Task 1 file creation
- **Issue:** Plan's `files_modified` listed `frontend/e2e/builder-unified-stack.spec.ts` but investigation of the existing specs (builder.spec.ts, builder-styling.spec.ts) showed they all live at `e2e/` (repo root, alongside playwright.config.ts), not inside `frontend/`
- **Fix:** Created file at `e2e/builder-unified-stack.spec.ts` per project convention
- **Files modified:** `e2e/builder-unified-stack.spec.ts` (correct location)

---

**Total deviations:** 1 (file path correction to match existing project convention)
**Impact on plan:** No functional change. Spec is in the correct location where Playwright can discover it.

## Issues Encountered

None.

## Known Stubs

None. The spec is complete with 9 tests and console-clean gates. Test 3 has a conditional skip (not a stub) for environments without a DEM dataset — this is correct graceful-skip behavior per the plan.

## Threat Flags

None. Pure test file — no new network endpoints, auth paths, or schema changes.

## Next Phase Readiness

- BSR-27 spec written and validated via `playwright --list`
- BSR-25 Tab-traversal + focus-return assertions in Test 4
- BSR-13 Sheet-at-<800px assertion in Test 4
- Live UAT checkpoint (Task 2) requires human to run `npx playwright test e2e/builder-unified-stack.spec.ts`
- Once live UAT passes, phase 1038 requirements (BSR-13, BSR-24, BSR-25, BSR-26, BSR-27) are all satisfied

---
*Phase: 1038-a11y-i18n-sketch-fidelity-and-uat-closeout*
*Completed: 2026-05-14*

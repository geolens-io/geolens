---
phase: 1044-cross-cutting-closeout
plan: "02"
subsystem: testing
tags: [a11y, accessibility, aria, vitest, keyboard, mapbuilder, dnd-kit]

requires:
  - phase: 1040-drag-from-catalog-into-stack
    provides: aria-live announcement region (MapBuilderPage), drag handlers with announce() calls
  - phase: 1041-multi-layer-selection-and-bulk-ops
    provides: UnifiedStackPanel listbox ARIA wiring (role, aria-multiselectable, data-row-id, Shift+Arrow handler)
  - phase: 1043-error-empty-states-and-ia-cleanup
    provides: destructive-confirm autoFocus-on-Cancel (BulkActionBar, LayerEditorPanel, FolderGroupRow)

provides:
  - 8-test vitest a11y suite pinning UnifiedStackPanel listbox contract (role, multiselectable, label, keyboard nav)
  - 2-test vitest suite pinning MapBuilderPage aria-live region presence and initial state
  - 1044-A11Y-WALKTHROUGH.md: reusable manual UAT script for keyboard-only drag + multi-select flows

affects: [1044-03-playwright-e2e]

tech-stack:
  added: []
  patterns:
    - "a11y test focus: focus the role=option (tabIndex=0) inner row, not the outer data-row-id wrapper, before firing Shift+Arrow"
    - "MapBuilderPage full-render with mocked hooks reuses header-actions.test.tsx mock chain"
    - "Tests 3-6 (announcement content) deferred to e2e when dnd-kit PointerSensor internals block JSDOM triggering"

key-files:
  created:
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx
    - frontend/src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx
    - .planning/phases/1044-cross-cutting-closeout/1044-A11Y-WALKTHROUGH.md
  modified: []

key-decisions:
  - "Task 2 used Option B (full MapBuilderPage render) — no source extraction to preserve no-source-modification constraint"
  - "Tests 3-6 (drag announcement content) deferred to e2e spec (Plan 03); JSDOM cannot trigger dnd-kit PointerSensor at distance>=8px"
  - "Shift+Arrow tests focus document.getElementById('stack-row-{id}') (role=option, tabIndex=0) not querySelector('[data-row-id]') (outer wrapper, no tabIndex)"

requirements-completed:
  - POL-23

duration: 18min
completed: 2026-05-15
---

# Phase 1044 Plan 02: a11y Verification + Keyboard Walkthrough Doc Summary

**Vitest pinning of UnifiedStackPanel listbox ARIA contract (8 tests) + MapBuilderPage aria-live region presence (2 tests) + reusable keyboard-only walkthrough for drag-from-catalog and multi-select bulk delete**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-15T22:43:00Z
- **Completed:** 2026-05-15T23:01:00Z
- **Tasks:** 3
- **Files modified:** 3 created

## Accomplishments

- 8-test `UnifiedStackPanel.a11y.test.tsx` pins: `role="listbox"` + `aria-label` resolution (Test 1), `aria-multiselectable="true"` (Test 2), `data-row-id` on all overlay rows (Test 3), Shift+ArrowDown fires `onShiftClick` (Test 4), Shift+ArrowUp clamped at top = no-op (Test 5), Escape clears selection (Test 6), outside-mousedown clears (Test 7), basemap row `aria-selected` isolation (Test 8).
- 2-test `MapBuilderPage.a11y.test.tsx` pins: aria-live region DOM presence with all required attributes (Test 1), initial state empty (Test 2).
- `1044-A11Y-WALKTHROUGH.md` authored with three walkthroughs (drag-from-catalog, multi-select bulk delete, section transitions), exact screen-reader announcement strings from `a11y.*` i18n keys, source-of-truth file:line references, and known-limitations section.
- Builder vitest suite grew from 764 (Phase 1041-04 baseline) to 799 passing tests; 0 failures, 0 worker errors.

## Task Commits

1. **Task 1: Pin the listbox + multi-select a11y contract (vitest)** — `cc850d5d` (test)
2. **Task 2: Pin the drag-from-catalog aria-live announcement contract (vitest)** — `dcabdf06` (test)
3. **Task 2 lint fix: remove unused screen import** — `a01011d2` (fix)
4. **Task 3: Author the keyboard-only walkthrough document** — `c0f70144` (docs)

## Files Created/Modified

- `frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx` — 8 tests for listbox ARIA + Shift+Arrow + Escape + outside-mousedown + basemap isolation
- `frontend/src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx` — 2 tests for aria-live region presence + initial state; Tests 3-6 deferred to e2e
- `.planning/phases/1044-cross-cutting-closeout/1044-A11Y-WALKTHROUGH.md` — step-by-step keyboard walkthroughs for Walkthrough A (drag-from-catalog), B (multi-select bulk delete), C (section transitions)

## Decisions Made

1. **Deferred Tests 3-6 (announcement content) to e2e.** JSDOM cannot trigger dnd-kit's `PointerSensor` with `activationConstraint: distance >= 8px`, so `handleDragStart`/`End`/`Cancel` cannot be invoked from vitest. The e2e spec in Plan 03 covers these paths at full browser fidelity.
2. **No source modifications.** The plan explicitly prohibited modifying any source file. The `announce()` function extraction (Option A) was rejected because it would require source changes.
3. **Focus the `role=option` inner element, not the `data-row-id` outer wrapper.** `SortableStackRow` wraps the focusable `role="option"` `tabIndex=0` div with an outer div that has `data-row-id` but no `tabIndex`. Calling `.focus()` on the outer div is a JSDOM no-op; the inner `id="stack-row-{id}"` element must be focused for `document.activeElement.closest('[data-row-id]')` to resolve.

## Deviations from Plan

None — plan executed exactly as written. The deferred-Test scope was explicitly allowed by the plan: "reduce Task 2 to Tests 1+2 (region presence + initial empty state) — Tests 3-6 become a deferred item to Phase 1044 Plan 03's e2e spec."

## Known Coverage Gaps

Tests 3-6 (pickup/drop/cancel announcement content) are NOT covered in vitest. Verification path:
- **Phase 1044 Plan 03:** `frontend/e2e/builder-v1-5.spec.ts` — "drag-from-catalog negative: Escape cancels mid-drag" asserts the region contains "Drop cancelled."; "drag-from-catalog happy" asserts region contains the layer name after drop.

## Issues Encountered

**Test 4 (Shift+ArrowDown) initially failed:** The test was focusing `querySelector('[data-row-id="a"]')` (the outer wrapper div without `tabIndex`). JSDOM does not set `document.activeElement` for non-focusable elements, so the Shift+Arrow handler's `document.activeElement.closest('[data-row-id]')` resolved to null, and `onShiftClick` was never called. Fixed by focusing `getElementById('stack-row-a')` (the inner `role=option` `tabIndex=0` element) instead. — Rule 1 auto-fix.

**TypeScript TS6133 (unused import):** `screen` was imported but not used in `MapBuilderPage.a11y.test.tsx`. Fixed in a follow-up commit. — Rule 1 auto-fix.

## Next Phase Readiness

- POL-23 satisfied: ARIA contract pinned by tests + walkthrough documented.
- Plan 03 (Playwright UAT) can reference `1044-A11Y-WALKTHROUGH.md` as the manual verification companion to the e2e spec.
- Tests 3-6 (drag announcement content) named in Plan 03 as required e2e coverage.

---
*Phase: 1044-cross-cutting-closeout*
*Completed: 2026-05-15*

## Self-Check: PASSED

- `frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx` — EXISTS
- `frontend/src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx` — EXISTS
- `.planning/phases/1044-cross-cutting-closeout/1044-A11Y-WALKTHROUGH.md` — EXISTS
- Commits `cc850d5d`, `dcabdf06`, `a01011d2`, `c0f70144` — IN GIT LOG

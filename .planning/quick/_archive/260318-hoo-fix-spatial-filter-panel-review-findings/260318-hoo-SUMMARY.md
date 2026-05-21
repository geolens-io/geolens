---
phase: 260318-hoo
plan: 01
subsystem: search/spatial-filter
tags: [spatial, a11y, animation, validation, tests]
dependency_graph:
  requires: [260318-gnv, 260318-g6s]
  provides: [production-ready-spatial-panel]
  affects: [search-page, spatial-filter-panel]
tech_stack:
  added: []
  patterns: [always-render-for-animation, hasOpenedRef-lazy-mount, Literal-validation]
key_files:
  created: []
  modified:
    - frontend/src/components/search/SpatialFilterPanel.tsx
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/stores/__tests__/search-store.test.ts
    - backend/app/search/router.py
    - backend/app/search/service.py
    - backend/tests/test_search.py
decisions:
  - Always-render panel with CSS translate for slide animation instead of conditional mount/unmount
  - hasOpenedRef pattern to lazy-mount MapGL on first open then preserve across cycles
metrics:
  duration: 2min
  completed: 2026-03-18T16:51:57Z
  tasks_completed: 2
  tasks_total: 2
  files_modified: 6
---

# Phase 260318-hoo Plan 01: Fix Spatial Filter Panel Review Findings Summary

Always-render spatial panel for CSS slide animation, add a11y (dialog role, Escape, focus), bbox overlay for polygon mode, Literal validation on backend spatial_predicate, and 6 new tests.

## Task Results

### Task 1: Fix blockers and should-fixes in SpatialFilterPanel + FilterPanel
- **Commit:** c98fa779
- **Changes:**
  - FilterPanel: removed conditional wrapper so panel is always rendered (enables CSS transition)
  - FilterPanel: mobile "Clear location" now resets spatial_predicate to intersects
  - SpatialFilterPanel: "Use current map extent" calls td.setMode('rectangle') after setting draw mode
  - SpatialFilterPanel: added dashed red bbox overlay (line-dasharray [4,4]) when polygon mode has pending bbox
  - SpatialFilterPanel: added role="dialog", aria-modal="true", aria-label, tabIndex=-1, Escape key handler, focus-on-open
  - SpatialFilterPanel: replaced `{open && <MapGL>}` with `{hasOpenedRef.current && <MapGL>}` to preserve map state

### Task 2: Backend Literal validation + frontend/backend tests
- **Commit:** 32e6ac19
- **Changes:**
  - Router: all 4 spatial_predicate parameters use Literal["intersects", "within"] (handle_search, facets, datasets, items)
  - Service: get_facet_counts and search_datasets use Literal type annotation
  - Frontend: 5 new search-store tests for spatial_predicate (toParams includes/omits, restoreParams with/without, resetFilters)
  - Backend: test_search_bbox_within smoke test added

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- TypeScript: `npx tsc --noEmit` passes with zero errors
- Frontend tests: 14/14 pass (9 existing + 5 new spatial_predicate tests)

## Self-Check: PASSED

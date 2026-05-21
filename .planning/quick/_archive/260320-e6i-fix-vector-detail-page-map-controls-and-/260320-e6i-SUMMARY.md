---
phase: quick-260320-e6i
plan: 01
subsystem: frontend/dataset-map
tags: [map-controls, ux, vector, raster, vrt]
dependency_graph:
  requires: []
  provides: [always-visible-zoom-to-extent]
  affects: [DatasetMap]
tech_stack:
  added: []
  patterns: [extracted-showNavControl-boolean, cn-conditional-positioning]
key_files:
  created: []
  modified:
    - frontend/src/components/dataset/DatasetMap.tsx
    - frontend/src/components/dataset/__tests__/DatasetMap.test.tsx
decisions:
  - "Zoom-to-extent always visible when bbox exists (not gated on isDrawing)"
  - "Control container position adjusts dynamically based on NavigationControl visibility"
  - "Extracted showNavControl boolean to deduplicate condition across interactive, NavigationControl, and positioning"
metrics:
  duration: 2min
  completed: 2026-03-20
---

# Quick Task 260320-e6i: Fix Vector Detail Page Map Controls Summary

Zoom-to-extent button now always visible when bbox exists, with dynamic control positioning based on NavigationControl presence.

## What Changed

### Task 1: Fix map control visibility in DatasetMap
**Commit:** 87bfa1be

- Extracted `showNavControl` boolean from inline condition (used for `interactive` prop, NavigationControl rendering, and control container positioning)
- Removed `isDrawing` guard from zoom-to-extent button -- now shows whenever `hasBbox` is true
- Changed control container from fixed `top-[120px]` to conditional `top-[120px]` / `top-3` based on NavigationControl visibility
- Added `cn` import for conditional className composition
- Verified `scrollZoom={isFullscreen}` remains unchanged

### Task 2: Update DatasetMap tests for new control visibility
**Commit:** c24e455b

- Updated "keeps the hero map static" test: zoom-to-extent now expected to be present (was asserting absence)
- Added "shows zoom-to-extent for vector dataset in read-only mode" test (no nav-control, has zoom button)
- Added "shows zoom-to-extent for raster dataset" test
- Added "does not show zoom-to-extent when no bbox" test
- All 11 tests pass, no TypeScript errors

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- All 11 DatasetMap tests pass
- TypeScript compilation clean (no errors)

---
phase: quick
plan: 260331-azj
subsystem: frontend/import
tags: [vrt, raster, import, bulk-upload]
dependency_graph:
  requires: []
  provides: [vrt-multi-source-pre-selection, bulk-tracking-vrt-button]
  affects: [frontend/src/components/import/BulkTrackingList.tsx, frontend/src/components/import/VrtCreateDialog.tsx, frontend/src/components/import/VrtCreatorForm.tsx]
tech_stack:
  added: []
  patterns: [useQueries parallel fetch, ref guard for one-shot effect]
key_files:
  created: []
  modified:
    - frontend/src/components/import/BulkTrackingList.tsx
    - frontend/src/components/import/VrtCreateDialog.tsx
    - frontend/src/components/import/VrtCreatorForm.tsx
decisions:
  - Used useQueries with staleTime=Infinity in BulkTrackingList to read cached job status without adding extra polling (JobProgress already polls)
  - Used ref guard (multiInitializedRef) in VrtCreatorForm to ensure multi-source pre-selection runs exactly once on mount
metrics:
  duration: ~10 minutes
  completed: 2026-03-31
---

# Quick Task 260331-azj: Add Create VRT Button for Multiple Imports Summary

**One-liner:** "Create VRT Mosaic" button in BulkTrackingList auto-pre-selects completed raster datasets via initialSourceIds prop through VrtCreateDialog to VrtCreatorForm's parallel useQueries fetch.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add initialSourceIds to VrtCreateDialog and VrtCreatorForm | e3405b79 | VrtCreateDialog.tsx, VrtCreatorForm.tsx |
| 2 | Add VRT button to BulkTrackingList for completed raster imports | d7e67cb1 | BulkTrackingList.tsx |

## What Was Built

**VrtCreateDialog.tsx:** Added `initialSourceIds?: string[]` to `VrtCreateDialogProps` and passes it through to `VrtCreatorForm`.

**VrtCreatorForm.tsx:** Added `initialSourceIds?: string[]` prop. Imports `useQueries` from `@tanstack/react-query`. When `initialSourceIds` is set and `initialSourceId` is not (avoiding single-source flow conflict), fires parallel queries via `useQueries` for each ID. A `useEffect` watches the results and populates `selectedSources` with fetched raster datasets once all queries succeed, guarded by a ref to run only once.

**BulkTrackingList.tsx:** Added `useState` for dialog open state, `useQueries` to read cached job status for raster entries (`.tif`/`.tiff` files), and derives `completedRasterIds` from completed jobs with `dataset_id`. When `completedRasterIds.length >= 2`, renders a dashed-border section with a "Create VRT Mosaic" button. Renders `VrtCreateDialog` with `initialSourceIds={completedRasterIds}`.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- `frontend/src/components/import/BulkTrackingList.tsx` - FOUND
- `frontend/src/components/import/VrtCreateDialog.tsx` - FOUND
- `frontend/src/components/import/VrtCreatorForm.tsx` - FOUND
- Commit e3405b79 - FOUND
- Commit d7e67cb1 - FOUND
- TypeScript compiles clean (both tasks verified)

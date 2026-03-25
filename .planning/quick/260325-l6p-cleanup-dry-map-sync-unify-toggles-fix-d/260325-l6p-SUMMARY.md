---
phase: quick-260325-l6p
plan: 01
subsystem: ui
tags: [maplibre, refactoring, map-sync, layer-styling]

requires:
  - phase: quick-260325-jpw
    provides: fill/stroke visibility toggles and CUSTOM_PAINT_PROPS set in map-sync
provides:
  - DRY map-sync.ts with stripCustomProps, replayExpressions, finalizeLayer helpers
  - Single source of truth CUSTOM_PAINT_PROPS exported from map-sync
  - Legend swatch stroke-disabled border suppression
affects: [map-builder, layer-styling, legend]

tech-stack:
  added: []
  patterns:
    - "stripCustomProps/replayExpressions/finalizeLayer helpers for map-sync geometry branches"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/hooks/use-builder-layers.ts
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/map/layer-icons.tsx
    - frontend/src/components/map/MapLegend.tsx

key-decisions:
  - "Export CUSTOM_PAINT_PROPS as single source of truth from map-sync.ts"
  - "Use IIFE pattern to hoist currentDash computation outside .map() callback"

patterns-established:
  - "stripCustomProps for filtering custom paint props before addLayer"
  - "finalizeLayer for post-addLayer expression replay, opacity, and filter"

requirements-completed: [CLEANUP-1, CLEANUP-2, CLEANUP-3, CLEANUP-4, CLEANUP-5, CLEANUP-6, CLEANUP-7, CLEANUP-8]

duration: 3min
completed: 2026-03-25
---

# Quick 260325-l6p: Cleanup Summary

**DRY map-sync.ts with extracted helpers, unified CUSTOM_PAINT_PROPS, fixed legend/icon/editor minor issues**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-25T19:18:26Z
- **Completed:** 2026-03-25T19:21:40Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Extracted stripCustomProps, replayExpressions, finalizeLayer helpers eliminating 3x duplicated logic in map-sync.ts
- Unified CUSTOM_PAINT_PROPS as single exported constant; removed drifting local CUSTOM_PROPS from use-builder-layers.ts
- Hoisted currentDash computation outside .map() callback in LayerStyleEditor
- Unified handleToggleStroke to use variable width key instead of duplicated if/else branches
- Removed dead !isLine guard in layer-icons gradient section
- Added stroke-disabled border suppression on categorical/graduated legend swatches

## Task Commits

Each task was committed atomically:

1. **Task 1: DRY map-sync.ts helpers, export CUSTOM_PAINT_PROPS** - `88448b6f` (refactor)
2. **Task 2: Fix LayerStyleEditor, layer-icons, and MapLegend minor issues** - `8457b8ec` (fix)

## Files Created/Modified
- `frontend/src/components/builder/map-sync.ts` - Extracted helpers, exported CUSTOM_PAINT_PROPS, replaced duplicated blocks
- `frontend/src/hooks/use-builder-layers.ts` - Imports CUSTOM_PAINT_PROPS from map-sync, removed local CUSTOM_PROPS
- `frontend/src/components/builder/LayerStyleEditor.tsx` - Hoisted currentDash, unified handleToggleStroke
- `frontend/src/components/map/layer-icons.tsx` - Removed dead !isLine guard in gradient section
- `frontend/src/components/map/MapLegend.tsx` - Stroke-disabled border suppression on categorical/graduated swatches

## Decisions Made
- Export CUSTOM_PAINT_PROPS as the single source of truth from map-sync.ts rather than duplicating in consumers
- Use IIFE pattern to hoist currentDash outside .map() callback while keeping it within the JSX render scope

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

---
*Phase: quick-260325-l6p*
*Completed: 2026-03-25*

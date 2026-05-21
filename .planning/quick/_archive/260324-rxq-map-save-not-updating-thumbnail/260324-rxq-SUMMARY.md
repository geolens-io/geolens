---
phase: quick-260324-rxq
plan: 01
subsystem: ui
tags: [maplibre, thumbnail, canvas, map-builder]

requires:
  - phase: 0203
    provides: useBuilderSave hook with SaveState interface
provides:
  - Reliable map thumbnail capture on save regardless of map idle state
affects: [map-builder, maps-listing]

tech-stack:
  added: []
  patterns: [loaded-check-before-idle-wait, safety-timeout-for-event-listeners]

key-files:
  created: []
  modified:
    - frontend/src/hooks/use-builder-save.ts
    - frontend/src/hooks/__tests__/use-builder-save.test.ts

key-decisions:
  - "Use map.loaded() check instead of triggerRepaint+idle pattern for reliable thumbnail capture"
  - "3-second safety timeout prevents silent callback drops when idle event never fires"

patterns-established:
  - "loaded-check pattern: check map.loaded() before waiting for idle event to avoid missed callbacks"

requirements-completed: [QUICK-FIX]

duration: 1min
completed: 2026-03-24
---

# Quick Task 260324-rxq: Map Save Not Updating Thumbnail Summary

**Fixed thumbnail capture using map.loaded() check with 3s safety timeout instead of unreliable triggerRepaint+idle pattern**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-25T00:11:06Z
- **Completed:** 2026-03-25T00:12:10Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Fixed captureThumbnail to capture immediately when map is already idle (common after metadata-only saves)
- Added 3-second safety timeout when waiting for idle event to prevent silent drops
- Simplified maybeAutoCaptureThumbnail to delegate idle-checking to captureThumbnail
- All 10 existing tests pass

## Task Commits

1. **Task 1: Fix captureThumbnail to handle already-idle maps** - `2a402be6` (fix)

## Files Created/Modified
- `frontend/src/hooks/use-builder-save.ts` - Rewrote captureThumbnail with loaded() check, extracted doCapture helper, simplified maybeAutoCaptureThumbnail
- `frontend/src/hooks/__tests__/use-builder-save.test.ts` - Added loaded() and off() methods to mock map

## Decisions Made
- Used `map.loaded()` check instead of `triggerRepaint()` + `map.once('idle', ...)` -- the old pattern failed when the map was already idle because triggerRepaint doesn't guarantee a state transition through non-idle
- Extracted `doCapture` as a standalone helper so both the immediate and deferred code paths share the same capture logic
- 3-second safety timeout prevents the callback from being silently dropped in edge cases where idle never fires

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## Known Stubs
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Thumbnail capture is now reliable for all save scenarios
- No blockers

---
*Phase: quick-260324-rxq*
*Completed: 2026-03-24*

## Self-Check: PASSED

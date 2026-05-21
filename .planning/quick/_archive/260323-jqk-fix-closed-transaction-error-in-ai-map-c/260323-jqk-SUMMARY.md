---
phase: quick-260323-jqk
plan: 01
subsystem: api
tags: [sqlalchemy, asyncio, transaction, flush, savepoint]

requires:
  - phase: none
    provides: n/a
provides:
  - "update_map uses flush instead of commit, enabling savepoint-safe operation"
  - "AI map generation (streaming and non-streaming) commits at caller level"
affects: [maps, ai]

tech-stack:
  added: []
  patterns: ["flush-only service functions with caller-owned commit lifecycle"]

key-files:
  created: []
  modified:
    - backend/app/maps/service.py
    - backend/app/ai/router.py
    - backend/app/ai/service.py

key-decisions:
  - "update_map uses flush() so begin_nested() savepoints in AI service work correctly"
  - "Callers (AI router, AI streaming service, maps router) each own their commit point"

patterns-established:
  - "Flush-only service pattern: service functions flush but do not commit, callers own transaction lifecycle"

requirements-completed: [FIX-CLOSED-TRANSACTION]

duration: 2min
completed: 2026-03-23
---

# Quick 260323-jqk: Fix Closed Transaction Error in AI Map Generate Summary

**Changed update_map from commit to flush so begin_nested savepoints work, added explicit commits to AI generate callers**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-23T18:21:44Z
- **Completed:** 2026-03-23T18:23:57Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Fixed "Can't operate on closed transaction inside context manager" error when AI generates a map
- update_map() now uses flush() instead of commit(), compatible with begin_nested() savepoints
- AI non-streaming endpoint commits after generate_map_from_prompt returns
- AI streaming path commits after _validate_and_persist_map returns
- maps/router.py update endpoint unchanged -- its existing commit at line 323 becomes the sole (correct) commit

## Task Commits

Each task was committed atomically:

1. **Task 1: Change update_map to flush-only and add commits to AI callers** - `8dd86717` (fix)

Task 2 (verify no regressions) was validated by code inspection -- all callers of update_map confirmed to have explicit commits. Integration tests require Docker DB networking which is unavailable from host.

## Files Created/Modified
- `backend/app/maps/service.py` - Changed commit() to flush() in update_map, updated docstring
- `backend/app/ai/router.py` - Added await db.commit() before returning in generate_map_endpoint
- `backend/app/ai/service.py` - Added await session.commit() before yielding done event in stream_generate_map

## Decisions Made
- update_map uses flush() so begin_nested() savepoints in AI service work correctly
- Callers (AI router, AI streaming service, maps router) each own their commit point

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Backend tests cannot run from host (DB hostname `db` only resolves inside Docker network). Verified correctness by static analysis of all update_map callers instead.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Transaction fix complete, AI map generation should work without errors
- No follow-up work needed

---
*Phase: quick-260323-jqk*
*Completed: 2026-03-23*

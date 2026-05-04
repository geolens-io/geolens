---
phase: 238-boundary-guards-and-contract-stabilization
plan: 02
subsystem: testing
tags: [architecture, maps, search, size-budget, facade]
requires:
  - phase: 238-01
    provides: maps/search private import guards in test_layering.py
provides:
  - Maps/search facade line-count budget guard
  - Maps/search private service line-count budget guard
  - Explicit caps for known large private modules
affects: [maps-service-decomposition, search-service-decomposition, architecture-guards]
tech-stack:
  added: []
  patterns: [line-count-budget, explicit-cap-allowlist]
key-files:
  created: []
  modified:
    - backend/tests/test_layering.py
key-decisions:
  - "Known large private modules use explicit caps rather than exemptions, so future growth still fails the guard."
patterns-established:
  - "Facades and private service modules have separate line-count budgets to prevent god-module regression."
requirements-completed: [BOUND-02, BOUND-03]
duration: 4 min
completed: 2026-05-03
---

# Phase 238 Plan 02: Service Size Budget Guards Summary

**Maps/search service facades and private modules now have executable line-count budgets with explicit growth caps.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-04T00:10:00Z
- **Completed:** 2026-05-04T00:14:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Added `test_maps_search_service_modules_stay_within_size_budgets`.
- Enforced thin facade budgets for maps and search public service modules.
- Added reviewed caps for the known large maps/search private modules while keeping the default private-module budget strict.
- Verified the size guard, private import guards, and catalog/processing guards pass together.

## Task Commits

1. **Add facade and private-module size budget guard** - `e06c5c24` (`test`)
2. **Run size guard with import and cycle guards** - `e06c5c24` (`test`)

## Files Created/Modified

- `backend/tests/test_layering.py` - maps/search facade and private service line-count budget guard.

## Decisions Made

- Kept the allowlist as explicit per-file caps, not blanket exemptions.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- Command: cd backend && uv run pytest tests/test_layering.py::test_maps_search_service_modules_stay_within_size_budgets -q - passed.
- Command: cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_maps_private_service_modules tests/test_layering.py::test_no_external_imports_of_search_private_service_modules tests/test_layering.py::test_maps_search_service_modules_stay_within_size_budgets tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q - passed.
- Command: cd backend && uv run ruff check tests/test_layering.py - passed.
- Command: cd backend && uv run ruff format --check tests/test_layering.py - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 238 can proceed to goal verification with boundary and size regression guards in place.

## Self-Check: PASSED

---
*Phase: 238-boundary-guards-and-contract-stabilization*
*Completed: 2026-05-03*

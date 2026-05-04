---
phase: 238-boundary-guards-and-contract-stabilization
plan: 01
subsystem: testing
tags: [architecture, maps, search, facade, imports]
requires:
  - phase: 236
    provides: decomposed maps service behind public facade
  - phase: 237
    provides: decomposed search service behind public facade
provides:
  - Maps private service import architecture guard
  - Search private service import architecture guard
  - Catalog/processing guard preservation check
affects: [maps-service-decomposition, search-service-decomposition, architecture-guards]
tech-stack:
  added: []
  patterns: [ast-import-guard, public-facade-boundary]
key-files:
  created: []
  modified:
    - backend/tests/test_layering.py
key-decisions:
  - "Used an AST import scan so guards catch `from module import`, direct `import module`, and package-level `from package import service_x` bypasses."
patterns-established:
  - "Private maps/search service modules are importable only by their facade and sibling private service modules."
requirements-completed: [BOUND-01, BOUND-03]
duration: 7 min
completed: 2026-05-03
---

# Phase 238 Plan 01: Private Service Import Guards Summary

**AST-backed architecture guards now prevent production modules from bypassing the maps/search public service facades.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-04T00:03:33Z
- **Completed:** 2026-05-04T00:10:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Added maps private service import guard coverage for `service_shared`, `service_crud`, `service_layers`, and `service_public`.
- Added search private service import guard coverage for `service_filters`, `service_facets`, `service_collections`, `service_semantic`, `service_datasets`, and `service_records`.
- Verified existing catalog/processing boundary guards still pass with the new architecture tests.

## Task Commits

1. **Add maps private-module import guard** - `e06c5c24` (`test`)
2. **Add search private-module import guard and run existing cycle guards** - `e06c5c24` (`test`)

## Files Created/Modified

- `backend/tests/test_layering.py` - AST import scanner plus maps/search private-module boundary tests.

## Decisions Made

- Used AST parsing instead of grep regexes to cover all Python import shapes without brittle line-pattern gaps.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- Command: cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_maps_private_service_modules tests/test_layering.py::test_no_external_imports_of_search_private_service_modules tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q - passed.
- Command: cd backend && uv run ruff check tests/test_layering.py - passed.
- Command: cd backend && uv run ruff format --check tests/test_layering.py - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 02 can layer size-budget enforcement on the same architecture test surface.

## Self-Check: PASSED

---
*Phase: 238-boundary-guards-and-contract-stabilization*
*Completed: 2026-05-03*

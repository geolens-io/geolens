---
phase: 236-maps-service-decomposition
plan: 05
subsystem: testing
tags: [maps, facade, regression, architecture]
requires:
  - phase: 236-04
    provides: Public/share split module
provides:
  - Thin maps service facade and focused facade regression coverage
affects: [maps-service-decomposition, boundary-guards]
tech-stack:
  added: []
  patterns: [Explicit __all__ facade, source-introspection-light API regression]
key-files:
  created: []
  modified:
    - backend/app/modules/catalog/maps/service.py
    - backend/tests/test_maps.py
    - backend/tests/test_layering.py
key-decisions:
  - "Updated the existing concrete User ORM allowlist only for legitimate SQLAlchemy attribute use in decomposed maps modules."
patterns-established:
  - "Facade tests assert public API attributes and __all__, leaving private-module boundary guards to Phase 238."
requirements-completed: [MAPS-01, MAPS-02, MAPS-03, MAPS-04, MAPS-05, MAPS-06]
duration: 21min
completed: 2026-05-03
---

# Phase 236: Plan 05 Summary

**The maps service is now a thin explicit facade with regression coverage for public imports and existing map behavior.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-05-03T22:25:56Z
- **Completed:** 2026-05-03T22:46:43Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Reduced `service.py` to a docstring, focused sibling imports, and an explicit `__all__`.
- Added `test_maps_service_facade_exports_public_api` to lock the existing public maps service surface.
- Updated the existing Phase 214 concrete `User` import allowlist for `service_shared.py`, `service_crud.py`, and `service_public.py`.
- Verified full maps regression and architecture checks.

## Task Commits

1. **Task 1: Finalize thin service facade** - `48a01a5b` (feat)
2. **Task 2: Add facade regression and maintain existing architecture allowlist** - `48a01a5b` (feat)
3. **Task 3: Run decomposition lint and architecture smoke checks** - `48a01a5b` (feat)

## Files Created/Modified

- `backend/app/modules/catalog/maps/service.py` - Thin public facade.
- `backend/tests/test_maps.py` - Facade export regression test.
- `backend/tests/test_layering.py` - Existing concrete `User` ORM import guard allowlist update.

## Decisions Made

No Phase 238 boundary guard was added here; this plan only maintained the existing guard and added source-introspection-light facade coverage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test database port mismatch**
- **Found during:** Verification
- **Issue:** The first DB-backed pytest run connected to `localhost:5432` and failed because the active Docker Compose database is exposed on `localhost:5434`.
- **Fix:** Re-ran DB-backed verification with `POSTGRES_PORT=5434`, allowing the existing session fixture to create and migrate `geolens_test`.
- **Files modified:** None
- **Verification:** `POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -q` passed.
- **Committed in:** N/A

---

**Total deviations:** 1 auto-fixed (Rule 3). **Impact on plan:** Verification environment adjustment only; no product code scope change.

## Issues Encountered

The initial DB-backed focused test command failed at fixture setup with `asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test" does not exist` because it targeted the wrong local port. Re-running against the Compose DB port passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 237 can decompose search service independently. Phase 238 can add private-module import and size guards against the new maps module structure.

## Verification

- `POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -q` — 107 passed
- `uv run pytest tests/test_layering.py -m architecture -q` — 15 passed
- `uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py` — passed
- `uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py` — passed

## Self-Check: PASSED

---
*Phase: 236-maps-service-decomposition*
*Completed: 2026-05-03*

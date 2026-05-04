---
phase: 234-governance-contract-verification
plan: 01
status: complete
subsystem: api
tags:
  - sharing
  - edition
  - pydantic
requires: []
provides:
  - Overlay-free Community and Enterprise edition fixtures for backend tests
  - Schema-layer advanced sharing gates for embed tokens and share links
  - DB-light schema contract tests for Community and Enterprise behavior
affects:
  - 234-02-embed-token-service-contract
  - 234-03-share-token-service-contract
tech-stack:
  added: []
  patterns:
    - Pydantic model_validator edition gate using app.core.edition.is_enterprise
key-files:
  created:
    - backend/tests/test_advanced_sharing_schema.py
  modified:
    - backend/tests/conftest.py
    - backend/app/modules/embed_tokens/schemas.py
    - backend/app/modules/catalog/maps/schemas.py
key-decisions:
  - "Community rejects only non-default advanced sharing fields; default embed tokens and non-expiring share links remain valid."
  - "The local test DB lifecycle now yields to DB-light tests when a reachable Postgres instance lacks required extensions."
patterns-established:
  - "Advanced sharing schema gates raise a shared ADVANCED_SHARING_ERROR through model_validator(mode='after')."
  - "Edition fixtures force the singleton with init_edition([]) or init_edition(['enterprise']) without importing the enterprise overlay."
requirements-completed:
  - SHARE-01
duration: 16 min
completed: 2026-05-03
---

# Phase 234 Plan 01: Schema Edition Gates Summary

**Edition-aware schema validation for advanced embed-token and share-link controls, backed by DB-light contract tests**

## Performance

- **Duration:** 16 min
- **Started:** 2026-05-03T17:08:00Z
- **Completed:** 2026-05-03T17:24:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added `community_edition` and `enterprise_edition` fixtures that force the edition singleton without loading the Enterprise overlay.
- Added schema validators blocking Community custom embed lifetimes, non-empty embed origins, and non-null share-link expiration.
- Added focused schema tests proving Community rejects advanced controls, Community defaults remain valid, and Enterprise accepts advanced fields.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add edition fixtures for governance tests** - `e41d4da5` (`test`)
2. **Task 2: Add schema-level advanced sharing gates** - `ec52193c` (`feat`)
3. **Task 3: Add schema contract tests** - `5d436f93` (`test`)

## Files Created/Modified

- `backend/tests/conftest.py` - Adds edition fixtures and lets DB-light tests proceed when local Postgres lacks required extensions.
- `backend/app/modules/embed_tokens/schemas.py` - Adds `ADVANCED_SHARING_ERROR` and Community gates for custom lifetimes and origins.
- `backend/app/modules/catalog/maps/schemas.py` - Adds `ADVANCED_SHARING_ERROR` and Community gate for expiring share links.
- `backend/tests/test_advanced_sharing_schema.py` - Covers Community rejection/defaults and Enterprise acceptance.

## Decisions Made

- Kept the paid boundary narrow: Community rejects only `expires_in_days != 30`, non-empty `allowed_origins`, and non-null share `expires_at`.
- Treated reachable Postgres without `vector` as a DB-backed-test blocker, not a reason to fail DB-light schema tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Let DB-light tests run when local Postgres lacks pgvector**
- **Found during:** Task 1 (Add edition fixtures for governance tests)
- **Issue:** The session autouse DB fixture failed on `CREATE EXTENSION IF NOT EXISTS vector`, blocking even pure schema/edition tests.
- **Fix:** Catch SQLAlchemy setup failures during extension initialization, drop the partially created test database, yield, and let DB-backed tests fail only when they request DB fixtures.
- **Files modified:** `backend/tests/conftest.py`
- **Verification:** `cd backend && uv run pytest tests/test_edition.py::TestEditionDetection::test_is_enterprise -q`
- **Committed in:** `e41d4da5`

---

**Total deviations:** 1 auto-fixed (Rule 3).
**Impact on plan:** The change is limited to test lifecycle behavior and is required for the planned DB-light checks to run in the current environment.

## Issues Encountered

The local Postgres service is reachable but lacks the `vector` extension. The fixture now records that condition by bypassing session DB setup for DB-light tests; DB-backed checks still require a database with PostGIS/pgvector.

## Command Evidence

- `cd backend && uv run pytest tests/test_edition.py::TestEditionDetection::test_is_enterprise -q` - 1 passed
- `python -m compileall backend/app/modules/embed_tokens/schemas.py backend/app/modules/catalog/maps/schemas.py` - passed
- `cd backend && uv run pytest tests/test_advanced_sharing_schema.py tests/test_edition.py::TestEditionDetection::test_is_enterprise -q` - 8 passed, 5 existing Pydantic deprecation warnings
- `cd backend && uv run ruff check app/modules/embed_tokens/schemas.py app/modules/catalog/maps/schemas.py tests/conftest.py tests/test_advanced_sharing_schema.py` - passed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plans 02 and 03 can import the shared advanced-sharing error and rely on schema tests as the contract baseline for service-layer bypass guards.

## Self-Check

PASSED. Summary exists, key created test file exists, and three `234-01` task commits are present.

---
*Phase: 234-governance-contract-verification*
*Completed: 2026-05-03*

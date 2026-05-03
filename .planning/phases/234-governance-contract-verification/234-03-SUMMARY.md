---
phase: 234-governance-contract-verification
plan: 03
status: complete
subsystem: api
tags:
  - maps
  - share-tokens
  - edition
requires:
  - phase: 234-01-schema-edition-gates
    provides: shared ADVANCED_SHARING_ERROR and edition fixtures
provides:
  - Service-layer guards for expiring share links
  - HTTP 400 translation for share-token service guard failures
  - Community and Enterprise share-link contract tests
affects:
  - 234-05-copy-openapi-verification
tech-stack:
  added: []
  patterns:
    - service-before-DB edition guard for schema bypass protection
key-files:
  created: []
  modified:
    - backend/app/modules/catalog/maps/service.py
    - backend/app/modules/catalog/maps/router.py
    - backend/tests/test_maps.py
key-decisions:
  - "Community can create and revoke non-expiring share links; non-null expires_at is Enterprise-only."
  - "Existing PATCH expiration behavior remains covered under Enterprise edition fixtures."
patterns-established:
  - "Map share-token service guards mirror embed-token guards by raising ADVANCED_SHARING_ERROR before query execution."
requirements-completed:
  - SHARE-01
  - SHARE-03
duration: 15 min
completed: 2026-05-03
---

# Phase 234 Plan 03: Share Token Service Contract Summary

**Share-token service bypass protection for expiring links with preserved basic Community creation and revocation**

## Performance

- **Duration:** 15 min
- **Started:** 2026-05-03T18:02:00Z
- **Completed:** 2026-05-03T18:17:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added service-layer guards blocking Community non-null `expires_at` before share-token create/update queries.
- Wrapped create and patch share-token service guard failures in HTTP 400 translation.
- Added Community and Enterprise route coverage for expiring share links.
- Added direct service-bypass tests proving Community expiration guards fire without DB access.
- Marked existing share-token PATCH expiration tests as Enterprise-only while retaining basic Community share/revoke coverage.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add share-token service guards** - `92f4615a` (`feat`)
2. **Task 2: Add share-token contract tests** - `11b9eede` (`test`)

## Files Created/Modified

- `backend/app/modules/catalog/maps/service.py` - Adds pre-query Community guards for expiring share links.
- `backend/app/modules/catalog/maps/router.py` - Translates share-token service `ValueError` guard failures to HTTP 400.
- `backend/tests/test_maps.py` - Adds Community/Enterprise route tests and service-bypass guard tests.

## Decisions Made

- Kept route Community expiration failures at `422` because schema validation is the first normal request path gate.
- Preserved PATCH expiration tests by marking `TestUpdateShareToken` with the Enterprise edition fixture.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

DB-backed route tests must run against the Docker database on `POSTGRES_PORT=5434`; the default local Postgres on `5432` is not a valid test target for these suites. Backend pytest sessions were serialized to avoid `geolens_test` lifecycle collisions.

## Command Evidence

- `python -m compileall backend/app/modules/catalog/maps/service.py backend/app/modules/catalog/maps/router.py backend/tests/test_maps.py` - passed
- `cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/router.py tests/test_maps.py` - passed
- `cd backend && uv run pytest tests/test_maps.py::TestShareTokenServiceGuards -q` - 2 passed
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_maps.py::TestShareToken::test_share_public_map_success tests/test_maps.py::TestShareToken::test_revoke_share_token tests/test_maps.py::TestShareToken::test_share_expiration_requires_enterprise tests/test_maps.py::TestShareToken::test_share_expiration_allowed_in_enterprise tests/test_maps.py::TestShareTokenServiceGuards tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_set_expiration -q` - 7 passed
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_advanced_sharing_schema.py tests/test_maps.py::TestShareToken tests/test_maps.py::TestUpdateShareToken -q` - 24 passed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 05 can verify share-link schema, service, route, UI, OpenAPI, and GTM copy against one consistent Community/Enterprise boundary.

## Self-Check

PASSED. Summary exists, no new key files were created, and two `234-03` task commits are present.

---
*Phase: 234-governance-contract-verification*
*Completed: 2026-05-03*

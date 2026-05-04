---
phase: 234-governance-contract-verification
plan: 02
status: complete
subsystem: api
tags:
  - embed-tokens
  - sharing
  - edition
requires:
  - phase: 234-01-schema-edition-gates
    provides: shared ADVANCED_SHARING_ERROR and edition fixtures
provides:
  - Service-layer guards for embed-token custom lifetimes and origin restrictions
  - HTTP 400 translation for embed-token service guard failures
  - Community and Enterprise embed-token contract tests
affects:
  - 234-05-copy-openapi-verification
tech-stack:
  added: []
  patterns:
    - service-before-DB edition guard for schema bypass protection
key-files:
  created: []
  modified:
    - backend/app/modules/embed_tokens/service.py
    - backend/app/modules/embed_tokens/router.py
    - backend/tests/test_embed_tokens.py
key-decisions:
  - "Embed-token service guards run before revocation, layer lookup, or token update queries."
  - "Existing domain-locking tests are explicitly Enterprise-only because non-empty allowed_origins is now a paid control."
patterns-established:
  - "Service guards reuse the schema-layer ADVANCED_SHARING_ERROR so route and direct-call failures carry one product-contract message."
requirements-completed:
  - SHARE-01
  - SHARE-03
duration: 18 min
completed: 2026-05-03
---

# Phase 234 Plan 02: Embed Token Service Contract Summary

**Embed-token service bypass protection for advanced lifetimes and domain restrictions with preserved basic Community creation and revocation**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-03T17:44:00Z
- **Completed:** 2026-05-03T18:02:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added service-layer guards that reject Community custom embed lifetimes and non-empty origin restrictions before DB work.
- Wrapped PATCH service guard failures in HTTP 400 translation, matching the create endpoint's existing pattern.
- Added Community route tests for schema rejection and service-bypass tests proving direct calls fail before DB lookup.
- Marked existing custom lifetime/domain-locking tests as Enterprise-only so the paid path remains covered.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add embed-token service guards** - `33ad1459` (`feat`)
2. **Task 2: Add embed-token contract tests** - `1d61f5a2` (`test`)

## Files Created/Modified

- `backend/app/modules/embed_tokens/service.py` - Adds pre-query Community guards for advanced controls.
- `backend/app/modules/embed_tokens/router.py` - Translates update service `ValueError` guard failures to HTTP 400.
- `backend/tests/test_embed_tokens.py` - Adds Community route/service-bypass coverage and Enterprise marks for domain locking.

## Decisions Made

- Kept the route-level Community tests expecting `422` because Pydantic rejects paid fields before endpoint execution.
- Added service-bypass tests in the existing embed-token test module, with the tile-pool fixture skipped for tests that do not request DB fixtures.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Avoid tile-pool setup for DB-light service-bypass tests**
- **Found during:** Task 2 (Add embed-token contract tests)
- **Issue:** `tests/test_embed_tokens.py` had an autouse asyncpg tile-pool fixture that tried to connect for every test, including direct service-guard tests that intentionally avoid DB.
- **Fix:** The fixture now checks requested fixture names and skips pool setup when the test does not use DB/client fixtures.
- **Files modified:** `backend/tests/test_embed_tokens.py`
- **Verification:** `cd backend && uv run pytest tests/test_embed_tokens.py::TestEmbedTokenServiceGuards -q`
- **Committed in:** `1d61f5a2`

---

**Total deviations:** 1 auto-fixed (Rule 3).
**Impact on plan:** The change is test-fixture scoped and enables the planned DB-light bypass coverage.

## Issues Encountered

DB-backed route tests must run against the Docker database on `POSTGRES_PORT=5434`; the default local Postgres on `5432` lacks the required test DB/extensions. Parallel backend pytest sessions also collide because the session fixture recreates `geolens_test`, so the focused suites were serialized.

## Command Evidence

- `python -m compileall backend/app/modules/embed_tokens/service.py backend/app/modules/embed_tokens/router.py backend/tests/test_embed_tokens.py` - passed
- `cd backend && uv run ruff check app/modules/embed_tokens/service.py app/modules/embed_tokens/router.py tests/test_embed_tokens.py` - passed
- `cd backend && uv run pytest tests/test_embed_tokens.py::TestEmbedTokenServiceGuards -q` - 3 passed
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_embed_tokens.py::TestCreateEmbedToken::test_create_embed_token_default_expiration tests/test_embed_tokens.py::TestCreateEmbedToken::test_custom_expiration_requires_enterprise tests/test_embed_tokens.py::TestCreateEmbedToken::test_allowed_origins_require_enterprise tests/test_embed_tokens.py::TestEmbedTokenServiceGuards tests/test_embed_tokens.py::TestUpdateEmbedToken::test_patch_embed_token_update_origins tests/test_embed_tokens.py::TestRevokeEmbedToken::test_revoke_embed_token -q` - 8 passed
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_advanced_sharing_schema.py tests/test_embed_tokens.py::TestCreateEmbedToken tests/test_embed_tokens.py::TestCreateEmbedTokenWithOrigins tests/test_embed_tokens.py::TestUpdateEmbedToken tests/test_embed_tokens.py::TestRevokeEmbedToken -q` - 20 passed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 05 can cite embed-token schema, service, route, and UI coverage as SHARE-01/SHARE-03 evidence.

## Self-Check

PASSED. Summary exists, no new key files were created, and two `234-02` task commits are present.

---
*Phase: 234-governance-contract-verification*
*Completed: 2026-05-03*

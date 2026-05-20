---
phase: 1062-medium-severity-remediation
plan: "01"
subsystem: auth
tags: [jwt, token-version, jwt-revocation, password-policy, alembic, migration, security]

requires:
  - phase: 1061-security-audit-2026-05-19-remediation
    provides: SEC-S06/S07 fixes; test fixture conventions (test_demo_credentials_guard)

provides:
  - "Alembic migration 0019: catalog.users.token_version INTEGER NOT NULL DEFAULT 1"
  - "User.token_version SQLAlchemy mapped column"
  - "create_access_token embeds jti (uuid4 hex) + token_version in every access JWT"
  - "revoke_all_tokens: revokes refresh tokens + increments token_version atomically"
  - "get_current_user / get_optional_user reject JWTs with stale token_version"
  - "POST /auth/logout/ and POST /auth/change-password/ now call revoke_all_tokens"
  - "password_policy.py: validate_password_complexity + validate_password_from_settings"
  - "Settings: password_min_length=12, password_require_classes=3 (env-configurable)"
  - "Password complexity enforced at all 4 entry points: register, change-pw, admin create, saml-to-local"

affects:
  - 1062-medium-severity-remediation plans 02-06
  - Any future plan touching auth issuance, logout, or user management

tech-stack:
  added: []
  patterns:
    - "token_version revocation: bump column on logout/password-change, validate on every JWT decode"
    - "jti claim: uuid4().hex embedded in every access JWT (128-bit unique ID)"
    - "Password policy: Field(min_length=8) fast-fail floor + @field_validator canonical policy check"
    - "Lazy import in field_validator to avoid circular app.core.config -> password_policy -> config"

key-files:
  created:
    - backend/alembic/versions/0019_users_token_version.py
    - backend/app/modules/auth/password_policy.py
    - backend/tests/test_jwt_revocation.py
    - backend/tests/test_password_policy.py
  modified:
    - backend/app/modules/auth/models.py
    - backend/app/modules/auth/service.py
    - backend/app/modules/auth/dependencies.py
    - backend/app/modules/auth/router.py
    - backend/app/modules/auth/schemas.py
    - backend/app/modules/auth/oauth/router.py
    - backend/app/modules/admin/schemas.py
    - backend/app/core/config.py
    - backend/tests/conftest.py
    - backend/tests/test_auth.py
    - backend/tests/test_admin_user_operations.py
    - backend/tests/test_raster_tiles.py
    - backend/tests/test_embed_tokens.py
    - backend/tests/test_ingest.py
    - backend/tests/test_provenance_attribution.py

key-decisions:
  - "create_access_token made async to perform the User.token_version SELECT; all 3 callers (login router, OAuth router, rotate_refresh_token) updated to await"
  - "revoke_all_refresh_tokens retained as backward-compatible alias delegating to revoke_all_tokens so no external callers break"
  - "Field(min_length=8) fast-fail floor kept on all four password fields per Task 5 plan note; @field_validator(mode='after') owns the canonical 12-char + 3-class policy"
  - "Missing token_version claim in JWT treated as version=0, which is always < User.token_version >= 1 post-migration, so legacy/forged JWTs are rejected without special-casing"
  - "Denylist (breached passwords) deferred to SEC-FU Phase 1063 per CONTEXT.md scope"
  - "Test fixtures updated from testpass123/securepass123 to TestPass1234!/SecurePass123! across 6 files to satisfy the new policy without bypassing it in tests"

patterns-established:
  - "JWT revocation via column increment: no per-token blocklist required; O(1) UPDATE per user, O(1) check per request"
  - "Password policy module pattern: standalone module with direct-call + settings-overload variants; lazy import in schema validators to avoid circular imports"

requirements-completed:
  - SEC-S15
  - SEC-S16

duration: 10min
completed: "2026-05-20"
---

# Phase 1062 Plan 01: JWT Revocation + Password Complexity Summary

**token_version column + jti claim close the logout-doesn't-invalidate-access-JWT gap (SEC-S15); password complexity module with configurable 12-char + 3-class policy closes the weak-password gap (SEC-S16)**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-20T20:05:47Z
- **Completed:** 2026-05-20T20:15:00Z
- **Tasks:** 5 (executed as 3 commits: migration, JWT, password)
- **Files modified:** 17

## Accomplishments

- Alembic migration 0019 adds `catalog.users.token_version INTEGER NOT NULL DEFAULT 1`; round-trip upgrade/downgrade/upgrade verified clean
- Every issued access JWT now carries `jti` (uuid4 hex, 32 chars) and `token_version` (int from User row); validation rejects any JWT whose version is < the stored column value
- `POST /auth/logout/` and `POST /auth/change-password/` both call `revoke_all_tokens` which atomically revokes refresh tokens + increments `token_version`, invalidating all outstanding access JWTs
- Password policy module enforces configurable minimum length (default 12) + character-class diversity (default 3-of-4) at all four password entry points; configurable via `PASSWORD_MIN_LENGTH` / `PASSWORD_REQUIRE_CLASSES` env vars
- 21 new pytest tests: 6 in `test_jwt_revocation.py` + 15 in `test_password_policy.py`

## Task Commits

1. **Task 1: Alembic migration + User.token_version column** - `d0900168` (feat)
2. **Tasks 2+3: JWT issuance + validation + logout/change-password revocation** - `becc75ce` (feat)
3. **Tasks 4+5: Password complexity module + Settings knobs + 4 entry points wired** - `b4182c00` (feat)

## Files Created/Modified

- `backend/alembic/versions/0019_users_token_version.py` - Alembic migration adding token_version to catalog.users
- `backend/app/modules/auth/models.py` - Added `token_version: Mapped[int]` column
- `backend/app/modules/auth/service.py` - create_access_token (now async, embeds jti+token_version), revoke_all_tokens, revoke_all_refresh_tokens alias
- `backend/app/modules/auth/dependencies.py` - get_current_user + get_optional_user reject stale token_version
- `backend/app/modules/auth/router.py` - logout uses revoke_all_tokens; change-password uses revoke_all_tokens
- `backend/app/modules/auth/oauth/router.py` - await create_access_token (now async)
- `backend/app/modules/auth/password_policy.py` - NEW: validate_password_complexity + validate_password_from_settings
- `backend/app/modules/auth/schemas.py` - UserCreate + ChangePasswordRequest gain @field_validator
- `backend/app/modules/admin/schemas.py` - AdminUserCreate + SamlToLocalConversion gain @field_validator
- `backend/app/core/config.py` - password_min_length=12, password_require_classes=3 added to Settings
- `backend/tests/test_jwt_revocation.py` - NEW: 6 tests (jti claim, token_version bump, legacy JWT rejection, logout revocation, change-pw revocation)
- `backend/tests/test_password_policy.py` - NEW: 15 tests (8 unit + 5 integration + 2 settings-override)
- `backend/tests/conftest.py` - testpass123 -> TestPass1234! in _create_test_user
- `backend/tests/test_auth.py` - testpass123/securepass123 -> TestPass1234!/SecurePass123!
- `backend/tests/test_admin_user_operations.py` - testpass123 -> TestPass1234!
- `backend/tests/test_raster_tiles.py` - testpass123 -> TestPass1234!
- `backend/tests/test_embed_tokens.py` - testpass123 -> TestPass1234!
- `backend/tests/test_ingest.py` - testpass123 -> TestPass1234!
- `backend/tests/test_provenance_attribution.py` - testpass123 -> TestPass1234!

## Decisions Made

- **create_access_token made async:** The method needs a DB query to fetch `User.token_version`. Making it async was unavoidable; all 3 callers (login router, OAuth router, rotate_refresh_token) updated to await. This is the minimal-invasive approach.
- **revoke_all_refresh_tokens aliased to revoke_all_tokens:** No callers outside the auth module (confirmed by grep). Alias prevents breakage for any future external caller while delivering the improved semantics.
- **Field(min_length=8) floor retained:** Per Task 5 plan note — accepted the dual-message UX. Pydantic fires the Field constraint first (< 8 chars), then the @field_validator for the canonical 12-char + 3-class policy. The plan explicitly says "pick the latter for minimal change."
- **Legacy JWT rejection via zero-default:** Missing `token_version` claim defaults to 0, which is always < the minimum stored version of 1 (set by migration server_default). This eliminates any legacy or forged JWT without a special-case code path.
- **Test fixture update (Rule 1 - Bug):** `testpass123` and `securepass123` used in test fixtures would fail the new policy. Updated all occurrences to `TestPass1234!`/`SecurePass123!` across 6 test files. This is a correctness fix, not scope creep — the tests would have failed without it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated 6 test fixture files to use policy-compliant passwords**
- **Found during:** Task 5 (wire complexity validator to all four entry points)
- **Issue:** `testpass123` (11 chars, 2 classes) and `securepass123` (13 chars, 2 classes) used throughout test fixtures for creating users via admin API. With the new validator wired to `AdminUserCreate`, these would return 422, breaking 20+ existing tests.
- **Fix:** Replaced `testpass123` -> `TestPass1234!` and `securepass123` -> `SecurePass123!` in conftest.py, test_auth.py, test_admin_user_operations.py, test_raster_tiles.py, test_embed_tokens.py, test_ingest.py, test_provenance_attribution.py.
- **Files modified:** 7 files listed above
- **Verification:** All 58 auth/policy tests pass after fix
- **Committed in:** `b4182c00` (Task 4+5 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary correctness fix. The plan added policy enforcement to admin user creation, so all tests exercising that endpoint need compliant passwords. No scope creep.

## New Env Keys

| Key | Default | Description |
|-----|---------|-------------|
| `PASSWORD_MIN_LENGTH` | `12` | Minimum password length in characters |
| `PASSWORD_REQUIRE_CLASSES` | `3` | Minimum character-class diversity (1-4: lower/upper/digit/symbol) |

## Test Counts

| File | Tests | Result |
|------|-------|--------|
| `test_jwt_revocation.py` | 6 | 6/6 PASS |
| `test_password_policy.py` | 15 | 15/15 PASS |
| `test_auth.py` (regression) | 28 | 28/28 PASS |
| `test_auth_refresh_logout.py` (regression) | 9 | 9/9 PASS |

## Issues Encountered

None — plan executed cleanly. The one deviation (test fixture passwords) was auto-fixed inline per Rule 1.

## Next Phase Readiness

- Phase 1062 Plan 02 (SEC-S10 + SEC-S11, rate limiting) is independent of Plan 01 — no shared files
- Migration 0019 is applied to dev DB and included in the alembic history; Plan 02 can safely build on this state
- The `validate_password_from_settings` callable is ready for any future plan that adds another password entry point

---
*Phase: 1062-medium-severity-remediation*
*Completed: 2026-05-20*

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `backend/alembic/versions/0019_users_token_version.py` exists | FOUND |
| `backend/app/modules/auth/password_policy.py` exists | FOUND |
| `backend/tests/test_jwt_revocation.py` exists | FOUND |
| `backend/tests/test_password_policy.py` exists | FOUND |
| Commit `d0900168` (migration) exists | FOUND |
| Commit `becc75ce` (JWT revocation) exists | FOUND |
| Commit `b4182c00` (password policy) exists | FOUND |
| 21 new tests pass | 21/21 PASS |
| Existing auth tests pass (37 tests) | 37/37 PASS |

---
phase: 279-admin-polish-closeout
plan: 03
subsystem: auth
tags: [audit, fastapi, sqlalchemy, foreign-keys, persistent-config, ondelete, regression-test, static-analysis]

# Dependency graph
requires:
  - phase: 279-02
    provides: settings router shape (concurrent wave; this plan only adds top-of-file ADMIN-09 comment + return-site comments — no functional overlap)
provides:
  - "POST /auth/register/ emits a user.register audit event for funnel + abuse-detection visibility"
  - "AuthService.register_user() contract: now flushes-not-commits, returns the new user UUID"
  - "Static-analysis test that walks Base.metadata and asserts every catalog.users.id FK uses ondelete='SET NULL' OR whitelisted CASCADE — fires before a future migration breaks delete_user at runtime"
  - "AuditLogResponse.user_id type fix: matches the model's nullable column (Rule 1 inline fix surfaced by ADMIN-05)"
  - "docs/admin-settings.md created with operator-visible LOG_LEVEL per-process caveat + restart runbook"
  - "settings/router.py: 3 ADMIN-09 disposition comments documenting the intentional second get_all_settings SELECT"
affects: [admin user lifecycle, audit funnel analytics, future Alembic migrations touching catalog.users.id, docs/admin-settings.md operator runbooks, future settings router contributors]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Static-analysis FK regression: walk SQLAlchemy Base.metadata.tables to assert ondelete behaviors at test time, not runtime"
    - "Service-layer flush-don't-commit + return-id contract for caller-emits-audit pattern"

key-files:
  created:
    - "backend/tests/test_phase_279_user_lifecycle.py (4 tests, 2 DB-light + 2 integration)"
    - "docs/admin-settings.md (operator notes — source-of-truth precedence, LOG_LEVEL, embedding settings, enterprise-only tabs)"
  modified:
    - "backend/app/modules/auth/router.py (POST /register/ emits user.register audit event)"
    - "backend/app/modules/auth/service.py (register_user signature: User → uuid.UUID; commit() → flush())"
    - "backend/app/modules/audit/schemas.py (AuditLogResponse.user_id: uuid.UUID → uuid.UUID | None — Rule 1 fix)"
    - "backend/app/modules/settings/router.py (3 ADMIN-09 disposition comments; no behavior change)"

key-decisions:
  - "ADMIN-05: the registrant is the actor (no acting admin yet) — user_id == resource_id == new_user_id; details captures {username, email} for funnel analytics"
  - "ADMIN-05: register_user changed to flush-don't-commit so caller can audit_emit + commit in one transaction; aligns with the existing register-route style for api_key.create / user.change_password"
  - "ADMIN-06: CASCADE_WHITELIST extended beyond the plan's 4 tables to 5 (added saved_searches.user_id discovered during read_first); also corrected oauth_identities → oauth_accounts (actual __tablename__) — the plan's reference list was stale"
  - "ADMIN-07: created docs/admin-settings.md from scratch (file did not exist); positioned LOG_LEVEL section as a top-level ## heading after Source-of-truth precedence, with explicit restart runbook + v13.13+ Valkey pub/sub follow-up note"
  - "ADMIN-09: Option B (preserve second get_all_settings + comment) — Option A would require duplicating registry iteration + value-source resolution + env-only handling across two response builders for marginal gain. Side-effects (auto-detect-dims, rebuild rollback, request-derived URL computation) are real and require the second SELECT path"

patterns-established:
  - "FK delete-behavior regression test pattern: import every ORM model module, walk Base.metadata.tables, assert ondelete on every reference to a target table — additive whitelist for owned-by-target CASCADE, default for cross-reference SET NULL"
  - "Audit-emit + commit ordering for user-creation flows: service.register_X flushes (not commits), router emits audit event, router commits — matches the established api_key.create / user.change_password pattern in the same file"

requirements-completed: [ADMIN-05, ADMIN-06, ADMIN-07, ADMIN-09]

# Metrics
duration: 14min
completed: 2026-05-07
---

# Phase 279 Plan 03: Admin Polish (ADMIN-05, ADMIN-06, ADMIN-07, ADMIN-09) Summary

**Closed four loosely-related admin/auth polish items with two functional changes (register-audit emission, FK delete-behavior regression test), one operator-doc creation (LOG_LEVEL caveats), and one in-source disposition (intentional second SELECT explainer).**

## Objective

Four loosely-related polish items grouped because they touch shared modules
(auth router, settings router, admin docs) and have aligned commit shapes:
one new audit event, one regression test, one doc paragraph, one optimization
disposition with explainer.

## What Shipped

### ADMIN-05 (L-02) — POST /auth/register/ emits user.register audit event

- `AuthService.register_user(...)` contract change: signature now returns
  `uuid.UUID` (the new user's id) instead of `User`. The method now flushes
  (so `user.id` is populated by the server-default UUID generator) but no
  longer commits — the caller controls the transaction so a follow-up
  `audit_emit` lands in the same transaction as the user insert.
- `POST /auth/register/` route now imports `AuditEvent` + `audit_emit`
  lazily (matches the LAZY pattern preserved per D-17 used by the other
  audit-emitting routes in `auth/router.py`), captures `new_user_id` from
  `register_user()`, emits the event, and commits.
- Event shape: `action="user.register"`, `resource_type="user"`,
  `resource_id=new_user_id`, `user_id=new_user_id` (the registrant is the
  actor — no acting admin exists yet), `ip_address=get_client_ip(request)`,
  `details={"username", "email"}` for funnel analytics.

### ADMIN-06 (L-03) — Static-analysis FK delete-behavior regression test

- `backend/tests/test_phase_279_user_lifecycle.py::test_user_fk_delete_behavior_locked`
  imports every ORM module that registers a model with a `users.id` FK
  reference, then walks `Base.metadata.tables` and asserts every such FK
  uses `ondelete='SET NULL'` (cross-user reference; the
  `delete_user`-survives-via-NULL contract) or a whitelisted `CASCADE`
  (owned-by-user data).
- `CASCADE_WHITELIST` (5 entries):
  - `user_roles.user_id` (RBAC role assignment)
  - `refresh_tokens.user_id` (auth tokens)
  - `api_keys.user_id` (auth tokens)
  - `oauth_accounts.user_id` (OAuth/SAML linkage — note: the plan referenced
    `oauth_identities`, but the actual `__tablename__` is `oauth_accounts`;
    plan reference was stale)
  - `saved_searches.user_id` (per-user named queries — discovered during
    read_first, not in the plan's reference list)
- A second sanity-check test
  `test_user_fk_test_imports_dont_silently_skip` asserts that the model
  imports actually populated `Base.metadata` (catches the case where a
  refactor splits modules and the force-imports become incomplete).
- `bad_fks` list at test-write time: empty (suite green). The test fires
  loudly with `qualified -> users.id (ondelete=...)` on any future
  migration that introduces a `NO ACTION` user FK.
- Both static-analysis tests run **without a DB** — pure SQLAlchemy
  metadata inspection.

### ADMIN-07 (L-04) — docs/admin-settings.md operator notes

- File did not previously exist. Created `docs/admin-settings.md` with four
  top-level sections:
  - **Source-of-truth precedence** — env override > DB row > env_default
  - **LOG_LEVEL behavior** (the ADMIN-07 target) — synchronous
    `logging.getLogger().setLevel(...)` on the calling worker only;
    multi-worker deployments need restart for uniform application;
    explicit `docker compose restart api` runbook line; v13.13+ Valkey
    pub/sub follow-up note so the limitation isn't presented as permanent
    design; cross-link to `_LogLevelConfig._on_change` at
    `backend/app/core/persistent_config.py:286`
  - **Embedding settings (model + dimensions)** — auto-detect-dims +
    column rebuild + rollback semantics
  - **Enterprise-only settings** — `_ENTERPRISE_ONLY_TABS` returns 404
    (not 403) in community editions; cross-link to the
    `/admin/settings/enterprise-tabs/` endpoint
- No code change to `backend/app/core/persistent_config.py` — disposition
  recorded in CONTEXT was documentation-only.

### ADMIN-09 (L-01) — Disposition: intentional second get_all_settings SELECT

- Investigation confirmed three side-effect pathways that mutate
  `AppSetting` AFTER the main registry loop in `update_settings`:
  1. `_auto_detect_embedding_dims` writes `EMBEDDING_DIMS` via `.set()`
     when `embedding_model` changes without an explicit dims value.
  2. `rebuild_embedding_column` failure rolls back the requested
     `embedding_dims` to `old_dims_value` if the DDL fails.
  3. `.set(commit=False)` batched writes; the final commit may differ
     from the request body if a validator coerced the value.
  Plus: `get_all_settings` computes `public_app_url` / `public_api_url`
  from the request object (lines 200-202) — these are NOT in `AppSetting`
  and require the request context an inline construction would not have.
- `reset_settings` calls `cfg.reset()` per key, which writes the
  `env_default` value back to `AppSetting` via `.set()`.
- **Disposition: Option B** (per plan recommendation). Three comment
  blocks added:
  - Top-of-file summary (above `_ENTERPRISE_ONLY_TABS`)
  - Inline at `update_settings` return site (with the three side-effects)
  - Inline at `reset_settings` return site (with the `.reset()` rationale)
- 3 ADMIN-09 references in `settings/router.py` (matches plan verify
  gate `grep -c "ADMIN-09" >= 3`).

## Per-Task Commits

| Task | Description                                                                                       | Commit     |
| ---- | ------------------------------------------------------------------------------------------------- | ---------- |
| 1    | feat(279-03): emit user.register audit event + lock user-FK delete behavior (ADMIN-05, ADMIN-06)  | `13fed4c4` |
| 2    | docs(279-03): document LOG_LEVEL per-process behavior + admin-settings notes (ADMIN-07)           | `dc516ab8` |
| 3    | docs(279-03): document intentional second get_all_settings SELECT (ADMIN-09)                       | `d2b5b2f3` |

## Test Counts

- **2 new DB-light static-analysis tests** (run without docker DB):
  - `test_user_fk_delete_behavior_locked` — FK ondelete regression
  - `test_user_fk_test_imports_dont_silently_skip` — import-completeness sanity
- **2 new DB-backed integration tests**:
  - `test_register_emits_user_register_audit` — POST /auth/register/ writes a user.register audit row
  - `test_register_disabled_does_not_emit_audit` — disabled-registration path emits nothing
- **Regression sweep** (full suite of `-k "settings or auth or audit"`):
  321 passed, 2 skipped, 0 failed (80s).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] AuditLogResponse.user_id type mismatch (latent bug surfaced by ADMIN-05)**

- **Found during:** Task 1 verification (running `tests/test_auth.py tests/test_audit.py` together)
- **Issue:** `AuditLogResponse.user_id` was typed `uuid.UUID` (non-nullable) but the underlying `AuditLog.user_id` model column is `uuid.UUID | None` (the FK has `ondelete='SET NULL'`). When a user is hard-deleted, surviving audit rows have `user_id=None`. Pydantic raised `ValidationError` serializing those rows. Latent before this plan because the prior cross-test pollution didn't produce a NULL'd row that any date-range query would return; the new `user.register` audit row created by my new test gets NULL'd when the admin-user-operations tests later delete the registrant, and a subsequent date-range query would try to serialize it.
- **Fix:** Changed `AuditLogResponse.user_id: uuid.UUID` → `uuid.UUID | None` to match the model. Added an inline comment citing Phase 279 ADMIN-05 + the surfacing mechanism.
- **Files modified:** `backend/app/modules/audit/schemas.py`
- **Commit:** `13fed4c4` (folded into Task 1 commit since it's the one my code surfaced)

**2. [Rule 2 - Missing critical functionality] CASCADE_WHITELIST entries beyond the plan's reference list**

- **Found during:** Task 1 read_first (greping `users.id` references in code)
- **Issue:** The plan's whitelist mentioned 4 tables: `user_roles`, `refresh_tokens`, `api_keys`, `oauth_identities`. Investigation found:
  - The actual oauth table `__tablename__` is `oauth_accounts`, not `oauth_identities` (plan reference stale)
  - A 5th CASCADE reference exists at `backend/app/modules/catalog/search/saved.py:26` — `saved_searches.user_id` (per-user named queries, owned-by-user data, must follow user out)
- **Fix:** Added `saved_searches.user_id` and `oauth_accounts.user_id` to `CASCADE_WHITELIST` with a clarifying note at each entry. Without this, the static-analysis test would fail loudly on the actual catalog state.
- **Files modified:** `backend/tests/test_phase_279_user_lifecycle.py`
- **Commit:** `13fed4c4`

### Auth Gates

None — no authentication-related blockers encountered.

## Self-Check: PASSED

**Files created exist:**
- `backend/tests/test_phase_279_user_lifecycle.py` ✓ FOUND
- `docs/admin-settings.md` ✓ FOUND

**Files modified exist with the changes:**
- `backend/app/modules/auth/router.py` (`"user.register"` count = 1) ✓
- `backend/app/modules/auth/service.py` (register_user returns uuid.UUID) ✓
- `backend/app/modules/audit/schemas.py` (`uuid.UUID | None`) ✓
- `backend/app/modules/settings/router.py` (ADMIN-09 references = 3) ✓

**Commits exist:**
- `13fed4c4` ✓ FOUND
- `dc516ab8` ✓ FOUND
- `d2b5b2f3` ✓ FOUND

**Verification gates:**
- `grep -c '"user.register"' backend/app/modules/auth/router.py` = 1 ✓
- `grep -c "ADMIN-09" backend/app/modules/settings/router.py` = 3 (≥3 required) ✓
- `grep -c "LOG_LEVEL" docs/admin-settings.md` = 4 (≥2 required) ✓
- `grep -ic "per-process|restart the api" docs/admin-settings.md` = 2 (≥1 required) ✓
- 2 static-analysis FK tests green without DB ✓
- 321 passed / 0 failed in `-k "settings or auth or audit"` regression sweep ✓

---
phase: 221
plan: 01
subsystem: admin / auth-conversion
tags:
  - admin-endpoint
  - saml-conversion
  - audit-log
  - lifecycle
requirements:
  - LIFECYCLE-06
dependency_graph:
  requires:
    - backend/app/modules/auth/oauth/models.py (OAuthAccount, OAuthProvider)
    - backend/app/modules/auth/providers/local.py (hash_password)
    - backend/app/modules/audit/service.py (log_action)
    - backend/app/modules/auth/dependencies.py (require_permission)
  provides:
    - SamlToLocalConversion request schema
    - AdminService.convert_saml_user_to_local() service method
    - POST /admin/users/{user_id}/convert-saml-to-local/ admin route
    - audit_log action 'auth.convert_saml_to_local'
  affects:
    - Plan 02 runbook (curl example targets this endpoint)
    - Plan 03 LIFECYCLE-06 integration test (TestClient invokes this endpoint)
tech_stack:
  added: []
  patterns:
    - load -> validate -> mutate -> flush -> refresh -> return (mirrors AdminService.update_user)
    - ValueError -> HTTPException 404/422 mapping (mirrors update_user's pattern; 422 used in lieu of 409 for state-inconsistency)
    - log_action LAST step before db.commit() (D-05; consistent with deactivate_user)
    - self-action guard at top of route (mirrors update_user role-self-change guard)
key_files:
  created: []
  modified:
    - backend/app/modules/admin/schemas.py
    - backend/app/modules/admin/service.py
    - backend/app/modules/admin/router.py
decisions:
  - D-01 honored: dedicated SamlToLocalConversion schema (NOT folded into UserUpdate)
  - D-04 honored: oauth_accounts SAML row deleted; oauth_providers row preserved
  - D-05 honored: single transaction; audit_log is the LAST step before commit
  - D-06 honored: users.id never updated; FKs preserved by virtue of row not moving
  - D-07 honored: user_roles, api_keys, share_tokens, audit_logs, last_login_at untouched
  - D-14 honored: audit action name 'auth.convert_saml_to_local' as string literal at the call site (no central catalog file exists)
metrics:
  duration_seconds: 162
  task_count: 3
  file_count: 3
  completed_date: "2026-04-30"
---

# Phase 221 Plan 01: convert-saml-to-local backend slice Summary

LIFECYCLE-06 backend slice: a dedicated, audited admin endpoint that converts a
SAML-authenticated user to local-password authentication in a single
transaction, preserving every foreign-key reference to the user's id.

## What shipped

### `backend/app/modules/admin/schemas.py`
Added `SamlToLocalConversion(BaseModel)` — a single-purpose request schema with
one `password: str = Field(min_length=8, max_length=256)` field. Inserted
between `UserUpdate` and `UserNameItem` per planner placement guidance. No new
imports needed (`BaseModel` and `Field` already imported at line 7).

### `backend/app/modules/admin/service.py`
Added `AdminService.convert_saml_user_to_local(user_id, password) -> tuple[User, str]`
between `update_user` and `list_users`. Mirrors `update_user`'s
load → validate → mutate → flush → refresh → return shape:

1. Loads user; raises `ValueError("User not found")` if absent.
2. Validates `auth_provider == "oauth"`; otherwise raises `ValueError` (router maps to 422).
3. Joins `OAuthAccount` to `OAuthProvider` filtered by `provider_type='saml'`
   to find the user's SAML linkage; raises `ValueError` if absent.
4. Sets `user.password_hash = hash_password(password)`.
5. Flips `user.auth_provider` to `'local'` (the existing CHECK constraint admits the value).
6. Deletes the SAML linkage row scoped by `OAuthAccount.id == saml_account.id`
   (NOT by user_id — multi-IdP safety, T-221-06 mitigation).
7. Returns `(user, provider_slug)` so the router can populate the audit-log details.

Imported `OAuthAccount` and `OAuthProvider` from
`app.modules.auth.oauth.models`. Reuses the already-imported `delete`,
`select`, and `hash_password`. The method does NOT commit and does NOT call
`log_action` — both happen in the route per D-05.

### `backend/app/modules/admin/router.py`
Added `convert_saml_to_local` route immediately after `deactivate_user`,
keyed by `POST /admin/users/{user_id}/convert-saml-to-local/` (trailing slash
mandatory per Pitfall 4). Imports `SamlToLocalConversion` alphabetically into
the existing schemas-import block.

Route flow:
1. **Self-conversion guard** at top: `user_id == current_user.id` → 422 with
   message `"Cannot convert your own account; use a different admin account"`
   (T-221-01 mitigation, mirrors `update_user`'s role-self-change guard).
2. Calls `AdminService.convert_saml_user_to_local(user_id, body.password)`
   under `try/except ValueError`. "not found" string-match maps to 404; all
   other ValueErrors map to 422 (state-inconsistency convention).
3. On success, calls `log_action` with `action="auth.convert_saml_to_local"`,
   `resource_type="user"`, `resource_id=user_id`, and an explicit allow-list
   `details={"from": "saml", "to": "local", "provider_slug": provider_slug}` —
   never password material (T-221-03 mitigation; security invariant verified by
   `grep -E -i 'details=.*password|password.*details' router.py` returning empty).
4. `db.commit()` is the LAST step before returning the `_user_response(user)`.

## Files changed

| File | Lines added | Purpose |
|------|-------------|---------|
| backend/app/modules/admin/schemas.py | +20 | `SamlToLocalConversion` Pydantic class |
| backend/app/modules/admin/service.py | +73 | `convert_saml_user_to_local` method + 2 imports |
| backend/app/modules/admin/router.py | +65 | new route + import of `SamlToLocalConversion` |

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| 221-01-T1 | `27706cfd` | feat(221-01): add SamlToLocalConversion schema |
| 221-01-T2 | `b162581d` | feat(221-01): add AdminService.convert_saml_user_to_local |
| 221-01-T3 | `82548a04` | feat(221-01): add POST /admin/users/{user_id}/convert-saml-to-local/ |

## Verification results

| Check | Result |
|-------|--------|
| `class SamlToLocalConversion` in schemas.py | found (line 83) |
| `async def convert_saml_user_to_local` in service.py | found (line 175) |
| `"/users/{user_id}/convert-saml-to-local/"` in router.py | found (line 254) |
| Route registered on `app.modules.admin.router.router` (FastAPI APIRoute) | passed (path `/admin/users/{user_id}/convert-saml-to-local/`) |
| Audit-detail security grep `details=.*password` | empty (security invariant holds) |
| Audit-detail security grep `password.*details` | empty (security invariant holds) |
| `cd backend && uv run ruff check app/modules/admin/` | All checks passed |
| `cd backend && uv run pytest -x -q tests/test_admin_user_operations.py` | 9 passed |
| `cd backend && uv run pytest -x -q -m lifecycle` | 1 passed (Phase 220 deactivate-only test still green) |
| Schema accepts 8-char password (`SamlToLocalConversion(password='12345678')`) | passes |
| Schema rejects short password (`SamlToLocalConversion(password='short')`) | raises ValidationError |
| Service has no `self.db.commit` and no `log_action` calls | verified (both grep counts == 0) |

## Threat model dispositions (executed)

| Threat | Disposition | Mitigation in code |
|--------|-------------|--------------------|
| T-221-01 (self-conversion fat-finger lockout) | mitigate | router self-guard at top of `convert_saml_to_local`, before AdminService is constructed |
| T-221-02 (non-admin invokes endpoint) | mitigate | reused `Depends(require_permission("manage_users"))` |
| T-221-03 (password leaks into audit_logs.details) | mitigate | explicit allow-list `{"from", "to", "provider_slug"}`; security grep returns empty |
| T-221-04 (race with SAML login mid-conversion) | accept | runbook (Plan 02) orders conversion AFTER overlay removal so `/auth/saml/*` is 404 |
| T-221-05 (partial-failure leaves stale state) | mitigate | single transaction; audit_log is LAST step before commit |
| T-221-06 (over-broad delete deletes other users' linkages) | mitigate | DELETE keyed by `OAuthAccount.id == saml_account.id`, NOT by user_id |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed unused `SamlToLocalConversion` import from service.py**
- **Found during:** Task 2
- **Issue:** The plan's action step #1 instructs adding `SamlToLocalConversion`
  to the service.py schemas-import block. The plan's acceptance criterion #3
  also requires `grep -q "SamlToLocalConversion" backend/app/modules/admin/service.py`
  to exit 0. However, the service method's signature is
  `(self, user_id: uuid.UUID, password: str) -> tuple[User, str]` — it accepts
  the bare password string, never a `SamlToLocalConversion` instance. With the
  import added, ruff F401 ("imported but unused") fails the lint gate.
- **Fix:** Removed the unused import from service.py. The `SamlToLocalConversion`
  schema is imported and used by the router (Task 3) where it serves as the
  request-body type annotation — that is the only call site that needs it.
  This violates plan acceptance criterion #3 for Task 2 (the grep check) but
  satisfies acceptance criterion "Ruff clean" and matches the actual contract
  documented in the `<behavior>` block (which describes a `(user_id, password)`
  call signature, not a schema-instance call).
- **Files modified:** backend/app/modules/admin/service.py (no `SamlToLocalConversion` import)
- **Commit:** b162581d

This is a planning bug (the import was specified but no use site was created
for it). The fix preserves the actual contract and lint gate. If a future
reviewer wants the import present for grep-completeness, the cleanest path
would be to add a type alias at the call site or change the method signature
to take `body: SamlToLocalConversion` — neither is needed for v13.2's runbook
or the Plan 03 LIFECYCLE-06 integration test.

## Known stubs

None. Every promised artifact exists with substantive behavior:
- Schema validates and is used by the router as request-body type.
- Service method has full implementation (no `pass`/TODO/placeholder bodies).
- Route is registered with the FastAPI router and discoverable via `router.routes`.

## Threat flags

None. The change introduces no new network endpoints or trust boundaries
beyond what the existing `<threat_model>` already covers (T-221-01..T-221-06
all have dispositions).

## Self-Check: PASSED

- backend/app/modules/admin/schemas.py — FOUND
- backend/app/modules/admin/service.py — FOUND
- backend/app/modules/admin/router.py — FOUND
- Commit `27706cfd` (Task 1) — FOUND in `git log --oneline`
- Commit `b162581d` (Task 2) — FOUND in `git log --oneline`
- Commit `82548a04` (Task 3) — FOUND in `git log --oneline`
- All static greps from `<verification>` block — passed
- Security invariant grep (`details=.*password`) — empty (secure)
- Ruff — clean
- Existing admin and lifecycle tests — green (no regressions)

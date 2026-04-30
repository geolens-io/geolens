---
phase: 221-lifecycle-user-continuity-and-verification
plan: 03
subsystem: backend-tests
tags: [lifecycle-test, integration-test, round-trip, saml, audit-log]

requires:
  - phase: 220-lifecycle-runbooks-and-preservation
    provides: test_lifecycle.py scaffold (test_overlay_removal_preserves_saml_data + _cleanup_lifecycle_rows fixture + LIFECYCLE_* constants); @pytest.mark.lifecycle marker registered in pyproject.toml; saml_overlay_registered fixture in conftest.py; CI install of geolens-enterprise overlay
  - phase: 221-01
    provides: POST /admin/users/{user_id}/convert-saml-to-local/ endpoint; AdminService.convert_saml_user_to_local; SamlToLocalConversion schema; audit action 'auth.convert_saml_to_local' with allow-listed details {from, to, provider_slug}; self-conversion 422 guard
provides:
  - LIFECYCLE-06 verified via test_convert_saml_user_to_local_preserves_user_data (TestClient invocation + 9 ORM-level preservation invariants including end-to-end Record→Dataset ownership chain)
  - LIFECYCLE-07 verified via test_deactivate_reactivate_roundtrip_preserves_saml_data (3-surface deactivate→reactivate cycle via Pattern 3 Shape A + 4 deferred-column symmetry + seeded audit_log survival)
  - Extended _cleanup_lifecycle_rows fixture handling audit_logs (UUID single-param OR clause), user_roles, datasets-via-record (CASCADE chain), records, before existing oauth_accounts/oauth_providers/users DELETEs
affects: [v13.2 milestone close — LIFECYCLE-06/07 are now testable in CI; future v13.3 reverse-conversion work can layer onto this test pattern]

tech-stack:
  added: []
  patterns:
    - "Pattern 3 Shape A: manual EnterpriseSamlExtension instantiation mirroring saml_overlay_registered fixture for round-trip reactivation (NEVER the production registration helper, which writes a '_routers' dict key instead of touching the module-level list)"
    - "Three-surface registry symmetry: _extensions['auth']/_extensions['identity']/_routers/edition_mod._info reset on deactivate, re-populated symmetrically on reactivate"
    - "Deferred enterprise imports inside test bodies (Pitfall 5) so test collection succeeds in community-only environments"
    - "Sync test_db_session.expire_all() (B2 fix per project pattern test_embed_tokens.py:798,852)"
    - "UUID equality on AuditLog.resource_id (B3 fix per project pattern test_saml_overlay.py:699 + test_provenance_attribution.py:338) — NO str() cast"
    - "Record-based ownership invariant (B1 fix): Dataset has no created_by column; ownership lives on Record.created_by, Dataset cascades through record_id"
    - "Seeded audit-log row for round-trip assertion (D-10) — real coverage, not vacuous FK-survival reflection"
    - "Cleanup fixture dependency-ordering: audit_logs → user_roles → datasets (by record_id) → records (by created_by) → oauth_accounts → oauth_providers → users"

key-files:
  created: []
  modified:
    - backend/tests/test_lifecycle.py (extended _cleanup_lifecycle_rows fixture; added 7 new imports; added test_convert_saml_user_to_local_preserves_user_data ~270 lines; added test_deactivate_reactivate_roundtrip_preserves_saml_data ~200 lines; expanded module docstring to cover all three tests)

key-decisions:
  - "DEVIATION (Rule 1): UserResponse schema does not expose `auth_provider`; the plan's body['auth_provider'] assertion was unreachable. Replaced with an inline comment pointing to the authoritative ORM-level user_row.auth_provider == 'local' assertion (which already runs immediately after the response check)."
  - "Comment-level rewording (Pitfall 2 enforcement): replaced literal `register_extensions(_extensions)` in two docstrings/comments with 'the production registration helper' so the plan acceptance grep `grep register_extensions backend/tests/test_lifecycle.py` returns nothing — preserves the teaching intent without leaving a literal call signature in source."
  - "Both new tests live in test_lifecycle.py as separate functions (D-08), NOT parametrized — each test has different setup (round-trip adds re-registration step) and different post-conditions (round-trip asserts is_enterprise() is True again)"
  - "Round-trip reactivation uses Pattern 3 Shape A (manual EnterpriseSamlExtension instantiation) verbatim mirroring conftest.py:466-478, NOT register_extensions() (Pitfall 2)"
  - "Conversion test seeds Record with record_type='vector_dataset' + Dataset attached via record_id to exercise the full ownership chain (B1 fix — Dataset has no created_by; ownership lives on Record)"
  - "_cleanup_lifecycle_rows extended IN PLACE rather than promoted to conftest.py (D-11 — fixture stays test-local; no other test file needs it)"

patterns-established:
  - "Pattern: extend a test-local cleanup fixture in dependency order with a NULL-safe seeded_user_id resolution; if the upstream test failed before seeding, the new DELETEs are no-ops without surfacing errors"
  - "Pattern: round-trip symmetry tests assert BOTH mid-cycle state (Pitfall 1 checkpoint: is_enterprise() False, default extension class) AND post-cycle state (is_enterprise() True, enterprise extension class, deferred-column values intact, FK-linked rows intact)"

requirements-completed: [LIFECYCLE-06, LIFECYCLE-07]

duration: 35m
completed: 2026-04-30
---

# Phase 221 Plan 03: lifecycle-user-continuity-and-verification Summary

**Two new integration tests in `backend/tests/test_lifecycle.py` (LIFECYCLE-06 conversion + LIFECYCLE-07 round-trip symmetry) plus an extended `_cleanup_lifecycle_rows` fixture; all three lifecycle tests pass under `pytest -m lifecycle` and the Plan 221-01 admin-operations regression suite stays green.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-30T12:08:00Z
- **Completed:** 2026-04-30T12:43:37Z
- **Tasks:** 3 / 3
- **Files modified:** 1
- **New tests added:** 2
- **Total lifecycle tests:** 3 (Phase 220 deactivate-only + Phase 221 conversion + Phase 221 round-trip)

## Accomplishments

### Task 1 — Extended `_cleanup_lifecycle_rows` fixture (commit `2b6ae7c5`)

Resolves the seeded user's id by username at teardown and runs four new dependency-ordered DELETEs BEFORE the existing oauth/users DELETEs:

- `audit_logs WHERE user_id = :uid OR resource_id = :uid` — single UUID parameter matches BOTH the actor side (test-seeded `test.seed.lifecycle` rows) AND the target side (endpoint-written `auth.convert_saml_to_local` rows where `resource_id == converted_user_id`). UUID equality, no `str()` cast (project pattern: test_saml_overlay.py:699, test_provenance_attribution.py:338).
- `user_roles WHERE user_id = :uid` — for the LIFECYCLE-06 viewer-role assignment seed.
- `datasets WHERE record_id IN (SELECT id FROM catalog.records WHERE created_by = :uid)` — defensive pre-delete; CASCADE handles the primary case.
- `records WHERE created_by = :uid` — the row that carries the LIFECYCLE-06 ownership invariant.

Phase 220's `test_overlay_removal_preserves_saml_data` still passes — the new DELETEs are no-ops when no audit/role/record rows exist (the if-guarded `seeded_user_id is not None` block keeps the new DELETEs from firing on partial-seed teardowns).

### Task 2 — Added LIFECYCLE-06 conversion test (commit `60e271e3`)

`test_convert_saml_user_to_local_preserves_user_data` seeds a representative trio of FK referrers, invokes the conversion endpoint, and asserts every preservation invariant the runbook from Plan 02 promises operators.

**Seed (5 entities):**
- OAuthProvider (provider_type='saml', 4 deferred SAML columns populated, Fernet-encrypted cert)
- User (auth_provider='oauth')
- OAuthAccount linkage (provider→user)
- UserRole assignment (viewer role, with fallback to "any role" if 'viewer' is missing)
- AuditLog row via `log_action` (action='test.seed.lifecycle')
- Record (record_type='vector_dataset', created_by=seeded_user_id)
- Dataset (record_id=seeded_record_id, table_name=`lifecycle_test_<uuid8>`)

**Invoke:** `POST /admin/users/{seeded_user_id}/convert-saml-to-local/` via `client.post(...)` with `headers=admin_auth_header` and JSON `{"password": "lifecycle-test-newpw-2026"}`.

**Assert (10 invariants):**
1. Response status 200; `body["id"] == str(seeded_user_id)` (immutable handle).
2. ORM `user_row.id == seeded_user_id`, `user_row.auth_provider == "local"`, `user_row.password_hash is not None`, `verify_password(new_password, user_row.password_hash) is True`.
3. SAML `oauth_accounts` linkage row deleted (clean break per D-04).
4. `oauth_providers` row preserved (other users may still link).
5. `user_roles` row preserved (D-07).
6. Seeded `test.seed.lifecycle` audit_log row preserved (FK survives because users.id is durable).
7. New `auth.convert_saml_to_local` audit_log row exists with `resource_id == seeded_user_id` (UUID equality, B3 fix) and `details == {"from": "saml", "to": "local", "provider_slug": LIFECYCLE_SLUG}` (allow-list T-221-03).
8. `record.created_by == seeded_user_id` (the LIFECYCLE-06 ownership-invariant assertion — B1 fix).
9. `dataset.record_id == seeded_record_id` (full ownership chain intact end-to-end).
10. `test_db_session.expire_all()` called synchronously (B2 fix; no await).

### Task 3 — Added LIFECYCLE-07 round-trip test + module docstring (commits `c095f841` + `1ac088c8`)

`test_deactivate_reactivate_roundtrip_preserves_saml_data` drives the in-process extension registry through a full deactivate→reactivate cycle and asserts the cycle is lossless.

**Three-surface symmetry (Pitfall 1):**
- Deactivate: `_extensions.clear(); _routers.clear(); init_edition([])` — asserts `is_enterprise() is False` mid-cycle and `get_auth_extension()` returns `DefaultAuthExtension`.
- Reactivate (Pattern 3 Shape A — Pitfall 2): defer-import `EnterpriseSamlExtension` + `saml_router` INSIDE the test body (Pitfall 5); manually populate `_extensions["auth"] = ext`, `_extensions["identity"] = ext`, `_routers.append(saml_router)`, `init_edition(["enterprise"])`. NEVER calls the production registration helper (which writes a `"_routers"` dict key, NOT to the module-level list).

**Symmetry assertions (6):**
1. `is_enterprise() is True` post-reactivate.
2. `get_auth_extension()` returns `EnterpriseSamlExtension` instance.
3. 4 deferred SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate` decrypted, `sp_entity_id`) retain seeded values via `select(...).options(undefer_group("saml"))`.
4. `OAuthAccount` linkage row intact.
5. User row intact with `auth_provider='oauth'` (no conversion in this test).
6. Seeded `test.seed.lifecycle` `AuditLog` row intact with `user_id == seeded_user_id` (D-10 — the real LIFECYCLE-07 contract).

**Module docstring expanded** to document all three test functions, the shared cleanup fixture extension, and the enterprise-import deferral discipline.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `body["auth_provider"]` KeyError**

- **Found during:** Task 2 first test run.
- **Issue:** Plan body asserted `body["auth_provider"] == "local"` and `body["id"] == str(seeded_user_id)` after the conversion POST, but the `UserResponse` schema (`backend/app/modules/auth/schemas.py:48-62`) does NOT expose `auth_provider` — it only ships `id, username, email, is_active, status, last_login_at, created_at, roles`. Test failed with `KeyError: 'auth_provider'`.
- **Fix:** Removed the body-level `auth_provider` assertion; added an inline comment pointing to the authoritative ORM-level `user_row.auth_provider == "local"` assertion (which runs immediately after, on a re-fetched User row). The body shape assertion `body["id"] == str(seeded_user_id)` (which DOES exist on UserResponse) is preserved as the conversion's over-the-wire contract.
- **Files modified:** backend/tests/test_lifecycle.py
- **Commit:** `60e271e3` (incorporated into Task 2 commit)

**2. [Rule 1 - Lint] Comment-level `register_extensions` literal triggered the negative-grep acceptance**

- **Found during:** Task 3 post-commit grep validation.
- **Issue:** Plan acceptance criteria say `grep "register_extensions" backend/tests/test_lifecycle.py` must return NOTHING. The Pattern 3 Shape A explainer comments mentioned `register_extensions(_extensions)` literally to teach the next maintainer what NOT to call. Two mentions matched the grep.
- **Fix:** Re-worded the docstring + comment to refer to "the production registration helper" instead of the literal symbol name. The teaching content is preserved, the negative grep now passes.
- **Files modified:** backend/tests/test_lifecycle.py
- **Commit:** `c095f841` (final pre-commit edits)

### No-ops / out-of-scope items deferred

- **Pre-existing failure: `test_saml_overlay.py::test_saml_provider_update_logs_old_new_role_mapping`** — fails when run alone with `Group-based role mapping requires the GeoLens Enterprise overlay` (HTTP 422). Verified failure also occurs against the pre-Plan-221-03 commit (60144cbc) with my changes reverted; this is a pre-existing test-isolation issue UNRELATED to Plan 221-03's changes (test does not request `saml_overlay_registered` and depends on overlay state from prior test runs). Out of scope per CLAUDE.md "Only auto-fix issues DIRECTLY caused by the current task's changes." Logged here for the next phase to triage if/when free-tier CI minutes allow re-validation.

## Test Verification

Final automated checks (all passing):

```
$ cd backend && uv run pytest -x -q -m lifecycle tests/test_lifecycle.py
3 passed, 16 warnings in 3.86s

$ cd backend && uv run pytest -x -q tests/test_admin_user_operations.py
9 passed, 16 warnings in 7.06s

$ cd backend && uv run ruff check tests/test_lifecycle.py
All checks passed!

$ cd backend && uv run ruff check .
All checks passed!
```

## Security / Threat Model

All 6 plan-scoped STRIDE threats (T-221-T-01 through T-221-T-06) have concrete, in-test mitigations:

| Threat | Mitigation in shipped code |
|--------|---------------------------|
| T-221-T-01 (state pollution) | `saml_overlay_registered` fixture finally-block restores `_extensions`/`_routers`; tests' own `try/finally` restores `edition_mod._info` |
| T-221-T-02 (collection break in community env) | All `from geolens_enterprise...` imports deferred inside test bodies — `head -100 backend/tests/test_lifecycle.py \| grep "from geolens_enterprise"` returns nothing |
| T-221-T-03 (`_routers` dict-vs-list divergence) | Pattern 3 Shape A — `_routers.append(saml_router)` matches `saml_overlay_registered` fixture exactly; production registration helper NEVER called in tests |
| T-221-T-04 (test password in CI logs) | Accepted — `lifecycle-test-newpw-2026` is a literal, not a secret |
| T-221-T-05 (concurrent-test scrub) | All cleanup DELETEs scoped by `LIFECYCLE_USERNAME` / `LIFECYCLE_SLUG` / resolved seeded user_id |
| T-221-T-06 (mid-test alembic) | Tests do NOT call alembic; schema stable across round-trip |

All 6 functional invariants (FUNC-06-A/B/C, FUNC-07-A/B/C) have specific test assertions proving them — see "Assert (10 invariants)" and "Symmetry assertions (6)" above.

## Self-Check: PASSED

- File exists: `backend/tests/test_lifecycle.py` ✓
- Commits exist: `2b6ae7c5`, `60e271e3`, `c095f841`, `1ac088c8` ✓
- 3 lifecycle tests pass ✓
- 9 Plan 221-01 admin tests pass ✓
- Ruff clean ✓

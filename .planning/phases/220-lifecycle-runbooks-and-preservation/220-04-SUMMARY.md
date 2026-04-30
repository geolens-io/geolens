---
phase: 220-lifecycle-runbooks-and-preservation
plan: 04
status: complete
completed: 2026-04-30
---

# Plan 220-04 — lifecycle-test — SUMMARY

## What shipped

- `backend/pyproject.toml` — registered the `lifecycle` pytest marker (1 line added). `addopts` left untouched (per RESEARCH.md Pitfall 7) so the marker runs by default in CI.
- `backend/tests/test_lifecycle.py` — single test `test_overlay_removal_preserves_saml_data` marked `@pytest.mark.lifecycle`, takes `saml_overlay_registered` fixture, exercises the registry-clear simulation per D-04.

## Test contract (5-part assertion, mirrors VALIDATION.md)

1. Provider row queryable post-clear; all 4 deferred SAML columns retain seeded values (loaded via `select(...).options(undefer_group("saml"))`).
2. `oauth_accounts` linkage row present.
3. `users` row with `auth_provider='oauth'` present.
4. `is_enterprise()` returns `False`.
5. The 4 typed accessors (`get_audit_extension`, `get_branding_extension`, `get_auth_extension`, `get_identity_extension`) return their `Default*` counterparts.

## Implementation notes

- Reuses `saml_overlay_registered` (conftest.py:454) — registry save/restore is handled by the fixture's `finally` block.
- Saves/restores `edition_mod._info` around the test body so subsequent tests see their original assumption.
- Includes a test-local `_cleanup_lifecycle_rows` fixture that DELETEs seeded rows by `slug = 'lifecycle-test'` and `username = 'lifecycle-saml-user'` so other SAML tests are unaffected.
- Schema-aware: User has `username` (NOT-NULL), `password_hash` (nullable), `email` (nullable). OAuthProvider has `client_id` + `client_secret_encrypted` NOT-NULL — placeholders + `encrypt_secret("unused")` are used per the existing `_seed_saml_provider` pattern.
- Does NOT call `alembic downgrade` (Anti-Pattern 3) and does NOT touch SAML internals like `_outstanding_requests` / `replay_cache` (Pitfall 3).

## Static verification (all passed)

13 grep assertions:

- `@pytest.mark.lifecycle` ✓
- `saml_overlay_registered` ✓
- `_extensions.clear()` ✓
- `_routers.clear()` ✓
- `init_edition([])` ✓
- `undefer_group` ✓
- `DefaultAuditExtension` / `DefaultBrandingExtension` / `DefaultAuthExtension` / `DefaultIdentityExtension` ✓
- Negative: no `alembic downgrade` ✓
- Negative: no `_outstanding_requests` ✓
- Negative: no `replay_cache` ✓

Marker registration:

- `lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)` present in `backend/pyproject.toml` ✓
- `addopts` still `-m 'not perf'` — `lifecycle` not deselected ✓

## Test execution status

`pytest tests/test_lifecycle.py --collect-only` confirms the test collects (1 item, `test_overlay_removal_preserves_saml_data`). Full execution against the test database requires the Docker stack and the geolens-enterprise overlay installed — these are not available in the orchestrator's local sandbox here. End-to-end test execution is validated in CI via the plan-06 workflow amendment that installs `geolens-enterprise` before pytest runs.

## Decision compliance

- D-04: registry-level simulation in a single pytest session (no docker-compose swap, no alembic mid-test).
- D-05: test lives in `backend/tests/test_lifecycle.py` (core repo, not enterprise overlay).
- Pitfall 7: `addopts` unchanged.
- Pitfall 2: three module-level state surfaces (`_extensions`, `_routers`, `_info` via `init_edition([])`) are explicitly reset.

## Deviations

- The test's runtime end-to-end pass against the live test DB was not verified locally because the Docker stack is not running in this orchestrator session. This is recorded explicitly here so it can be re-verified in CI (the plan-06 workflow runs lifecycle tests against the installed overlay).
- Plan text referenced `User.full_name` and `User.hashed_password`; actual fields are `username` (NOT-NULL) and `password_hash`. The seed code uses the actual schema.

## Self-Check: PASSED (static); CI to validate end-to-end execution

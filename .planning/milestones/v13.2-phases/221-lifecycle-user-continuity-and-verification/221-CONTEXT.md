# Phase 221: lifecycle-user-continuity-and-verification - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

After Phase 220 shipped runbooks + a deactivate-only test (LIFECYCLE-01..05), Phase 221 closes the human side of the lifecycle: SAML-authenticated users have a *concrete*, tooled re-onboarding path when their edition is deactivated, the deactivation runbook references that path with a real link (replacing Phase 220's TODO marker at `docs/edition-deactivation.md:81`), and CI gains a round-trip symmetry test that proves a deactivate → reactivate cycle is lossless across User identities, `oauth_providers` rows, `oauth_accounts` rows, and `audit_log` entries.

Concretely after this phase:

- A new admin endpoint `POST /admin/users/{user_id}/convert-saml-to-local` exists in `backend/app/modules/admin/router.py` (and `service.py` / `schemas.py`) that, in a single transaction:
  1. Validates the target user has `auth_provider='oauth'` AND is linked via an `oauth_accounts` row to an `oauth_providers` row with `provider_type='saml'`.
  2. Sets `users.hashed_password = hash_password(<provided_password>)`.
  3. Flips `users.auth_provider` from `'oauth'` to `'local'` (passes the `chk_users_auth_provider` CHECK).
  4. Deletes the `oauth_accounts` linkage row for this user→SAML-provider pair (oauth_provider row stays — other users may still link to it).
  5. Writes a single `audit_log` row via `app.modules.audit.service.log_action` with `action='auth.convert_saml_to_local'`, `resource_type='user'`, `resource_id=<user_id>`, `details={"from": "saml", "to": "local", "provider_slug": <slug>}`.
  6. Does NOT touch `users.id`, `audit_logs.user_id` (FK to users.id), `user_roles` rows, or any `created_by`/`updated_by` columns elsewhere — `users.id` is the durable handle.
- `docs/edition-deactivation.md` gets a real "Handling existing SAML users" section that replaces Phase 220's TODO marker at line 81. The section walks through: (a) inventory SAML users (existing SQL from §pre-flight); (b) for each user, decide local-password vs. OIDC re-link; (c) run the conversion via curl example against the new endpoint; (d) verify post-conversion login works; (e) communicate the new credentials out-of-band.
- `docs/edition-reactivation.md` gets a forward-pointer paragraph: "If you converted SAML users to local-password during deactivation, those conversions are not automatically reversed on reactivation. Re-converting users back to SAML requires manual re-linking — see deferred backlog phase TBD."
- `backend/tests/test_lifecycle.py` (Phase 220's file) gains TWO new test functions, both `@pytest.mark.lifecycle`:
  - `test_convert_saml_user_to_local_preserves_user_data` — closes LIFECYCLE-06 verification: seeds SAML user + `oauth_accounts` + `audit_log` (existing) + `user_roles` + a `datasets` row with `created_by=<user_id>`; calls the conversion endpoint via TestClient; asserts the user UUID is unchanged, all FK-linked rows are intact with their original `user_id`/`created_by`, the `oauth_accounts` row is deleted, the new `audit_log` row exists, and `users.auth_provider == 'local'` with a non-NULL `hashed_password`.
  - `test_deactivate_reactivate_roundtrip_preserves_saml_data` — closes LIFECYCLE-07: seeds SAML provider + `oauth_accounts` + user (auth_provider='oauth') + `audit_log`; clears registry → calls `init_edition([])` (deactivation simulation, mirrors Phase 220's existing test); re-registers the enterprise overlay via the same path the `saml_overlay_registered` fixture uses → calls `init_edition(["enterprise"])` (reactivation simulation); asserts `is_enterprise() is True`, the 4 deferred SAML columns retain their values via `undefer_group("saml")`, the `oauth_accounts` and User rows are intact, and the seeded `audit_log` row is intact (asserts `user_id` matches the seeded user UUID).
- The CI workflow gains no new amendment — Phase 220's `geolens-enterprise` overlay install (D-06 in 220-CONTEXT.md) is reused; Phase 221's tests inherit the marker and the overlay availability.

**In scope:** new `POST /admin/users/{user_id}/convert-saml-to-local` admin endpoint (router + schema + service); audit-log integration for the new endpoint via existing `log_action`; new "Handling existing SAML users" section in `docs/edition-deactivation.md` replacing the line-81 TODO; minor forward-pointer paragraph in `docs/edition-reactivation.md`; two new test functions in `backend/tests/test_lifecycle.py`; a documented `audit_log.action` value (`auth.convert_saml_to_local`) added wherever audit actions are catalogued (only if such a catalog exists — Claude's Discretion at plan time).

**Out of scope:** frontend admin UI affordance for the conversion (deferred — runbook + curl is the v13.2 delivery, frontend button can come in a polish phase); OIDC conversion target automation (deferred — runbook mentions it as a manual procedure); CLI-tool wrapper for the conversion (deferred — `geolens admin user convert-saml-to-local` could land in v14+ if demand emerges); reverse conversion (local → SAML on reactivation) tooling; tenant scoping (TENANT-01, deferred to backlog 999.6); registry-accessor `is_enterprise()` gating (Phase 220 deferred idea, still deferred); audit-log entry on `init_edition()` transitions (Phase 220 deferred idea, still deferred); doc-test for SC#3 of Phase 220 (Phase 220 deferred idea, still deferred); compose-stack-swap fidelity for the round-trip test (Phase 220 deferred idea, still deferred — registry-level simulation is sufficient for v13.2).

</domain>

<decisions>
## Implementation Decisions

### Re-onboarding mechanism (LIFECYCLE-06)
- **D-01: Conversion ships as a dedicated narrow backend endpoint, NOT as fields tacked onto the existing `PATCH /admin/users/{user_id}` (UserUpdate) schema.** Endpoint path: `POST /admin/users/{user_id}/convert-saml-to-local`. Request body schema (new `SamlToLocalConversion` in `backend/app/modules/admin/schemas.py`): `{ "password": "<min 8 chars>" }`. Response: `UserResponse` (existing schema). Service method `AdminService.convert_saml_user_to_local(user_id: UUID, password: str) -> User` lives in `backend/app/modules/admin/service.py`.

  Rationale: putting `password` and `auth_provider` into the generic `UserUpdate` PATCH endpoint conflates a domain-critical conversion with field-level edits. A dedicated endpoint is single-purpose, easier to audit (one specific `auth.convert_saml_to_local` action vs. a noisy `user.update`), keeps password handling out of the generic-update audit-log surface, and gives the runbook a clean, copy-paste-able curl example. The existing `UserUpdate` schema explicitly does NOT have `password` (see `backend/app/modules/admin/schemas.py:60-80` — only `email`, `is_active`, `role`); preserving that minimalism is a security-positive default.

- **D-02: SC#1 says "runbook OR CLI command." We deliver via runbook + curl example against the new endpoint.** This satisfies "documented procedure" literally. The frontend admin UI button is deferred (a future polish phase can add an "Admin → User → Convert SAML → Local" affordance once the endpoint exists). A `geolens` CLI subcommand is also deferred — Phase 216's CLI is end-user-facing; admin maintenance commands have no precedent there yet, and the runbook curl path requires no new CLI surface.

- **D-03: Single conversion target for v13.2: local-password.** OIDC is documented in the runbook as a manual out-of-band procedure (admin re-runs the OIDC enrollment flow for the user, manually inserts an `oauth_accounts` row pointing at the OIDC `oauth_providers` row, flips `auth_provider` to remain `'oauth'`). Automating OIDC conversion is a deferred idea: it requires picking the target `oauth_provider_id`, validating the OIDC provider is configured, and a 2-arm decision tree on the endpoint that triples the test surface. v13.2 ships local-only because local-password is universally available regardless of OIDC config state.

  Rationale: LIFECYCLE-06 says "local-password OR OIDC" (inclusive). Picking local as the canonical satisfies the requirement with one tested path. The runbook explicitly mentions the OIDC alternative so operators with an existing OIDC provider know it's possible without endpoint support.

- **D-04: `oauth_accounts` linkage row is DELETED on conversion (clean break, not soft-delete or preserve).** The `oauth_providers` SAML row is NOT deleted — other users may still link to it post-reactivation, and Phase 220 D-01 specifies that deactivation never destroys provider rows.

  Rationale: preserving the `oauth_accounts` row creates ambiguous truth: a user with `auth_provider='local'` AND a live `oauth_accounts` link is a contradiction the system has no clean policy for. On reactivation, the user is now local — re-linking back to SAML is an explicit admin action (deferred backlog), not an automatic one. The audit_log entry preserves the historical fact ("this user was once SAML-linked, converted on $date"); we do not need the join-table row to preserve history.

- **D-05: Conversion is a single transaction; partial failures roll back.** The endpoint wraps all five steps (validate → set password → flip auth_provider → delete oauth_accounts → write audit_log) in one DB transaction. If any step fails, no state changes. The audit_log write is the LAST step in the transaction so a failed conversion does not produce an "I tried to convert but it didn't take" entry.

  Note on failure surfaces: the validate step produces 404 (user not found) or 422 (user is not SAML-authenticated, e.g., already local). The password step uses `hash_password` from `backend/app/modules/auth/providers/local.py` (existing, no new dep). The delete is keyed by `(user_id, provider_id)` — if the linkage row is missing, that's a 422 (user state is inconsistent — manual remediation required).

### Conversion preserves what (LIFECYCLE-06 acceptance)
- **D-06: The `users.id` UUID is the immutable handle.** Conversion never updates `users.id`. Every FK that references `users.id` (audit_logs.user_id, user_roles.user_id, datasets.created_by, oauth_accounts.user_id — being deleted, not updated; api_keys.user_id; share_tokens.user_id; etc.) automatically retains its pointer because the target row is unchanged. No FK-walk-and-update is needed.

  Verification scope for the LIFECYCLE-06 test: the test seeds a representative trio (audit_log, user_roles, datasets.created_by) and asserts they survive. We do NOT enumerate every FK that exists in the schema — the design promise is "user_id is durable," and three independent FKs from three different domains demonstrate that promise.

- **D-07: Conversion does NOT clear `users.last_login_at`, role memberships (`user_roles`), API keys (`api_keys`), share tokens (`share_tokens`), or any other user-attributed records.** Only the four explicit fields touched in D-01: `hashed_password` (set), `auth_provider` (flipped to `local`), `oauth_accounts` row (deleted), `audit_log` row (created).

### Round-trip test design (LIFECYCLE-07)
- **D-08: Both new tests live in `backend/tests/test_lifecycle.py` (Phase 220's file), as separate test functions — not parametrized over the existing `test_overlay_removal_preserves_saml_data`.** Per Phase 220 CONTEXT.md deferred-ideas note ("Phase 221's deactivation→reactivation symmetry test placement — likely co-located with Phase 220's lifecycle test"). Three test functions total after Phase 221:
  1. `test_overlay_removal_preserves_saml_data` (Phase 220) — deactivate-only.
  2. `test_convert_saml_user_to_local_preserves_user_data` (Phase 221, LIFECYCLE-06) — invokes the conversion endpoint via TestClient.
  3. `test_deactivate_reactivate_roundtrip_preserves_saml_data` (Phase 221, LIFECYCLE-07) — registry clear → re-register → assert.

  Rationale: separate functions keep each test's intent crystal clear. Parametrizing test 1 over deactivate-only and round-trip would obscure that round-trip has different setup (re-registration step) and different post-conditions (`is_enterprise() is True` again). Co-location lets all three share fixtures (`saml_overlay_registered`, `_seed_saml_provider`, `_cleanup_lifecycle_rows` extended).

- **D-09: Round-trip test simulates reactivation via the same `register_extensions()` path the `saml_overlay_registered` fixture uses for setup.** The fixture (conftest.py:454-484) imports `geolens_enterprise` and calls its `register_extensions()` to populate `_extensions` and `_routers`. The round-trip test:
  1. Setup: `saml_overlay_registered` fixture leaves registry populated. Save `edition_mod._info` then `init_edition(["enterprise"])`.
  2. Seed phase: SAML provider + `oauth_accounts` + user + `audit_log` row (per fixtures D-10).
  3. Deactivate phase: `_extensions.clear()`, `_routers.clear()`, `init_edition([])`. Assert `is_enterprise() is False` mid-cycle.
  4. Reactivate phase: import `geolens_enterprise` and re-call its `register_extensions()` (same call the fixture made in setup); `init_edition(["enterprise"])`. Assert `is_enterprise() is True`.
  5. Symmetry assertions: 4 deferred SAML columns retain values (via `undefer_group("saml")`), `oauth_accounts` row intact, User row intact with `auth_provider='oauth'`, seeded `audit_log` row intact with `user_id == seeded_user.id`.
  6. Teardown: `saml_overlay_registered` fixture's finally block restores `_extensions` and `_routers` to their pre-test snapshot; the test's own finally block restores `edition_mod._info`.

  The test does NOT touch `alembic` mid-test (per Phase 220 destructive_path_prohibition). The 4 SAML columns remain physically present throughout — that is the point of the round-trip.

- **D-10: Audit-trail assertion uses a SEEDED `audit_log` row, not just FK-survival reflection.** Without a seeded row, "audit trail intact" is a vacuous assertion — there's nothing to check. The test seeds one `audit_log` row via `app.modules.audit.service.log_action` (or by direct ORM insertion if log_action requires a request context the test can't provide cleanly) before deactivation, then asserts the row is queryable post-cycle and its `user_id` matches the seeded user UUID. Cost: ~5 lines of seed code; benefit: real end-to-end coverage of the requirement's literal text.

- **D-11: Test cleanup extends Phase 220's `_cleanup_lifecycle_rows` pattern.** Phase 221's tests seed additional row types (audit_log, user_roles, datasets) — the cleanup fixture must DELETE those scoped to the lifecycle test's known UUIDs/emails before yielding back. The fixture stays test-local (defined inside `test_lifecycle.py` or a sibling helper); it is NOT promoted to conftest.py because no other test file needs it.

### Documentation structure (LIFECYCLE-06)
- **D-12: The "Handling existing SAML users" section in `docs/edition-deactivation.md` replaces line 81's TODO marker in-place.** Section structure (matches the existing runbook's procedural-doc style):
  1. **Inventory SAML users** — reuse the existing SQL query at lines 70-77 (`SELECT COUNT(*) AS saml_users ...`).
  2. **Decide conversion targets per user** — local-password (canonical) or OIDC re-link (manual; see appendix).
  3. **For each SAML user, run the conversion endpoint** — copy-paste-able curl example: `curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"password": "<temp-strong-pw>"}' https://geolens.example.com/admin/users/<user-id>/convert-saml-to-local`.
  4. **Communicate new credentials out-of-band** — admin chooses delivery channel (encrypted email, password manager share, etc.).
  5. **Verify the user can log in via the new credential path** — admin's responsibility; runbook documents the verification step but doesn't prescribe the exact mechanism.
  6. **Appendix: OIDC conversion (manual)** — short paragraph describing the manual SQL+OAuth-flow procedure for operators who already have an OIDC provider configured. Out of scope for tooling.
- **D-13: `docs/edition-reactivation.md` gets a one-paragraph forward-pointer.** Inserted near the bottom (or in a new "Caveats" section if one already exists). Text: "If SAML users were converted to local-password during deactivation (per docs/edition-deactivation.md §Handling existing SAML users), those conversions persist after reactivation. The users continue logging in via local-password until an admin manually re-links them to a SAML provider. Automating reverse conversion is on the deferred roadmap."

### Audit-log catalog (Claude's Discretion)
- **D-14: `auth.convert_saml_to_local` is the new audit-log action name.** Pattern matches existing actions like `user.update`, `user.deactivate`. If a central catalog or enum of audit-log action names exists (e.g., `app/modules/audit/actions.py` or similar), the new action is registered there. If no such catalog exists, the action is referenced by string literal at the call site in `AdminService.convert_saml_user_to_local`. Planner verifies at plan time and picks the appropriate path.

### Claude's Discretion
- **Frontend admin UI deferred but track its shape** — when the polish phase lands, the affordance is likely a "Convert auth method" button on the user detail/edit view (visible only when `user.auth_provider == 'oauth'` AND `user.role` permits admin manage_users). Modal collects a temp password (or auto-generates one displayed once); calls the new endpoint; refetches the user. Out of Phase 221.
- **Validation of `auth_provider` value before conversion** — the endpoint must reject conversion requests for non-SAML users (e.g., `auth_provider='local'` already, or an OIDC-but-not-SAML oauth user). The check is "user has at least one `oauth_accounts` row to a SAML `oauth_providers` row." If a user has multiple oauth_accounts (multi-IdP — uncommon but possible), the endpoint deletes ONLY the SAML linkage. Planner picks the exact SQL (probably `DELETE FROM oauth_accounts WHERE user_id = ? AND provider_id IN (SELECT id FROM oauth_providers WHERE provider_type = 'saml')`).
- **Password complexity requirement on the conversion endpoint** — the new schema enforces `min_length=8` matching the existing `create_user` schema (`backend/app/modules/admin/schemas.py:23-26`). Planner can lift this to whatever the project standard is at plan time if there's a stricter password policy elsewhere; otherwise stick with min-8.
- **Where the curl example's auth token comes from in the runbook** — runbook references the existing admin login flow (`POST /auth/token` with admin credentials) for obtaining the token. Planner picks whether to embed the full two-step (login then convert) curl flow, or just the convert call with a "$TOKEN" placeholder + a one-line "obtain via /auth/token" note.
- **Post-cycle cleanup robustness in `_cleanup_lifecycle_rows`** — when extending the cleanup fixture to handle audit_log + user_roles + datasets rows, planner picks whether each delete is FK-cascaded automatically (if the test's user_id is deleted first, audit_logs SET NULL, datasets SET NULL — see audit/models.py:22 + datasets/domain/models.py:121-125), or whether explicit DELETEs are needed for tighter test isolation. The simpler pattern: delete in dependency order (audit_log first by user_id; user_roles by user_id; datasets by created_by; then oauth_accounts; then user; oauth_providers row stays — it predates any test-seeded user via Phase 220's pattern).
- **Whether to add a `Conversion History` section in admin UI** — out of Phase 221 scope; flag as a polish-phase consideration. The audit_log already records all conversions; an admin UI surface for it is a reporting feature, not a v13.2 requirement.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements / roadmap (the source of truth)
- `.planning/REQUIREMENTS.md` §LIFECYCLE-06 — re-onboarding path requirement; "an admin can convert their account to local-password or OIDC without losing audit history, group memberships, or dataset ownership." This is the user-continuity contract.
- `.planning/REQUIREMENTS.md` §LIFECYCLE-07 — round-trip symmetry test; "Re-activation symmetry test confirms the `deferred=True` SAML columns round-trip losslessly through a deactivate → reactivate cycle (User identities, `oauth_providers` rows, and audit trail all intact). Test runs in CI as part of the standard backend suite."
- `.planning/ROADMAP.md` §Phase 221 — goal statement + 3 success criteria. SC#1 is the conversion procedure contract; SC#2 is the docs contract (replaces the line-81 TODO); SC#3 is the round-trip test contract.
- `.planning/STATE.md` — confirms milestone state, Phase 220 shipped (UAT-1 ✓, UAT-2 deferred to 2026-05-01), Phase 221 next.
- `.planning/PROJECT.md` — milestone overview.

### Project / state (most-load-bearing upstream context)
- `.planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md` — **most important upstream context.** D-01 (overlay-removal canonical), D-04 (registry-level test pattern), D-05 (test placement in core repo), D-06 (CI overlay install), and the deferred-ideas note explicitly anchoring Phase 221's symmetry-test placement. Read in full.
- `.planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md` — pitfalls (1-8) the test-pattern decisions trace back to. Phase 221 inherits Pitfall 2 (three module-level state surfaces, three explicit resets), Pitfall 3 (do not touch `_outstanding_requests` / `replay_cache`), Pitfall 7 (do not add `not lifecycle` to addopts), Pitfall 8 (SQL-only assertions are sufficient).
- `.planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md` — verbatim seed-helper pattern, deferred-column query pattern, module-docstring shape. The Phase 221 conversion test reuses these patterns.
- `.planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md` — LIFECYCLE-04's 5-assertion contract; Phase 221's tests follow the same structure for their respective requirements.
- `.planning/milestones/v13.1-phases/217-auth-saml-enterprise/217-CONTEXT.md` — the SAML implementation Phase 220 documents and Phase 221 extends. D-01 (oauth_providers reuse), D-04 (oauth_accounts linkage + auth_provider='oauth'), D-13 (single-class dual-Protocol).

### Code (the new endpoint lands here)
- `backend/app/modules/admin/router.py` — Phase 221 adds `POST /admin/users/{user_id}/convert-saml-to-local` near the existing user-management routes (lines 168-373 hold the user CRUD; new route slots in alongside `update_user` at line 168 or `deactivate_user` at line 213). Existing pattern for `current_user: User = Depends(require_permission("manage_users"))` is reused; existing `log_action` import + call shape is reused.
- `backend/app/modules/admin/service.py` — `AdminService` class (line 21+); `update_user` method at line 114 is the closest existing analog. The new method `convert_saml_user_to_local(user_id: UUID, password: str) -> User` mirrors its shape (load user, validate, mutate, return). Imports `hash_password` from `backend.app.modules.auth.providers.local` (already imported at line 15 — reuse).
- `backend/app/modules/admin/schemas.py` — adds `SamlToLocalConversion` Pydantic schema (just `password: str = Field(min_length=8, ...)`). Pattern matches existing `UserCreate.password` field at line 23-26.
- `backend/app/modules/auth/providers/local.py` — `hash_password()` (already imported in admin/service.py:15). Black-box reuse.
- `backend/app/modules/audit/service.py` — `log_action()` is the existing audit-write entry point (called from `admin/router.py:200` for `user.update`). Phase 221's endpoint reuses it with `action='auth.convert_saml_to_local'`.

### Code (the conversion validates against)
- `backend/app/modules/auth/models.py` — `User` ORM. Critical: `auth_provider` column at line 44 with `chk_users_auth_provider` CHECK constraint at line 26 (`auth_provider IN ('local', 'oidc', 'oauth')`). Conversion target `'local'` is valid. `users.id` is the durable UUID handle (immutable across conversion).
- `backend/app/modules/auth/oauth/models.py` — `OAuthProvider` (lines 40-78) with the 4 deferred SAML columns; `OAuthAccount` (lines after) is the join table. Phase 221 deletes the `OAuthAccount` row, NOT the `OAuthProvider` row.
- `backend/app/modules/auth/models.py` (UserRole at line 77+) — survives conversion automatically (FK keyed by user_id, not by auth_provider).
- `backend/app/modules/audit/models.py:22` — `AuditLog.user_id` FK with `ondelete="SET NULL"`. Conversion does NOT delete the user, so audit_log entries' `user_id` survives unchanged.
- `backend/app/modules/catalog/datasets/domain/models.py:121-125` — `Dataset.created_by` (and `updated_by`) FK to `users.id` with `ondelete="SET NULL"`. Conversion does NOT delete the user, so dataset ownership survives.

### Code (the test extends)
- `backend/tests/test_lifecycle.py` — Phase 220's file. Phase 221 ADDS two new test functions to this file. Existing `test_overlay_removal_preserves_saml_data` stays as-is. The `_cleanup_lifecycle_rows` fixture at top of the file gets EXTENDED to also delete audit_log + user_roles + datasets rows scoped to the lifecycle test's user UUIDs.
- `backend/tests/conftest.py` — `saml_overlay_registered` fixture at lines 454-484 (REUSE — both new tests take it). `test_db_session` fixture for ORM access. `test_client` (or equivalent) for HTTP-level invocation of the conversion endpoint.
- `backend/tests/test_saml_overlay.py` — Phase 217 + Phase 220 reference. `_seed_saml_provider()` helper at lines 96-137 (REUSE for the SAML provider seed in both new tests). `FIXTURE_*` constants at top.
- `backend/tests/test_admin_users.py` (or similar — verify exists at plan time) — admin endpoint test patterns; the conversion test follows whatever pattern admin user-update tests use for TestClient + auth.

### Code (CI is unchanged but referenced)
- `.github/workflows/ci.yml` — Phase 220 D-06 already amends this to install `geolens-enterprise` before the backend test job. Phase 221's tests inherit the install. NO new amendment needed.

### Code (enterprise overlay — outside repo)
- `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` — `register_extensions()` populates the registry. Phase 221's round-trip test imports this and calls it for the reactivation phase (same call the `saml_overlay_registered` fixture makes during setup).
- `~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py` — schema reference. Phase 221's tests run against the schema this migration produces (CI installs the overlay; alembic upgrade head applies it).

### Existing docs (where Phase 221 edits land)
- `docs/edition-deactivation.md:81` — the existing TODO marker that Phase 221's new section replaces. Line 81 currently reads: "> **Existing SAML users will lose their login path.** Phase 221 ships the user re-onboarding procedure ('Handling existing SAML users', planned). Until that lands, communicate the downgrade to SAML users out-of-band and convert their accounts manually via the admin UI (set local password or convert to OIDC)." Phase 221 replaces this with a real cross-link to the new section ("Handling existing SAML users") and removes the "manually via the admin UI" claim (which was never true) in favor of the new endpoint-backed procedure.
- `docs/edition-deactivation.md` (overall) — style reference for the new section's tone; existing pre-flight (§3 step 3) and inventory queries (§3 step 2 SQL) are reused/referenced from the new section.
- `docs/edition-reactivation.md` — Phase 221 adds the one-paragraph forward-pointer. Read existing structure before deciding placement.
- `docs/saml.md` — referenced for the IdP-side cleanup (admin disables the SAML app at the IdP after deactivation); Phase 221 does NOT edit saml.md.

### CLAUDE.md operational notes
- `CLAUDE.md` (project-local + user-global) — `feedback_audit_sibling_repos_at_milestone_close.md` is relevant when v13.2 ships (Phase 221 is the milestone closer); the audit will check `geolens-enterprise` for unpushed commits tied to Phase 220/221. `feedback_run_ci_local_first.md` and `project_geolens_io_actions_billing.md` are relevant: run lint/typecheck/tests locally before pushing; use PR path for time-sensitive verification because free-tier Actions minutes are routinely exhausted.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`AdminService.update_user` (`backend/app/modules/admin/service.py:114-...`)** — pattern for "load user → validate → mutate → return" used by the new `convert_saml_user_to_local` method. Same DB-session injection, same `ValueError` raising contract for 404/422 mapping.
- **`hash_password` (`backend/app/modules/auth/providers/local.py`)** — already imported in admin/service.py:15. Black-box password hashing for the conversion's password-set step.
- **`log_action` (`backend/app/modules/audit/service.py`)** — already used by `admin/router.py:200` for the `user.update` audit entry. Phase 221's endpoint calls it with `action='auth.convert_saml_to_local'` and `details={"from": "saml", "to": "local", "provider_slug": ...}`.
- **`require_permission("manage_users")` (`backend/app/modules/auth/permissions.py`)** — existing dependency used by admin/router.py user CRUD routes. The new endpoint reuses it.
- **`_seed_saml_provider` + FIXTURE_* constants (`backend/tests/test_saml_overlay.py:96-137`)** — reused for the SAML provider seed in Phase 221's conversion test AND round-trip test.
- **`saml_overlay_registered` fixture (`backend/tests/conftest.py:454-484`)** — reused; both new tests take it. Setup call `geolens_enterprise.register_extensions()` is the exact path Phase 221's round-trip test re-invokes for the reactivation phase.
- **`undefer_group("saml")` deferred-column query pattern (Phase 220 PATTERNS.md)** — reused for symmetry assertions in the round-trip test.
- **`_cleanup_lifecycle_rows` fixture (Phase 220's `backend/tests/test_lifecycle.py`)** — extended for Phase 221 to also clean up audit_log + user_roles + datasets rows scoped to the test's user UUIDs.
- **`init_edition` save/restore pattern (`backend/tests/test_saml_overlay.py:233+270`)** — reused for both new tests' edition-state hygiene.

### Established Patterns
- **Admin endpoint shape** — `backend/app/modules/admin/router.py:168-373` user CRUD routes follow a consistent shape: HTTP verb decorator → response_model → params (path, body, request, current_user, db) → service method → ValueError-to-HTTPException mapping → log_action → db.commit → return. Phase 221's new endpoint follows this verbatim.
- **Pydantic schema for admin endpoints** — `backend/app/modules/admin/schemas.py` keeps schemas narrow (UserCreate, UserUpdate, UserResponse, etc.). Phase 221 adds one new schema `SamlToLocalConversion` with one field (`password: str = Field(min_length=8)`).
- **Pytest marker + fixture cleanup yield pattern** — Phase 220's `_cleanup_lifecycle_rows` is a `yield` fixture (best-effort delete on teardown). Phase 221 extends it.
- **`@pytest.mark.lifecycle`** — registered in `backend/pyproject.toml` (Phase 220). Both new tests use it. Marker runs by default in CI (NOT deselected via addopts per Phase 220 Pitfall 7).
- **`current_user.id == user_id` self-action guards** — `admin/router.py:180-184` blocks role self-changes. Phase 221's conversion endpoint should mirror this guard for the analogous case (admin converts THEIR OWN account to local-password — risky if it's the only admin and they fat-finger the password). Recommendation: if `user_id == current_user.id`, surface a 422 telling the admin to convert someone else's account or use a different account first. Planner picks the exact wording.

### Integration Points
- **The new endpoint is a route addition only** — no new module, no new top-level package, no new migration. It joins the existing admin router under `/admin/users/{user_id}/...`.
- **The audit module connection** — `log_action` is called inside the endpoint's transaction before `db.commit()` (matches `admin/router.py:200-209` `user.update` pattern).
- **The frontend gets nothing in Phase 221** — no `frontend/src/api/admin.ts` change, no UI affordance. The `apiFetch` consumer pattern is documented for the deferred polish phase but not exercised here.
- **Round-trip test connection to enterprise overlay** — the test imports `geolens_enterprise` directly (deferred inside the test body, not at module level, so collection succeeds in community-only environments per Phase 220 Pitfall 5). CI guarantees the overlay is installed before pytest runs (Phase 220 D-06).

### Risk surfaces
- **Race condition: admin converts their own account, fat-fingers password, locks themselves out.** Mitigation in D-04 above (Claude's Discretion): block self-conversion via 422.
- **Race condition: simultaneous SAML login + conversion.** Window: a SAML user is mid-login (POST `/auth/saml/{slug}/acs`) when admin runs the conversion. The login flow uses `find_or_create_oauth_user` which JIT-creates the User row OR finds the existing one. If the conversion has just deleted `oauth_accounts` and flipped `auth_provider` to `'local'`, the next ACS hit may try to re-create the user (user lookup on `email` may match the existing local user, then JIT path tries to insert a duplicate `oauth_accounts` row). Acceptable for v13.2: the maintenance-window mention in `docs/edition-deactivation.md:83` already says "SAML logins fail immediately when the overlay is removed" — the conversion procedure is intended to run AFTER the overlay is removed (so SAML routes are 404 and no SAML login can race). Phase 221 runbook explicitly orders: "convert users AFTER deactivation, not before."
- **`audit_log.user_id` SET NULL semantics** — `audit_logs.user_id` FK is `ondelete=SET NULL`. Conversion does NOT delete the user, so this is fine. But if a future phase ever HARD-deletes a converted user, all their audit_log rows go to NULL — that's the existing project policy, not Phase 221's concern.
- **Round-trip test reliance on `register_extensions()` idempotency** — calling `register_extensions()` twice in one process (fixture setup + test mid-cycle) must be idempotent. Phase 217 designed it to be (it's a dict-set populating `_extensions` and an append populating `_routers`). The mid-test clear before re-register guarantees a clean slate. Verify at plan time that no `register_extensions()` side effects (e.g., DB writes, file I/O) trip on second invocation.
- **Test runtime cost** — three tests in `test_lifecycle.py` instead of one. Each test exercises the saml_overlay_registered fixture (overlay import + register cost). Estimated added test-suite runtime: ~6-10s. Acceptable.
- **Audit-log seeding for the round-trip test (D-10)** — if `log_action` requires a request context the test can't cleanly synthesize, the test falls back to direct ORM insertion of an `AuditLog(user_id=..., action='test.seed', ...)` row. Either path satisfies LIFECYCLE-07's literal text. Planner picks at plan time.
- **Documentation drift** — Phase 221 deletes the line-81 TODO from `docs/edition-deactivation.md`. Risk: Phase 220's discussion log + verification artifacts reference line 81 explicitly. Mitigation: Phase 221's commits clearly link the change to LIFECYCLE-06 + Phase 220's TODO marker; PR review confirms the new section addresses every concern the TODO flagged.
- **Free-tier Actions billing exhaustion (project memory)** — Phase 220 hit this for UAT-2 (deferred to 2026-05-01). Phase 221 should run lint/typecheck/tests locally before pushing per `feedback_ci_local_first.md`; prefer PR path for verification per `project_geolens_io_actions_billing.md`.

</code_context>

<specifics>
## Specific Ideas

- **Dedicated narrow endpoint, not generic PATCH extension** — D-01: `POST /admin/users/{user_id}/convert-saml-to-local`. Single-purpose, single-action audit log entry, password kept out of the generic `UserUpdate` schema.
- **Local-password is the only automated conversion target for v13.2** — D-03: OIDC mentioned in runbook as manual procedure; OIDC tooling is deferred.
- **`oauth_accounts` row DELETED on conversion, `oauth_providers` row preserved** — D-04: clean break for the user; provider stays for other users.
- **Single-transaction conversion** — D-05: validate → set password → flip auth_provider → delete oauth_accounts → write audit_log. All-or-nothing.
- **Three-test-function `test_lifecycle.py`** — D-08: deactivate-only (Phase 220) + conversion (LIFECYCLE-06) + round-trip (LIFECYCLE-07). Co-located, separate functions, shared fixtures.
- **Round-trip via `register_extensions()` re-invocation** — D-09: mirror the fixture's setup path for the reactivation phase; do NOT touch alembic.
- **Audit trail assertion uses a seeded `audit_log` row** — D-10: real coverage, not vacuous reflection.
- **Frontend UI affordance + OIDC tooling + reverse conversion are all deferred** — Out-of-scope per D-02, D-03, D-13. Documented as polish-phase / v14+ candidates.
- **Self-conversion guard** — Claude's Discretion: block `current_user.id == user_id` to prevent admin self-lockout fat-finger.
- **Reuse Phase 220 patterns wholesale** — `_seed_saml_provider`, `saml_overlay_registered`, `undefer_group("saml")`, `init_edition` save/restore, `_cleanup_lifecycle_rows` (extended). Smallest possible diff per Phase 220 RESEARCH "Don't Hand-Roll."

</specifics>

<deferred>
## Deferred Ideas

- **Frontend admin UI affordance for the conversion endpoint** — a "Convert SAML → Local" button on the user detail/edit view, with a modal that collects (or auto-generates) the temp password. Out of Phase 221 scope; track as a polish-phase candidate (likely v14+ when it's clear how often operators actually run conversions). The endpoint exists, so the UI is a thin layer.
- **OIDC conversion tooling** — `POST /admin/users/{user_id}/convert-saml-to-oidc` (or extend the v13.2 endpoint with a `target` arm). Requires picking the target `oauth_provider_id`, validating the OIDC provider is configured, and a 2-arm test surface. Out of v13.2; defer until the manual-procedure traffic justifies automation.
- **Reverse conversion (local → SAML on reactivation)** — `POST /admin/users/{user_id}/relink-to-saml`. The mirror of LIFECYCLE-06 for the reactivation half. Out of v13.2; defer to a later polish phase. Without it, conversions are one-way; admins re-link manually via SQL or by deleting the user and waiting for SAML JIT-create on next login (loses the local password and any local-only metadata).
- **CLI subcommand `geolens admin user convert-saml-to-local`** — wraps the endpoint. Out of v13.2 because the runbook + curl path is the "documented procedure" SC#1 specifies. Defer until admin tooling expands generally.
- **Audit-log catalog of action names** — if no `app/modules/audit/actions.py` enum exists today, adding one (with `auth.convert_saml_to_local` registered) is a future hygiene improvement. Out of v13.2 (the action name is fine as a string literal at the call site).
- **Conversion History admin UI surface** — a UI for "show me all conversions in the audit log" filtered by `action='auth.convert_*'`. Out of Phase 221 (the data exists in audit_log; UI surfacing is a reporting feature).
- **Compose-stack-swap fidelity for the round-trip test** — Phase 220's deferred idea, still deferred. Registry-level simulation is sufficient for v13.2; nightly compose-stack-swap test is a future hardening enhancement.
- **`is_enterprise()` gating on registry accessors** — Phase 220's deferred idea (D-08), still deferred. Closing it would make `GEOLENS_EDITION=community` a complete deactivation lever; out of v13.2.
- **Audit-log entry on `init_edition()` transitions** — Phase 220's deferred idea, still deferred. Out of v13.2.
- **Doc-test for `docs/saml.md` SC#3 of Phase 220** — Phase 220's deferred idea, still deferred. Manual PR review is the v13.2 control.

</deferred>

---

*Phase: 221-lifecycle-user-continuity-and-verification*
*Context gathered: 2026-04-30*

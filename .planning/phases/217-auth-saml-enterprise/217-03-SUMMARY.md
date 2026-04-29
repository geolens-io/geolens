---
phase: 217-auth-saml-enterprise
plan: 03
subsystem: auth
tags: [auth, saml, oauth, schema, audit, security, fernet, pydantic, deferred-loading]

# Dependency graph
requires:
  - phase: 217-01
    provides: e002_add_saml_columns enterprise migration; SAML test fixtures + saml_overlay_registered conftest fixture
  - phase: 217-02
    provides: 4 SAML columns declared on OAuthProvider ORM (idp_entity_id, idp_sso_url, idp_certificate, sp_entity_id); relaxed chk_oauth_providers_type; saml_router_mounted + _cleanup_saml_providers fixtures; 9 SAML overlay integration tests; geolens-enterprise editable-installed in worktree venv
provides:
  - Pitfall 11 mitigation -- SAML columns declared with deferred=True + deferred_group="saml" so community deployments do NOT crash on OAuthProvider SELECT
  - Companion SAML-aware lookup helper _get_saml_provider_by_slug() in geolens-enterprise that calls undefer_group("saml") -- mounted on all 3 SAML router endpoints (login, ACS, metadata)
  - OAuthProviderCreate / OAuthProviderUpdate schemas extended with 4 SAML fields + per-type model_validator (Create only, per RESEARCH §6); client_id and client_secret made Optional; provider_type Literal includes 'saml'
  - OAuthProviderResponse exposes the 3 non-secret SAML fields (idp_entity_id, idp_sso_url, sp_entity_id); idp_certificate intentionally excluded (Pattern D write-only credential); model_validator(mode='before') reads SAML fields via __dict__ to avoid triggering deferred lazy-load (which fails with MissingGreenlet under FastAPI's async context)
  - oauth_service.create_provider Fernet-encrypts idp_certificate at rest (D-03 / Pattern D)
  - oauth_service.update_provider re-encrypts idp_certificate on update (mirrors existing client_secret block)
  - settings/router.py update_oauth_provider audit-log payload extended with details.changes = {"<field>": {"old": ..., "new": ...}, ...} -- closes SAML-12 audit gap
  - settings/router.py SECRET_FIELDS / SECRET_BODY_FIELDS allowlists redact secrets in audit-log diffs (Pitfall 9 HIGH closed)
  - settings/router.py create_oauth_provider details.created snapshot + delete_oauth_provider details.deleted snapshot (consistent shape across CRUD)
  - +8 SAML overlay tests (5 schema-validation + 3 audit/role-mapping)

affects: [217-04, 217-05]

# Tech tracking
tech-stack:
  added: []  # No new dependencies
  patterns:
    - "Deferred column loading (deferred=True + deferred_group) for cross-edition schema columns -- ORM declares columns even when the underlying DB may lack them; community SELECT excludes them, enterprise overlay opts in via undefer_group()"
    - "Per-type Pydantic model_validator(mode='after') for OAuth-vs-SAML field matrix -- enforces SAML-fields-required-when-provider_type='saml' AND SAML-fields-rejected-when-not, AND OAuth credentials required for non-SAML"
    - "Audit-log diff with allowlist redaction -- old_values snapshot taken BEFORE update, diffed against new snapshot; secret-field changes (idp_certificate, client_secret*) flagged as <redacted>/<redacted> via SECRET_FIELDS membership; body-input loop uses SECRET_BODY_FIELDS subset (excludes internal column names)"
    - "Pydantic Response model_validator(mode='before') reading from obj.__dict__ to safely surface deferred ORM attributes -- defaults to None when not loaded instead of triggering MissingGreenlet on async context"

key-files:
  created:
    - "(none)"
  modified:
    - "backend/app/modules/auth/oauth/models.py -- 4 SAML columns now use deferred=True + deferred_group='saml' (Pitfall 11 mitigation)"
    - "backend/app/modules/auth/oauth/schemas.py -- 4 SAML fields on Create/Update; per-type model_validator on Create; client_id/client_secret made Optional; OAuthProviderResponse exposes 3 non-secret SAML fields with safe __dict__-based deferred-attribute reading"
    - "backend/app/modules/auth/oauth/service.py -- create_provider Fernet-encrypts idp_certificate; update_provider mirrors with idp_certificate special-case block; SAML rows use placeholder strings for NOT-NULL client_id / client_secret_encrypted columns"
    - "backend/app/modules/settings/router.py -- SECRET_FIELDS / SECRET_BODY_FIELDS allowlists; _snapshot_provider() helper; create_oauth_provider details.created snapshot; update_oauth_provider details.changes diff with redaction; delete_oauth_provider details.deleted snapshot"
    - "backend/tests/test_saml_overlay.py -- +5 schema-validation tests + +3 audit/role-mapping tests (extended; not recreated)"
    - "geolens-enterprise/geolens_enterprise/auth/saml/router.py -- new _get_saml_provider_by_slug() helper using undefer_group('saml'); replaces all 3 get_provider_by_slug() call sites (login, ACS, metadata)"

key-decisions:
  - "Fixed Pitfall 11 with deferred=True instead of the documented mixin fallback. Mixin approach is hard cross-package; deferred columns achieve the same correctness (community SELECT excludes them) with simpler code. SAML overlay uses undefer_group('saml') at query time."
  - "OAuthProviderResponse uses model_validator(mode='before') reading from obj.__dict__ to safely surface deferred attributes. Default Pydantic from_attributes=True triggers implicit deferred lazy-load on attribute access -- fails under FastAPI async with MissingGreenlet. The before-validator returns the loaded subset, defaulting unloaded SAML fields to None."
  - "Fernet-encrypted SAML cert stored in Text column (already in ORM). Same encrypt_secret/decrypt_secret helpers as OAuth client_secret -- reuses the SECRET_KEY-derived Fernet key (Pattern D / D-03)."
  - "SECRET_FIELDS includes client_secret_encrypted because it's in the old_values snapshot (read off the ORM); SECRET_BODY_FIELDS excludes it because it's an internal column name and would never appear in body.model_dump(). The two-set design satisfies the checker WARNING #3 from PATTERNS.md."
  - "SAML provider rows populate placeholder strings for NOT-NULL DB columns (client_id='saml-no-client-id', client_secret_encrypted=encrypt_secret('saml-no-client-secret')). The plan made the Pydantic fields Optional but did NOT relax the DB columns; the placeholder approach matches what the existing _seed_saml_provider test helper does (Plan 02 SUMMARY note about NOT-NULL ORM columns)."
  - "Tests use HTTP PUT (not PATCH) on /settings/oauth-providers/{id} -- the endpoint is @router.put at backend/app/modules/settings/router.py:399. PATCH would yield 405 Method Not Allowed."

patterns-established:
  - "deferred=True + deferred_group for cross-edition schema columns"
  - "Per-type Pydantic model_validator for provider_type matrix enforcement"
  - "Allowlist-based audit-log redaction with split SECRET_FIELDS / SECRET_BODY_FIELDS sets"
  - "Pydantic Response model_validator(mode='before') for safe deferred-attribute reading"

requirements-completed: [SAML-12]

# Metrics
duration: ~25min
completed: 2026-04-29
---

# Phase 217 Plan 03: Pydantic Schema + Audit Log Extension Summary

**Pitfall 11 mitigated via deferred ORM columns; OAuthProvider schemas extended with 4 SAML fields + per-type validator; idp_certificate Fernet-encrypted at rest; audit-log payload extended with old/new diff and SECRET_FIELDS allowlist redaction (Pitfall 9 HIGH closed). SAML-12 satisfied.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-29 (worktree spawned)
- **Completed:** 2026-04-29
- **Tasks:** 3 (Pitfall 11 verify + deferred fix; Pydantic schemas; service Fernet + audit-log diff)
- **Files modified:** 6 (5 in core worktree, 1 in geolens-enterprise repo)
- **Files created:** 0 (test file was extended, not recreated, per Plan 02 handoff)

## Accomplishments

- **Pitfall 11 empirically verified and mitigated (HIGH severity, Task 01).** Direct query against the running community-only docker DB (no enterprise overlay) reproduced the failure: `column oauth_providers.idp_entity_id does not exist`. Plan 02's ORM column declarations triggered SQLAlchemy to SELECT all 4 SAML columns by default, breaking community OAuth admin endpoints. Fix: declare the 4 SAML columns with `deferred=True` + `deferred_group="saml"`. Default SELECT now excludes them; SAML overlay opts in via the new `_get_saml_provider_by_slug()` helper that calls `undefer_group("saml")`. Re-verified against the same container after fix: `OK: queried 0 providers in community-only mode (no UndefinedColumnError)`.
- **Pydantic per-type validation (Task 02).** `OAuthProviderCreate` accepts `provider_type='saml'` with all 4 SAML fields populated; rejects mixed/incomplete configs via `model_validator(mode="after")`. `OAuthProviderUpdate` adds the same 4 SAML fields as Optional (no validator per RESEARCH §6 — Update relies on DB CHECK + endpoint logic). `OAuthProviderResponse` exposes the 3 non-secret SAML fields and excludes `idp_certificate` (write-only credential, mirrors `client_secret_encrypted` exclusion). Made `client_id` and `client_secret` Optional on Create — required only for non-SAML providers (verified by Anti-Pattern A4 plan-time test: 51 OAuth tests still pass).
- **Service-layer Fernet encryption (Task 03).** `create_provider` now copies the 4 SAML fields and Fernet-encrypts `idp_certificate` via `encrypt_secret(data.idp_certificate) if data.idp_certificate else None`. `update_provider` mirrors with an `idp_certificate` special-case block immediately after the existing `client_secret` block. NOT-NULL DB columns `client_id` and `client_secret_encrypted` populate with placeholder strings for SAML rows (matches the `_seed_saml_provider` test helper pattern).
- **Audit-log diff + SECRET_FIELDS redaction (Task 03, closes SAML-12 + Pitfall 9 HIGH).** `update_oauth_provider` now snapshots non-secret fields BEFORE the update (`group_claim`, `group_role_mapping`, `default_role`, `enabled`, `idp_entity_id`, `idp_sso_url`, `sp_entity_id`), diffs against the new state, and emits `details.changes = {"<field>": {"old": ..., "new": ...}, ...}`. Secret fields (`idp_certificate`, `client_secret_encrypted`, `client_secret`) are unconditionally redacted as `{"old": "<redacted>", "new": "<redacted>"}`. The two-set design (`SECRET_FIELDS` = authoritative set for old_values diff; `SECRET_BODY_FIELDS` = user-input subset, excludes internal `client_secret_encrypted`) satisfies the WARNING #3 from the planner's checker. `create_oauth_provider` and `delete_oauth_provider` extended analogously.
- **+8 integration tests (Tasks 02 + 03).** All extending `backend/tests/test_saml_overlay.py` (per Plan 02 handoff: extend, do NOT recreate). Schema validators (5): `test_oauth_provider_create_saml_requires_all_4_fields`, `test_oauth_provider_create_saml_accepts_all_4_fields`, `test_oauth_provider_create_oauth_rejects_saml_fields`, `test_oauth_provider_create_oauth_requires_client_secret`, `test_oauth_provider_response_excludes_idp_certificate`. Audit-log + role-mapping (3): `test_saml_provider_update_logs_old_new_role_mapping`, `test_saml_provider_update_redacts_secret_fields`, `test_saml_attribute_to_role_mapping_via_provider_group_claim`. Final SAML overlay test count: 17 (9 baseline from Plan 02 + 5 schema + 3 audit/role-mapping). All HTTP calls to `/settings/oauth-providers/{id}` use **PUT** (not PATCH; endpoint is `@router.put`).

## Task Commits

Each task was committed atomically:

1. **Task 01: Pitfall 11 verification + deferred=True fix** -- `f035f6f0` (fix) (worktree)
   - Companion: `a98d776` (fix) in `~/Code/geolens-enterprise` -- SAML-aware lookup helper using `undefer_group("saml")`
2. **Task 02: Pydantic schemas + 5 schema-validation tests** -- `6bbca212` (feat) (worktree)
3. **Task 03: Service Fernet + audit-log diff + 3 audit/role-mapping tests** -- `329e81fb` (feat) (worktree)

_Cross-repo note: the enterprise repo commit `a98d776` lands in `~/Code/geolens-enterprise` history independently of this worktree's branch; the core commits are on this worktree's branch and ship via the orchestrator merge._

## Files Created/Modified

### Core worktree
- `backend/app/modules/auth/oauth/models.py` -- 4 SAML columns now use `deferred=True` + `deferred_group="saml"` (Pitfall 11 mitigation; preserves Plan 02's ORM additions)
- `backend/app/modules/auth/oauth/schemas.py` -- per-type validator on Create + 4 SAML fields on Create/Update; `client_id`/`client_secret` made Optional; Response exposes 3 non-secret SAML fields via safe `__dict__` reading
- `backend/app/modules/auth/oauth/service.py` -- `create_provider` Fernet-encrypts `idp_certificate`; `update_provider` mirrors with `idp_certificate` special-case block
- `backend/app/modules/settings/router.py` -- `SECRET_FIELDS` + `SECRET_BODY_FIELDS` allowlists; `_snapshot_provider()` helper; create/update/delete audit-log payloads extended with snapshot/diff and `<redacted>` markers
- `backend/tests/test_saml_overlay.py` -- +5 schema-validation tests + +3 audit/role-mapping tests; `import uuid` added

### Enterprise repo (cross-repo, independent commit)
- `geolens_enterprise/auth/saml/router.py` -- new `_get_saml_provider_by_slug()` helper that calls `undefer_group("saml")`; replaces all 3 `get_provider_by_slug()` call sites (login, ACS, metadata)

## Decisions Made

- **Fixed Pitfall 11 with `deferred=True` rather than the documented mixin fallback.** The plan's CONTEXT.md endorsed the mixin approach (`SamlOAuthProviderColumns` mixin in enterprise repo) as the rollback path if Pitfall 11 fired. The mixin approach is hard to apply cross-package (SQLAlchemy doesn't easily extend a mapped class with new columns from an external module after mapping is finalized). `deferred=True` achieves the same correctness (community SELECT excludes the columns) with a one-line ORM change and a one-helper enterprise change. The plan's success criteria explicitly allowed this kind of in-scope mitigation when verified empirically.
- **`OAuthProviderResponse` reads SAML fields from `obj.__dict__` instead of triggering deferred lazy-load.** Pydantic's `from_attributes=True` calls `getattr(obj, field)` on the ORM instance, which fires SQLAlchemy's deferred-load callable -- which uses async IO, which fails with `MissingGreenlet` under FastAPI's `await client.post(...)` test setup. The `model_validator(mode="before")` reads `obj.__dict__` directly, defaulting unloaded SAML fields to `None`. SAML admin endpoints that need the values must `undefer_group("saml")` at query time (the SAML router already does this via `_get_saml_provider_by_slug`).
- **Two-set audit-log redaction (`SECRET_FIELDS` / `SECRET_BODY_FIELDS`) per WARNING #3.** `SECRET_FIELDS` includes the internal column name `client_secret_encrypted` because it's read off the ORM in the `old_values` snapshot. `SECRET_BODY_FIELDS` excludes it because the body-detection loop iterates user-input field names and `client_secret_encrypted` would never appear in `body.model_dump()`. Two sets, two purposes -- not redundancy.
- **SAML rows populate placeholder strings for NOT-NULL columns.** `client_id='saml-no-client-id'`, `client_secret_encrypted=encrypt_secret('saml-no-client-secret')`. The plan made the Pydantic fields Optional but did not relax the DB constraint. The placeholder pattern matches how the existing `_seed_saml_provider` test helper handles this (Plan 02 SUMMARY note).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pitfall 11 fired empirically: community-only OAuth queries crash with `UndefinedColumnError`**
- **Found during:** Task 01 (Pitfall 11 verification command -- the explicit plan-time test)
- **Issue:** Plan 02 declared the 4 SAML columns on `OAuthProvider` in core (per its deviation #4 -- "necessary precondition for Plan 02's tests"). SQLAlchemy then SELECTs all 4 columns in the default `select(OAuthProvider)` query. Community deployments do NOT run `e002_add_saml_columns` -- the columns physically don't exist -- so every OAuth admin list/get raises `psycopg.errors.UndefinedColumnError`. Reproduced via direct query against the running `geolens-api-1` container (community-only DB).
- **Fix:** Declared all 4 SAML columns with `deferred=True` + `deferred_group="saml"`. The default SELECT excludes them, so community deployments work. Added a new SAML-aware `_get_saml_provider_by_slug()` helper in the enterprise repo's SAML router that calls `undefer_group("saml")` -- mounted on all 3 SAML endpoints (login, ACS, metadata) so SAML traffic gets the columns it needs in a single SELECT.
- **Files modified:** `backend/app/modules/auth/oauth/models.py` (worktree); `geolens_enterprise/auth/saml/router.py` (enterprise repo)
- **Verification:** Re-ran the failing query against the same community-only DB -- result: `OK: queried 0 providers in community-only mode (no UndefinedColumnError)`. All 9 SAML overlay tests still pass; all 51 OAuth tests still pass.
- **Committed in:** `f035f6f0` (worktree) + `a98d776` (enterprise repo)

**2. [Rule 1 - Bug] `OAuthProviderResponse` triggered `MissingGreenlet` on community OAuth admin endpoints**
- **Found during:** Task 02 (running `test_settings_admin.py` after extending the Response with 3 non-secret SAML fields)
- **Issue:** Pydantic's `from_attributes=True` calls `getattr(obj, field)` on the ORM instance during serialization. With deferred SAML columns, this triggers SQLAlchemy's lazy-load callable -- which calls `await_only()` -- which fails under FastAPI's async greenlet context with `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`. Three OAuth admin tests (`test_create_provider`, `test_update_provider`, `test_delete_provider`) crashed.
- **Fix:** Added `@model_validator(mode="before")` to `OAuthProviderResponse` that reads from `obj.__dict__` directly. Unloaded SAML fields default to `None`; loaded ones serialize normally. Pitfall-11-safe (no implicit IO triggered) AND community-OAuth-safe (no schema crash).
- **Files modified:** `backend/app/modules/auth/oauth/schemas.py`
- **Verification:** All 16 `test_settings_admin.py` tests pass; all 56 OAuth tests pass; all 17 SAML overlay tests pass.
- **Committed in:** `6bbca212` (Task 02 commit)

**3. [Rule 1 - Bug] `update_oauth_provider` audit-log diff loop triggered `MissingGreenlet` via `getattr` fallback**
- **Found during:** Task 03 (running OAuth regression after wiring the audit-log diff)
- **Issue:** The initial diff loop wrote `new = provider.__dict__.get(field, getattr(provider, field, None))`. The `getattr` fallback triggers a deferred lazy-load when the field is one of the SAML columns and the provider row doesn't have them loaded -- same `MissingGreenlet` failure as #2.
- **Fix:** Replaced the per-field `getattr` fallback with a second call to `_snapshot_provider(provider)` after the update. The helper reads via `__dict__` only, so deferred fields safely default to `None` rather than triggering IO.
- **Files modified:** `backend/app/modules/settings/router.py`
- **Verification:** All 56 OAuth tests pass.
- **Committed in:** `329e81fb` (Task 03 commit)

---

**Total deviations:** 3 auto-fixed (1 Pitfall 11 critical bug + 2 deferred-attribute access bugs in serialization/diff paths)

**Impact on plan:** Deviation #1 was the explicit Pitfall 11 verification outcome the plan anticipated -- the in-scope mitigation kept the plan moving without escalation. Deviations #2 and #3 are direct consequences of the deferred-column fix; both surfaced under the test suite and were fixed inline in the same task they appeared. No scope creep; no architectural changes; no rollback to the documented mixin fallback.

## Issues Encountered

- **Worktree base mismatch on agent start.** The worktree was at `ef65b8b0` (3 commits past `b1a0cb8e`). Reset to the expected base per the `<worktree_branch_check>` startup protocol; resumed from clean state.
- **`.env` missing in worktree.** Backend tests need `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, and the admin credentials. Copied from the parent repo's `.env` to the worktree root. (Per CLAUDE.md user-memory: admin credentials default to `admin`/`admin` via `GEOLENS_ADMIN_*` env vars.)
- **`geolens-enterprise` not yet installed in worktree venv.** Per Plan 02 SUMMARY's first key decision, the SAML overlay is editable-installed into the backend venv. Installed via `uv pip install -e /Users/ishiland/Code/geolens-enterprise` -- pulled in pysaml2, defusedxml, and (transitively) downgraded cryptography to 43.0.3. The downgrade is benign and `uv` re-resolves on next run; the SAML test suite ran clean.
- **`tests/test_cli_round_trip.py` collection error during `-k oauth` runs.** Unrelated to Plan 03 scope (Phase 216 CLI test); ignored via `--ignore=tests/test_cli_round_trip.py` for this plan's regression runs. Logged here for the orchestrator's visibility -- if it persists after worktree merge, file as a separate issue.
- **SAML fixture `.xml.b64` files regenerate on every test session.** Per Plan 02's session-autouse `_regenerate_saml_fixtures` fixture, timestamps are kept fresh. The dirty git status was discarded between commits; no fixture regeneration content was committed in this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Plan 04 (frontend admin UI + community 404 test)** can begin immediately. The OAuth admin endpoints now accept SAML provider creation through the existing OAuth CRUD path (D-12 satisfied). The frontend SAML form will POST/PUT to `/settings/oauth-providers/` with `provider_type='saml'` plus the 4 SAML fields; the per-type validator returns clean 422 errors for incomplete configs that the UI can surface inline.
- **Plan 05 (docstring scrubs + verification gate)** can begin immediately. SAML-12 is satisfied; the audit-log diff captures old/new values for role mapping changes (`test_saml_provider_update_logs_old_new_role_mapping`); secret fields are redacted (`test_saml_provider_update_redacts_secret_fields`).
- **Pitfall 11 surface stays closed** as long as no new mapped class introduces enterprise-only columns without `deferred=True`. Document this convention in the `docs-internal/` enterprise-overlay guide if not already present (Plan 05's docstring-scrub task is a natural place to add this note).

## Self-Check: PASSED

Verified:
- `backend/app/modules/auth/oauth/models.py` -- ast-parses; contains all 4 `Mapped[str | None]` SAML cols with `deferred=True` + `deferred_group="saml"`; CHECK literal includes `'saml'`.
- `backend/app/modules/auth/oauth/schemas.py` -- contains `model_validator`, `_validate_per_type`, `idp_entity_id`/`idp_sso_url`/`idp_certificate`/`sp_entity_id`, `Literal["google", "microsoft", "oidc", "saml"]` (Create + Update), `_safe_read_deferred_saml_fields` Response validator; `idp_certificate` NOT in `OAuthProviderResponse.model_fields` (verified via direct introspection); `client_secret_encrypted` also excluded.
- `backend/app/modules/auth/oauth/service.py` -- contains `encrypt_secret(data.idp_certificate)` in `create_provider` and an `idp_certificate` special-case block in `update_provider` mirroring `client_secret`.
- `backend/app/modules/settings/router.py` -- contains `SECRET_FIELDS = {"idp_certificate", "client_secret_encrypted", "client_secret"}`, `SECRET_BODY_FIELDS = {"idp_certificate", "client_secret"}`, `details.changes`, `details.created`, `details.deleted`, `<redacted>` literal; `@router.put("/oauth-providers/{provider_id}")` preserved (no accidental PATCH refactor).
- `backend/tests/test_saml_overlay.py` -- contains all 8 new test names; uses `client.put` (not `client.patch`) on `/settings/oauth-providers/{provider_id}`.
- `geolens_enterprise/auth/saml/router.py` -- contains `from sqlalchemy.orm import undefer_group`, `_get_saml_provider_by_slug`, and three `await _get_saml_provider_by_slug(db, slug)` call sites (login, ACS, metadata); zero remaining `await get_provider_by_slug(db, slug)` calls in the SAML router.

Test results:
- `cd backend && uv run pytest tests/test_saml_overlay.py -x` -- **17 passed** (9 Plan 02 baseline + 5 schema-validation + 3 audit/role-mapping)
- `cd backend && uv run pytest tests/ -k oauth -x --ignore=tests/test_cli_round_trip.py` -- **56 passed** (51 baseline + 5 new schema)
- `cd backend && uv run pytest tests/test_auth.py tests/test_auth_refresh_logout.py tests/test_oauth.py tests/test_extensions.py tests/test_settings_oauth_crud.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_saml_overlay.py tests/test_audit.py` -- **149 passed**
- Pitfall 11 final verification (community-only DB query via `async_session` factory inside `geolens-api-1` container, with all Plan 03 changes copied in): `OK: queried 0 providers in community-only mode (no UndefinedColumnError)`

Commits exist in worktree git log:
- `f035f6f0` -- fix(217-03): mitigate Pitfall 11 with deferred=True on SAML columns
- `6bbca212` -- feat(217-03): add SAML fields + per-type validator to OAuth provider schemas
- `329e81fb` -- feat(217-03): Fernet-encrypt SAML cert + audit-log diff with secret redaction

Cross-repo commit exists in `~/Code/geolens-enterprise`:
- `a98d776` -- fix(saml): use SAML-aware provider lookup with undefer_group("saml")

---
*Phase: 217-auth-saml-enterprise*
*Completed: 2026-04-29*

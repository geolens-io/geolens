---
phase: 221
slug: lifecycle-user-continuity-and-verification
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-30
last_updated: 2026-04-30
---

# Phase 221 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3+ (anyio_mode=auto, asyncio_mode=strict) |
| **Config file** | `backend/pyproject.toml` (`[tool.pytest.ini_options]`); `lifecycle` marker registered Phase 220 |
| **Quick run command** | `cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py` |
| **Full suite command** | `cd backend && uv run pytest -q -m 'not perf'` |
| **Doc-content check** | inline grep block (see Doc-Content Greps section below) |
| **Estimated runtime** | ~10-15 seconds (3 lifecycle tests); ~5 minutes (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py`
- **After every plan wave:** Run full backend suite (`uv run pytest -q -m 'not perf'`) + doc-grep block
- **Before `/gsd-verify-work`:** Full suite must be green; `cd backend && uv run ruff check .` must be clean; all doc-grep assertions green
- **Max feedback latency:** 60 seconds (lifecycle subset)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 221-01-T1 | 01 | 1 | LIFECYCLE-06 | T-221-03 | SamlToLocalConversion schema enforces password length (min 8, max 256); no secret material accepted as field | unit (Pydantic) | `cd backend && uv run python -c "from app.modules.admin.schemas import SamlToLocalConversion; SamlToLocalConversion(password='12345678')"` exits 0 + grep `class SamlToLocalConversion` | ✅ exists (existing schemas.py) | ⬜ pending |
| 221-01-T2 | 01 | 1 | LIFECYCLE-06 | T-221-05, T-221-06 | Service mutates exactly 4 fields in 1 transaction (no commit, no audit); ValueError raised on 3 failure modes; multi-IdP-safe id-scoped DELETE | unit (function shape) | `cd backend && uv run python -c "from app.modules.admin.service import AdminService; assert hasattr(AdminService, 'convert_saml_user_to_local')"` exits 0 + grep `delete(OAuthAccount).where(OAuthAccount.id == saml_account.id)` | ✅ exists (existing service.py) | ⬜ pending |
| 221-01-T3 | 01 | 1 | LIFECYCLE-06 | T-221-01, T-221-02, T-221-03 | Endpoint registered at `/users/{user_id}/convert-saml-to-local/` (trailing slash); self-conversion blocked with 422; require_permission("manage_users") gates non-admins; audit details allow-listed | route registration | `cd backend && uv run python -c "from fastapi.routing import APIRoute; from app.modules.admin.router import router; assert any(r.path == '/users/{user_id}/convert-saml-to-local/' for r in router.routes if isinstance(r, APIRoute))"` exits 0 + negative grep on `details=.*password` | ✅ exists (existing router.py) | ⬜ pending |
| 221-02-T1 | 02 | 1 | LIFECYCLE-06 | T-221-01, T-221-03, T-221-04, T-221-PITFALL-4, T-221-PITFALL-5 | Runbook documents trailing-slash URL, allow-listed audit details, "convert AFTER overlay removal" ordering, self-conversion blocked, correct token endpoint `/auth/login/` | doc-grep | `grep -q "## Handling existing SAML users" docs/edition-deactivation.md && grep -q "convert-saml-to-local/" docs/edition-deactivation.md && ! grep -q "Phase 221 ships" docs/edition-deactivation.md && ! grep -q "/auth/token" docs/edition-deactivation.md` | ✅ exists (Phase 220 file) | ⬜ pending |
| 221-02-T2 | 02 | 1 | LIFECYCLE-06 | — | Reactivation runbook documents that local-password conversions persist; reverse conversion is on deferred roadmap | doc-grep | `grep -q "## Note on previously converted SAML users" docs/edition-reactivation.md && grep -q -i "deferred" docs/edition-reactivation.md` | ✅ exists (Phase 220 file) | ⬜ pending |
| 221-03-T1 | 03 | 2 | LIFECYCLE-06, LIFECYCLE-07 | T-221-T-05 | Cleanup fixture deletes audit_logs/user_roles/datasets BEFORE oauth_accounts/oauth_providers/users; scoped by resolved user_id; existing Phase 220 test still green | regression test | `cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data` exits 0 + grep ordering check | ✅ exists (Phase 220 file) | ⬜ pending |
| 221-03-T2 | 03 | 2 | LIFECYCLE-06 | T-221-03, T-221-T-04 | Endpoint exercised via TestClient with admin auth; 8 ORM-level preservation invariants asserted; audit_log details exact-equality checked against allow-list | integration test | `cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py::test_convert_saml_user_to_local_preserves_user_data` exits 0 | ✅ exists (Phase 220 file, extended) | ⬜ pending |
| 221-03-T3 | 03 | 2 | LIFECYCLE-07 | T-221-T-01, T-221-T-02, T-221-T-03, T-221-T-06 | Round-trip uses Pattern 3 Shape A (NOT register_extensions); deferred imports inside body; 3-surface re-population on reactivate; SEEDED audit_log row asserted (D-10); 4 deferred SAML columns symmetric via undefer_group | integration test | `cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py::test_deactivate_reactivate_roundtrip_preserves_saml_data` exits 0 + negative grep on `register_extensions` | ✅ exists (Phase 220 file, extended) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** No 3 consecutive tasks lack an automated verify command. Plan 01 has 3 tasks each with `<automated>`; Plan 02 has 2 tasks each with `<automated>` doc-grep; Plan 03 has 3 tasks each with `<automated>` pytest invocation.

---

## Wave 0 Requirements

- [x] No new fixtures required — `_seed_saml_provider`, `saml_overlay_registered`, `_cleanup_lifecycle_rows` (extended in 221-03-T1) all inherited from Phase 220 / Phase 217.
- [x] No new framework install — pytest + `lifecycle` marker already registered in `backend/pyproject.toml` (Phase 220).
- [x] No new dependencies — `hash_password`, `log_action`, `require_permission("manage_users")`, `AsyncClient`, `admin_auth_header`, `verify_password` all already imported in their respective modules.
- [x] No new CI workflow change — `.github/workflows/ci.yml` already installs `geolens-enterprise` overlay before backend test job (Phase 220 D-06).
- [x] All `<read_first>` references resolve to files that EXIST today (verified by phase-directory listing + repo grep).

*Existing infrastructure covers all phase requirements. Wave 0 is complete by virtue of Phase 220's groundwork.*

---

## Doc-Content Greps (LIFECYCLE-06 docs assertions — Plan 02)

```bash
# Negative greps -- TODO marker and false claims removed from edition-deactivation.md
! grep -q "Phase 221 ships the user re-onboarding" docs/edition-deactivation.md
! grep -q "manually via the admin UI" docs/edition-deactivation.md
! grep -q "/auth/token" docs/edition-deactivation.md

# Positive greps -- new Handling existing SAML users section content
grep -q "## Handling existing SAML users" docs/edition-deactivation.md
grep -q "convert-saml-to-local/" docs/edition-deactivation.md     # Pitfall 4 trailing slash
grep -q "auth.convert_saml_to_local" docs/edition-deactivation.md # D-14 audit action name
grep -q "/auth/login/" docs/edition-deactivation.md               # Pitfall 5 correct endpoint
grep -q -i "after the overlay is removed" docs/edition-deactivation.md  # Pitfall 8 ordering
grep -q -i "appendix.*oidc\|oidc conversion" docs/edition-deactivation.md
grep -q "handling-existing-saml-users" docs/edition-deactivation.md     # anchor link
grep -q -i "self-conversion is blocked\|cannot convert your own account" docs/edition-deactivation.md  # T-221-01

# Negative grep -- audit details documented WITHOUT password
! grep -E -i 'details.*"password"' docs/edition-deactivation.md   # T-221-03

# Preservation greps -- existing Phase 220 content not destroyed
grep -q "Plan a maintenance window" docs/edition-deactivation.md  # line 83 preserved
grep -q "pg_dump" docs/edition-deactivation.md
grep -q "## Destructive path: permanent decommissioning" docs/edition-deactivation.md
grep -q "edition-reactivation" docs/edition-deactivation.md

# Reactivation runbook
grep -q "## Note on previously converted SAML users" docs/edition-reactivation.md
grep -q -i "converted" docs/edition-reactivation.md
grep -q "edition-deactivation" docs/edition-reactivation.md
grep -q -i "deferred" docs/edition-reactivation.md
grep -q "## Why this works" docs/edition-reactivation.md
grep -q "## References" docs/edition-reactivation.md
```

---

## Code/Schema Greps (LIFECYCLE-06 backend assertions — Plan 01)

```bash
# Schema (Plan 01 Task 1)
grep -q "class SamlToLocalConversion" backend/app/modules/admin/schemas.py
grep -q "min_length=8" backend/app/modules/admin/schemas.py
grep -q "max_length=256" backend/app/modules/admin/schemas.py

# Service (Plan 01 Task 2)
grep -q "async def convert_saml_user_to_local" backend/app/modules/admin/service.py
grep -q "from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider" backend/app/modules/admin/service.py
grep -q 'raise ValueError("User not found")' backend/app/modules/admin/service.py
grep -q "user.password_hash = hash_password(password)" backend/app/modules/admin/service.py
grep -q 'user.auth_provider = "local"' backend/app/modules/admin/service.py
grep -q "delete(OAuthAccount).where(OAuthAccount.id == saml_account.id)" backend/app/modules/admin/service.py

# Router (Plan 01 Task 3)
grep -q '"/users/{user_id}/convert-saml-to-local/"' backend/app/modules/admin/router.py
grep -q "async def convert_saml_to_local" backend/app/modules/admin/router.py
grep -q "SamlToLocalConversion" backend/app/modules/admin/router.py
grep -q '"Cannot convert your own account; use a different admin account"' backend/app/modules/admin/router.py
grep -q '"auth.convert_saml_to_local"' backend/app/modules/admin/router.py
grep -q '"from": "saml", "to": "local", "provider_slug"' backend/app/modules/admin/router.py
# Negative -- no password material in audit details (T-221-03)
! grep -E -i 'details=.*password|password.*details' backend/app/modules/admin/router.py
```

---

## Test Execution Checks (LIFECYCLE-06 + LIFECYCLE-07 — Plan 03)

```bash
# Lifecycle marker still registered (Phase 220 inheritance)
grep -q 'lifecycle:' backend/pyproject.toml

# All three lifecycle tests run and pass
cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py
# Expected output: 3 passed

# Each test runs individually and passes
cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data
cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py::test_convert_saml_user_to_local_preserves_user_data
cd backend && uv run pytest -x -q -m lifecycle backend/tests/test_lifecycle.py::test_deactivate_reactivate_roundtrip_preserves_saml_data

# Pitfall enforcement greps
# Pitfall 2: Pattern 3 Shape A used (NO register_extensions call)
! grep "register_extensions" backend/tests/test_lifecycle.py

# Pitfall 5: deferred enterprise imports (no module-level)
! head -100 backend/tests/test_lifecycle.py | grep "from geolens_enterprise"

# Three-surface re-population assertions present
grep -q '_extensions\["auth"\] = ext' backend/tests/test_lifecycle.py
grep -q '_extensions\["identity"\] = ext' backend/tests/test_lifecycle.py
grep -q "_routers.append(saml_router)" backend/tests/test_lifecycle.py

# D-10 SEEDED audit_log assertion
grep -q "test.seed.lifecycle" backend/tests/test_lifecycle.py
grep -q "audit_log row was destroyed" backend/tests/test_lifecycle.py

# Three @pytest.mark.lifecycle markers (Phase 220 + 221 conversion + 221 round-trip)
test "$(grep -c "@pytest.mark.lifecycle" backend/tests/test_lifecycle.py)" -eq 3

# Cleanup fixture extended (audit_logs / user_roles / datasets BEFORE existing DELETEs)
grep -q "DELETE FROM catalog.audit_logs WHERE user_id" backend/tests/test_lifecycle.py
grep -q "DELETE FROM catalog.user_roles WHERE user_id" backend/tests/test_lifecycle.py
grep -q "DELETE FROM catalog.datasets WHERE created_by" backend/tests/test_lifecycle.py
awk '/DELETE FROM catalog\.audit_logs/{a=NR} /DELETE FROM catalog\.oauth_accounts/{b=NR} END{exit !(a<b)}' backend/tests/test_lifecycle.py
```

---

## CI Integration Checks

```bash
# Phase 220 D-06 install of geolens-enterprise overlay still in place (no Phase 221 amendment needed)
grep -q 'geolens-enterprise' .github/workflows/ci.yml
grep -q -E 'GEOLENS_ENTERPRISE_TOKEN|secrets.GEOLENS' .github/workflows/ci.yml
```

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Operator follows the runbook end-to-end against a deactivated edition | LIFECYCLE-06 (SC#2 doc surface) | Runbook is operator-facing prose; doc-test would be a reading-comprehension proxy | Render `docs/edition-deactivation.md`, walk the new "Handling existing SAML users" section start-to-finish on a staging stack, confirm copy-paste curl + `/auth/login/` flow works end-to-end |
| `audit_log` row produced by the new endpoint visible in operator audit-trail tooling | LIFECYCLE-06 (SC#1 audit history) | Audit-tooling UX is out-of-scope for Phase 221 | After running the conversion against staging, query `SELECT * FROM audit_log WHERE action='auth.convert_saml_to_local'` and confirm the row matches expected shape (allow-listed details only) |
| Markdown anchor `(#handling-existing-saml-users)` resolves correctly when rendered on GitHub | LIFECYCLE-06 (D-12 cross-link) | Markdown anchor generation is renderer-specific | Reviewer opens `docs/edition-deactivation.md` on GitHub and clicks the forward-link from §pre-flight step 3 → confirms it scrolls to the new section |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (Plan 01 = 3 task auto; Plan 02 = 2 task auto; Plan 03 = 3 task auto)
- [x] Wave 0 covers all MISSING references (none — all infra reused from Phase 220)
- [x] No watch-mode flags
- [x] Feedback latency < 60s for lifecycle subset
- [x] `nyquist_compliant: true` set in frontmatter
- [x] Per-Task Verification Map filled (one row per task — 8 tasks total across 3 plans)
- [x] All 7 phase threats (T-221-01..T-221-06 + T-221-T-01..T-221-T-06) have a disposition in the relevant plan's `<threat_model>`

**Approval:** ready for execution

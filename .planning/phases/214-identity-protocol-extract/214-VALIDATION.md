---
phase: 214
slug: identity-protocol-extract
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-27
formalized: 2026-04-29
formalization_note: "Post-hoc paperwork close per v13.1-MILESTONE-AUDIT.md (2026-04-29). Backend test baseline (2001 tests) green; 18-file allowlist guard at test_layering.py:237 enforces cross-domain User-import invariant; Plan 04 verification gate covered all 5 ROADMAP SC; no coverage gaps surfaced by milestone audit. Original status=draft was paperwork lag, not coverage gap."
---

# Phase 214 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Sourced from `214-RESEARCH.md` § Validation Architecture (lines 1215–1256).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥9.0.3 with `anyio_mode = "auto"` / `asyncio_mode = "strict"` |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command (architecture-only)** | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` |
| **Quick run command (auth-affected slice)** | `cd backend && uv run pytest tests/test_layering.py tests/test_extensions.py tests/test_auth_*.py tests/test_admin_*.py tests/test_audit_*.py -v --tb=short` |
| **Full suite command** | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` |
| **Estimated runtime (quick arch)** | ~50ms |
| **Estimated runtime (auth slice)** | ~3-5min |
| **Estimated runtime (full suite)** | ~6-8min |
| **Test floor** | 1999 tests passing (per Phase 213-04 commit `05a60c65`) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_layering.py tests/test_extensions.py -v` (~30s — covers arch guards + new accessor unit test)
- **After every plan wave:** Run the auth-affected slice (~3-5min — auth + admin + audit + extensions slice)
- **Before `/gsd-verify-work`:** Full suite must be green AND `cd backend && uv run alembic check` returns no auth-table changes
- **Max feedback latency:** ~30s for arch guards; ~5min for full auth slice

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 214-01-01 | 01 | 1 | IDENT-01 | T-214-IL | `core/identity.py` defines `IdentityProtocol` + `RoleProtocol` + `IdentityExtension` + `Identity` alias | unit (architecture) | `cd backend && python -c "from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity; print('ok')"` | ❌ W0 (new file) | ⬜ pending |
| 214-01-02 | 01 | 1 | IDENT-03 | T-214-EH | `DefaultIdentityExtension` returns None; `get_identity_extension()` returns it when no overlay registered | unit | `cd backend && uv run pytest tests/test_extensions.py::test_get_identity_extension_returns_default_when_unregistered -v` | ❌ W0 (new test) | ⬜ pending |
| 214-02-01 | 02 | 2 | IDENT-02 (a) | T-214-AB | `get_optional_user`, `get_current_user`, `get_current_active_user` retyped to return `Identity` | integration | `cd backend && uv run pytest tests/test_auth_*.py -v --tb=short` | ✅ existing | ⬜ pending |
| 214-02-02 | 02 | 2 | IDENT-03 | T-214-EH | Extension wired into `get_optional_user` between API-key and JWT paths; default returns None preserves JWT path | integration | `cd backend && uv run pytest tests/test_auth_jwt.py tests/test_auth_api_key.py -v --tb=short` | ✅ existing | ⬜ pending |
| 214-02-03 | 02 | 2 | IDENT-02 (c) | T-214-AB | JWT login → access endpoint flow unchanged | integration | `cd backend && uv run pytest -k "test_login or test_jwt" -v` | ✅ existing | ⬜ pending |
| 214-02-04 | 02 | 2 | IDENT-02 (d) | T-214-AB | API key path (header > query > JWT) unchanged | integration | `cd backend && uv run pytest -k "api_key" -v` | ✅ existing | ⬜ pending |
| 214-02-05 | 02 | 2 | IDENT-02 (e) | T-214-AB | OAuth/OIDC callback → user resolution unchanged | integration | `cd backend && uv run pytest -k "oauth" -v` | ✅ existing | ⬜ pending |
| 214-02-06 | 02 | 2 | IDENT-02 (f) | T-214-AB | Refresh-token rotation unchanged | integration | `cd backend && uv run pytest -k "refresh" -v` | ✅ existing | ⬜ pending |
| 214-03-01 | 03 | 3 | IDENT-02 (a) | T-214-AB | ~42 cross-domain `User` imports rewritten to `Identity` | integration (full suite) | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | ✅ existing 1999+ tests | ⬜ pending |
| 214-03-02 | 03 | 3 | IDENT-02 (a) | T-214-AB | Information-disclosure protection: cross-domain code can no longer access `password_hash`, `auth_provider`, `last_login_at` | manual + grep | `git grep -nE "user\.(password_hash\|auth_provider\|last_login_at)" backend/app/ \| grep -vE "auth/\|admin/"` returns no hits | ✅ git CLI | ⬜ pending |
| 214-04-01 | 04 | 4 | IDENT-01 (regression) | T-214-IL | `test_core_does_not_import_from_any_module` passes (broadens Phase 212 guard) | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module -v` | ❌ W0 (new test) | ⬜ pending |
| 214-04-02 | 04 | 4 | IDENT-02 (regression) | T-214-AB | `test_cross_domain_does_not_import_user_from_auth_models` passes — git pathspec allowlist enforces ~9-site exemption | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models -v` | ❌ W0 (new test) | ⬜ pending |
| 214-04-03 | 04 | 4 | SC#5 (soft) | — | `pyright` reports no new errors on `core/identity.py` and `auth/dependencies.py` (ad-hoc) | manual | `cd backend && npx --yes pyright app/core/identity.py app/modules/auth/dependencies.py` | manual | ⬜ pending |
| 214-04-04 | 04 | 4 | D-23 | — | `alembic check` returns no diff (no schema change from Protocol introduction) | smoke (CLI) | `cd backend && uv run alembic check` | ✅ alembic CLI exists | ⬜ pending |
| 214-04-05 | 04 | 4 | All | — | Full suite green | integration (full suite) | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | ✅ existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/app/core/identity.py` — NEW file containing `IdentityProtocol`, `RoleProtocol`, `IdentityExtension`, `Identity` alias (Plan 01).
- [ ] `backend/app/platform/extensions/defaults.py` — extend with `DefaultIdentityExtension` async class (Plan 01).
- [ ] `backend/app/platform/extensions/__init__.py` — extend with `get_identity_extension()` typed accessor (Plan 01).
- [ ] `backend/tests/test_layering.py` — extend with two new `@pytest.mark.architecture` tests (Plan 04).
- [ ] `backend/tests/test_extensions.py` — extend with `test_get_identity_extension_returns_default_when_unregistered` (Plan 01).
- [ ] No new pytest markers required. `architecture` already registered in Phase 212-03.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `pyright` spot-check on retyped deps | SC#5 (soft) | Project does not run pyright/mypy in CI (per CONTEXT.md D-25). Soft-interpreted SC | Run `cd backend && npx --yes pyright app/core/identity.py app/modules/auth/dependencies.py` after Wave 4 completes; capture output |
| Manual smoke of admin Settings UI | n/a (sanity) | UI doesn't change, but a 30-second smoke verifies no auth regression | `docker compose up -d --build api && curl -fsS http://localhost:8000/health` then login as admin in browser; verify Settings → Branding loads |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`core/identity.py`, two architecture tests, one extension test)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s for arch guards; < 5min for auth slice
- [ ] `nyquist_compliant: true` set in frontmatter (after planner finalizes Plan IDs and acceptance criteria)

**Approval:** pending

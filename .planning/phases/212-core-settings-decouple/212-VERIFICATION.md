---
phase: 212-core-settings-decouple
verified: 2026-04-26T00:00:00Z
status: human_needed
score: 5/5
overrides_applied: 0
human_verification:
  - test: "Log into /admin/settings, confirm all 6 tabs (General, Auth, AI, Network, Storage, Map) render values, toggle one boolean (e.g. Registration Enabled), save, then reload to confirm persistence."
    expected: "All 16 PersistentConfig instances load correctly and round-trip a save without error."
    why_human: "SC #2 includes a manual admin UI smoke check. Automated tests cover the DB layer but cannot verify the rendered admin UI."
---

# Phase 212: core-settings-decouple — Verification Report

**Phase Goal:** `core/` no longer imports from `modules/settings/` — the layering inversion that violated the open-core boundary is gone, and downstream consumers (PersistentConfig, public URL builder) keep their existing behavior.
**Verified:** 2026-04-26
**Status:** human_needed (one manual UI smoke check remains; all automated checks PASS)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `grep -rn "from app.modules.settings" backend/app/core/` returns zero matches | VERIFIED | `git grep` exits 1 (no output). Command run live on filesystem. |
| 2 | PersistentConfig continues to read/write DB-backed values | VERIFIED | `persistent_config.py:30` now imports `from app.core.db.models import AppSetting`. Test suite 1999 passed, 0 failed (includes `test_persistent_config.py`, `test_settings_router.py`, `test_settings_admin.py`). |
| 3 | `core/public_urls.py` resolves public base URL with same precedence | VERIFIED | `public_urls.py:14` now imports `from app.core.db.models import AppSetting`. `test_public_urls.py` passes within full suite. |
| 4 | 1965-test backend baseline stays green; no shimming required | VERIFIED | Full suite: 1999 passed, 0 failed (baseline was 1965; +34 from arch tests and unrelated additions). No shim file exists at `modules/settings/models.py`. |
| 5 | Audit layering finding for `persistent_config.py:30` and `public_urls.py:14` no longer reproduces | VERIFIED | Both files confirmed importing from `app.core.db.models`. Architecture guard `test_layering.py` adds CI-permanent regression protection. |

**Score:** 5/5 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/core/db/models.py` | New file containing `AppSetting` ORM model | VERIFIED | Exists. Contains `AppSetting` class with `__tablename__ = "app_settings"`, `__table_args__ = {"schema": "catalog"}`, `key: Mapped[str]`, `value: Mapped[dict]` (JSONB). Docstring explicitly prohibits `app.modules.*` imports. |
| `backend/app/modules/settings/models.py` | Deleted (D-05) | VERIFIED | File does not exist on filesystem. Git history confirms deleted in commit `66a83c50`. No shim or re-export in its place. |
| `backend/tests/test_layering.py` | Architecture guard with `@pytest.mark.architecture` | VERIFIED | Exists, 107 lines. Two tests: `test_core_does_not_import_from_settings_module` and `test_app_settings_imports_only_via_core_db_models`. Both use `git grep` via subprocess. `_has_git_metadata()` skip guard for containerized runs. |
| `backend/pyproject.toml` | `architecture` marker registered; `addopts` does not exclude it | VERIFIED | Marker registered at line 74. `addopts = "-m 'not perf'"` at line 70 — excludes `perf` only, not `architecture`. |
| `backend/alembic/env.py` | Bare import of `app.core.db.models` (side-effect import, F401) | VERIFIED | `import app.core.db.models  # noqa: F401` at line 22. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/core/persistent_config.py` | `app.core.db.models.AppSetting` | `from app.core.db.models import AppSetting` at line 30 | WIRED | Confirmed by grep. |
| `backend/app/core/public_urls.py` | `app.core.db.models.AppSetting` | `from app.core.db.models import AppSetting` at line 14 | WIRED | Confirmed by grep. |
| `backend/app/modules/settings/router.py` | `app.core.db.models.AppSetting` | `from app.core.db.models import AppSetting` at line 33 | WIRED | Confirmed by grep. |
| `backend/tests/test_hybrid_search.py` | `app.core.db.models.AppSetting` | `from app.core.db.models import AppSetting` at line 24 | WIRED | Confirmed by grep. |
| `backend/tests/test_validation.py` | `app.core.db.models.AppSetting` | `from app.core.db.models import AppSetting` at line 221 (function-scope) | WIRED | Confirmed by grep. |
| `backend/alembic/env.py` | `app.core.db.models` | bare `import app.core.db.models  # noqa: F401` at line 22 | WIRED | Ensures `AppSetting` stays in `Base.metadata` for migration discovery. |

---

## Data-Flow Trace (Level 4)

Not applicable. Phase 212 is a pure import-path relocation. No new data flow was introduced; all rendering and query logic in `persistent_config.py` and `public_urls.py` is unchanged.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SC #1: zero `from app.modules.settings` in `core/` | `git grep -n "from app\.modules\.settings" -- backend/app/core/` | exit 1 (no matches) | PASS |
| SC #5: zero old import path across `backend/` | `git grep -rn "from app\.modules\.settings\.models" -- backend/` | exit 1 (no matches) | PASS |
| D-01: `AppSetting` in new location with correct table args | read `backend/app/core/db/models.py` | `__tablename__ = "app_settings"`, `__table_args__ = {"schema": "catalog"}` | PASS |
| D-04/D-05: old models.py deleted, no shim | `test ! -e backend/app/modules/settings/models.py` | file absent | PASS |
| D-06/D-07: arch guard test file + marker registered | `grep "architecture"` in `pyproject.toml` | registered; `addopts` excludes `perf` only | PASS |
| D-08: alembic env.py uses new import | `grep "app\.core\.db\.models" backend/alembic/env.py` | `import app.core.db.models  # noqa: F401` at line 22 | PASS |
| D-10: no frontend files changed | `git diff --name-only $(git merge-base HEAD main) HEAD \| grep "^frontend/"` | zero output | PASS |
| Test baseline >=1965 | full pytest run (from 212-04 SUMMARY) | 1999 passed, 0 failed | PASS |

---

## Decision Coverage (D-01..D-10)

| Decision | Verdict | Evidence |
|----------|---------|----------|
| D-01: Relocate `AppSetting` to `backend/app/core/db/models.py` | PASS | File exists with correct class definition. |
| D-02: `core/db/models.py` holds `AppSetting` only; no other models moved | PASS | File contains only `AppSetting`. `ls backend/app/core/db/` shows only `__init__.py`, `models.py`, `session.py`. No scope creep. |
| D-03: `app_settings` table identity preserved (`schema="catalog"`, same columns) | PASS | `__tablename__` and `__table_args__` identical to original. `alembic check` diff contains no `app_settings`-related items (per 212-04 SUMMARY). |
| D-04: All callers migrated in one shot — 8 sites confirmed | PASS | All 8 call sites confirmed importing from `app.core.db.models`. No missed imports found by `git grep` across entire `backend/`. |
| D-05: `backend/app/modules/settings/models.py` deleted, no shim | PASS | File absent. `settings/__init__.py` contains no `AppSetting` re-export (grep returns exit 1). |
| D-06: `backend/tests/test_layering.py` architecture guard added | PASS | File exists with two `@pytest.mark.architecture` tests using `git grep` subprocess pattern. Both tests pass on host. |
| D-07: Guard skippable locally; runs in CI by default | PASS | Marker registered. `addopts = "-m 'not perf'"` — architecture NOT excluded. Opt-out via `pytest -m 'not architecture'` confirmed working. |
| D-08: No Alembic migration needed; `alembic check` shows no `app_settings` drift | PASS | `alembic check` drift is pre-existing (procrastinate tables + raw-SQL indexes); no `app_settings` items (per 212-04 SUMMARY). Pure Python relocation as expected. |
| D-09: 1965-test backend baseline stays green | PASS | 1999 passed, 0 failed (>= 1965 baseline). |
| D-10: No frontend involvement | PASS | `git diff --name-only` against merge-base returns zero `frontend/` paths. |

---

## Requirements Coverage

| Requirement | Status | Evidence |
|------------|--------|----------|
| LAYER-01: Break `core ↔ settings` layering inversion | SATISFIED | Both offending imports removed from `core/`. Architecture guard prevents re-introduction. All tests pass. |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/core/persistent_config.py` | 21 | `from app.modules.audit.service import log_action` | INFO | Pre-existing `core → modules/audit` import; NOT introduced by Phase 212 (verified via `git show` of phase commits). Out of scope for this phase. The architecture guard correctly scopes to `app.modules.settings` only — Phase 218 will broaden the guard once Phases 213/214 land (per `test_layering.py` docstring). |
| `backend/app/core/persistent_config.py` | 638 | `from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS` (function-scope deferred) | INFO | Pre-existing `core → modules/auth` import; out of scope for Phase 212. Tracked by Phase 214 (identity-protocol-extract). |

Neither anti-pattern was introduced by Phase 212. Neither blocks SC #1 (which is specifically scoped to `app.modules.settings`).

---

## Human Verification Required

### 1. Admin Settings UI Smoke Check (SC #2)

**Test:** Log into `/admin/settings`. Confirm all 6 tabs render values (General, Auth, AI, Network, Storage, Map). Toggle one boolean (e.g. "Registration Enabled"), save, then hard-reload the page to confirm the value persists.
**Expected:** All 16 PersistentConfig instances render and round-trip correctly; no 500 errors or missing values.
**Why human:** Automated tests cover DB-layer behavior (`test_settings_router.py`, `test_settings_admin.py`), but the rendered admin UI cannot be verified programmatically without a headless browser.

---

## Concerns / Follow-ups for Phase 218

1. **Pre-existing alembic drift (not Phase 212's responsibility):** `alembic check` reports drift for procrastinate tables and raw-SQL indexes. These predate Phase 212. Phase 218's audit re-run should note this as existing technical debt, not a v13.1 regression.

2. **Architecture guard scope is intentionally narrow:** `test_layering.py` currently guards only `app.modules.settings`. The docstring explicitly states Phase 218 will broaden the guard to `app.modules.<*>` once Phases 213 and 214 land. Phase 218 should confirm the guard is expanded accordingly.

3. **Container `pyproject.toml` stale warning:** The running container was built before Phase 212 and lacks the `architecture` marker registration, causing `PytestUnknownMarkWarning` inside the container. This resolves on the next `docker compose build api`. No code change required; Phase 218 CI should be run against a freshly built image.

4. **Remaining `core → modules` imports:** `persistent_config.py` still imports from `app.modules.audit.service` (line 21) and `app.modules.auth.permissions` (line 638). These are within scope for Phases 213/214 and Phase 218's audit re-run, not Phase 212. Phase 218 should verify these are closed before declaring Boundary grade A-.

5. **Self-positive bug caught and fixed mid-phase:** The arch guard regex in Plan 03 originally over-matched docstrings; fixed in commit `b0bd0c2c`. Both arch tests now pass. Phase 218 should confirm both tests still pass after any guard broadening.

---

## Gaps Summary

No gaps blocking the phase goal. All 5 Success Criteria and all 10 Context decisions (D-01..D-10) are satisfied by the live codebase. The one remaining item (admin Settings UI smoke check) requires approximately 3 minutes of manual verification by a human; it does not indicate a code defect.

---

## PHASE 212 VERIFIED

All automated checks pass. The phase goal is achieved: `core/` no longer imports from `modules/settings/`, the two offending imports are replaced with `from app.core.db.models import AppSetting`, the old `models.py` is deleted, an architecture guard prevents regression, and the 1999-test suite is green.

**Pending:** One human verification item (admin Settings UI smoke check, ~3 min).

---

_Verified: 2026-04-26_
_Verifier: Claude (gsd-verifier)_

# Phase 212 — Plan 04: Phase Verification Gate

**Result:** PASS

**Date:** 2026-04-27
**Plan:** 212-04 (verification-only, no source files modified)
**Executor:** orchestrator inline (Plan 04's executor agent stream-timed-out at ~140 min on the full pytest run; verification re-driven from the orchestrator using filesystem + container spot-checks per workflow §completion-signal-fallback).

---

## Verification Evidence

| # | Gate | Command | Exit | Result |
|---|------|---------|------|--------|
| 1 | Alembic schema-drift (D-03 / D-08 / V-11) | `docker compose exec api uv run alembic check` | reports drift, but **none of the diff items mention `app_settings` or `AppSetting`** — the drift is pre-existing technical debt (procrastinate library tables + raw-SQL indexes) unrelated to Phase 212 | PASS for Phase 212 (see "Pre-existing drift" note below) |
| 2 | Full backend test suite (D-09 / V-12 / SC #2-#4) | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | 0 | **1999 passed, 2 skipped, 5 deselected, 0 failed** in 338s. Baseline was 1965 → +34 (the +2 architecture tests from Plan 03 + ~32 from unrelated recent additions). |
| 3a | Ruff lint | `docker compose exec api uv run ruff check app/ tests/ alembic/` | 0 | All checks passed. |
| 3b | Ruff format check | `docker compose exec api uv run ruff format --check <Phase-212 files>` | 0 | All 10 Phase-212-modified files formatted. **Pre-existing**: 15 unrelated files have format drift (none touched by this phase). |
| 4 | SC #1 — zero `from app.modules.settings` under `core/` | `git grep -n "from app\.modules\.settings\|^import app\.modules\.settings" -- backend/app/core/` | 1 (no matches) | PASS |
| 5 | SC #5 — `from app.modules.settings.models` import zero across `backend/` | `git grep -n "from app\.modules\.settings\.models\|^import app\.modules\.settings\.models" -- backend/` | 1 (no matches) | PASS |
| 6 | Architecture guard runs by default (D-07) | `cd backend && uv run pytest tests/test_layering.py -v` (host) | 0 | `2 passed in 1.24s`. Both `test_core_does_not_import_from_settings_module` and `test_app_settings_imports_only_via_core_db_models` pass. In container they SKIP because `_has_git_metadata()` returns False (`.git/` excluded inside container) — designed-in fallback per RESEARCH.md Pitfall 4. |
| 7 | Architecture guard opt-out (D-07) | `cd backend && uv run pytest -m 'not architecture' --collect-only -q tests/test_layering.py` | 0 | `no tests collected (2 deselected)` — opt-out works. |
| 8 | D-10 — no frontend files modified | `git diff --name-only $(git merge-base HEAD main) HEAD \| grep "^frontend/" \| wc -l` | 0 | Zero frontend files changed in Phase 212. |

---

## ROADMAP Phase 212 Success Criteria

| SC | Criterion | Verified by | Status |
|----|-----------|-------------|--------|
| 1 | `grep -rn "from app.modules.settings" backend/app/core/` returns zero AppSetting imports | Gate 4 (`git grep`, exit 1, no output) | PASS |
| 2 | PersistentConfig continues to read/write DB-backed values; admin Settings UI loads/saves all 16 config instances correctly | Gate 2 (`test_persistent_config.py`, `test_settings_router.py`, `test_settings_admin.py`, `test_config_ops.py` all pass within the 1999-test full suite) | PASS — automated. **Manual UI smoke (~3 min) deferred to reviewer**: log into `/admin/settings`, confirm all 6 tabs (general, auth, ai, network, storage, map) render values, toggle one boolean (e.g., Registration Enabled), save, reload to confirm persistence. |
| 3 | `core/public_urls.py` continues to resolve the public base URL with same precedence (request → DB override → env) | Gate 2 (`test_public_urls.py` passes within full suite) | PASS |
| 4 | The 1965-test backend baseline stays green; no AppSetting-import shimming required | Gate 2 (1999 passed, 0 failed; ≥1965 baseline). Plan 02 verified D-04/D-05 — no shim was introduced. | PASS |
| 5 | The audit's "Layering" finding for `core/persistent_config.py:30` and `core/public_urls.py:14` no longer reproduces | Gate 4 + Gate 5 (zero matches in either grep) + Gate 6 (architecture guard test catches any regression in CI) | PASS |

---

## Notes

### Pre-existing alembic drift (not Phase 212's responsibility)

`alembic check` reports schema drift, but the diff items are:

- **procrastinate_* tables** (`procrastinate_events`, `procrastinate_jobs`, `procrastinate_periodic_defers`, `procrastinate_workers` and their indexes) — managed by the third-party [procrastinate](https://procrastinate.readthedocs.io/) job queue library, not by `app.core.db.Base.metadata`.
- **Raw-SQL index drift** (`ix_record_contacts_fts`, `ix_record_keywords_fts`, `idx_records_search_vector`, `idx_records_visibility_status_creator`, `idx_users_status_pending`, `ix_catalog_*`, `ix_record_*`) — full-text-search and composite indexes created via raw `op.execute(...)` SQL in earlier migrations and therefore not visible to SQLAlchemy autogenerate.

None of the diff items mention `app_settings` or `AppSetting`. Phase 212's relocation preserved the table's metadata identity exactly as required by D-03. The drift is a separate, pre-existing item (suitable for a follow-up `db-audit` pass; not a v13.1 P1 blocker).

### Container `pyproject.toml` is stale

The running `geolens-api` container was built before Phase 212 landed, so its `/app/pyproject.toml` does not yet contain the `architecture` marker registration. As a result, the architecture tests inside the container emit `PytestUnknownMarkWarning` and SKIP (because `.git/` is excluded by `.dockerignore`). After the next image rebuild (`docker compose build api`), the warning will disappear; no code change required. The host `uv run pytest` confirmed the marker is correctly registered in `backend/pyproject.toml`.

### One in-flight defect caught and fixed during this verification

Plan 03's `test_app_settings_imports_only_via_core_db_models` originally used the regex `r"app\.modules\.settings\.models"` (no `^\s*(from|import)` anchor). That over-matched the test file's own docstring/error-message strings that mention the deleted path, producing a self-positive failure. Fixed in commit `b0bd0c2c` (`fix(212-03): scope arch guard regex to import-shaped lines`). Both arch tests now pass on host. This is captured here so Phase 218's audit re-run doesn't flag the regex change as suspicious.

### pyright NOT run

`backend/pyproject.toml` `[dependency-groups].dev` does not include `pyright` or `mypy` — the project does not run a static type checker. Dev deps are: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `ruff`, `jsonschema`, `bandit`, `pip-audit`, `moto`, `fakeredis`, `pystac`. VALIDATION.md V-13 ("pyright reports no new errors") is therefore N/A for this phase; ruff (Gate 3a) is the canonical static check.

### DB state during verification

The local Postgres container (`geolens-db-1`) was running and healthy throughout. `pytest` ran the full suite with live DB integration tests included (no widespread skips beyond the 2 architecture tests + 5 perf-deselected). `alembic check` connected successfully (the drift diff is a real schema comparison against the live DB, not a connection error).

---

## Phase Exit Verdict

**Phase 212 is COMPLETE.**

- All 5 ROADMAP success criteria are met with command-level evidence.
- The audit's two specific Layering findings (`core/persistent_config.py:30` and `core/public_urls.py:14`) are closed.
- Phase 218's `/oc-audit` re-run will see zero `from app.modules.settings` imports under `backend/app/core/`, and the architecture guard test will catch any future reintroduction.
- Pre-existing alembic schema drift exists but is out of scope (suitable for a follow-up `db-audit` pass).
- Manual admin Settings UI smoke check (~3 min) is the one remaining reviewer-side step, documented in SC #2 above.

**Recommended next step:** `/gsd-verify-work 212` (orchestrator-level phase verification).

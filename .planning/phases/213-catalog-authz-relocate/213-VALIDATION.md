---
phase: 213
slug: catalog-authz-relocate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-27
---

# Phase 213 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with `anyio_mode = "auto"` / `asyncio_mode = "strict"` |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` |
| **Full suite command** | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` |
| **Estimated runtime** | ~3s (architecture tests) / ~120s (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_layering.py -v` — fast architecture-guard sanity check
- **After every plan wave:** Run `cd backend && uv run pytest tests/test_layering.py tests/test_dataset_visibility.py tests/test_search.py tests/test_features.py tests/test_tiles.py -v --tb=short` — RBAC slice across the most exercised endpoints
- **Before `/gsd-verify-work`:** Full suite green AND `cd backend && uv run alembic check` returns no catalog-table changes AND `git grep -nE "auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'` exits 1 (no matches)
- **Max feedback latency:** ~3s for architecture, ~120s for full suite

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 213-01-01 | 01 | 1 | LAYER-02 | — | New module exists at `backend/app/modules/catalog/authorization.py` with verbatim public surface | unit (smoke) | `cd backend && uv run python -c "from app.modules.catalog.authorization import DatasetVisibility, apply_visibility_filter, get_user_roles, check_dataset_access, check_dataset_access_or_anonymous; print('ok')"` | ❌ W0 (file created in this task) | ⬜ pending |
| 213-02-01 | 02 | 2 | LAYER-02 | — | All 22 module-level + 4 deferred imports rewritten to `app.modules.catalog.authorization`; `auth/visibility.py` deleted | unit (architecture) | `git grep -cE "from app\.modules\.auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'` (must be 0) | ❌ W0 | ⬜ pending |
| 213-02-02 | 02 | 2 | LAYER-02 | — | RBAC parity preserved across search, datasets, features, tiles, STAC, OGC, maps, collections, jobs, AI, export, ingest, sandbox | integration (full suite) | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` (≥1999 passing) | ✅ existing corpus | ⬜ pending |
| 213-03-01 | 03 | 3 | LAYER-02 | — | `test_no_imports_from_auth_visibility` arch test passes; no `from app.modules.auth.visibility` import lines anywhere in backend/ | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_no_imports_from_auth_visibility -v` | ❌ W0 | ⬜ pending |
| 213-03-02 | 03 | 3 | LAYER-02 | — | `test_no_auth_visibility_module_referenced` arch test passes; broader `auth.visibility` reference guard active (excludes test file via pathspec or anchor) | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_no_auth_visibility_module_referenced -v` | ❌ W0 | ⬜ pending |
| 213-04-01 | 04 | 4 | LAYER-02 | — | Alembic schema-drift check returns no diff (pure-Python relocation, table unchanged) | smoke (CLI) | `cd backend && uv run alembic check` exits 0 with "no new operations" | ✅ alembic CLI | ⬜ pending |
| 213-04-02 | 04 | 4 | LAYER-02 | — | Ruff lint + format pass | smoke (CLI) | `cd backend && uv run ruff check . && uv run ruff format --check .` exits 0 | ✅ ruff installed | ⬜ pending |
| 213-04-03 | 04 | 4 | LAYER-02 | — | All 4 ROADMAP success criteria satisfied + 1999-test baseline green | full suite + assertions | Verification gate plan documents `git grep` exit code, alembic output, pytest summary, ruff output | ✅ pattern from 212-04 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/app/modules/catalog/authorization.py` — new module file, verbatim copy of visibility.py with DatasetGrant import promoted to module level (Plan 01)
- [ ] `backend/tests/test_layering.py` — extend with `test_no_imports_from_auth_visibility` and `test_no_auth_visibility_module_referenced`; update module docstring (Plan 03)

*Existing infrastructure covers all RBAC behavior verification — no new test scaffolding for parity. The 1999-test baseline corpus already exercises visibility on search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification. The phase deliberately adds no new RBAC behavior; existing test coverage proves parity.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter (toggle when planner finalizes plans)

**Approval:** pending

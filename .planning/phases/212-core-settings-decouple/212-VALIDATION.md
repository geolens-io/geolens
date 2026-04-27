---
phase: 212
slug: core-settings-decouple
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-27
---

# Phase 212 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) — existing |
| **Config file** | `backend/pyproject.toml` (pytest section); `backend/Makefile` `test` target |
| **Quick run command** | `cd backend && uv run pytest tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_layering.py -x` |
| **Full suite command** | `cd backend && uv run pytest -m 'not perf' --tb=short` (mirrors CI) |
| **Estimated runtime** | quick ~30s · full ~5–8 min (1965 tests) |

Notes:
- Test runner is the host `uv run pytest` (not `docker compose exec`) per RESEARCH.md §6 and `Makefile` `make test` target. The Docker variant exists but the host invocation is the canonical local path because `uv` is the project's package manager.
- The architecture-guard test (D-06) uses `subprocess.run(["git", "grep", ...])` and requires `.git/` to be present at test time. Skip guard via `_has_git_metadata()` (RESEARCH.md Pitfall 4).
- `alembic check` is run separately as a non-pytest shell verification: `cd backend && uv run alembic check`. No `make migrations-check` target exists; use the raw command.

---

## Sampling Rate

- **After every task commit:** Run `quick run command` (target ~30s; covers PersistentConfig + settings router + admin endpoint + new layering guard).
- **After every plan wave:** Run full suite command.
- **Before `/gsd-verify-work`:** Full suite green AND `cd backend && uv run alembic check` reports no schema drift.
- **Max feedback latency:** 60s (quick) / 480s (full).

---

## Per-Task Verification Map

> The exact task IDs are assigned by the planner. The rows below describe the verification dimensions every task in this phase must hit; the planner maps these to its concrete task IDs (e.g., `212-01-01`, `212-02-03`).

| # | Verification Dimension | Plan (TBD by planner) | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---|------------------------|-----------------------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| V-01 | New `core/db/models.py` exists, exports `AppSetting`, satisfies `Base` | 01 | 1 | LAYER-01 | — | N/A | unit | `cd backend && uv run python -c "from app.core.db.models import AppSetting; assert AppSetting.__tablename__=='app_settings'; assert AppSetting.__table_args__=={'schema':'catalog'}"` | ✅ Wave 0 (commit 1 produces it) | ⬜ pending |
| V-02 | Old `modules/settings/models.py` deleted | 02 | 2 | LAYER-01 | — | N/A | unit | `test ! -e backend/app/modules/settings/models.py` | ✅ | ⬜ pending |
| V-03 | Zero `from app.modules.settings` imports under `backend/app/core/` | 02/03 | 2/3 | LAYER-01 | — | N/A | unit | `! git grep -n 'from app\.modules\.settings' -- backend/app/core/` | ✅ | ⬜ pending |
| V-04 | All 9 caller files migrated (RESEARCH.md §1) | 02 | 2 | LAYER-01 | — | N/A | unit | `! git grep -n 'from app\.modules\.settings\.models import AppSetting' -- backend/` | ✅ | ⬜ pending |
| V-05 | `backend/alembic/env.py` imports `AppSetting` from `app.core.db.models` | 02 | 2 | LAYER-01 | — | Migration metadata still includes `app_settings` after relocation | unit | `git grep -n 'from app\.core\.db\.models import' -- backend/alembic/env.py` | ✅ | ⬜ pending |
| V-06 | PersistentConfig get/set/reset behavior preserved | 03 | 3 | LAYER-01 | — | DB override → cache → env-default precedence unchanged | unit | `cd backend && uv run pytest tests/test_persistent_config.py -x` | ✅ existing | ⬜ pending |
| V-07 | Public URL precedence preserved (request → DB override → env) | 03 | 3 | LAYER-01 | — | URL builder unchanged | unit/integration | `cd backend && uv run pytest tests/test_public_urls.py -x` (or full search if name differs — see RESEARCH.md §7) | ✅ existing | ⬜ pending |
| V-08 | Settings router round-trips all 16 PersistentConfig keys | 03 | 3 | LAYER-01 | — | Admin Settings UI loads/saves preserved (API-level proof) | integration | `cd backend && uv run pytest tests/test_settings_router.py tests/test_settings_admin.py -x` | ✅ existing | ⬜ pending |
| V-09 | Architecture guard test exists and passes | 04 | 4 | LAYER-01 | — | Future regression of LAYER-01 caught at test time | unit | `cd backend && uv run pytest tests/test_layering.py -x -m architecture` | ❌ W0 (created in Wave 4) | ⬜ pending |
| V-10 | Architecture guard FAILS when LAYER-01 violated (proves guard works) | 04 | 4 | LAYER-01 | — | Negative-test discipline | unit | manual: temporarily add `from app.modules.settings.models import AppSetting` to `core/persistent_config.py`, run `pytest tests/test_layering.py`, expect failure, revert | ❌ W0 | ⬜ pending |
| V-11 | Alembic reports no schema drift after relocation | 04 | 4 | LAYER-01 | — | No phantom migration generated | shell | `cd backend && uv run alembic check` (exit 0; output contains "No new upgrade operations" or equivalent) | ✅ | ⬜ pending |
| V-12 | Full backend test baseline holds (1965 → 1965 + new layering test) | 04 | 4 | LAYER-01 | — | No regression introduced by relocation | integration | `cd backend && uv run pytest -m 'not perf' --tb=short` (exit 0; collection ≥1965) | ✅ | ⬜ pending |
| V-13 | `pyright` / type checker reports no new errors | 04 | 4 | LAYER-01 | — | Catches missed importer | unit | `cd backend && uv run pyright app/` (or whatever check the repo uses; RESEARCH.md flags `mypy` as alternate) | ✅ | ⬜ pending |
| V-14 | Audit findings for `core/persistent_config.py:30` and `core/public_urls.py:14` no longer reproduce | 04 | 4 | LAYER-01 | — | Phase 218 audit re-run will show LAYER-01 closed | shell | `! git grep -n 'from app\.modules\.settings\.models import AppSetting' -- backend/app/core/` (combined with V-03) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_layering.py` — created in Wave 4 (architecture guard); dependency for V-09 and V-10. Contains:
  - `test_core_does_not_import_settings_module()` — `git grep` assertion, requires `_has_git_metadata()` skip guard
  - `test_no_app_settings_import_outside_core_db()` — broader guard preventing reintroduction at any other call site
  - `pytest.ini`/`pyproject.toml` `markers = ["architecture: ..."]` registration so `-m architecture` works
- [ ] `backend/app/core/db/models.py` — created in Wave 1; dependency for V-01, V-04, V-05.
- [ ] No new framework or fixture installs needed — pytest, alembic, uv, ruff, pyright already present.

*Existing infrastructure covers all phase verifications except the architecture guard (which this phase introduces).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Admin Settings UI smoke | LAYER-01 SC#2 | Frontend rendering not auto-tested at this layer; API tests cover the data path | After full pytest pass, run `docker compose up -d`, log in as admin, open `/admin/settings`, confirm all 6 tabs (general, auth, ai, network, storage, map) load values; toggle one boolean (e.g., `Registration Enabled`); confirm save returns 200 and value persists across page reload. ~3 min. |
| Negative test for guard | LAYER-01 D-06 | Negative test is destructive (introduces a violation) | One-time during Wave 4: temporarily add `from app.modules.settings.models import AppSetting` (the deleted module — should also fail) OR `from app.modules.settings import router` to `core/persistent_config.py`, run `pytest tests/test_layering.py`, confirm it FAILS, revert. Document the result in plan-level commit message; do NOT commit the violation. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (architecture-guard test is the only Wave-introduced check)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (each commit runs the quick suite)
- [ ] Wave 0 covers all MISSING references (V-09, V-10 depend on `tests/test_layering.py` introduced in Wave 4)
- [ ] No watch-mode flags (`-x` halts on first failure; no `--watch`)
- [ ] Feedback latency < 60s (quick) / 480s (full)
- [ ] `nyquist_compliant: true` set in frontmatter (planner sets after writing plans)

**Approval:** pending

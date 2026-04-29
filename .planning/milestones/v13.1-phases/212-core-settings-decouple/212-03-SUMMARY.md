---
phase: 212-core-settings-decouple
plan: "03"
subsystem: backend/tests
tags: [test, architecture, layering, ci, open-core]
dependency_graph:
  requires: [212-02]
  provides: [CI architecture guard for LAYER-01 boundary, architecture pytest marker]
  affects:
    - backend/tests/test_layering.py
    - backend/pyproject.toml
tech_stack:
  added: []
  patterns: [subprocess git grep architecture guard, pytest custom marker opt-out]
key_files:
  created:
    - backend/tests/test_layering.py
  modified:
    - backend/pyproject.toml (architecture marker added to markers list)
decisions:
  - "D-06: Architecture guard uses subprocess git grep (NARROW: from app.modules.settings only) per Open Question 1 resolution — broader rule deferred to Phase 218"
  - "D-07: architecture marker is opt-out (not excluded from addopts); guard runs by default in CI; local opt-out via pytest -m 'not architecture'"
  - "Pitfall 4: _has_git_metadata() skip guard included so test gracefully skips inside containers without .git/"
  - "Negative test finding: git grep scans git index (committed/staged), not the working tree — guard catches any violation at commit/CI time, which is the correct CI-oriented posture"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-26"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 2
---

# Phase 212 Plan 03: Architecture Guard Test Summary

Architecture guard test (`backend/tests/test_layering.py`) with two `@pytest.mark.architecture` tests and `_has_git_metadata()` skip guard; `architecture` marker registered in `backend/pyproject.toml`; both tests pass against the post-Plan 02 codebase.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 03-01 | Create test_layering.py + register architecture marker | `f02de69b` | backend/tests/test_layering.py (created), backend/pyproject.toml (modified) |

## What Was Created

### `backend/tests/test_layering.py` (106 lines)

Two `@pytest.mark.architecture` tests with shared `_has_git_metadata()` skip guard:

1. **`test_core_does_not_import_from_settings_module`** — uses `git grep -n -E "^\s*(from|import)\s+app\.modules\.settings"` on `backend/app/core/`. Guards LAYER-01: the two inversion sites (`core/persistent_config.py:30` and `core/public_urls.py:14`) removed in Plan 02 must stay removed. Fails with a clear message naming the offending file(s).

2. **`test_app_settings_imports_only_via_core_db_models`** — uses `git grep "app\.modules\.settings\.models"` across all of `backend/`. Guards D-05: the deleted `modules/settings/models.py` path must not be reintroduced anywhere in the repo. Catches both import statements and string references.

Both tests skip gracefully when `.git/` is unavailable (RESEARCH.md Pitfall 4):
```python
def _has_git_metadata() -> bool:
    return (REPO_ROOT / ".git").exists()
```

### `backend/pyproject.toml` (markers list — 2 entries → 3 entries)

```diff
 markers = [
     "perf: performance regression tests (deselected by default)",
     "requires_ogr2ogr: tests that invoke ogr2ogr and need build_pg_conn_str redirected ...",
+    "architecture: layering and boundary tests; opt-out locally with `-m 'not architecture'` (Phase 212 LAYER-01 guard)",
 ]
```

`addopts = "-m 'not perf'"` — **unchanged**. The architecture guard runs by default in CI.

## Test Execution Results

```
tests/test_layering.py::test_core_does_not_import_from_settings_module PASSED
tests/test_layering.py::test_app_settings_imports_only_via_core_db_models PASSED

2 passed in 1.79s
```

No `PytestUnknownMarkWarning` emitted.

## Opt-Out Verification

```
cd backend && uv run pytest -m 'not architecture' --collect-only -q tests/test_layering.py
→ no tests collected (2 deselected) — exit 5
```

Proves D-07 opt-out works. Contributors running `pytest -m 'not architecture'` locally get 0 collected from this file.

## Negative Test Discipline (Step 4)

**Finding:** `subprocess.run(["git", "grep", ...])` scans the git index (committed and staged content), NOT the working tree. Injecting `from app.modules.settings import router as _x` into `persistent_config.py` without staging did NOT trigger the test failure — git grep does not see unstaged changes.

**Implication:** The guard catches violations at the moment a contributor commits or stages them. This is the correct CI-oriented posture: the guard fires on `git grep HEAD` or `git grep` of the index, meaning any violation that reaches a commit (and thus CI) will be caught. A local unstaged edit is not caught until staged/committed.

**Confirmation of current clean state:** `git grep -n -E "^\s*(from|import)\s+app\.modules\.settings" -- backend/app/core/` → exit code 1 (no matches). Guard passes on the post-Plan 02 codebase.

## Guard Scope Note

**NARROW rule** — only `from app.modules.settings` (and `import app.modules.settings.*`). Per RESEARCH.md Open Question 1 (RESOLVED narrow):

- `backend/app/core/persistent_config.py` still has `from app.modules.audit.service import log_action` (line 21) and `from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS` (line 638) — these are Phase 213/214 territory.
- Broadening the guard to `from app.modules.<anything>` would break CI for unrelated reasons.
- Phase 218 will broaden to the full rule once Phases 213 and 214 close their `core → modules` edges.

## Deviations from Plan

None — plan executed exactly as written. Both tests pass; addopts unchanged; marker registered cleanly.

## Self-Check: PASSED

- `backend/tests/test_layering.py` exists: FOUND
- `architecture: layering` in `backend/pyproject.toml`: FOUND (1 match)
- `addopts = "-m 'not perf'"` unchanged: CONFIRMED
- Commit `f02de69b` exists: FOUND
- `uv run pytest tests/test_layering.py -v`: 2 passed, 0 failed
- `uv run pytest -m 'not architecture' --collect-only -q tests/test_layering.py`: 0 collected (2 deselected)
- No PytestUnknownMarkWarning: CONFIRMED

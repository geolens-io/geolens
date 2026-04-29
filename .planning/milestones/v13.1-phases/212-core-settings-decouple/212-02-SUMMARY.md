---
phase: 212-core-settings-decouple
plan: "02"
subsystem: backend/core/db
tags: [refactor, layering, migration, alembic, open-core]
dependency_graph:
  requires: [212-01]
  provides: [AppSetting imported exclusively from app.core.db.models across all callers]
  affects:
    - backend/app/core/persistent_config.py
    - backend/app/core/public_urls.py
    - backend/app/modules/settings/router.py
    - backend/alembic/env.py
    - backend/tests/test_hybrid_search.py
    - backend/tests/test_validation.py
    - backend/tests/test_persistent_config.py
    - backend/tests/test_ai_send_sample_values.py
tech_stack:
  added: []
  patterns: [import-path migration (Pattern A from-style + Pattern B alembic bare), git rm for staged deletion]
key_files:
  created: []
  modified:
    - backend/app/core/persistent_config.py (line 30: from-import migrated)
    - backend/app/core/public_urls.py (line 14: from-import migrated)
    - backend/app/modules/settings/router.py (line 33: from-import migrated)
    - backend/alembic/env.py (line 22: bare side-effect import migrated)
    - backend/tests/test_hybrid_search.py (line 24: from-import migrated)
    - backend/tests/test_validation.py (line 221: function-scope from-import migrated)
    - backend/tests/test_persistent_config.py (lines 18, 942, 985, 1021, 1079: 5 function-scope from-imports migrated)
    - backend/tests/test_ai_send_sample_values.py (line 22: function-scope from-import migrated)
  deleted:
    - backend/app/modules/settings/models.py (D-05 — no shim, no re-export)
decisions:
  - "D-04: All 12 import sites across 9 files migrated in one pass, no backward-compat shim"
  - "D-05: backend/app/modules/settings/models.py deleted via git rm, no replacement file"
  - "Pitfall 1 mitigated: alembic/env.py uses bare import form `import app.core.db.models  # noqa: F401`"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-27"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 9
---

# Phase 212 Plan 02: Migrate Callers and Delete Old models.py Summary

Migrated all 12 AppSetting import sites across 9 files from `app.modules.settings.models` to `app.core.db.models`; deleted `backend/app/modules/settings/models.py` via `git rm`; smoke test slice (101 tests) passed; alembic env.py resolves the new module path without ModuleNotFoundError.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 02-01 | Migrate all 9 caller files to new import path | `c2fd4c61` | 8 files modified |
| 02-02 | Delete backend/app/modules/settings/models.py | `66a83c50` | 1 file deleted |

## Migration Detail

### Inventory Verification

Pre-execution `git grep` confirmed the inventory matches RESEARCH.md §1 exactly:

```
backend/alembic/env.py:22                      import app.modules.settings.models  # noqa: F401
backend/app/core/persistent_config.py:30       from app.modules.settings.models import AppSetting
backend/app/core/public_urls.py:14             from app.modules.settings.models import AppSetting
backend/app/modules/settings/router.py:33      from app.modules.settings.models import AppSetting
backend/tests/test_ai_send_sample_values.py:22 from app.modules.settings.models import AppSetting
backend/tests/test_hybrid_search.py:24         from app.modules.settings.models import AppSetting
backend/tests/test_persistent_config.py:18     from app.modules.settings.models import AppSetting
backend/tests/test_persistent_config.py:942    from app.modules.settings.models import AppSetting
backend/tests/test_persistent_config.py:985    from app.modules.settings.models import AppSetting
backend/tests/test_persistent_config.py:1021   from app.modules.settings.models import AppSetting
backend/tests/test_persistent_config.py:1079   from app.modules.settings.models import AppSetting
backend/tests/test_validation.py:221           from app.modules.settings.models import AppSetting
```

Total: 12 import statements, 9 files. No extra sites found.

### Edit Patterns Applied

**Pattern A — `from`-style import (11 lines):**

```diff
-from app.modules.settings.models import AppSetting
+from app.core.db.models import AppSetting
```

Applied to all files except `alembic/env.py`.

**Pattern B — alembic side-effect import (1 line, `backend/alembic/env.py:22`):**

```diff
-import app.modules.settings.models  # noqa: F401
+import app.core.db.models  # noqa: F401
```

The `# noqa: F401` comment preserved exactly. Bare `import` form retained (not converted to `from` import) per Pitfall 1 / RESEARCH.md.

### File-by-file changes

| File | Line(s) | Pattern | Notes |
|------|---------|---------|-------|
| `backend/alembic/env.py` | 22 | B | Side-effect import for Base.metadata registration |
| `backend/app/core/persistent_config.py` | 30 | A | Module-level; LAYER-01 primary finding |
| `backend/app/core/public_urls.py` | 14 | A | Module-level; LAYER-01 primary finding |
| `backend/app/modules/settings/router.py` | 33 | A | In-domain caller; Pitfall 5 |
| `backend/tests/test_ai_send_sample_values.py` | 22 | A | Function-scope (autouse fixture) |
| `backend/tests/test_hybrid_search.py` | 24 | A | Module-level |
| `backend/tests/test_persistent_config.py` | 18, 942, 985, 1021, 1079 | A | 5 function-scope imports |
| `backend/tests/test_validation.py` | 221 | A | Function-scope |

### Deletion

`backend/app/modules/settings/models.py` deleted via `git rm` (D-05). No shim, no re-export stub. `git status` shows `deleted: backend/app/modules/settings/models.py` staged in commit `66a83c50`.

### Unchanged Files (Verified)

- `backend/app/core/db/__init__.py` — zero diff (Pitfall 2 avoided)
- `backend/app/modules/settings/__init__.py` — zero diff (single-line docstring, no re-export)
- `backend/tests/test_settings_router.py` — zero diff (indirect import via `__init__.py`, not `models.py`)

## Smoke Test Slice Output

```
101 passed, 18 warnings in 27.22s
```

Files covered: `tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_hybrid_search.py tests/test_validation.py tests/test_ai_send_sample_values.py`

## Alembic Check Output

`cd backend && uv run python -m alembic check` — DB connection error (PostGIS extension not installed on local dev DB), but NOT a `ModuleNotFoundError`. Alembic env.py resolved `import app.core.db.models` successfully. This is the expected acceptable result per the plan's Step 6 acceptance criteria.

## Post-Migration Verification

```
git grep "app.modules.settings.models" -- backend/ → 0 matches (PASS)
grep -n "^import app.core.db.models" backend/alembic/env.py → line 22 (PASS)
test ! -e backend/app/modules/settings/models.py → exit 0 (PASS)
```

## Deviations from Plan

None — plan executed exactly as written. Inventory matched RESEARCH.md §1 exactly (no additional files found). All 12 sites migrated in one pass.

## Self-Check: PASSED

- `c2fd4c61` commit exists: FOUND
- `66a83c50` commit exists: FOUND
- `backend/app/modules/settings/models.py` absent: CONFIRMED
- `git grep "app.modules.settings.models" -- backend/` returns zero: CONFIRMED
- `grep "^import app.core.db.models" backend/alembic/env.py` returns line 22: CONFIRMED
- Smoke test slice: 101 passed, 0 failed

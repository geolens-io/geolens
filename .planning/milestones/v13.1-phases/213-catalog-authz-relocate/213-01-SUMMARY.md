---
phase: 213-catalog-authz-relocate
plan: "01"
subsystem: backend/catalog
tags: [refactor, layering, relocation, open-core]
requirements_addressed: [LAYER-02]

dependency_graph:
  requires: []
  provides:
    - backend/app/modules/catalog/authorization.py (new — verbatim public surface of auth/visibility.py)
  affects:
    - backend/app/modules/auth/visibility.py (untouched; co-exists pending Plan 02)

tech_stack:
  added: []
  patterns:
    - "Verbatim relocation with deferred-import promotion (DatasetGrant moved from function scope to module level)"

key_files:
  created:
    - backend/app/modules/catalog/authorization.py
  modified: []

decisions:
  - "D-01: Flat single file catalog/authorization.py (not catalog/_authz/visibility.py)"
  - "D-02: Exact public surface preserved — DatasetVisibility, apply_visibility_filter, get_user_roles, check_dataset_access, check_dataset_access_or_anonymous"
  - "D-03: DatasetGrant promoted from function-scope deferred import to module-level; Role/User/UserRole still from auth.models"
  - "No inline comment added to DatasetGrant import line (per plan constraint 7)"

metrics:
  duration: "~10 minutes"
  completed: "2026-04-27T13:10:00Z"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 213 Plan 01: Introduce Catalog Authorization — Summary

New file `backend/app/modules/catalog/authorization.py` created as verbatim copy of `auth/visibility.py` with docstring updated to note Phase 213 relocation and `DatasetGrant` import promoted from function scope (line 148 of source) to module level.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 01-01 | Create catalog/authorization.py | 0dd3269c | backend/app/modules/catalog/authorization.py |

## What Was Built

### New file: `backend/app/modules/catalog/authorization.py` (182 lines)

Path: `backend/app/modules/catalog/authorization.py`
Line count: 182 (source `auth/visibility.py` was 183 lines; net change = +1 docstring line, -2 deferred import lines, +1 module-level import line = -0 net, rounding to 182 due to trailing newline difference)

#### Diff 1 — Module docstring update

Added one line before the closing `"""`:

```
Before (line 9 of source):
SEC-04: All dataset access paths use these shared functions.
"""

After (lines 9-10 of new file):
SEC-04: All dataset access paths use these shared functions.
Relocated from app.modules.auth.visibility (Phase 213).
"""
```

#### Diff 2 — DatasetGrant import promotion

Added at module level (after `from sqlalchemy.ext.asyncio import AsyncSession`):
```python
from app.modules.catalog.datasets.domain.models import DatasetGrant
```

Removed from inside `check_dataset_access()` function body (was source line 148):
```python
    from app.modules.catalog.datasets.domain.models import DatasetGrant
    
    if user_roles is None:   # blank line between import and first statement also removed
```

## Verification Results

All acceptance criteria passed:

- `test -f backend/app/modules/catalog/authorization.py` — PASS (file exists)
- Smoke import: `from app.modules.catalog.authorization import DatasetVisibility, apply_visibility_filter, get_user_roles, check_dataset_access, check_dataset_access_or_anonymous` — PASS (`public_surface_ok` printed)
- Enum values: `DatasetVisibility.PUBLIC.value == 'public'`, `.RESTRICTED.value == 'restricted'`, `.PRIVATE.value == 'private'` — all PASS
- `grep -c "^from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$"` returns `1` — PASS (module-level import present)
- `grep -c "^    from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$"` returns `0` — PASS (no deferred copy in function body)
- `grep -q "Relocated from app.modules.auth.visibility (Phase 213)"` — PASS
- `grep -q "SEC-04"` — PASS
- `ruff check app/modules/catalog/authorization.py` — PASS (no F401 unused imports, no F821)
- `ruff format --check app/modules/catalog/authorization.py` — PASS (no formatting drift)
- `git diff backend/app/modules/auth/visibility.py` — zero output (old file byte-unchanged) — PASS
- `git diff backend/app/modules/catalog/__init__.py` — zero output (no re-exports added) — PASS

## Deviations from Plan

None — plan executed exactly as written. Two surgical diffs only: docstring update and DatasetGrant import promotion.

## Known Stubs

None. The new file is a verbatim copy of fully-implemented RBAC logic. No placeholders or hardcoded empty values.

## Threat Flags

No new threat surface introduced. The new module is not yet wired to any caller (Plan 02 wires it). The SEC-04 RBAC invariant is preserved verbatim. No new network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- `test -f backend/app/modules/catalog/authorization.py` → FOUND
- `git log --oneline | grep 0dd3269c` → `0dd3269c feat(213-01): create catalog/authorization.py (verbatim copy + DatasetGrant promotion)`

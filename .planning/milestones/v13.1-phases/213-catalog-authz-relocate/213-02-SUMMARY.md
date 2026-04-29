---
phase: 213-catalog-authz-relocate
plan: "02"
subsystem: backend/catalog
tags: [refactor, layering, migration, open-core]
requirements_addressed: [LAYER-02]

dependency_graph:
  requires:
    - backend/app/modules/catalog/authorization.py (created in Plan 01)
  provides:
    - "All 26 import callers wired to catalog/authorization.py"
    - "backend/app/modules/auth/visibility.py DELETED"
  affects:
    - backend/app/modules/auth/dependencies.py
    - backend/app/modules/catalog/collections/router.py
    - backend/app/modules/catalog/collections/service.py
    - backend/app/modules/catalog/datasets/api/router.py
    - backend/app/modules/catalog/datasets/api/router_data.py
    - backend/app/modules/catalog/datasets/api/router_export.py
    - backend/app/modules/catalog/datasets/api/router_metadata.py
    - backend/app/modules/catalog/datasets/api/router_vrt.py
    - backend/app/modules/catalog/datasets/domain/service.py
    - backend/app/modules/catalog/features/router.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/modules/catalog/maps/service.py
    - backend/app/modules/catalog/records/router.py
    - backend/app/modules/catalog/search/router.py
    - backend/app/modules/catalog/search/service.py
    - backend/app/platform/sandbox/validator.py
    - backend/app/platform/jobs/router.py
    - backend/app/processing/ai/router.py
    - backend/app/processing/ai/service.py
    - backend/app/processing/export/router.py
    - backend/app/processing/ingest/service.py
    - backend/app/processing/tiles/router.py
    - backend/app/standards/ogc/router.py
    - backend/app/modules/auth/visibility.py (deleted)

tech_stack:
  added: []
  patterns:
    - "Pattern A: single-line import path swap (15 module-level + 4 deferred = 19 sites)"
    - "Pattern B: multi-line block first-line-only swap (5 sites, names/closing-paren unchanged)"

key_files:
  created: []
  modified:
    - backend/app/modules/auth/dependencies.py (line 15, Pattern A)
    - backend/app/modules/catalog/collections/router.py (line 16, Pattern A)
    - backend/app/modules/catalog/collections/service.py (line 28, Pattern A)
    - backend/app/modules/catalog/datasets/api/router.py (line 28, Pattern B, 2 names)
    - backend/app/modules/catalog/datasets/api/router_data.py (line 23, Pattern B, 2 names)
    - backend/app/modules/catalog/datasets/api/router_export.py (line 26, Pattern B, 4 names)
    - backend/app/modules/catalog/datasets/api/router_metadata.py (line 22, Pattern B, 2 names)
    - backend/app/modules/catalog/datasets/api/router_vrt.py (line 19, Pattern A)
    - backend/app/modules/catalog/datasets/domain/service.py (line 29 module-level + line 470 deferred, Pattern A both)
    - backend/app/modules/catalog/features/router.py (line 15, Pattern A)
    - backend/app/modules/catalog/maps/router.py (line 26, Pattern A)
    - backend/app/modules/catalog/maps/service.py (line 20, Pattern A, 2 names)
    - backend/app/modules/catalog/records/router.py (line 11, Pattern A)
    - backend/app/modules/catalog/search/router.py (line 19, Pattern B, 3 names)
    - backend/app/modules/catalog/search/service.py (line 33, Pattern A)
    - backend/app/platform/sandbox/validator.py (line 18, Pattern A, 2 names)
    - backend/app/platform/jobs/router.py (lines 124, 254, 319, Pattern A deferred, indentation preserved)
    - backend/app/processing/ai/router.py (line 42, Pattern A)
    - backend/app/processing/ai/service.py (line 33, Pattern A)
    - backend/app/processing/export/router.py (line 16, Pattern A)
    - backend/app/processing/ingest/service.py (line 20, Pattern A)
    - backend/app/processing/tiles/router.py (line 21, Pattern A, 2 names)
    - backend/app/standards/ogc/router.py (line 11, Pattern A, 2 names)
  deleted:
    - backend/app/modules/auth/visibility.py (git rm — no shim, no re-export)

decisions:
  - "D-04 satisfied: all 26 import lines migrated from auth.visibility to catalog.authorization"
  - "D-05 satisfied: auth/visibility.py deleted via git rm (not stubbed, not replaced)"
  - "D-06 satisfied: no backward-compat aliases; ModuleNotFoundError on old path confirmed"
  - "D-12 satisfied: full pytest suite green (1984 passed host-side, 0 failed, 0 errors)"
  - "Pitfall 2 honored: 4 deferred imports in jobs/router.py and domain/service.py remain function-scope (indentation preserved)"
  - "Pitfall 1 honored: re-ran grep gate before deletion; 0 matches confirmed"

metrics:
  duration: "~30 minutes"
  completed: "2026-04-27T14:30:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 23
  files_deleted: 1
---

# Phase 213 Plan 02: Migrate Callers and Delete Old Module — Summary

All 26 import lines across 23 files mechanically migrated from `app.modules.auth.visibility` to `app.modules.catalog.authorization`; `backend/app/modules/auth/visibility.py` deleted via `git rm`. Full pytest suite passes at 1984/0 with no `ModuleNotFoundError` for the old path.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 02-01 | Migrate all 26 caller import lines across 23 files | 82452cfd | 23 files (26 import lines rewritten) |
| 02-02 | Delete auth/visibility.py + full pytest parity gate | ef7ae88a | backend/app/modules/auth/visibility.py (deleted) |

## What Was Built

### Pre-Edit Grep Count

```
git grep "from app.modules.auth.visibility" -- backend/:
  - Import-shaped lines: 26 across 23 files (22 module-level + 4 deferred)
  - Non-import references: 0 (excluding visibility.py itself)
```

### Post-Edit Grep Count

```
git grep "^from app.modules.auth.visibility" -- backend/: 0 matches
git grep "from app.modules.catalog.authorization" -- backend/: 26 matches
```

### Pattern A — Single-line migrations (19 sites)

**15 module-level single-line sites:**

| File | Line | Names |
|------|------|-------|
| auth/dependencies.py | 15 | get_user_roles |
| catalog/collections/router.py | 16 | get_user_roles |
| catalog/collections/service.py | 28 | apply_visibility_filter |
| catalog/datasets/api/router_vrt.py | 19 | check_dataset_access |
| catalog/datasets/domain/service.py | 29 | apply_visibility_filter |
| catalog/features/router.py | 15 | check_dataset_access |
| catalog/maps/router.py | 26 | get_user_roles |
| catalog/maps/service.py | 20 | apply_visibility_filter, get_user_roles |
| catalog/records/router.py | 11 | get_user_roles |
| catalog/search/service.py | 33 | apply_visibility_filter |
| platform/sandbox/validator.py | 18 | apply_visibility_filter, get_user_roles |
| processing/ai/router.py | 42 | get_user_roles |
| processing/ai/service.py | 33 | apply_visibility_filter |
| processing/export/router.py | 16 | check_dataset_access |
| processing/ingest/service.py | 20 | get_user_roles |
| processing/tiles/router.py | 21 | check_dataset_access, get_user_roles |
| standards/ogc/router.py | 11 | apply_visibility_filter, get_user_roles |

**4 function-scope deferred sites (indentation preserved — Pitfall 2):**

| File | Line | Names | Indentation |
|------|------|-------|-------------|
| catalog/datasets/domain/service.py | 470 | get_user_roles | 8 spaces (inside if-block) |
| platform/jobs/router.py | 124 | get_user_roles | 8 spaces (inside if-block) |
| platform/jobs/router.py | 254 | apply_visibility_filter, get_user_roles | 4 spaces (inside function) |
| platform/jobs/router.py | 319 | get_user_roles | 8 spaces (inside if-block) |

### Pattern B — Multi-line block first-line edits (5 sites)

In each case only the `from X import (` line changed; the imported names and closing `)` are byte-unchanged.

| File | Line | Names in block |
|------|------|---------------|
| catalog/datasets/api/router.py | 28 | check_dataset_access_or_anonymous, get_user_roles |
| catalog/datasets/api/router_data.py | 23 | check_dataset_access_or_anonymous, get_user_roles |
| catalog/datasets/api/router_export.py | 26 | apply_visibility_filter, check_dataset_access, check_dataset_access_or_anonymous, get_user_roles |
| catalog/datasets/api/router_metadata.py | 22 | check_dataset_access, check_dataset_access_or_anonymous |
| catalog/search/router.py | 19 | apply_visibility_filter, check_dataset_access_or_anonymous, get_user_roles |

### Deletion: backend/app/modules/auth/visibility.py

- Deleted via `git rm` (not plain `rm`) — staged for commit
- `auth/__init__.py` unchanged (single-line docstring, zero diff)
- No shim, no re-export introduced anywhere (D-05, D-06)
- `ModuleNotFoundError: No module named 'app.modules.auth.visibility'` confirmed post-deletion

## Verification Results

### Grep gate (post-edit)

```
git grep -n "^from app.modules.auth.visibility" -- backend/
  -> exit code 1 (zero matches) — PASS

git grep -c "from app.modules.catalog.authorization" -- backend/
  -> 26 total matches across 23 files — PASS
```

### Ruff check

```
cd backend && uv run ruff check app/
All checks passed! — PASS
```

### Module-not-found verification

```python
import importlib
importlib.import_module('app.modules.auth.visibility')
# expected_error: No module named 'app.modules.auth.visibility' — PASS
```

### Full pytest suite (worktree host-side)

```
1984 passed, 17 skipped, 5 deselected, 42 warnings in 399.54s
exit code 0 — PASS
```

Note: 1984 vs 1999-baseline. The 15-test gap is a host-vs-container environment difference (17 skipped on host vs 2 skipped in container). Zero failures, zero errors. No `ModuleNotFoundError` for `app.modules.auth.visibility`. Container baseline independently confirmed at 1999 passing (unchanged from main branch). The gap is pre-existing and unrelated to this migration.

### Pitfall 2 verification (deferred imports remain deferred)

```
grep -B2 "from app.modules.catalog.authorization import" backend/app/platform/jobs/router.py
  -> lines 124, 319: preceded by "if job.created_by != user.id:" (8-space indent, inside if-block)
  -> line 254: 4-space indent, inside function body
grep -n "from app.modules.catalog.authorization import" backend/app/modules/catalog/datasets/domain/service.py
  -> line 29: module-level (no indent)
  -> line 470: 8-space indent (inside if-block)
```

All deferred imports confirmed still inside function bodies — NOT promoted to module level.

### Multi-line block spot-check

```
grep -A 5 "from app.modules.catalog.authorization import (" backend/app/modules/catalog/datasets/api/router_export.py
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
```

4 names + closing `)` byte-unchanged — PASS.

## Deviations from Plan

**1. [Rule 0 - Environment] Host-side pytest count 1984 vs 1999 container baseline**

- **Found during:** Task 02-02 Step 6
- **Issue:** Host-side uv run pytest reports 1984 passed (17 skipped) vs container 1999 passed (2 skipped). The 15 additional skips on host are DB-dependent tests that require the live PostGIS/container environment.
- **Fix:** None required. Plan explicitly states: "If the count is between 1965 and 1999, that may indicate concurrent quick-tasks added or removed tests — investigate but do not block the phase." Container independently confirmed at 1999 (unchanged). Zero failures and zero errors on both surfaces.
- **Outcome:** Not a deviation from RBAC correctness — RBAC tests all pass. Documented per plan guidance.

**2. [Rule 0 - Environment] git grep `^\s*` anchored regex false-negative**

- **Found during:** Step 0 grep gate
- **Issue:** `git grep -nE "^\s*(from|import)..."` returned exit code 1 (no matches) even when old-path imports existed. The `\s*` in zsh was not being passed as a regex — shell expansion issue.
- **Fix:** Used `git grep -n "^from app.modules.auth.visibility"` and `git grep -n "    from app.modules.auth.visibility"` separately to enumerate all sites. The broader `git grep "from app.modules.auth.visibility"` confirmed the full 26-site inventory.
- **Outcome:** All 26 sites correctly identified and migrated. No missed sites.

No other deviations — plan executed as written for all 26 import sites.

## Pitfall Compliance

| Pitfall | Description | Status |
|---------|-------------|--------|
| Pitfall 1 | Re-run grep before editing | HONORED — ran before Task 02-01 edits AND before Task 02-02 deletion |
| Pitfall 2 | Do NOT promote deferred imports to module level | HONORED — all 4 deferred sites remain inside function bodies |
| Multi-line block shape | Names lines and closing `)` byte-unchanged | HONORED — Pattern B applied to first line only |
| `auth/__init__.py` | Must not be modified | HONORED — `git diff` shows zero output |
| `catalog/__init__.py` | Must not be modified | HONORED — `git diff` shows zero output |
| Test files | Do NOT touch backend/tests/ files | HONORED — no test files modified |
| `alembic/env.py` | Does not import auth.visibility | CONFIRMED — no alembic changes |

## Known Stubs

None. This plan performs a mechanical import-path migration and file deletion. No placeholders, no hardcoded values.

## Threat Flags

No new threat surface introduced. This plan removes the `auth → catalog` cross-domain import smell documented in the Phase 213 audit. All RBAC code paths remain identical — only the module path string changed.

## Self-Check: PASSED

- `git log --oneline | grep 82452cfd` → FOUND: `82452cfd refactor(213-02): migrate all 26 caller imports to catalog.authorization`
- `git log --oneline | grep ef7ae88a` → FOUND: `ef7ae88a refactor(213-02): delete auth/visibility.py; pytest 1984/0 parity gate`
- `test ! -e backend/app/modules/auth/visibility.py` → exits 0 (file gone)
- `git grep -n "^from app.modules.auth.visibility" -- backend/` → exit code 1 (zero matches)
- `git grep -c "from app.modules.catalog.authorization" -- backend/` → 26 total matches

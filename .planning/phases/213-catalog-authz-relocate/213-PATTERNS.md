# Phase 213: catalog-authz-relocate - Pattern Map

**Mapped:** 2026-04-27
**Files analyzed:** 26 (1 new, 1 modified, 22 caller-migration, 1 delete + 1 no-op __init__.py)
**Analogs found:** 4 / 4 primary target files

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/modules/catalog/authorization.py` | service (auth utility) | request-response | `backend/app/modules/auth/visibility.py` | exact (verbatim source) |
| `backend/tests/test_layering.py` | test (architecture guard) | batch (git grep subprocess) | `backend/tests/test_layering.py` lines 79–106 (Phase 212 second test) | exact |
| 22 module-level caller files | various (router, service, middleware) | varies | `backend/app/modules/auth/dependencies.py:15` (single-line) / `backend/app/modules/catalog/datasets/api/router.py:28–31` (multi-line block) | role-match |
| 4 deferred-import caller sites | router / service | request-response | `backend/app/platform/jobs/router.py:124` / `backend/app/modules/catalog/datasets/domain/service.py:470` | exact |
| `backend/app/modules/auth/visibility.py` | — | — | — | DELETE (no analog needed) |

---

## Pattern Assignments

### `backend/app/modules/catalog/authorization.py` (service, request-response)

**Analog:** `backend/app/modules/auth/visibility.py` — this IS the source; the new file is a verbatim copy with two import-level changes only.

**Complete source file** (`backend/app/modules/auth/visibility.py` lines 1–183):

The new file is an exact copy of the source with these two diffs applied:

**Diff 1 — module docstring update** (lines 1–10 of source → lines 1–12 of new file):
```python
"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
Relocated from app.modules.auth.visibility (Phase 213).
"""
```

**Diff 2 — promote DatasetGrant to module-level import** (lines 20–21 of new file, replacing line 148 deferred import):

Before (source `visibility.py` lines 20–21, then line 148 inside `check_dataset_access`):
```python
# line 20 — existing module-level imports end here
from app.modules.auth.models import Role, User, UserRole
# (no DatasetGrant import at module level)

# ... line 148 inside check_dataset_access():
    from app.modules.catalog.datasets.domain.models import DatasetGrant
```

After (new `catalog/authorization.py` lines 20–22, line 148 removed from function body):
```python
from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant  # promoted from deferred (Phase 213)
```

**Complete imports block** (new file lines 12–22):
```python
import enum
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant  # promoted from deferred (Phase 213)
```

**DatasetGrant promotion diff inside `check_dataset_access()`** (source lines 148–150 → removed in new file):
```diff
 async def check_dataset_access(...) -> set[str]:
-    from app.modules.catalog.datasets.domain.models import DatasetGrant
-
-    if user_roles is None:
+    if user_roles is None:
```

Everything else in the file body (lines 23–183 of source, adjusted for the removed 2-line function-scope import) is copied verbatim. No other changes.

---

### `backend/tests/test_layering.py` (test, architecture guard)

**Analog:** `backend/tests/test_layering.py` lines 79–106 — the existing `test_app_settings_imports_only_via_core_db_models` test from Phase 212-03.

**Module docstring update** (lines 1–16 of current file):

Current line 8:
```python
Scope (Phase 212): NARROW — only `from app.modules.settings`. Phases 213
(catalog-authz-relocate) and 214 (identity-protocol-extract) close additional
core->modules edges; Phase 218 will broaden this guard to `from app.modules.<*>`
once those phases land.
```

Replace with:
```python
Scope (Phases 212–213): `from app.modules.settings` (Phase 212 LAYER-01) and
`from app.modules.auth.visibility` (Phase 213 LAYER-02). Phase 214
(identity-protocol-extract) closes additional edges; Phase 218 will broaden this
guard to `from app.modules.<*>` once those phases land.
```

**New test 1 — import-shaped guard** (add after line 106):
```python
@pytest.mark.architecture
def test_no_imports_from_auth_visibility() -> None:
    """`auth.visibility` import path must not appear anywhere under `backend/`.

    Closes Phase 213 LAYER-02: the deleted `app.modules.auth.visibility` path
    becomes a hard ModuleNotFoundError after this phase — any surviving import
    is a migration miss. Maps directly to ROADMAP SC#4.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.auth\.visibility",
        "backend/",
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: deleted import path `app.modules.auth.visibility` is still "
            "referenced. Migrate to `app.modules.catalog.authorization`. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**New test 2 — broader module-reference guard** (add after test 1):
```python
@pytest.mark.architecture
def test_no_auth_visibility_module_referenced() -> None:
    """Broader guard: `auth.visibility` string must not appear as a module reference.

    Catches re-exports in `__init__.py` files or indirect references that the
    import-shaped guard above would miss. Excludes this test file itself so the
    regex literal in the guard does not produce a self-positive (Phase 212-03
    bug, commit b0bd0c2c).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"app\.modules\.auth\.visibility|auth\.visibility",
            "--",
            "backend/",
            ":!backend/tests/test_layering.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: `auth.visibility` is referenced outside test_layering.py. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**Key distinction from test 1:** Test 1 uses the `_git_grep` helper with an import-line anchor (`^\s*(from|import)`) and searches all of `backend/`. Test 2 calls `subprocess.run` directly (not `_git_grep`) because it needs to pass a pathspec exclusion (`:!backend/tests/test_layering.py`) which `_git_grep`'s fixed signature does not support. The exclusion prevents the regex literal inside the test file itself from matching — the exact self-positive bug that hit Phase 212-03.

**Open question for planner (from RESEARCH.md):** Verify that `git grep ":!<path>"` pathspec negation works with the project's git version by running the broader grep manually during wave 0. If `:!backend/tests/test_layering.py` is not supported, fall back to using the import-anchor (`^\s*(from|import)\s+app\.modules\.auth\.visibility`) for both tests — that pattern is proven by Phase 212-03 commit `b0bd0c2c`.

---

### Caller migration — single-line module-level import pattern

**Analog:** `backend/app/modules/auth/dependencies.py` line 15 (current state):
```python
from app.modules.auth.visibility import get_user_roles
```

**After migration:**
```python
from app.modules.catalog.authorization import get_user_roles
```

Only the module path changes. The imported name(s) are untouched. Apply to all 15 single-line module-level import sites listed in RESEARCH.md §Caller Inventory.

---

### Caller migration — multi-line (parenthesized) import block pattern

**Analog:** `backend/app/modules/catalog/datasets/api/router.py` lines 28–31 (current state):
```python
from app.modules.auth.visibility import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
```

**After migration:**
```python
from app.modules.catalog.authorization import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
```

Only the first line of the block (the module path) changes. The name lines below are untouched. Apply to all 5 multi-line import sites:
- `catalog/datasets/api/router.py:28`
- `catalog/datasets/api/router_data.py:23`
- `catalog/datasets/api/router_export.py:26` (4 names — largest block)
- `catalog/datasets/api/router_metadata.py:22`
- `catalog/search/router.py:19`

**Largest block for reference** (`router_export.py:26–31` current state):
```python
from app.modules.auth.visibility import (
    apply_visibility_filter,
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
```

---

### Caller migration — deferred (function-scope) import pattern

**Rule:** Rewrite the module path only. Keep the import inside the function body. Do NOT promote to module level.

**Analog 1:** `backend/app/modules/catalog/datasets/domain/service.py` line 470 (current state):
```python
        from app.modules.auth.visibility import get_user_roles
```

**After migration:**
```python
        from app.modules.catalog.authorization import get_user_roles
```

**Analog 2:** `backend/app/platform/jobs/router.py` line 124 (current state):
```python
        from app.modules.auth.visibility import get_user_roles
```

**After migration:**
```python
        from app.modules.catalog.authorization import get_user_roles
```

**Two-name deferred line** (`jobs/router.py:254` current state):
```python
        from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
```

**After migration:**
```python
        from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
```

Apply the same path-only rewrite to `jobs/router.py:319` (single name, same structure as line 124).

---

## Shared Patterns

### Architecture guard test structure
**Source:** `backend/tests/test_layering.py` lines 29–46 (`_has_git_metadata`, `_git_grep` helpers), lines 49–106 (two existing tests)
**Apply to:** Both new tests in `test_layering.py`

```python
# Skip guard (lines 29–36):
def _has_git_metadata() -> bool:
    return (REPO_ROOT / ".git").exists()

# Reusable subprocess helper (lines 39–46):
def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

# Standard test body shape (lines 57–76 as template):
if not _has_git_metadata():
    pytest.skip("git metadata unavailable; arch test only runs on full clones")

result = _git_grep(r"<pattern>", "<path>/")

if result.returncode == 0:
    pytest.fail("... Offending lines:\n" + result.stdout)
if result.returncode != 1:
    pytest.fail(f"git grep failed unexpectedly: rc={result.returncode}\nstderr: {result.stderr}")
```

### Self-positive avoidance (import-anchor vs. pathspec exclusion)
**Source:** Phase 212-03 commit `b0bd0c2c` fix; documented in RESEARCH.md Pitfall 3
**Apply to:** `test_no_auth_visibility_module_referenced` (test 2 of the new pair)

- **Narrow test (test 1):** Use import-line anchor `^\s*(from|import)` — the anchor itself prevents the regex literal from matching a docstring or comment in `test_layering.py`. Pattern: `r"^\s*(from|import)\s+app\.modules\.auth\.visibility"` via `_git_grep`.
- **Broad test (test 2):** The anchor cannot be used (it would miss `__init__.py` re-export shims which are not import-shaped lines in some editors). Use `:!backend/tests/test_layering.py` pathspec exclusion instead. Call `subprocess.run` directly, not `_git_grep`, to pass the extra pathspec argument.

### `@pytest.mark.architecture` marker
**Source:** `backend/pyproject.toml` line 74 (registered by Phase 212-03; no change needed)
**Apply to:** Both new architecture guard tests

---

## No Analog Found

None. Every new or modified file has a direct analog in the codebase.

| File | Note |
|------|------|
| `backend/app/modules/catalog/authorization.py` | Analog is the verbatim source `auth/visibility.py` — it is not "no analog," it is the closest possible match |

---

## Metadata

**Analog search scope:** `backend/app/modules/auth/`, `backend/tests/`, all 23 caller files
**Files read directly:** `visibility.py` (183 lines), `test_layering.py` (107 lines), `router.py:25–34`, `router_export.py:23–31`, `domain/service.py:467–472`, `jobs/router.py:121–126`, `dependencies.py:13–17`
**Pattern extraction date:** 2026-04-27

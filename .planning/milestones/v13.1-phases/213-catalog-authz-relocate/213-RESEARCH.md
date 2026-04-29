# Phase 213: catalog-authz-relocate - Research

**Researched:** 2026-04-27
**Domain:** Backend Python refactor — module relocation, import migration, layering enforcement
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Target file is `backend/app/modules/catalog/authorization.py` — flat single file, not `catalog/_authz/visibility.py`.
- **D-02:** New module keeps the exact public surface of today's `auth/visibility.py`: `DatasetVisibility`, `apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous`. No renames, no signature changes.
- **D-03:** Only two import changes inside the relocated file: `Role/User/UserRole` still imported from `app.modules.auth.models`; the deferred `DatasetGrant` import at line 148 is promoted to module level. No other content changes.
- **D-04:** All 26 import lines across 23 files migrated in one shot. No shim. Callers listed in CONTEXT.md D-04.
- **D-05:** `backend/app/modules/auth/visibility.py` deleted. Not stubbed. `auth/__init__.py` (docstring-only) untouched.
- **D-06:** No backward-compat aliases. `app.modules.auth.visibility` becomes a hard `ModuleNotFoundError` after this phase.
- **D-07:** Extend `backend/tests/test_layering.py` with two new `@pytest.mark.architecture` tests.
- **D-08:** Both new tests use `_has_git_metadata()` skip guard and `_git_grep` helper from the existing file.
- **D-09:** Update `test_layering.py` module docstring to reflect broadened scope.
- **D-10:** No Alembic migration. Proof: `cd backend && uv run alembic check` reports no diff.
- **D-11:** 1965-test backend baseline is the acceptance gate. (Actual live count is 1999 as of Phase 212 gate — the baseline floor is ≥1999.)
- **D-12:** No new visibility tests added. Existing corpus proves RBAC parity.
- **D-13:** No frontend involvement. No HTTP contract change.
- **D-14:** Independent of Phase 212 and 214.

### Claude's Discretion

- Commit decomposition (likely 3 atomic + 1 verification gate, mirroring Phase 212).
- Module docstring wording in `catalog/authorization.py`.
- Whether to refactor any trivial dead-imports during the move (default: no).
- Test marker reuse (`@pytest.mark.architecture` is already registered — default is reuse).

### Deferred Ideas (OUT OF SCOPE)

- `AuthorizationProtocol` / `VisibilityExtension` seam.
- RBAC test coverage expansion.
- Promoting the 4 remaining function-scope deferred imports in callers to module level.
- `catalog/__init__.py` re-exports.
- Splitting `catalog/authorization.py` into smaller modules.
- Phase 214 `IdentityProtocol` migration of the relocated module.

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LAYER-02 | `auth/visibility.py` is removed; all 23 inbound callers (15 visibility imports + 8 deferred-import callers) migrated to `catalog/authorization.py` with no behavior change to dataset-visibility semantics. | All 26 import sites confirmed by live grep (25 module-level + 4 deferred; no test-file callers found). No callers import `DatasetVisibility` — enum is internal-use only. `DatasetGrant` promotion validated against its class definition at `domain/models.py:411`. Architecture guard pattern verified in `test_layering.py`. |

</phase_requirements>

---

## Summary

Phase 213 is a mechanical Python-only relocation. `backend/app/modules/auth/visibility.py` (183 lines, 4 functions + 1 enum) moves to `backend/app/modules/catalog/authorization.py`. Every import site in the codebase that references `app.modules.auth.visibility` is rewritten to `app.modules.catalog.authorization`. The source file is deleted. No behavior changes.

The phase mirrors Phase 212 (core-settings-decouple) exactly in pattern: one-shot migration with no shim, `git grep`-based architecture guard added to `test_layering.py`, `alembic check` as the no-migration proof, full pytest as the acceptance gate. Phase 212's shipped machinery (the `_has_git_metadata()` skip guard, the `_git_grep` helper, the `@pytest.mark.architecture` marker registered in `pyproject.toml`) is reused verbatim.

The only non-trivial content change inside the relocated file is the `DatasetGrant` import promotion: line 148's function-scope deferred `from app.modules.catalog.datasets.domain.models import DatasetGrant` becomes a module-level import. The deferral existed solely to break the `auth → catalog` import cycle; that cycle disappears when the file moves inside `catalog/`.

**Primary recommendation:** Execute in 4 atomic commits: (1) create `catalog/authorization.py` with verbatim body + promoted import; (2) migrate all 26 caller lines + delete `auth/visibility.py`; (3) extend `test_layering.py` with two new architecture guard tests + update its docstring; (4) verification gate (alembic check + full pytest + ruff + SC verification).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dataset visibility / RBAC enforcement | Backend / `app.modules.catalog` | — | Visibility logic is catalog-domain knowledge (operates on `Record.visibility`, `DatasetGrant`, `Record.record_status`). Belonging in `auth/` was an architectural smell. |
| Identity types (`User`, `Role`, `UserRole`) | Backend / `app.modules.auth` | — | Auth module owns the identity ORM models. The relocated module continues to import from `auth.models`. Phase 214 will abstract `User` to `IdentityProtocol`. |
| Layering-rule enforcement | Backend / `tests/test_layering.py` | CI workflow | Pytest-runnable static check; no runtime side effects. |
| No-migration proof | `alembic check` CLI | — | Pure Python relocation; no table or column change. |

## Standard Stack

### Core (no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | ≥3.13 | Language | `pyproject.toml requires-python = ">=3.13"` [VERIFIED: pyproject.toml:5] |
| FastAPI | ≥0.115.0 | HTTP framework | Already in use; `HTTPException`, `status` imported by `visibility.py` [VERIFIED: visibility.py:16] |
| SQLAlchemy | ≥2.0.25 | ORM / async queries | `Select`, `and_`, `or_`, `select` imported by `visibility.py` [VERIFIED: visibility.py:17] |
| pytest | ≥9.0.3 | Test runner | Existing 1965/1999-test suite [VERIFIED: pyproject.toml:49] |
| ruff | dev dep | Lint + format | Canonical static check; no mypy/pyright [VERIFIED: pyproject.toml:52, 212-04-SUMMARY.md] |
| alembic | ≥1.13.0 | Migration / drift check | `alembic check` subcommand confirmed available [VERIFIED: 212-04-SUMMARY.md Gate 1] |

### No new packages required.

This is a pure relocation refactor.

## Architecture Patterns

### System Architecture Diagram

```
BEFORE
─────────────────────────────────────────────────────────────────────
  app.modules.auth.visibility
    ├─ imports: Role, User, UserRole  ← app.modules.auth.models (OK)
    ├─ deferred import at line 148:   ← app.modules.catalog.datasets.domain.models.DatasetGrant
    │                                    (CYCLE: auth → catalog)
    └─ is imported by 22 module-level sites + 4 deferred call sites
         across catalog/, processing/, platform/, standards/, auth/

AFTER
─────────────────────────────────────────────────────────────────────
  app.modules.catalog.authorization   (NEW — verbatim body)
    ├─ imports: Role, User, UserRole  ← app.modules.auth.models (unchanged direction)
    ├─ module-level import:           ← app.modules.catalog.datasets.domain.models.DatasetGrant
    │                                    (NO CYCLE: catalog importing catalog sibling)
    └─ all 26 caller import lines rewritten to point here

  app.modules.auth.visibility          ← DELETED

  tests/test_layering.py               ← extended with 2 new @pytest.mark.architecture tests:
    test_no_imports_from_auth_visibility        (import-shaped grep on backend/)
    test_no_auth_visibility_module_referenced   (broader grep excluding self-match)
```

### Recommended Project Structure

```
backend/
├── app/
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── __init__.py          # unchanged (docstring only)
│   │   │   ├── dependencies.py      # line 15: import path updated
│   │   │   ├── models.py            # unchanged (User, Role, UserRole stay here)
│   │   │   └── visibility.py        # DELETED (D-05)
│   │   └── catalog/
│   │       ├── __init__.py          # unchanged (docstring only)
│   │       ├── authorization.py     # NEW — verbatim body + promoted DatasetGrant import
│   │       ├── collections/         # router.py:16, service.py:28 updated
│   │       ├── datasets/            # 5 files updated (api/ x4, domain/service.py x2 lines)
│   │       ├── features/            # router.py:15 updated
│   │       ├── maps/                # router.py:26, service.py:20 updated
│   │       ├── records/             # router.py:11 updated
│   │       └── search/              # router.py:19, service.py:33 updated
│   ├── platform/
│   │   ├── jobs/                    # router.py: 3 deferred sites updated
│   │   └── sandbox/                 # validator.py:18 updated
│   ├── processing/
│   │   ├── ai/                      # router.py:42, service.py:33 updated
│   │   ├── export/                  # router.py:16 updated
│   │   ├── ingest/                  # service.py:20 updated
│   │   └── tiles/                   # router.py:21 updated
│   └── standards/
│       └── ogc/                     # router.py:11 updated
└── tests/
    └── test_layering.py             # extended with 2 new arch tests; docstring updated
```

### Pattern 1: Verbatim relocation with import promotion

**What:** Copy the source file body unchanged, update the one deferred import to module level, rewrite all caller import paths.
**When to use:** When a file belongs in a different package and the cycle reason disappears with the move.
**Example (the new file header):**
```python
# backend/app/modules/catalog/authorization.py
"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
Relocated from app.modules.auth.visibility (Phase 213).
"""

import enum
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant  # promoted from deferred
```
[VERIFIED: visibility.py lines 1–20 + line 148]

**The single diff inside `check_dataset_access()`:**
```diff
-    from app.modules.catalog.datasets.domain.models import DatasetGrant
-
-    if user_roles is None:
+    if user_roles is None:
```
(The `from ... import DatasetGrant` line at line 148 is removed from the function body; `DatasetGrant` is now a module-level import.) [VERIFIED: visibility.py:148–150]

### Pattern 2: Single-import-line migration (module-level, single-import)

For the 15 single-line module-level import sites, the diff is always:
```diff
-from app.modules.auth.visibility import <names>
+from app.modules.catalog.authorization import <names>
```
Only the module path changes; the imported names are untouched. [VERIFIED: grep output 2026-04-27]

### Pattern 3: Multi-line import block migration

Five sites use parenthesized multi-import blocks. The rewrite touches only the first line of the block (the module path); the name lines below are untouched.

**router.py:28 (example):**
```python
# BEFORE
from app.modules.auth.visibility import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)

# AFTER
from app.modules.catalog.authorization import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
```
[VERIFIED: router.py:28–31, router_data.py:23–26, router_export.py:26–31, router_metadata.py:22–25, search/router.py:19–23]

**router_export.py:26 imports 4 names (largest block):**
```python
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    check_dataset_access,
    check_dataset_access_or_anonymous,
    get_user_roles,
)
```
[VERIFIED: router_export.py:26–31]

### Pattern 4: Deferred import migration (keep deferred, rewrite path)

The 4 function-scope deferred imports in callers are rewritten in place. Example from `platform/jobs/router.py:124`:
```python
# BEFORE
from app.modules.auth.visibility import get_user_roles

# AFTER
from app.modules.catalog.authorization import get_user_roles
```
The deferral (inside an `if` body or a function) is preserved unchanged. [VERIFIED: jobs/router.py:124, 254, 319; domain/service.py:470]

Note: `jobs/router.py:254` is a two-name deferred block:
```python
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
```
[VERIFIED: jobs/router.py:254]

### Pattern 5: Architecture guard tests (extending test_layering.py)

The existing `test_layering.py` (Phase 212) already provides `_has_git_metadata()` and `_git_grep()` helpers. The two new tests follow the same structure. [VERIFIED: test_layering.py lines 29–46, 49–106]

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


@pytest.mark.architecture
def test_no_auth_visibility_module_referenced() -> None:
    """Broader guard: `auth.visibility` string must not appear as a module reference.

    Catches re-exports in `__init__.py` files or indirect references that the
    import-shaped guard above would miss. Excludes this test file itself so the
    regex literal in the guard does not produce a self-positive.
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

**Important:** The broader test uses `":!backend/tests/test_layering.py"` as a pathspec exclude so the regex literals in the guard file itself do not produce a self-positive. This is the fix pattern from Phase 212-03 (`commit b0bd0c2c`), where the absence of an `^\s*(from|import)` anchor caused exactly this self-match failure. [VERIFIED: 212-04-SUMMARY.md §"One in-flight defect caught and fixed"]

**The pathspec `:!<file>` syntax** is supported by `git grep` when using full pathspec syntax. Alternative: use `--` to restrict to `backend/` and rely on the import-anchor in the first test being sufficient for the "no shim in `__init__.py`" concern. The planner should choose based on whether the broader regex produces false positives during planning.

### Anti-Patterns to Avoid

- **Leave a re-export shim in `app.modules.auth`**: explicitly forbidden by D-05/D-06. Hard `ModuleNotFoundError` is the intended state post-phase.
- **Promote the 4 deferred imports in callers to module level**: those deferrals exist for reasons unrelated to the auth cycle (slow-import mitigation in `jobs/router.py`, function-local helpers in `domain/service.py`). Leave them deferred.
- **Add `DatasetVisibility` to any public `__init__.py`**: the enum is only used internally within `visibility.py`/`authorization.py` — no external caller imports it. Verified: grep for `DatasetVisibility` outside the source file returns zero hits in `backend/app/`. [VERIFIED: grep 2026-04-27]
- **Pre-emptively do Phase 214 work**: `catalog/authorization.py` imports `from app.modules.auth.models import User, Role, UserRole` concretely. Phase 214 rewrites this; Phase 213 does not.
- **Introduce import-linter or architecture-DSL**: the project uses `subprocess git grep` per Phase 212 D-06. Do not add new tooling.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting missed import migrations | Custom AST scanner | `ruff check` (F821 catches unresolved imports) | Already in dev deps; CI-enforced; zero config [VERIFIED: pyproject.toml:52] |
| Layering enforcement | Custom AST walker | `subprocess git grep` in `test_layering.py` | Established pattern from Phase 212; cheap, fast, explicit failure messages |
| No-migration proof | Generate and inspect a migration file | `cd backend && uv run alembic check` | Confirmed available and working in Phase 212 Gate 1; reports no diff for pure Python moves [VERIFIED: 212-04-SUMMARY.md] |
| Multi-import-statement migration | Custom sed script | Per-file `Edit` tool passes (26 import lines across 23 files) | Bounded set; auditable diff; no automation justified |

**Key insight:** Every "we could automate this" temptation has an existing tool (ruff, alembic, git grep) or is too small to be worth automating (26 lines across 23 files).

## Caller Inventory (Authoritative)

Live grep run 2026-04-27 confirms **26 import lines across 23 files** — matches CONTEXT.md D-04 exactly. No test files import `app.modules.auth.visibility` (unlike Phase 212, which had 5 test-file callers). No alembic env import exists (unlike Phase 212's `env.py:22` surprise — `alembic/env.py` does not reference `visibility`).

### Module-level imports (22 lines across 19 files)

| File | Line | Names imported | Block shape |
|------|------|----------------|-------------|
| `auth/dependencies.py` | 15 | `get_user_roles` | single-line |
| `catalog/collections/router.py` | 16 | `get_user_roles` | single-line |
| `catalog/collections/service.py` | 28 | `apply_visibility_filter` | single-line |
| `catalog/datasets/api/router.py` | 28 | `check_dataset_access_or_anonymous`, `get_user_roles` | multi-line block |
| `catalog/datasets/api/router_data.py` | 23 | `check_dataset_access_or_anonymous`, `get_user_roles` | multi-line block |
| `catalog/datasets/api/router_export.py` | 26 | `apply_visibility_filter`, `check_dataset_access`, `check_dataset_access_or_anonymous`, `get_user_roles` | multi-line block (4 names) |
| `catalog/datasets/api/router_metadata.py` | 22 | `check_dataset_access`, `check_dataset_access_or_anonymous` | multi-line block |
| `catalog/datasets/api/router_vrt.py` | 19 | `check_dataset_access` | single-line |
| `catalog/datasets/domain/service.py` | 29 | `apply_visibility_filter` | single-line |
| `catalog/features/router.py` | 15 | `check_dataset_access` | single-line |
| `catalog/maps/router.py` | 26 | `get_user_roles` | single-line |
| `catalog/maps/service.py` | 20 | `apply_visibility_filter`, `get_user_roles` | single-line (2 names) |
| `catalog/records/router.py` | 11 | `get_user_roles` | single-line |
| `catalog/search/router.py` | 19 | `apply_visibility_filter`, `check_dataset_access_or_anonymous`, `get_user_roles` | multi-line block |
| `catalog/search/service.py` | 33 | `apply_visibility_filter` | single-line |
| `platform/sandbox/validator.py` | 18 | `apply_visibility_filter`, `get_user_roles` | single-line (2 names) |
| `processing/ai/router.py` | 42 | `get_user_roles` | single-line |
| `processing/ai/service.py` | 33 | `apply_visibility_filter` | single-line |
| `processing/export/router.py` | 16 | `check_dataset_access` | single-line |
| `processing/ingest/service.py` | 20 | `get_user_roles` | single-line |
| `processing/tiles/router.py` | 21 | `check_dataset_access`, `get_user_roles` | single-line (2 names) |
| `standards/ogc/router.py` | 11 | `apply_visibility_filter`, `get_user_roles` | single-line (2 names) |

### Function-scope (deferred) imports (4 lines across 2 files)

| File | Line | Names imported | Context |
|------|------|----------------|---------|
| `catalog/datasets/domain/service.py` | 470 | `get_user_roles` | Inside function body (conditional branch) |
| `platform/jobs/router.py` | 124 | `get_user_roles` | Inside `if job.created_by != user.id:` branch |
| `platform/jobs/router.py` | 254 | `apply_visibility_filter`, `get_user_roles` | Function body (2 names, one line) |
| `platform/jobs/router.py` | 319 | `get_user_roles` | Inside `if job.created_by != user.id:` branch |

### No test-file callers

`backend/tests/` has zero direct imports of `app.modules.auth.visibility`. [VERIFIED: live grep 2026-04-27] The test suite exercises visibility behavior through the FastAPI HTTP layer, not by importing the module directly.

### No alembic env.py caller

Unlike Phase 212 where `alembic/env.py:22` was a surprise caller, `alembic/env.py` has no reference to `auth.visibility`. [VERIFIED: live grep 2026-04-27]

## Runtime State Inventory

> Phase 213 is a pure Python relocation with no DB changes.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | None — `dataset_grants`, `records`, `datasets`, `users`, `roles` tables are unchanged. Visibility logic reads these tables; their schemas and data are untouched. | None. |
| **Live service config** | None. The RBAC HTTP API contracts are unchanged at the wire level (D-13). | None. |
| **OS-registered state** | None. No systemd / pm2 / Task Scheduler registrations reference Python module paths. | None. |
| **Secrets and env vars** | None. No env vars reference `auth.visibility`. | None. |
| **Build artifacts** | `backend/.venv/` and `__pycache__/` may have stale `.pyc` for `app.modules.auth.visibility`. They regenerate on next import; if local pytest fails strangely after the delete, `find backend -type d -name __pycache__ -exec rm -rf {} +` clears them. | None for CI (clean checkout). Note in plan. |

**Nothing found in any category that requires a data migration or runtime reconfiguration.**

## Common Pitfalls

### Pitfall 1: Forgetting to verify the grep is exhaustive before migrating

**What goes wrong:** A caller added after CONTEXT.md was written (e.g., a quick-task or post-discussion commit) imports `app.modules.auth.visibility` and is not in the CONTEXT.md D-04 list. After deletion, that file raises `ModuleNotFoundError` at import time, causing a pytest collection error or HTTP 500 at startup.
**Why it happens:** CONTEXT.md's D-04 list was assembled at discussion time; the codebase continues to evolve.
**How to avoid:** Plan step 0 of the migration commit: run `git grep -nE "auth\.visibility|from app\.modules\.auth\.visibility" -- backend/` and verify every hit corresponds to D-04's list. If new hits appear, add them to the migration sweep.
**Warning signs:** `ModuleNotFoundError: No module named 'app.modules.auth.visibility'` in pytest collection output.

### Pitfall 2: Promoting the wrong deferred imports

**What goes wrong:** The plan promotes the 4 function-scope deferred imports in *callers* (jobs/router.py etc.) to module level, reasoning "since the cycle is gone." Those deferrals exist for reasons unrelated to the auth cycle — slow-import mitigation, lazy load. Promoting them could introduce import-time side effects or circular imports for those specific callers.
**Why it happens:** The DatasetGrant promotion inside `visibility.py` itself is correct and explained by CONTEXT.md D-03. Applying that logic to all deferred sites is a mis-generalization.
**How to avoid:** Only promote `DatasetGrant` inside the new `catalog/authorization.py`. The 4 deferred caller sites are rewritten path only — the `from ... import` stays inside the function body.
**Warning signs:** Import errors or unexpected behavior in `platform/jobs/` endpoints.

### Pitfall 3: The broader architecture guard self-positive

**What goes wrong:** The second new test (`test_no_auth_visibility_module_referenced`) uses a broad regex like `auth\.visibility` without excluding `test_layering.py` itself. The regex literals inside the test file match, producing a false failure on the first run.
**Why it happens:** Phase 212-03 hit exactly this bug (commit `b0bd0c2c` fixed it). The Phase 212 test used `r"app\.modules\.settings\.models"` without an import-line anchor, over-matched its own docstring, and had to be patched.
**How to avoid:** Either (a) use the `":!backend/tests/test_layering.py"` pathspec exclusion in `git grep`, or (b) anchor the broader regex with `^\s*(from|import)` — but note the broader test's value is catching `__init__.py` re-exports which are not import-shaped, so anchoring defeats the purpose. Use the pathspec exclusion.
**Warning signs:** `test_no_auth_visibility_module_referenced` fails immediately after being added, with the offending lines all coming from `test_layering.py` itself.

### Pitfall 4: `alembic check` false alarm from pre-existing drift

**What goes wrong:** `alembic check` reports schema drift and the executor concludes Phase 213 caused it, stopping work.
**Why it happens:** Phase 212-04-SUMMARY.md Gate 1 documents pre-existing drift: procrastinate library tables and raw-SQL indexes are NOT in `Base.metadata`, so alembic always reports them as "pending." This drift predates Phase 212 and is unrelated to Phase 213.
**How to avoid:** When reviewing `alembic check` output, confirm that none of the reported items reference `auth_` tables, `dataset_grants`, `records`, `datasets`, `roles`, or `users` as new or dropped tables. Any drift should be the same pre-existing procrastinate / raw-SQL index items from Phase 212. If the diff mentions any catalog-domain table, stop and investigate.
**Warning signs:** `alembic check` reports tables like `auth_visibility_*` or changes to `dataset_grants` — these would be real Phase 213 regressions (but should not happen since the relocation is pure Python).

### Pitfall 5: The architecture guard runs in the container but git is absent

**What goes wrong:** `docker compose exec api uv run pytest tests/test_layering.py` fails with "git metadata unavailable" in SKIP (expected) but the CI invocation counts these as failures rather than skips.
**Why it happens:** `.dockerignore` excludes `.git/` from the container image. The `_has_git_metadata()` guard produces `pytest.skip`, not `pytest.fail`, so the behavior is correct by design. Phase 212-04-SUMMARY.md Gate 6 confirms: "In container they SKIP because `_has_git_metadata()` returns False — designed-in fallback."
**How to avoid:** Run the architecture guard tests on the host (`cd backend && uv run pytest tests/test_layering.py -v -m architecture`), not in the container. The phase verification gate plan should mirror Phase 212's Gate 6 structure.
**Warning signs:** "2 passed" on host but "2 skipped" in container — that is the correct behavior, not a failure.

### Pitfall 6: `DatasetVisibility` enum is caller-facing

**What goes wrong:** A plan task adds `DatasetVisibility` to the migration checklist as a "name that callers import" and wastes time hunting for external callers.
**Why it happens:** `DatasetVisibility` is listed in the module's docstring as part of the public surface (D-02), suggesting callers might import it.
**How to avoid:** Grep confirms: no file outside `auth/visibility.py` imports `DatasetVisibility`. The enum is used only within `visibility.py` itself (comparing `record_cls.visibility == DatasetVisibility.PUBLIC` etc.). External code uses string literals like `"public"` / `"restricted"` directly. The migration does not need to touch any caller for this name. [VERIFIED: grep 2026-04-27]

### Pitfall 7: Stale `__pycache__` after local file deletion (same as Phase 212 Pitfall 6)

**What goes wrong:** After deleting `auth/visibility.py`, stale `.pyc` in `__pycache__` allows Python to continue importing from the old path locally, masking missed migrations.
**How to avoid:** After the deletion commit, `find backend -type d -name __pycache__ -exec rm -rf {} +` before running local pytest. CI is unaffected (fresh checkout).

## Code Examples

### The new file: complete header through imports

```python
# backend/app/modules/catalog/authorization.py
# Source: relocated from backend/app/modules/auth/visibility.py (Phase 213)
"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
Relocated from app.modules.auth.visibility (Phase 213).
"""

import enum
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant
```
[CITED: visibility.py lines 1–20 + line 148; DatasetGrant class at domain/models.py:411]

### The promoted DatasetGrant import — before/after diff inside check_dataset_access()

```diff
 async def check_dataset_access(
     db: AsyncSession,
     dataset: Any,
     dataset_id: uuid.UUID,
     user: User,
     *,
     user_roles: set[str] | None = None,
 ) -> set[str]:
-    from app.modules.catalog.datasets.domain.models import DatasetGrant
-
-    if user_roles is None:
+    if user_roles is None:
```
[VERIFIED: visibility.py:148–150]

### Verification commands (Phase 213 equivalents of Phase 212's gates)

```bash
# Gate 1: No remaining callers of the old path (SC#4)
git grep -n "from app\.modules\.auth\.visibility\|^import app\.modules\.auth\.visibility" -- backend/ ; test $? -eq 1

# Gate 2: Broader check — no 'auth.visibility' reference anywhere except test_layering.py
git grep -n "app\.modules\.auth\.visibility\|auth\.visibility" -- backend/ ':!backend/tests/test_layering.py' ; test $? -eq 1

# Gate 3: Source file is deleted (D-05)
test ! -e backend/app/modules/auth/visibility.py

# Gate 4: Alembic schema drift check (D-10)
cd backend && uv run alembic check
# Expected: reports same pre-existing procrastinate drift as Phase 212; zero catalog-table changes

# Gate 5: Full backend test suite (D-11 / SC#3)
docker compose exec api uv run pytest -m 'not perf' --tb=short -q
# Expected: ≥1999 passed (the baseline post-Phase-212), 0 failed

# Gate 6: Ruff lint + format
cd backend && uv run ruff check app/ tests/ alembic/
cd backend && uv run ruff format --check app/ tests/ alembic/

# Gate 7: Architecture guard standalone
cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
# Expected: 4 passed (2 Phase 212 tests + 2 new Phase 213 tests)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| RBAC / visibility logic lives in `auth/` alongside JWT/token code | Visibility logic lives in `catalog/authorization.py` alongside catalog business logic | This phase (Phase 213) | `auth/` becomes a pure identity module; catalog owns its own access rules |
| `DatasetGrant` imported via deferred cycle-breaker inside `auth/visibility.py` | `DatasetGrant` imported at module level in `catalog/authorization.py` (no cycle) | This phase | Removes architectural smell flagged in audit §5 |
| Layering guard covers only `from app.modules.settings` (Phase 212 NARROW) | Guard extended to also cover `from app.modules.auth.visibility` | This phase | `test_layering.py` grows from 2 to 4 architecture tests |

**Deprecated/outdated after this phase:**
- `backend/app/modules/auth/visibility.py` — deleted; hard `ModuleNotFoundError` if referenced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `.git/` is excluded inside the `geolens-api` container, so the architecture guard tests SKIP (not FAIL) when run via `docker compose exec api uv run pytest`. | Pitfall 5 | If `.git/` is somehow present inside the container, the guard would run — which is fine (and better). No action needed either way because `_has_git_metadata()` handles both cases correctly. Low risk. [CITED: 212-04-SUMMARY.md Gate 6 confirms skip behavior] |
| A2 | The live test count is ≥1999 (not still exactly 1965). | Validation Architecture | If the baseline is exactly 1965, the Phase 212 gate evidence is stale. Phase 212-04-SUMMARY.md Gate 2 shows 1999 passed — planners should treat 1999 as the floor. [CITED: 212-04-SUMMARY.md Gate 2] |
| A3 | No enterprise overlay repo imports `from app.modules.auth.visibility`. | Caller Inventory | If a sibling `geolens-enterprise` repo imports the old path, deleting it breaks enterprise CI. [ASSUMED — no enterprise overlay repo was grepped. The phase brief scopes to this repo only.] |

## Open Questions

1. **Broader regex vs. pathspec exclusion in `test_no_auth_visibility_module_referenced`**
   - What we know: Using `r"auth\.visibility"` without scope restriction will match the regex literals in `test_layering.py` itself, producing a false positive (the Phase 212-03 bug). Two options: (a) `:!backend/tests/test_layering.py` pathspec exclude in `git grep`, or (b) anchor the regex to import-shaped lines (but anchoring limits the "catches `__init__.py` re-exports" purpose).
   - What's unclear: Whether `git grep` in this repo supports pathspec negative exclusions via `:!<path>` in the subprocess call.
   - Recommendation: The planner tests option (a) during wave 0 by running the grep manually. If `:!` is not supported, fall back to option (b) with the import anchor. The Phase 212 fix (commit `b0bd0c2c`) used anchoring successfully, so that is the proven fallback.

2. **`test_layering.py` docstring scope update wording**
   - What we know: The current docstring says "Scope (Phase 212): NARROW — only `from app.modules.settings`. Phases 213 (catalog-authz-relocate) and 214 (identity-protocol-extract) close additional core->modules edges; Phase 218 will broaden this guard to `from app.modules.<*>` once those phases land."
   - What's unclear: The docstring text anticipates this exact phase. The planner updates it to reflect "Scope (Phases 212–213)" without over-promising Phase 214's shape.
   - Recommendation: Minimal update — change "Scope (Phase 212): NARROW" to "Scope (Phases 212–213)" and add a sentence summarizing what Phase 213 adds. Keep the Phase 214/218 forward note.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | ≥3.13 | — |
| `uv` | Build / test | ✓ | 0.10.2 | — |
| `alembic` | D-10 drift check | ✓ | ≥1.13.0; `check` subcommand confirmed | — |
| `ruff` | Lint / format check | ✓ | dev dep | — |
| `pytest` | Test suite | ✓ | ≥9.0.3 | — |
| `git` CLI | Architecture guard tests | ✓ on host; absent inside container | — | `_has_git_metadata()` skip guard (designed-in) |
| Docker Compose | `docker compose exec api uv run pytest` | ✓ | project standard | Direct `cd backend && uv run pytest` on host |

**Missing dependencies with no fallback:** None.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥9.0.3 with `anyio_mode = "auto"` / `asyncio_mode = "strict"` |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` (lines 62–75) |
| Quick run command | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` |
| Full suite command | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LAYER-02 (a) — `auth/visibility.py` deleted, zero import sites remain | Static import inspection (import-shaped) | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_no_imports_from_auth_visibility -v` | ❌ Wave 0 (new test in existing file) |
| LAYER-02 (b) — no `auth.visibility` string referenced anywhere (catches `__init__.py` shims) | Broader static inspection | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_no_auth_visibility_module_referenced -v` | ❌ Wave 0 |
| LAYER-02 (c) — RBAC behavior parity (search, datasets, features, tiles, STAC, OGC, maps, collections, jobs, AI, export, ingest, sandbox) | Full RBAC regression | integration (full suite) | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | ✅ existing corpus |
| LAYER-02 (d) — no alembic schema drift | `alembic check` exits 0 with no catalog-domain changes | smoke (CLI) | `cd backend && uv run alembic check` | ✅ alembic CLI exists |
| LAYER-02 (e) — 1999-test baseline green | Full pytest run | full suite | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | ✅ existing 1999 tests |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_layering.py -v` (quick; covers arch guard)
- **Per wave merge:** `cd backend && uv run pytest tests/test_layering.py tests/test_dataset_visibility.py tests/test_search.py tests/test_features.py tests/test_tiles.py -v --tb=short` (RBAC slice; confirm visibility behavior across key endpoints)
- **Phase gate:** Full suite green (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q`) AND `cd backend && uv run alembic check` returns no catalog-table changes AND `git grep -nE "auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'` exits 1 (no matches) BEFORE `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] Two new tests in `backend/tests/test_layering.py` — `test_no_imports_from_auth_visibility` and `test_no_auth_visibility_module_referenced` (Pattern 5 above). Added in Wave 3 (architecture guard plan), not Wave 1.
- [ ] `test_layering.py` module docstring update (D-09) — same wave as the new tests.

No new test files required. No new marker registration required (`architecture` marker already registered at `pyproject.toml:74`). [VERIFIED: pyproject.toml:71–75]

*(Existing test infrastructure covers all RBAC behavior parity requirements — no Wave 0 gaps there.)*

## Security Domain

> Phase is a Python-only relocation with no auth surface change, no new input parsing, no cryptographic code.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | JWT/OAuth code in `auth/dependencies.py` is unchanged. |
| V3 Session Management | no | No session-handling changes. |
| V4 Access Control | **yes** (relocation of the control) | `check_dataset_access`, `check_dataset_access_or_anonymous`, `apply_visibility_filter` — same logic, new path. SEC-04 invariant preserved verbatim. |
| V5 Input Validation | no | No user-input parsing in `visibility.py`. |
| V6 Cryptography | no | No crypto code. |

**V4 note:** The RBAC enforcement functions are relocated, not changed. The SEC-04 invariant ("All dataset access paths use these shared functions") remains the same — only the module path changes. Any future bypass would be caught by the existing test corpus (RBAC integration tests pass unchanged = parity proven).

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Authorization bypass via missed import migration | Elevation of Privilege | `ruff check` (F821 unresolved import) + `_git_grep` architecture guard + full pytest RBAC coverage. All three gates must pass. |
| Re-introduction of `auth → catalog` cycle via `__init__.py` shim | Tampering (code structure) | `test_no_auth_visibility_module_referenced` (broader guard test) catches re-exports, not just direct imports. |

## Sources

### Primary (HIGH confidence)
- `backend/app/modules/auth/visibility.py` — full file read 2026-04-27; 183 lines confirmed
- `backend/tests/test_layering.py` — full file read 2026-04-27; `_has_git_metadata()`, `_git_grep` helpers confirmed at lines 29–46
- `backend/pyproject.toml` — full read 2026-04-27; `architecture` marker at line 74; no pyright/mypy confirmed
- `backend/app/modules/catalog/datasets/domain/models.py` — `DatasetGrant` class at lines 411–421 confirmed
- `backend/app/modules/auth/models.py` — `User`, `Role`, `UserRole` at module level confirmed
- `backend/app/modules/catalog/__init__.py` — docstring-only confirmed
- `backend/app/modules/auth/dependencies.py:14–15` — imports `get_user_roles` from `auth.visibility` confirmed
- Live grep `git grep -n "auth\.visibility|from app\.modules\.auth\.visibility"` — 26 import lines across 23 files, zero test-file callers, no alembic env caller [VERIFIED: 2026-04-27]
- Live grep `grep -rn "DatasetVisibility" backend/` — enum is internal-use only, no external callers [VERIFIED: 2026-04-27]
- `.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md` — live test count is 1999 (not 1965); alembic pre-existing drift documented; architecture guard skip behavior in container confirmed
- `.planning/phases/212-core-settings-decouple/212-04-phase-verification-gate-PLAN.md` — verification gate command structure (template for Phase 213-04)

### Secondary (MEDIUM confidence)
- `.planning/phases/213-catalog-authz-relocate/213-CONTEXT.md` — all locked decisions
- `.planning/ROADMAP.md` Phase 213 section — 4 success criteria
- `.planning/REQUIREMENTS.md` §LAYER-02

### Tertiary (LOW confidence)
- A3 (enterprise overlay assumption) — not verified against sibling repo

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies verified in pyproject.toml
- Architecture: HIGH — caller inventory from live grep; file shapes from direct reads
- Pitfalls: HIGH for 1, 3, 4, 5, 6, 7; MEDIUM for 2 (inferred from codebase conventions)
- Caller inventory: HIGH — exhaustive live grep 2026-04-27, 0 discrepancies from CONTEXT.md D-04
- Validation Architecture: HIGH — framework and test corpus verified; commands confirmed by Phase 212 evidence

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (30 days; codebase is stable but baseline test count could drift from concurrent quick-tasks)

---

## RESEARCH COMPLETE

**Phase:** 213 - catalog-authz-relocate
**Confidence:** HIGH

### Key Findings

1. **Caller inventory matches CONTEXT.md exactly** — live grep confirms 26 import lines across 23 files (22 module-level + 4 deferred). No test files import `auth.visibility`. No alembic env caller. No surprises unlike Phase 212's hidden `env.py:22`.

2. **`DatasetVisibility` enum has zero external callers** — only used inside `visibility.py` itself via string comparisons. No caller migration needed for this name despite it being listed in D-02's public surface.

3. **The DatasetGrant promotion is the only content change** — `visibility.py:148`'s deferred import becomes a module-level import in `catalog/authorization.py`. Everything else is verbatim copy + import path rewrite.

4. **The self-positive bug from Phase 212-03** (commit `b0bd0c2c`) must be avoided in the second new architecture guard test. Use a pathspec exclusion (`:!backend/tests/test_layering.py`) or import-anchor to prevent the regex literal in the test file from matching itself.

5. **Live test baseline is 1999, not 1965** — Phase 212 shipped with 1999 passing tests (Phase 212-04-SUMMARY.md Gate 2). The 1965 number in `STATE.md` is the floor from the restore operation; the actual live count rose by 34 between restore and Phase 212 landing. The verification gate should check ≥1999.

### File Created
`.planning/phases/213-catalog-authz-relocate/213-RESEARCH.md`

### Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Standard stack | HIGH | All deps in pyproject.toml; no new packages required |
| Caller inventory | HIGH | Live grep run; zero discrepancies from CONTEXT.md D-04 |
| Architecture patterns | HIGH | Phase 212 fully shipped; patterns directly reusable |
| Pitfalls | HIGH | Pitfall 3 (self-positive) documented from Phase 212's actual bug history |
| Validation Architecture | HIGH | Framework confirmed; commands verified by Phase 212 evidence |

### Open Questions

- Whether `git grep ":!<path>"` pathspec negation works in the subprocess call for the broader architecture guard test. Planner should test during wave 0. Fallback is the import-anchor pattern (proven in Phase 212).

### Ready for Planning

Research complete. Planner can now create PLAN.md files.

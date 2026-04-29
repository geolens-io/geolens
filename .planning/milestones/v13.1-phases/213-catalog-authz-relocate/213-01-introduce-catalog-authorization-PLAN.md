---
phase: 213-catalog-authz-relocate
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/modules/catalog/authorization.py
autonomous: true
requirements: [LAYER-02]
requirements_addressed: [LAYER-02]
tags: [refactor, layering, relocation, open-core]

must_haves:
  truths:
    - "D-01: A new file exists at `backend/app/modules/catalog/authorization.py` (flat single file, sibling to `catalog/sources/`, `catalog/search/`, etc. — NOT `catalog/_authz/visibility.py`)."
    - "D-02: The new module exposes the exact same public surface as `auth/visibility.py`: `DatasetVisibility`, `apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous` — same names, same signatures, same behavior."
    - "D-03: Inside the new module, the `from app.modules.catalog.datasets.domain.models import DatasetGrant` import is at MODULE level (after the `from sqlalchemy.ext.asyncio import AsyncSession` import), and the corresponding function-scope `from ... import DatasetGrant` line inside `check_dataset_access()` (was `visibility.py:148`) has been REMOVED."
    - "D-03: The new module STILL imports `Role, User, UserRole` from `app.modules.auth.models` (Phase 213 does NOT pre-empt Phase 214's IdentityProtocol work)."
    - "The module docstring is updated to (a) preserve the SEC-04 invariant statement, and (b) note the relocation source `Relocated from app.modules.auth.visibility (Phase 213)`."
    - "The OLD file `backend/app/modules/auth/visibility.py` is STILL PRESENT after this plan (Plan 02 deletes it). Both modules co-exist at this point, both exporting the same names — Python imports them by path so there is no symbol clash."
    - "All 26 caller import sites STILL point at `app.modules.auth.visibility` after this plan (Plan 02 migrates them)."
  artifacts:
    - path: "backend/app/modules/catalog/authorization.py"
      provides: "Verbatim copy of auth/visibility.py with module docstring updated and DatasetGrant import promoted to module level"
      contains: "class DatasetVisibility"
      min_lines: 175
  key_links:
    - from: "backend/app/modules/catalog/authorization.py"
      to: "backend/app/modules/auth/models.py:User"
      via: "module-level import"
      pattern: "from app\\.modules\\.auth\\.models import Role, User, UserRole"
    - from: "backend/app/modules/catalog/authorization.py"
      to: "backend/app/modules/catalog/datasets/domain/models.py:DatasetGrant"
      via: "module-level import (promoted from deferred per D-03)"
      pattern: "from app\\.modules\\.catalog\\.datasets\\.domain\\.models import DatasetGrant"
---

<objective>
Create `backend/app/modules/catalog/authorization.py` as a verbatim copy of `backend/app/modules/auth/visibility.py` with two surgical changes only:

1. The module docstring adds a one-line "Relocated from app.modules.auth.visibility (Phase 213)" note (D-03 / module docstring discretion in CONTEXT.md).
2. The function-scope `from app.modules.catalog.datasets.domain.models import DatasetGrant` import at line 148 of `visibility.py` is PROMOTED to a module-level import (after the existing `from sqlalchemy.ext.asyncio import AsyncSession` import) — this removes the `auth → catalog` cycle smell that originally forced the deferred import (D-03).

Purpose: This is the foundation for the LAYER-02 relocation. After this plan lands, the new module exists and is importable; downstream caller migration and source-file deletion happen in Plan 02. Splitting the file-creation step from the caller-migration step keeps the diff easy to review and lets the public-surface smoke test happen in isolation, before the old path is deleted.

Output: A new file at `backend/app/modules/catalog/authorization.py` with the same public surface as the source. No callers move. No deletions. The OLD file at `backend/app/modules/auth/visibility.py` is untouched. Both files temporarily co-exist; Plan 02 migrates the callers and deletes the old file in the same plan.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/213-catalog-authz-relocate/213-CONTEXT.md
@.planning/phases/213-catalog-authz-relocate/213-RESEARCH.md
@.planning/phases/213-catalog-authz-relocate/213-PATTERNS.md
@.planning/phases/213-catalog-authz-relocate/213-VALIDATION.md
@backend/app/modules/auth/visibility.py
@backend/app/modules/auth/models.py
@backend/app/modules/catalog/datasets/domain/models.py
@backend/app/modules/catalog/__init__.py

<interfaces>
<!-- Source-of-truth file: copy this body verbatim except for the two diffs below. -->
<!-- The file is 183 lines. Read it end-to-end before writing the new file. -->

Source file: `backend/app/modules/auth/visibility.py` (183 lines)
Public surface (D-02 — must match exactly):
- `class DatasetVisibility(str, enum.Enum)` — `PUBLIC`, `RESTRICTED`, `PRIVATE`
- `def apply_visibility_filter(...)` — query-level filtering
- `def get_user_roles(...)` — role lookup helper
- `async def check_dataset_access(...)` — per-endpoint visibility check (the function that contained the deferred DatasetGrant import at line 148)
- `async def check_dataset_access_or_anonymous(...)` — anonymous-friendly variant

Existing imports block (lines 12-20 of source; reproduce verbatim except for the new DatasetGrant line):
```python
import enum
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserRole
```

Existing module docstring (lines 1-10 of source — needs the "Relocated" line added):
```python
"""Dataset visibility enforcement.

Provides:
- DatasetVisibility enum for public/restricted/private
- apply_visibility_filter() for query-level dataset filtering
- get_user_roles() for role lookup (replaces per-router duplicates)
- check_dataset_access() for per-endpoint visibility checks

SEC-04: All dataset access paths use these shared functions.
"""
```

The deferred import currently at `visibility.py:148` (inside `check_dataset_access()`) — must be REMOVED from the function body in the new file:
```python
async def check_dataset_access(
    db: AsyncSession,
    dataset: Any,
    dataset_id: uuid.UUID,
    user: User,
    *,
    user_roles: set[str] | None = None,
) -> set[str]:
    from app.modules.catalog.datasets.domain.models import DatasetGrant   # <-- this line is removed in the new file (promoted to module level)

    if user_roles is None:
        ...
```

DatasetGrant lives at `backend/app/modules/catalog/datasets/domain/models.py:411` (verified by RESEARCH.md sources).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 01-01: Create catalog/authorization.py (verbatim copy + docstring update + DatasetGrant promotion)</name>
  <files>backend/app/modules/catalog/authorization.py</files>
  <read_first>
    - backend/app/modules/auth/visibility.py (THE SOURCE OF TRUTH — read end-to-end before writing; the new file's body is a verbatim copy of this file with two surgical diffs only)
    - backend/app/modules/auth/models.py (confirm `User`, `Role`, `UserRole` are exported here at module level — the new file imports them from this path unchanged per D-03)
    - backend/app/modules/catalog/datasets/domain/models.py (confirm `class DatasetGrant` is defined at module level around line 411 — the new file imports it at module level, replacing the line 148 deferred import in the source)
    - backend/app/modules/catalog/__init__.py (confirm it is a docstring-only file — DO NOT modify it; per CONTEXT.md "Integration Points" no re-exports are added)
    - .planning/phases/213-catalog-authz-relocate/213-CONTEXT.md (D-01 file location; D-02 public surface; D-03 import changes)
    - .planning/phases/213-catalog-authz-relocate/213-RESEARCH.md (Pattern 1 — verbatim relocation with import promotion; Pitfall 1 — verify grep before assuming caller list is current; Pitfall 6 — DatasetVisibility enum has zero external callers, so no caller-side enum-rename concern)
    - .planning/phases/213-catalog-authz-relocate/213-PATTERNS.md ("File Classification" → first row; "Pattern Assignments" → "backend/app/modules/catalog/authorization.py" section showing both diffs)
  </read_first>
  <action>
Create `backend/app/modules/catalog/authorization.py`. The file MUST be a byte-equivalent copy of `backend/app/modules/auth/visibility.py` with EXACTLY the following two diffs applied:

**Diff 1 — module docstring update** (replace the source's lines 1-10 with the version below; the only change is adding the final "Relocated from..." line before the closing `"""`):

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

**Diff 2 — promote `DatasetGrant` to module-level import**

In the new file's imports block (immediately after `from sqlalchemy.ext.asyncio import AsyncSession`), add:
```python
from app.modules.auth.models import Role, User, UserRole
from app.modules.catalog.datasets.domain.models import DatasetGrant
```

Then, inside the body of `check_dataset_access()` (which appears later in the file — the source had the import at line 148), DELETE these two lines:
```python
    from app.modules.catalog.datasets.domain.models import DatasetGrant

```
(the deferred import line and the blank line that follows it). The function logic that uses `DatasetGrant` (the SQL query starting `select(DatasetGrant)...`) stays unchanged — only the deferred import line is removed because `DatasetGrant` is now in the module namespace via the promoted top-level import.

**Hard constraints (from CONTEXT.md, RESEARCH.md, PATTERNS.md):**

1. The body of every function (`apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous`) and the `DatasetVisibility` enum MUST match the source byte-for-byte except for the single 2-line removal inside `check_dataset_access()` described in Diff 2.
2. The import order in the new file MUST be: stdlib (`enum`, `uuid`, `typing.Any`) → third-party (`fastapi`, `sqlalchemy`, `sqlalchemy.ext.asyncio`) → first-party (`app.modules.auth.models`, then the newly added `app.modules.catalog.datasets.domain.models`). This matches PEP 8 and ruff's import sort order.
3. DO NOT modify `backend/app/modules/catalog/__init__.py`. Specifically, DO NOT add a `from .authorization import ...` re-export. Per CONTEXT.md "Integration Points": "every importer already uses the submodule path; introducing re-exports is a separate concern."
4. DO NOT delete or modify `backend/app/modules/auth/visibility.py` in this plan — Plan 02 handles that. After this task, BOTH `auth/visibility.py` AND `catalog/authorization.py` exist on disk. Both define `DatasetVisibility`, `apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous`. Python imports them by full module path, so there is no naming collision; SQLAlchemy does not see any new `__tablename__` registration because this file declares no ORM models.
5. DO NOT alter any function signature, default-value, or return-type annotation. D-02 says "exact public surface — no renames, no signature changes."
6. DO NOT introduce any new dependency. The new file's imports come entirely from `enum`, `uuid`, `typing`, `fastapi`, `sqlalchemy`, `sqlalchemy.ext.asyncio`, `app.modules.auth.models`, and `app.modules.catalog.datasets.domain.models` — every one of which is already imported elsewhere in the codebase.
7. DO NOT add `# Phase 213` comments inside function bodies. The only Phase 213 reference in the new file is the docstring's "Relocated from app.modules.auth.visibility (Phase 213)." line. PATTERNS.md's example annotation `# promoted from deferred (Phase 213)` is illustrative only — keep the import line clean (`from app.modules.catalog.datasets.domain.models import DatasetGrant`) without the inline comment.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && test -f backend/app/modules/catalog/authorization.py && (cd backend && uv run python -c "from app.modules.catalog.authorization import DatasetVisibility, apply_visibility_filter, get_user_roles, check_dataset_access, check_dataset_access_or_anonymous; assert DatasetVisibility.PUBLIC.value == 'public'; assert DatasetVisibility.RESTRICTED.value == 'restricted'; assert DatasetVisibility.PRIVATE.value == 'private'; print('public_surface_ok')") && (cd backend && uv run ruff check app/modules/catalog/authorization.py) && (cd backend && uv run ruff format --check app/modules/catalog/authorization.py) && grep -c "^from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$" backend/app/modules/catalog/authorization.py | tr -d ' ' | (read n; test "$n" = "1") && bash -c 'BODY_DEFERRED=$(grep -c "^    from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$" backend/app/modules/catalog/authorization.py | tr -d " "); test "$BODY_DEFERRED" = "0"' && grep -q "Relocated from app.modules.auth.visibility (Phase 213)" backend/app/modules/catalog/authorization.py && test -f backend/app/modules/auth/visibility.py</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/app/modules/catalog/authorization.py` exists.
    - `cd backend && uv run python -c "from app.modules.catalog.authorization import DatasetVisibility, apply_visibility_filter, get_user_roles, check_dataset_access, check_dataset_access_or_anonymous"` exits 0 (the public surface is intact).
    - The smoke import also asserts `DatasetVisibility.PUBLIC.value == 'public'`, `DatasetVisibility.RESTRICTED.value == 'restricted'`, `DatasetVisibility.PRIVATE.value == 'private'` (the enum values are unchanged from the source).
    - `grep -c "^from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$" backend/app/modules/catalog/authorization.py` returns exactly 1 (DatasetGrant is at module level).
    - `grep -c "^    from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$" backend/app/modules/catalog/authorization.py` returns exactly 0 (the deferred function-scope import line from `visibility.py:148` is NOT carried over — the line was removed during Diff 2).
    - `grep -q "Relocated from app.modules.auth.visibility (Phase 213)" backend/app/modules/catalog/authorization.py` exits 0 (docstring update applied).
    - `grep -q "SEC-04" backend/app/modules/catalog/authorization.py` exits 0 (the SEC-04 invariant line is preserved verbatim from the source).
    - `cd backend && uv run ruff check app/modules/catalog/authorization.py` exits 0 (no F401 unused imports, no F821 undefined names — proves DatasetGrant is actually used somewhere in the body).
    - `cd backend && uv run ruff format --check app/modules/catalog/authorization.py` exits 0 (no formatting drift).
    - `test -f backend/app/modules/auth/visibility.py` exits 0 — the OLD file is still present (Plan 02 deletes it; this plan must NOT touch it).
    - `git diff backend/app/modules/auth/visibility.py` produces zero output (the old file is byte-unchanged).
    - `git diff backend/app/modules/catalog/__init__.py` produces zero output (CONTEXT.md "Integration Points" — no re-exports added).
  </acceptance_criteria>
  <done>
    `backend/app/modules/catalog/authorization.py` exists with the verbatim public surface of the source, the docstring updated to note the relocation, and `DatasetGrant` imported at module level. The old file is untouched and still on disk; no callers have been migrated. Plan 02 picks up here, migrates 26 import sites, and deletes the old file.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan adds a single new Python module containing dataset RBAC enforcement helpers. The functions implementing access control are byte-equivalent to the existing `auth/visibility.py` — `check_dataset_access`, `check_dataset_access_or_anonymous`, `apply_visibility_filter`, `get_user_roles`. The SEC-04 invariant ("all dataset access paths use these shared functions") is preserved. No new external attack surface is introduced; the new module is not yet wired to any caller (Plan 02 wires it).

| Boundary | Description |
|----------|-------------|
| (none new) | Pure relocation; the trust boundary that crosses RBAC enforcement (HTTP request → visibility filter → DB query) is structurally unchanged. The new module replicates the existing controls verbatim. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-213-01 | E (Elevation of Privilege) — RBAC bypass via accidental signature drift in copy | `backend/app/modules/catalog/authorization.py` (new) | mitigate | Acceptance criteria require a public-surface smoke import that exercises every function name and the enum values. ASVS V4 invariant (SEC-04 single-helper-set) is preserved by the docstring + verbatim copy. Plan 04 (phase verification gate) runs the full pytest suite which exercises `check_dataset_access` and friends across search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox; any signature drift would surface as a wide test failure. |
| T-213-02 | T (Tampering) — DatasetGrant promotion introduces import-time side effect | New module-level `from app.modules.catalog.datasets.domain.models import DatasetGrant` | accept | The promotion does not introduce a new `Base.metadata` registration (DatasetGrant was already registered by `domain/models.py` import paths used by the catalog datasets routers). It does not introduce a cycle: `catalog/authorization.py` depends on `catalog/datasets/domain/models` (sibling package importing sibling package); no `auth → catalog → auth` cycle is reintroduced. Plan 04 runs `alembic check` which would surface any `Base.metadata` divergence. |
| T-213-03 | INFO — temporary co-existence of two modules exporting the same names | `auth/visibility.py` + new `catalog/authorization.py` co-exist between Plan 01 and Plan 02 | accept | Python imports modules by full path; there is no symbol clash because nothing imports both. Callers continue to use `auth.visibility` until Plan 02 rewrites them. The window of co-existence is sub-PR. |
</threat_model>

<verification>
- File exists: `test -f backend/app/modules/catalog/authorization.py` exits 0.
- Public surface intact: `cd backend && uv run python -c "from app.modules.catalog.authorization import DatasetVisibility, apply_visibility_filter, get_user_roles, check_dataset_access, check_dataset_access_or_anonymous; print('ok')"` prints `ok` and exits 0.
- Enum values preserved: the same smoke command asserts `DatasetVisibility.PUBLIC.value == 'public'`, `.RESTRICTED.value == 'restricted'`, `.PRIVATE.value == 'private'`.
- DatasetGrant promoted: `grep -c "^from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$" backend/app/modules/catalog/authorization.py` returns 1; `grep -c "^    from app\.modules\.catalog\.datasets\.domain\.models import DatasetGrant$"` returns 0 (no remaining deferred copy).
- Docstring updated: `grep -q "Relocated from app.modules.auth.visibility (Phase 213)" backend/app/modules/catalog/authorization.py` exits 0; SEC-04 line preserved.
- Lint + format clean: `ruff check` and `ruff format --check` against the new file both exit 0 (catches F401 unused-import if `DatasetGrant` somehow ended up dead after the body copy, and any whitespace drift).
- Old file untouched: `git diff backend/app/modules/auth/visibility.py` produces zero output.
- `__init__.py` untouched: `git diff backend/app/modules/catalog/__init__.py` produces zero output.
</verification>

<success_criteria>
- `backend/app/modules/catalog/authorization.py` exists, imports cleanly, exposes the 5-symbol public surface (D-02), and has `DatasetGrant` at module level (D-03).
- The body of every function is byte-equivalent to the source except for the surgically removed deferred-import line.
- The plan introduces zero behavior change at the wire level (no caller migrated, HTTP responses unchanged) and no schema change (DatasetGrant ORM identity is unchanged).
- The OLD file at `backend/app/modules/auth/visibility.py` is still present and untouched — Plan 02 deletes it after migrating callers.
</success_criteria>

<output>
After completion, create `.planning/phases/213-catalog-authz-relocate/213-01-SUMMARY.md` documenting:
- The new file's exact path and line count.
- The two diffs applied (docstring update + DatasetGrant promotion) — quote the actual lines added/removed.
- Confirmation that `auth/visibility.py` is byte-unchanged (`git diff` output is empty).
- Confirmation that `catalog/__init__.py` is byte-unchanged.
- The smoke import command that proves the public surface resolves.
- Any deviation from the verbatim copy (there should be none — only the docstring and the import-promotion diff).
</output>
</content>
</invoke>
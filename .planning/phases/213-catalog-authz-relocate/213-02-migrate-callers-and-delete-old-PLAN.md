---
phase: 213-catalog-authz-relocate
plan: 02
type: execute
wave: 2
depends_on: ["213-01"]
files_modified:
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
  - backend/app/modules/auth/visibility.py
autonomous: true
requirements: [LAYER-02]
requirements_addressed: [LAYER-02]
tags: [refactor, layering, migration, open-core]

must_haves:
  truths:
    - "D-04: Every Python source under `backend/` that previously imported from `app.modules.auth.visibility` now imports from `app.modules.catalog.authorization`. No shim, no re-export."
    - "D-05: The file `backend/app/modules/auth/visibility.py` is DELETED (not stubbed, not emptied, not replaced with a re-export module)."
    - "D-06: No backward-compat aliases anywhere in the repo. After this plan, `from app.modules.auth.visibility import X` raises `ModuleNotFoundError` at import time — that is the intended terminal state and what ROADMAP SC#4's `git grep` zero-match assertion enforces."
    - "D-04: 22 module-level import sites (15 single-line + 7 multi-line blocks; the `domain/service.py:29` site is single-line per RESEARCH.md but RESEARCH.md also lists it under module-level — verify count via grep) and 4 function-scope deferred import sites are all rewritten to the new module path. Function-scope deferrals stay deferred — only the path changes."
    - "D-04: `git grep -nE \"^\\s*(from|import)\\s+app\\.modules\\.auth\\.visibility\" -- backend/` returns ZERO matches after this plan (closes ROADMAP SC#1 and SC#4)."
    - "D-12: RBAC behavior is preserved — full pytest suite (≥1999 passing per RESEARCH.md A2) stays green. No new tests are added; the existing corpus across search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox proves parity."
    - "Multi-line `from X import (\\n  A,\\n  B,\\n)` blocks are migrated by changing ONLY the `from X` path on line 1; the imported-names lines below are byte-unchanged (RESEARCH.md Pattern 3, CONTEXT.md \"Risk surfaces\")."
    - "Function-scope deferred imports in `platform/jobs/router.py` (lines 124, 254, 319) and `catalog/datasets/domain/service.py` (line 470) keep their deferral — Pitfall 2 (do NOT promote to module level)."
  artifacts:
    - path: "backend/app/modules/auth/visibility.py"
      provides: "DELETED — no longer exists after this plan"
      contains: "(file must not exist)"
    - path: "backend/app/modules/auth/dependencies.py"
      provides: "Auth dependency consuming get_user_roles from new path"
      contains: "from app.modules.catalog.authorization import get_user_roles"
    - path: "backend/app/modules/catalog/datasets/api/router_export.py"
      provides: "Largest multi-line import block migrated (4 names)"
      contains: "from app.modules.catalog.authorization import ("
    - path: "backend/app/platform/jobs/router.py"
      provides: "3 function-scope deferred imports rewritten to new path; deferrals preserved"
      contains: "from app.modules.catalog.authorization import"
  key_links:
    - from: "backend/app/modules/catalog/datasets/api/router.py"
      to: "backend/app/modules/catalog/authorization.py"
      via: "module-level multi-line import block"
      pattern: "from app\\.modules\\.catalog\\.authorization import \\("
    - from: "backend/app/platform/jobs/router.py"
      to: "backend/app/modules/catalog/authorization.py"
      via: "function-scope deferred imports (3 sites)"
      pattern: "from app\\.modules\\.catalog\\.authorization import"
---

<objective>
Mechanically migrate all 26 import lines across 23 files from `app.modules.auth.visibility` to `app.modules.catalog.authorization`, then delete `backend/app/modules/auth/visibility.py`, then run the full pytest suite to prove RBAC parity.

Purpose: This is the substantive content of LAYER-02. Plan 01 introduced the new module; Plan 02 wires every caller to it and removes the old file. After this plan, `git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns zero matches (closes ROADMAP SC#1 and SC#4), the old `auth/visibility.py` does not exist on disk (closes SC#1's deletion clause), and the full backend test suite stays green at ≥1999 passing (closes SC#3 — RBAC behavior preserved across search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox).

Output: 23 source files edited (26 import lines rewritten), 1 file deleted via `git rm`, full pytest suite re-run as the parity gate. The new module from Plan 01 is now load-bearing for the entire codebase.
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
@.planning/phases/213-catalog-authz-relocate/213-01-SUMMARY.md
@backend/app/modules/auth/visibility.py
@backend/app/modules/catalog/authorization.py

<interfaces>
<!-- Authoritative caller inventory verified by live grep 2026-04-27 (RESEARCH.md "Caller Inventory"). -->
<!-- Each entry: file:lineno - block shape - exact existing first-line of the import. -->

**Module-level imports (22 sites across 19 files):**

```
backend/app/modules/auth/dependencies.py:15            single-line  from app.modules.auth.visibility import get_user_roles
backend/app/modules/catalog/collections/router.py:16   single-line  from app.modules.auth.visibility import get_user_roles
backend/app/modules/catalog/collections/service.py:28  single-line  from app.modules.auth.visibility import apply_visibility_filter
backend/app/modules/catalog/datasets/api/router.py:28  multi-line   from app.modules.auth.visibility import (
backend/app/modules/catalog/datasets/api/router_data.py:23      multi-line   from app.modules.auth.visibility import (
backend/app/modules/catalog/datasets/api/router_export.py:26    multi-line   from app.modules.auth.visibility import (    [4-name block — largest]
backend/app/modules/catalog/datasets/api/router_metadata.py:22  multi-line   from app.modules.auth.visibility import (
backend/app/modules/catalog/datasets/api/router_vrt.py:19       single-line  from app.modules.auth.visibility import check_dataset_access
backend/app/modules/catalog/datasets/domain/service.py:29       single-line  from app.modules.auth.visibility import apply_visibility_filter
backend/app/modules/catalog/features/router.py:15      single-line  from app.modules.auth.visibility import check_dataset_access
backend/app/modules/catalog/maps/router.py:26          single-line  from app.modules.auth.visibility import get_user_roles
backend/app/modules/catalog/maps/service.py:20         single-line  from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
backend/app/modules/catalog/records/router.py:11       single-line  from app.modules.auth.visibility import get_user_roles
backend/app/modules/catalog/search/router.py:19        multi-line   from app.modules.auth.visibility import (
backend/app/modules/catalog/search/service.py:33       single-line  from app.modules.auth.visibility import apply_visibility_filter
backend/app/platform/sandbox/validator.py:18           single-line  from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
backend/app/processing/ai/router.py:42                 single-line  from app.modules.auth.visibility import get_user_roles
backend/app/processing/ai/service.py:33                single-line  from app.modules.auth.visibility import apply_visibility_filter
backend/app/processing/export/router.py:16             single-line  from app.modules.auth.visibility import check_dataset_access
backend/app/processing/ingest/service.py:20            single-line  from app.modules.auth.visibility import get_user_roles
backend/app/processing/tiles/router.py:21              single-line  from app.modules.auth.visibility import check_dataset_access, get_user_roles
backend/app/standards/ogc/router.py:11                 single-line  from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
```

That's 22 module-level lines (15 single-line + 7 multi-line block-starts). The 5 multi-line blocks are at:
- `catalog/datasets/api/router.py:28` (2 names)
- `catalog/datasets/api/router_data.py:23` (2 names)
- `catalog/datasets/api/router_export.py:26` (4 names — largest block)
- `catalog/datasets/api/router_metadata.py:22` (2 names)
- `catalog/search/router.py:19` (3 names)

**Function-scope (deferred) imports (4 sites across 2 files):**

```
backend/app/modules/catalog/datasets/domain/service.py:470   from app.modules.auth.visibility import get_user_roles
backend/app/platform/jobs/router.py:124                       from app.modules.auth.visibility import get_user_roles
backend/app/platform/jobs/router.py:254                       from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
backend/app/platform/jobs/router.py:319                       from app.modules.auth.visibility import get_user_roles
```

**Total: 26 import lines across 23 files.** Pre-edit live-count gate (Step 1 of Task 02-01) re-runs the grep to catch any post-discussion drift (Pitfall 1).

<!-- Two distinct edit patterns. -->

**Pattern A (single-line module-level + function-scope deferred):**
```diff
-from app.modules.auth.visibility import <names>
+from app.modules.catalog.authorization import <names>
```
Whitespace prefix (4 or 8 spaces for function-scope; none for module-level) is preserved exactly.

**Pattern B (multi-line block):**
ONLY the first line of the parenthesized block changes. The imported-names lines below are byte-unchanged.
```diff
-from app.modules.auth.visibility import (
+from app.modules.catalog.authorization import (
     check_dataset_access_or_anonymous,
     get_user_roles,
 )
```

The closing `)` is on its own line, untouched. The names inside the block are untouched. Use the `Edit` tool with `old_string` containing JUST the first line `from app.modules.auth.visibility import (` and `new_string` `from app.modules.catalog.authorization import (` — there are 5 instances of this exact `old_string` across the codebase (one per multi-line block); use `replace_all=true` if the Edit tool supports it, otherwise edit each file individually.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 02-01: Migrate all 26 caller import lines across 23 files</name>
  <files>backend/app/modules/auth/dependencies.py, backend/app/modules/catalog/collections/router.py, backend/app/modules/catalog/collections/service.py, backend/app/modules/catalog/datasets/api/router.py, backend/app/modules/catalog/datasets/api/router_data.py, backend/app/modules/catalog/datasets/api/router_export.py, backend/app/modules/catalog/datasets/api/router_metadata.py, backend/app/modules/catalog/datasets/api/router_vrt.py, backend/app/modules/catalog/datasets/domain/service.py, backend/app/modules/catalog/features/router.py, backend/app/modules/catalog/maps/router.py, backend/app/modules/catalog/maps/service.py, backend/app/modules/catalog/records/router.py, backend/app/modules/catalog/search/router.py, backend/app/modules/catalog/search/service.py, backend/app/platform/sandbox/validator.py, backend/app/platform/jobs/router.py, backend/app/processing/ai/router.py, backend/app/processing/ai/service.py, backend/app/processing/export/router.py, backend/app/processing/ingest/service.py, backend/app/processing/tiles/router.py, backend/app/standards/ogc/router.py</files>
  <read_first>
    - .planning/phases/213-catalog-authz-relocate/213-RESEARCH.md ("Caller Inventory" — full table of 26 sites; "Pattern 2" — single-line; "Pattern 3" — multi-line block migration; "Pattern 4" — deferred-import migration; Pitfall 1 — re-run grep before editing; Pitfall 2 — do NOT promote deferred imports in callers)
    - .planning/phases/213-catalog-authz-relocate/213-CONTEXT.md (D-04 — exact site list; D-06 — no backward-compat aliases; "Risk surfaces" — multi-line block shape preservation)
    - .planning/phases/213-catalog-authz-relocate/213-PATTERNS.md ("Caller migration — single-line", "multi-line", "deferred" sections with concrete diffs)
    - backend/app/modules/auth/visibility.py (still present after Plan 01 — confirm before editing callers)
    - backend/app/modules/catalog/authorization.py (the new target — exists from Plan 01)
    - backend/app/modules/catalog/datasets/api/router_export.py (the LARGEST block; read lines 23-32 to confirm the 4-name block shape before editing)
    - backend/app/platform/jobs/router.py (read lines 120-130, 250-260, 315-325 — the 3 deferred sites; confirm indentation depth and surrounding context before editing)
    - backend/app/modules/catalog/datasets/domain/service.py (read lines 25-35 for the module-level site at line 29 AND lines 465-475 for the deferred site at line 470 — TWO edits in this single file)
  </read_first>
  <action>
Edit each caller file. There are two distinct edit patterns; apply them mechanically.

**Step 0 — Re-run the grep gate (Pitfall 1, fail-safe before any edits):**

```bash
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/
```

Expected: exactly 26 matches across 23 files. Cross-check against the inventory above. If the count differs (e.g., a recent quick-task added a new caller), ADD the new site(s) to the migration sweep — do NOT skip them. If the count is lower than 26, that means a prior partial migration left the codebase in an inconsistent state — STOP and investigate before editing.

Also run the broader grep to surface any non-import references that might exist:
```bash
git grep -nE "auth\.visibility" -- backend/ ':!backend/tests/test_layering.py' ':!backend/app/modules/auth/visibility.py'
```

Expected: only the 26 import lines (no docstring or comment references; if any exist, document them in the SUMMARY but do not migrate them — Plan 03's broader architecture guard will catch any post-deletion non-import references that remain).

**Step 1 — Apply Pattern A to the 17 single-line sites (15 module-level + ... wait, the count is 22 module-level total, of which 15 are single-line and 7 are multi-line block-starts — let me re-state):**

Pattern A applies to: 15 single-line module-level sites + 4 function-scope deferred sites = 19 lines.
Pattern B applies to: 5 multi-line block-starts (router.py:28, router_data.py:23, router_export.py:26, router_metadata.py:22, search/router.py:19) — 5 first-line edits + 7 imported-names lines untouched (NOTE: the inventory says "22 sites, 15 unique single-line + 7 multi-import blocks"; some block-edits collapse to a single first-line edit each — the total module-level edit-LINE count is 15 + 5 = 20, plus 4 deferred = 24 lines edited, but 22 module-level *sites* because each multi-line block is one site even though it spans 4-5 file lines). The mathematically clean number to gate on is the BEFORE/AFTER `git grep` count: 26 first-line matches before, 0 after; 26 new-path matches after.

Actually, the cleanest gate is: `git grep -cE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns 26 BEFORE this task and 0 AFTER. `git grep -cE "^\s*(from|import)\s+app\.modules\.catalog\.authorization" -- backend/` returns 0 BEFORE this task (only Plan 01's new file exists, but that file does not import its own module) and 26 AFTER. **Use these two grep gates as the unambiguous numeric check.**

**Pattern A — single-line edits (apply to all 15 module-level single-line sites + 4 deferred sites = 19 edits):**

For each line, change ONLY the module path in the `from ... import` statement; the imported names are byte-unchanged. Use the Edit tool with `old_string` set to the EXACT existing line (including any leading whitespace for indented function-scope imports) and `new_string` identical except `auth.visibility` → `catalog.authorization`.

Examples (one per file shape — apply to every single-line site listed in inventory):

- `backend/app/modules/auth/dependencies.py:15` (no indent):
  ```diff
  -from app.modules.auth.visibility import get_user_roles
  +from app.modules.catalog.authorization import get_user_roles
  ```

- `backend/app/modules/catalog/maps/service.py:20` (two names, no indent):
  ```diff
  -from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
  +from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
  ```

- `backend/app/platform/jobs/router.py:124` (function-scope, deferred — indented; PRESERVE INDENTATION exactly; DO NOT promote to module level per Pitfall 2):
  ```diff
  -        from app.modules.auth.visibility import get_user_roles
  +        from app.modules.catalog.authorization import get_user_roles
  ```

- `backend/app/platform/jobs/router.py:254` (function-scope, two names — indented):
  ```diff
  -        from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
  +        from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
  ```

- `backend/app/modules/catalog/datasets/domain/service.py` has TWO edits in the same file: one module-level at line 29, one function-scope at line 470. They are independent — edit both. The line 470 edit preserves its function-scope indentation (Pitfall 2).

**Pattern B — multi-line block first-line edits (apply to 5 sites):**

For each multi-line block, edit ONLY the first line. The names inside the parenthesized block and the closing `)` are byte-unchanged.

- `backend/app/modules/catalog/datasets/api/router.py:28` (2 names):
  ```diff
  -from app.modules.auth.visibility import (
  +from app.modules.catalog.authorization import (
       check_dataset_access_or_anonymous,
       get_user_roles,
   )
  ```

- `backend/app/modules/catalog/datasets/api/router_export.py:26` (4 names — largest block):
  ```diff
  -from app.modules.auth.visibility import (
  +from app.modules.catalog.authorization import (
       apply_visibility_filter,
       check_dataset_access,
       check_dataset_access_or_anonymous,
       get_user_roles,
   )
  ```

The same pattern applies to `router_data.py:23`, `router_metadata.py:22`, and `search/router.py:19`. In each case, the Edit tool's `old_string` is the EXACT `from app.modules.auth.visibility import (` first line (no trailing names), and the `new_string` is `from app.modules.catalog.authorization import (` — 5 separate edits across 5 files.

**Hard constraints (from CONTEXT.md, RESEARCH.md, PATTERNS.md):**

1. Function-scope deferred imports STAY DEFERRED. Pitfall 2 explicitly forbids promoting them to module level — those deferrals exist for slow-import mitigation in `platform/jobs/router.py` and function-local helpers in `domain/service.py`, NOT for the auth-cycle reason. Only the module path changes; the import statement stays inside the function body.
2. Multi-line block shape MUST be preserved. The names lines and closing `)` are byte-unchanged. CONTEXT.md "Risk surfaces" warns that a naive `sed` over `import\s+X` would work because only the path on line 1 changes — but using the Edit tool with the full first line `from app.modules.auth.visibility import (` as `old_string` is the safest approach.
3. DO NOT add `from app.modules.catalog.authorization import ...` re-exports to ANY `__init__.py` (CONTEXT.md "Integration Points" / "Deferred Ideas").
4. DO NOT modify `backend/app/modules/auth/__init__.py` — it is a one-line docstring (`"""Auth module namespace."""`) and does not re-export `visibility` (verified by RESEARCH.md sources).
5. DO NOT modify `backend/app/modules/auth/visibility.py` in this task — Task 02-02 deletes it as the next step.
6. Test files do NOT import `app.modules.auth.visibility` directly (verified by RESEARCH.md "No test-file callers" — the test corpus exercises visibility through the FastAPI HTTP layer). DO NOT touch `backend/tests/` files in this task; if the grep at Step 0 finds a test-file caller (post-discussion drift), add it to the migration list and document the addition in the SUMMARY.
7. DO NOT touch `backend/alembic/env.py` — it does NOT import `app.modules.auth.visibility` (verified by RESEARCH.md "No alembic env.py caller"; Phase 212 had this surprise but Phase 213 does not).
8. Preserve any `# noqa: ...` comments on caller import lines exactly. (RESEARCH.md does not flag any such comments on `auth.visibility` import lines, but if present in any of the 26 lines, they must be carried over byte-for-byte.)
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && bash -c 'OLD=$(git grep -cE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/ | awk -F: "{s+=\$2} END {print s+0}"); NEW=$(git grep -cE "^\s*(from|import)\s+app\.modules\.catalog\.authorization" -- backend/ | awk -F: "{s+=\$2} END {print s+0}"); echo "old=$OLD new=$NEW"; test "$OLD" = "0" && test "$NEW" -ge "26"' && (cd backend && uv run ruff check app/) && (cd backend && uv run python -c "import app.modules.auth.dependencies; import app.modules.catalog.collections.router; import app.modules.catalog.datasets.api.router; import app.modules.catalog.datasets.api.router_export; import app.modules.catalog.search.router; import app.modules.catalog.maps.service; import app.platform.jobs.router; import app.processing.tiles.router; import app.standards.ogc.router; print('all_callers_import_ok')")</automated>
  </verify>
  <acceptance_criteria>
    - `git grep -cE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns 0 matches across all files (the old path is fully removed from import-shaped lines).
    - `git grep -cE "^\s*(from|import)\s+app\.modules\.catalog\.authorization" -- backend/` returns at least 26 matches across the 23 caller files (the new path is wired in everywhere).
    - `cd backend && uv run ruff check app/` exits 0 (no F401 unused-import or F821 undefined-name warnings introduced — proves every imported name resolves).
    - `cd backend && uv run python -c "import app.modules.auth.dependencies; import app.modules.catalog.collections.router; import app.modules.catalog.datasets.api.router; import app.modules.catalog.datasets.api.router_export; import app.modules.catalog.search.router; import app.modules.catalog.maps.service; import app.platform.jobs.router; import app.processing.tiles.router; import app.standards.ogc.router"` exits 0 — the 9 representative caller modules import cleanly under the new path.
    - `git diff backend/app/modules/auth/__init__.py` produces zero output (NOT modified).
    - `git diff backend/app/modules/catalog/__init__.py` produces zero output (NOT modified).
    - `git diff backend/app/modules/auth/visibility.py` produces zero output (still present, NOT modified — Task 02-02 deletes it).
    - `git diff backend/alembic/env.py` produces zero output (no alembic caller).
    - For each multi-line block, the imported-names lines are byte-unchanged. Spot-check via: `grep -A 3 "from app.modules.catalog.authorization import (" backend/app/modules/catalog/datasets/api/router_export.py` shows the 4 names `apply_visibility_filter`, `check_dataset_access`, `check_dataset_access_or_anonymous`, `get_user_roles` (one per line, indented as before) followed by a `)` line.
    - For each function-scope deferred site, the indentation is preserved and the import is still inside a function body. Spot-check via: `grep -B 1 "from app.modules.catalog.authorization import" backend/app/platform/jobs/router.py` — each match should show the indented import line (8 spaces) inside an `if`/function block, NOT at column 0.
  </acceptance_criteria>
  <done>
    All 26 caller import lines now reference `app.modules.catalog.authorization`. `git grep` confirms zero remaining `auth.visibility` import-shaped lines. Ruff check passes. The 9 representative caller modules import cleanly. Function-scope deferrals are preserved (Pitfall 2). Multi-line block shapes are preserved (CONTEXT.md "Risk surfaces"). The OLD file at `backend/app/modules/auth/visibility.py` still exists (Task 02-02 deletes it as the very next step).
  </done>
</task>

<task type="auto">
  <name>Task 02-02: Delete backend/app/modules/auth/visibility.py and run full pytest suite for parity gate</name>
  <files>backend/app/modules/auth/visibility.py</files>
  <read_first>
    - .planning/phases/213-catalog-authz-relocate/213-CONTEXT.md (D-05 — file deleted entirely; no shim, no re-export; D-06 — no backward-compat aliases)
    - .planning/phases/213-catalog-authz-relocate/213-RESEARCH.md (Pitfall 1 — re-run grep before deletion as fail-safe; Pitfall 7 — clear `__pycache__` after local file deletion)
    - .planning/phases/213-catalog-authz-relocate/213-VALIDATION.md ("Sampling Rate" — full suite is the parity gate; baseline ≥1999 passing)
    - backend/app/modules/auth/__init__.py (verify still single-line docstring; do NOT modify)
  </read_first>
  <action>
This task is a fail-safe gate, the deletion, the local-cache cleanup, and the full pytest run. Execute in order; STOP if any step fails.

**Step 1 — Re-run the grep gate from Task 02-01 (fail-safe; Pitfall 1):**

```bash
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/
```

Expected: zero output (exit code 1 from `git grep` = "no matches"). If this returns ANY matches, STOP — Task 02-01 is incomplete. Do not delete the file. Find the unmigrated site(s) and fix them.

Also run the broader grep that excludes the source file itself (which still contains its own module docstring):
```bash
git grep -nE "auth\.visibility" -- backend/ ':!backend/app/modules/auth/visibility.py' ':!backend/tests/test_layering.py'
```

Expected: zero output. If this returns matches, those are non-import references (e.g., comments, docstrings) that the import-shaped grep above missed — investigate each one and migrate it before proceeding to Step 2. (Plan 03's `test_no_auth_visibility_module_referenced` test will catch any such reference post-deletion, but it is cleaner to fix them here.)

**Step 2 — Delete the file via `git rm`:**

```bash
git rm backend/app/modules/auth/visibility.py
```

Per CONTEXT.md D-05, the file is deleted entirely — no shim, no re-export module, no replacement file. Using `git rm` (rather than plain `rm`) ensures the deletion is staged for the upcoming commit and visible in `git status`.

**Step 3 — Verify `auth/__init__.py` is unchanged:**

```bash
git diff backend/app/modules/auth/__init__.py
```

Expected: zero output. Per CONTEXT.md "Integration Points", `backend/app/modules/auth/__init__.py` is a single-line docstring (`"""Auth module namespace."""`) and does not re-export `visibility`; it stays as-is.

**Step 4 — Clear local stale `__pycache__` (Pitfall 7):**

```bash
find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

This is host-only hygiene. Stale `.pyc` files for the deleted module would let Python continue to resolve the old path locally, masking missed migrations. CI is unaffected (fresh checkout has no pycache).

**Step 5 — Verify the deletion was clean (the file is gone, no cache shadow):**

```bash
test ! -e backend/app/modules/auth/visibility.py
cd backend && uv run python -c "
import importlib
try:
    importlib.import_module('app.modules.auth.visibility')
except ModuleNotFoundError as e:
    print('expected_error:', e)
else:
    raise AssertionError('app.modules.auth.visibility should not be importable after deletion')
"
```

Expected: the first command exits 0, the second prints `expected_error: No module named 'app.modules.auth.visibility'` and exits 0. If the second command does NOT raise `ModuleNotFoundError`, the pycache cleanup in Step 4 was incomplete — re-run it.

**Step 6 — Run the full pytest suite (the RBAC parity gate; D-12 / VALIDATION.md "Phase gate"):**

```bash
docker compose exec api uv run pytest -m 'not perf' --tb=short -q 2>&1 | tee /tmp/213-02-pytest.log
```

(If `docker compose` is not available in the executor's environment, fall back to host-side: `cd backend && uv run pytest -m 'not perf' --tb=short -q`. The container path is preferred because `docker-compose.yml` exposes the live PostgreSQL/PostGIS test database; host-side pytest may skip or fail tests requiring DB connectivity. RESEARCH.md A2 establishes that the live test count is ≥1999 — this is the floor.)

Expected: zero failures, summary line shows `≥1999 passed`. The 1965 number in CONTEXT.md D-11 is the original restore floor; RESEARCH.md A2 documents that the live count rose to 1999 by Phase 212-04. If the count is between 1965 and 1999, that may indicate concurrent quick-tasks added or removed tests — investigate but do not block the phase.

If any test fails, classify by the failure mode:
- `ModuleNotFoundError: app.modules.auth.visibility` → Task 02-01 missed an import site. Re-run the Step 1 grep, find the orphan, fix it, re-run pytest. (Note: pycache shadowing in Step 4 may also produce this error; re-run Step 4 first.)
- `ImportError: cannot import name 'X'` from `app.modules.catalog.authorization` → Plan 01's public surface is malformed. Re-read Plan 01's task verification and fix the new module.
- `ModuleNotFoundError: app.modules.catalog.authorization` → Plan 01 was not committed. Confirm Plan 01 ran first.
- A test that previously passed now FAILS with an assertion error → real RBAC behavior regression introduced by the relocation. Review the function bodies in `catalog/authorization.py` against the deleted `auth/visibility.py` (use `git show HEAD~1:backend/app/modules/auth/visibility.py` to retrieve the deleted contents) and find the diff that drifted from "verbatim copy."

**Hard constraints:**

- After this task, `test ! -e backend/app/modules/auth/visibility.py` MUST be true.
- `git diff backend/app/modules/auth/__init__.py` MUST be empty (Step 3).
- No new files are introduced under `backend/app/modules/auth/` to compensate for the deletion (D-05 / D-06 — no shim, no re-export).
- Full pytest passes with ≥1999 passing (RESEARCH.md A2). Do NOT mark this task complete with any failing tests.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && test ! -e backend/app/modules/auth/visibility.py && bash -c 'git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/; test $? -eq 1' && (cd backend && uv run python -c "import importlib; assert False if importlib.util.find_spec('app.modules.auth.visibility') else True; print('module_gone')" 2>&1 | grep -q "module_gone\|None") && bash -c '(docker compose exec api uv run pytest -m "not perf" --tb=short -q 2>&1 || cd backend && uv run pytest -m "not perf" --tb=short -q 2>&1) | tee /tmp/213-02-pytest.log | tail -5 | grep -E "[0-9]+ passed"'</automated>
  </verify>
  <acceptance_criteria>
    - `test ! -e backend/app/modules/auth/visibility.py` exits 0 (file does not exist).
    - `git status` shows `deleted: backend/app/modules/auth/visibility.py` staged.
    - `git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns ZERO matches (combined gate over Pattern A and Pattern B from Task 02-01).
    - `git grep -nE "auth\.visibility" -- backend/ ':!backend/tests/test_layering.py'` returns ZERO matches (no non-import references survive — note the source file is no longer in the repo so its own docstring is gone).
    - `git diff backend/app/modules/auth/__init__.py` produces zero output.
    - `cd backend && uv run python -c "import importlib.util; assert importlib.util.find_spec('app.modules.auth.visibility') is None; print('gone')"` exits 0 with output `gone`.
    - The full pytest invocation (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q` OR host-fallback) exits 0; final summary line shows `≥1999 passed`. Capture the exact summary line in the SUMMARY.
    - Zero `ModuleNotFoundError: app.modules.auth.visibility` in the pytest output.
    - Zero `ImportError: cannot import name 'X' from 'app.modules.catalog.authorization'` in the pytest output.
  </acceptance_criteria>
  <done>
    `backend/app/modules/auth/visibility.py` is deleted (staged via `git rm`). The full pytest suite passes at ≥1999 passing — RBAC parity preserved across search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox per ROADMAP SC#3. ROADMAP SC#1 (zero `auth.visibility` import lines) and SC#4 (`git grep` returns zero matches across the repo) are satisfied. Plan 03 adds the regression guard.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan rewrites 26 import paths and deletes one file. Every changed call site continues to invoke the same 5 functions — `DatasetVisibility`, `apply_visibility_filter`, `get_user_roles`, `check_dataset_access`, `check_dataset_access_or_anonymous` — implemented by Plan 01's verbatim copy. The SEC-04 invariant is preserved at runtime: every dataset access path goes through the same shared helpers. The `auth → catalog` business-logic boundary that was previously crossed (visibility logic inside `auth/`) is REMOVED by this plan; the catalog domain now owns its own access rules.

| Boundary | Description |
|----------|-------------|
| `auth/` ↔ `catalog/` (BEFORE) | The audit's identified smell: `auth/visibility.py` reaches into `catalog/` (deferred `DatasetGrant` import). After this plan, this boundary is no longer crossed. |
| `catalog/` → `catalog/` (AFTER) | All 26 callers now depend on a peer file inside `catalog/`. No cross-domain import for visibility logic. The relocated module still imports `User, Role, UserRole` from `auth/` (correct direction; Phase 214 abstracts this). |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-213-04 | E (Elevation of Privilege) — RBAC bypass via missed import migration | All 26 caller sites | mitigate | Task 02-01 acceptance criteria gate on `git grep` count: 0 OLD-path matches AND ≥26 NEW-path matches. Ruff catches F821 (undefined name) on any caller that imports a name from a non-existent module. Task 02-02's full pytest run exercises every RBAC code path — any caller still pointing at the deleted module raises `ModuleNotFoundError` at collection time. The deletion-fail-safe in Task 02-02 Step 1 re-runs the grep before `git rm` to prevent a half-migrated state. |
| T-213-05 | T (Tampering) — silent drift in deferred-import call sites | `platform/jobs/router.py:124,254,319` and `domain/service.py:470` | mitigate | Pitfall 2 explicitly forbids promoting deferrals; only the path is rewritten. Acceptance criteria spot-check the indentation of each deferred site (8-space prefix preserved; import remains inside function body). Full pytest covers the jobs/datasets endpoints. |
| T-213-06 | I (Information disclosure) — multi-line block shape corruption | 5 multi-line block sites | accept | The `from X import (` first-line edit is mechanically simple; the names lines and closing `)` are byte-unchanged. Ruff parses the resulting Python and would report `SyntaxError` on a corrupted block. Full pytest collection would fail-fast on import. The window for this threat is sub-PR. |
| T-213-07 | INFO — temporary co-existence reduced to zero | (n/a — both plans run sequentially) | accept | After Task 02-02, only `catalog/authorization.py` exists. The Plan 01 → Plan 02 boundary is a single PR; production never sees the co-existence state. |
</threat_model>

<verification>
- `git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns ZERO matches (closes ROADMAP SC#1 and SC#4 partially; the broader SC#4 check is in Plan 04).
- `git grep -nE "^\s*(from|import)\s+app\.modules\.catalog\.authorization" -- backend/` returns ≥26 matches (every caller is wired to the new path).
- `test ! -e backend/app/modules/auth/visibility.py` exits 0 (the deletion is committed; ROADMAP SC#1's deletion clause is satisfied).
- `cd backend && uv run ruff check app/` exits 0 (no F401 / F821).
- The full pytest run (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q` or host-fallback) exits 0 with ≥1999 passing.
- `git diff backend/app/modules/auth/__init__.py` produces zero output.
- `git diff backend/app/modules/catalog/__init__.py` produces zero output.
- Sample multi-line block (`router_export.py:26`): `grep -A 5 "from app.modules.catalog.authorization import (" backend/app/modules/catalog/datasets/api/router_export.py` shows the 4 names plus closing `)` on consecutive lines, indentation byte-unchanged.
</verification>

<success_criteria>
- LAYER-02 substantively satisfied: `auth/visibility.py` is deleted; all 26 inbound callers resolve to `catalog/authorization.py`.
- ROADMAP SC#1: file is deleted, all imports migrated. (Plan 04 verifies the broader `auth.visibility` reference grep.)
- ROADMAP SC#3: full backend test suite stays green at ≥1999 passing — RBAC behavior across search/datasets/features/tiles/STAC/OGC/maps/collections/jobs/AI/export/ingest/sandbox is preserved.
- ROADMAP SC#4: `git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.visibility" -- backend/` returns zero matches. (Plan 04 broadens this gate via the architecture guard.)
- The `auth → catalog` cycle smell is gone (Plan 01's `DatasetGrant` promotion + Plan 02's caller migration together close the audit's §5 finding).
- No backward-compat shim or re-export remains (D-05, D-06).
</success_criteria>

<output>
After completion, create `.planning/phases/213-catalog-authz-relocate/213-02-SUMMARY.md` documenting:
- The exhaustive list of edited files with line numbers and the diff style applied (Pattern A vs Pattern B).
- The pre-edit grep count (should be 26) and post-edit grep count (should be 0 for old path, ≥26 for new path).
- Confirmation that `backend/app/modules/auth/visibility.py` was deleted via `git rm` and `git status` shows the deletion staged.
- The full pytest output (passed count, failed count, runtime — captured from `/tmp/213-02-pytest.log`). Confirm the count is ≥1999 (RESEARCH.md A2 floor).
- Any deviations from the plan (e.g., if a site was found that wasn't in the inventory, document the new site and the grep that surfaced it).
- Confirmation that Pitfall 2 was honored: the 4 deferred sites in `platform/jobs/router.py` and `catalog/datasets/domain/service.py` STILL have their imports inside function bodies (not promoted to module level).
</output>
</content>
</invoke>
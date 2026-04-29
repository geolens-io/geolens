---
phase: 212-core-settings-decouple
plan: 02
type: execute
wave: 2
depends_on: ["212-01"]
files_modified:
  - backend/app/core/persistent_config.py
  - backend/app/core/public_urls.py
  - backend/app/modules/settings/router.py
  - backend/alembic/env.py
  - backend/tests/test_hybrid_search.py
  - backend/tests/test_validation.py
  - backend/tests/test_persistent_config.py
  - backend/tests/test_ai_send_sample_values.py
  - backend/app/modules/settings/models.py
autonomous: true
requirements: [LAYER-01]
requirements_addressed: [LAYER-01]
tags: [refactor, layering, migration, alembic, open-core]

must_haves:
  truths:
    - "Every Python source under `backend/` that previously imported `AppSetting` from `app.modules.settings.models` now imports it from `app.core.db.models`."
    - "The file `backend/app/modules/settings/models.py` is deleted (no shim, no re-export — D-05)."
    - "`backend/alembic/env.py` registers `AppSetting` against `Base.metadata` via `import app.core.db.models  # noqa: F401` (D-04 + RESEARCH.md Pitfall 1)."
    - "`backend/app/core/persistent_config.py:30` and `backend/app/core/public_urls.py:14` no longer reference `app.modules.settings` — closing the audit's specific layering finding (LAYER-01)."
    - "PersistentConfig get/set/reset behavior, public URL precedence (request -> DB -> env), and settings router HTTP contract are unchanged at the wire level (verified by the smoke test slice in Task 02-02)."
  artifacts:
    - path: "backend/app/modules/settings/models.py"
      provides: "DELETED — no longer exists after this plan"
      contains: "(file must not exist)"
    - path: "backend/alembic/env.py"
      provides: "Alembic autogenerate model registration for `AppSetting` via the new module path"
      contains: "import app.core.db.models"
    - path: "backend/app/core/persistent_config.py"
      provides: "PersistentConfig registry consuming `AppSetting` from `app.core.db.models`"
      contains: "from app.core.db.models import AppSetting"
    - path: "backend/app/core/public_urls.py"
      provides: "Public URL resolver consuming `AppSetting` from `app.core.db.models`"
      contains: "from app.core.db.models import AppSetting"
  key_links:
    - from: "backend/app/core/persistent_config.py"
      to: "backend/app/core/db/models.py:AppSetting"
      via: "module-level import"
      pattern: "from app\\.core\\.db\\.models import AppSetting"
    - from: "backend/app/core/public_urls.py"
      to: "backend/app/core/db/models.py:AppSetting"
      via: "module-level import"
      pattern: "from app\\.core\\.db\\.models import AppSetting"
    - from: "backend/alembic/env.py"
      to: "backend/app/core/db/models.py"
      via: "side-effect import for Base.metadata registration"
      pattern: "import app\\.core\\.db\\.models"
---

<objective>
Migrate all 9 caller files to the new `app.core.db.models` import path, update `backend/alembic/env.py:22` to reference the new module (RESEARCH.md Pitfall 1 — without this, alembic fails at import once the old file is deleted), and delete `backend/app/modules/settings/models.py` (D-05). After this plan, `git grep "from app.modules.settings.models"` returns zero matches across `backend/`.

Purpose: This is the substantive content of LAYER-01. The audit's two specific findings (`core/persistent_config.py:30` and `core/public_urls.py:14`) are closed by the production-code edits; the alembic env.py edit prevents a `ModuleNotFoundError` at the next migration check; the test edits prevent collection-time `ImportError`s; deletion of the old file ensures no shim is left behind (D-05) and forces all imports through the new path.

Output: 8 files edited (4 production + alembic + 4 test files; one of those — `test_persistent_config.py` — gets 5 separate edits at lines 18, 942, 985, 1021, 1079) and 1 file deleted. After this plan, the per-task smoke test slice still passes (run as part of Task 02-02), and `git grep` confirms the migration is complete.
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
@.planning/phases/212-core-settings-decouple/212-CONTEXT.md
@.planning/phases/212-core-settings-decouple/212-RESEARCH.md
@.planning/phases/212-core-settings-decouple/212-VALIDATION.md
@.planning/phases/212-core-settings-decouple/212-01-SUMMARY.md
@backend/app/core/persistent_config.py
@backend/app/core/public_urls.py
@backend/app/modules/settings/router.py
@backend/alembic/env.py

<interfaces>
<!-- Authoritative caller inventory verified by re-running `git grep` on 2026-04-27. -->
<!-- Each entry: file:lineno - exact existing import statement. -->

Caller inventory (9 files, 12 import statements):

```
backend/alembic/env.py:22                      import app.modules.settings.models  # noqa: F401
backend/app/core/persistent_config.py:30       from app.modules.settings.models import AppSetting
backend/app/core/public_urls.py:14             from app.modules.settings.models import AppSetting
backend/app/modules/settings/router.py:33      from app.modules.settings.models import AppSetting
backend/tests/test_ai_send_sample_values.py:22 from app.modules.settings.models import AppSetting   (function-scope)
backend/tests/test_hybrid_search.py:24         from app.modules.settings.models import AppSetting
backend/tests/test_persistent_config.py:18     from app.modules.settings.models import AppSetting   (function-scope)
backend/tests/test_persistent_config.py:942    from app.modules.settings.models import AppSetting   (function-scope)
backend/tests/test_persistent_config.py:985    from app.modules.settings.models import AppSetting   (function-scope)
backend/tests/test_persistent_config.py:1021   from app.modules.settings.models import AppSetting   (function-scope)
backend/tests/test_persistent_config.py:1079   from app.modules.settings.models import AppSetting   (function-scope)
backend/tests/test_validation.py:221           from app.modules.settings.models import AppSetting   (function-scope)
```

<!-- The alembic env.py line is `import app.modules.settings.models  # noqa: F401` (a side-effect import for Base.metadata registration). It must become `import app.core.db.models  # noqa: F401`. NOT `from app.core.db.models import AppSetting` — the side-effect contract requires the bare `import` form. -->
<!-- All other 11 lines are `from app.modules.settings.models import AppSetting` and become `from app.core.db.models import AppSetting`. -->
<!-- Verified count: `grep -c "from app.modules.settings.models import AppSetting" backend/tests/test_persistent_config.py` = 5. -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 02-01: Migrate all 9 caller files to the new import path</name>
  <files>backend/app/core/persistent_config.py, backend/app/core/public_urls.py, backend/app/modules/settings/router.py, backend/alembic/env.py, backend/tests/test_hybrid_search.py, backend/tests/test_validation.py, backend/tests/test_persistent_config.py, backend/tests/test_ai_send_sample_values.py</files>
  <read_first>
    - .planning/phases/212-core-settings-decouple/212-RESEARCH.md (sections: Caller Inventory; Pitfall 1 — alembic env.py; Pitfall 5 — settings router self-import)
    - .planning/phases/212-core-settings-decouple/212-CONTEXT.md (D-04, D-05 — full migration with no shim)
    - backend/app/core/persistent_config.py (line 30 — module-level import; verify nothing else in this file references `app.modules.settings`)
    - backend/app/core/public_urls.py (line 14 — module-level import)
    - backend/app/modules/settings/router.py (line 33 — in-domain import; RESEARCH.md Pitfall 5)
    - backend/alembic/env.py (line 22 — `import app.modules.settings.models  # noqa: F401`; RESEARCH.md Pitfall 1)
    - backend/tests/test_persistent_config.py (5 separate import sites at lines 18, 942, 985, 1021, 1079 — count verified 2026-04-27 by `grep -c "from app.modules.settings.models import AppSetting" backend/tests/test_persistent_config.py` returning 5)
    - backend/tests/test_hybrid_search.py (line 24)
    - backend/tests/test_validation.py (line 221)
    - backend/tests/test_ai_send_sample_values.py (line 22)
  </read_first>
  <action>
Edit every caller file in `<files>` to swap the `AppSetting` import path from `app.modules.settings.models` to `app.core.db.models`. There are two distinct edit patterns.

**Pattern A — `from`-style import (applies to 11 of 12 lines):**

For every occurrence of `from app.modules.settings.models import AppSetting` (preserving any leading indentation), change it to `from app.core.db.models import AppSetting`. This is the diff:

```
-from app.modules.settings.models import AppSetting
+from app.core.db.models import AppSetting
```

Files where this pattern applies (line numbers from RESEARCH.md Caller Inventory; verify with `grep -n "from app.modules.settings.models import AppSetting" <file>` before editing each one):

- `backend/app/core/persistent_config.py` — 1 site at line 30 (module-level)
- `backend/app/core/public_urls.py` — 1 site at line 14 (module-level)
- `backend/app/modules/settings/router.py` — 1 site at line 33 (module-level; RESEARCH.md Pitfall 5 — this in-domain import MUST be migrated, do not skip on the assumption "same-module is fine," because Plan 02 deletes the old file)
- `backend/tests/test_hybrid_search.py` — 1 site at line 24 (module-level)
- `backend/tests/test_validation.py` — 1 site at line 221 (function-scope, indented)
- `backend/tests/test_persistent_config.py` — 5 sites at lines 18, 942, 985, 1021, 1079 (all function-scope, indented; the count is exact — `grep -c "from app.modules.settings.models import AppSetting" backend/tests/test_persistent_config.py` MUST equal 5 before AND `grep -c "from app.core.db.models import AppSetting" backend/tests/test_persistent_config.py` MUST equal 5 after)
- `backend/tests/test_ai_send_sample_values.py` — 1 site at line 22 (function-scope, indented)

**Pattern B — alembic side-effect import (applies to 1 line):**

For `backend/alembic/env.py:22`, the existing line is `import app.modules.settings.models  # noqa: F401` (it is a side-effect import that registers `AppSetting` into `Base.metadata` for autogenerate; RESEARCH.md Pitfall 1 — if this is missed, alembic raises `ModuleNotFoundError` at startup once the old file is deleted in Task 02-02). Change to:

```
-import app.modules.settings.models  # noqa: F401
+import app.core.db.models  # noqa: F401
```

Preserve the `# noqa: F401` comment exactly. Do NOT change to a `from` import — the side-effect contract requires the bare `import` form (alembic discovers tables by importing modules; `from X import Y` would import only the symbol, but `import X` registers `X` in `sys.modules` which is what alembic relies on for autogenerate detection through `Base.metadata`).

**Hard constraints:**

- Preserve the leading whitespace exactly. Function-scope imports inside test fixtures use 4 or 8 spaces; copy that indentation byte-for-byte (use the Edit tool with `old_string` containing the original indentation).
- Do NOT add `AppSetting` to `backend/app/core/db/__init__.py` `__all__` (RESEARCH.md Pitfall 2 / Anti-Patterns to Avoid). All callers import directly from `app.core.db.models`, never from `app.core.db`.
- Do NOT delete `backend/app/modules/settings/models.py` in this task — Task 02-02 does that as the final step, AFTER all imports are migrated. Deleting first risks pytest collection failures during incremental file edits.
- Do NOT touch `backend/tests/test_settings_router.py` — its line 130 is `from app.modules.settings import router as settings_router` which goes through `__init__.py` (which is empty/docstring-only per RESEARCH.md Caller Inventory), NOT through `models.py`, so it is unaffected (verified safe in RESEARCH.md "Indirect imports").
- Do NOT touch `backend/app/modules/settings/__init__.py` — it is a single-line docstring (`"""Settings module namespace."""`) and does not re-export `AppSetting`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && bash -c 'OLD=$(git grep -n "from app\.modules\.settings\.models import AppSetting" -- backend/ | wc -l | tr -d " "); ALEMBIC_OLD=$(git grep -n "^import app\.modules\.settings\.models" -- backend/alembic/env.py | wc -l | tr -d " "); NEW=$(git grep -n "from app\.core\.db\.models import AppSetting" -- backend/ | wc -l | tr -d " "); ALEMBIC_NEW=$(grep -c "^import app\.core\.db\.models" backend/alembic/env.py | tr -d " "); echo "old_from=$OLD old_alembic=$ALEMBIC_OLD new_from=$NEW new_alembic=$ALEMBIC_NEW"; test "$OLD" = "0" && test "$ALEMBIC_OLD" = "0" && test "$NEW" = "11" && test "$ALEMBIC_NEW" = "1"' && cd backend && uv run python -c "import app.core.persistent_config; import app.core.public_urls; from app.modules.settings import router as r; import app.core.db.models; print('imports_ok')" && uv run ruff check app/ tests/ alembic/</automated>
  </verify>
  <acceptance_criteria>
    - `git grep -n "from app\.modules\.settings\.models import AppSetting" -- backend/` returns ZERO matches (all 11 `from`-style sites migrated).
    - `git grep -n "import app\.modules\.settings\.models" -- backend/` returns ZERO matches (the alembic env.py side-effect import is migrated).
    - `git grep -n "from app\.core\.db\.models import AppSetting" -- backend/` returns exactly 11 matches across the 8 files (sum: persistent_config 1 + public_urls 1 + settings/router 1 + tests/test_hybrid_search 1 + tests/test_validation 1 + tests/test_persistent_config 5 + tests/test_ai_send_sample_values 1 = 11).
    - `grep -n "^import app\.core\.db\.models" backend/alembic/env.py` returns exactly 1 match (line 22) with the `# noqa: F401` comment preserved.
    - `cd backend && uv run python -c "import app.core.persistent_config; import app.core.public_urls; from app.modules.settings import router as r; import app.core.db.models"` exits 0 (the four importers resolve).
    - `cd backend && uv run ruff check app/ tests/ alembic/` exits 0 (no unused-import or undefined-name warnings introduced).
    - `git diff backend/app/core/db/__init__.py` shows zero changes (Pitfall 2 — must not be touched).
    - `git diff backend/tests/test_settings_router.py` shows zero changes (RESEARCH.md indirect imports — line 130's `from app.modules.settings import router` is unaffected).
    - `git diff backend/app/modules/settings/__init__.py` shows zero changes.
  </acceptance_criteria>
  <done>
    All 12 import sites across 8 files now reference `app.core.db.models`. The alembic side-effect import uses the `import app.core.db.models  # noqa: F401` form. `git grep "from app.modules.settings.models"` returns zero matches across `backend/`. The old file at `backend/app/modules/settings/models.py` is still present (Task 02-02 deletes it).
  </done>
</task>

<task type="auto">
  <name>Task 02-02: Delete backend/app/modules/settings/models.py and run smoke test slice</name>
  <files>backend/app/modules/settings/models.py</files>
  <read_first>
    - .planning/phases/212-core-settings-decouple/212-CONTEXT.md (D-05 — file is deleted entirely; no shim, no re-export)
    - .planning/phases/212-core-settings-decouple/212-RESEARCH.md (Pitfall 6 — stale `__pycache__` after local file deletion)
    - .planning/phases/212-core-settings-decouple/212-VALIDATION.md (Sampling Rate — per-task quick run command)
    - backend/app/modules/settings/__init__.py (verify it is still the single-line docstring; do NOT modify)
  </read_first>
  <action>
This task is a fail-safe gate, the deletion, and the per-task smoke test. Execute in order; STOP if any step fails.

**Step 1 — Re-run the gate from Task 02-01 locally (fail-safe):**

```bash
git grep -n "from app\.modules\.settings\.models import AppSetting" -- backend/
git grep -n "^import app\.modules\.settings\.models" -- backend/
```

Both commands MUST return zero output (exit code 1 from `git grep` = "no matches"). If either returns matches, STOP — Task 02-01 is incomplete. Do not delete the file. Find the unmigrated site and fix it (it almost certainly indicates Pitfall 1 — alembic env.py — was missed if `^import` returned a match).

**Step 2 — Delete the file via `git rm`:**

```bash
git rm backend/app/modules/settings/models.py
```

Per CONTEXT.md D-05, the file is deleted entirely — no shim, no re-export module left behind, no replacement file. Using `git rm` (rather than `rm`) ensures the deletion is staged for the upcoming commit and visible in `git status`.

**Step 3 — Verify `__init__.py` is unchanged:**

```bash
git diff backend/app/modules/settings/__init__.py
```

MUST return zero output. Per RESEARCH.md Caller Inventory, `backend/app/modules/settings/__init__.py` is a single-line docstring (`"""Settings module namespace."""`) and does not re-export `AppSetting`; it stays as-is.

**Step 4 — Clear local stale `__pycache__` (RESEARCH.md Pitfall 6):**

```bash
find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

This is host-only hygiene to prevent Python from resolving the deleted module from a `.pyc` cache. CI is unaffected (fresh checkout).

**Step 5 — Run the per-task smoke test slice (per VALIDATION.md "Sampling Rate / After every task commit"):**

```bash
cd backend && uv run pytest tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_hybrid_search.py tests/test_validation.py tests/test_ai_send_sample_values.py -x --tb=short
```

This confirms all migrated test files load AND the production importers (`persistent_config.py`, `public_urls.py`, `modules/settings/router.py`) import cleanly under pytest collection.

Expected: zero failures, zero collection errors. If any test fails with `ModuleNotFoundError: app.modules.settings.models`, Task 02-01 missed an import site — re-run the grep gate from Step 1, find the unmigrated file, fix it, and re-run this slice. If a test fails for any OTHER reason (assertion error, fixture error, real bug), that is a regression introduced by this phase and must be debugged before proceeding to Plan 03.

**Step 6 — Verify alembic env.py resolves with the new import:**

```bash
cd backend && uv run alembic check
```

Expected: either prints "No new upgrade operations." (the success case) OR fails ONLY with a database-connection error if the local DB is not running — but NOT with a `ModuleNotFoundError`. (A connection error here is acceptable for this task; Plan 04 runs `alembic check` against a live DB as part of the phase-gate verification.)

If you see `ModuleNotFoundError: app.modules.settings.models`, Pitfall 1 was missed — go back to Task 02-01, edit `backend/alembic/env.py:22`, and re-run.

**Hard constraints:**

- After this task, `test ! -e backend/app/modules/settings/models.py` MUST be true.
- `git diff backend/app/modules/settings/__init__.py` MUST be empty (Step 3).
- No new files are introduced under `backend/app/modules/settings/` to compensate for the deletion (D-05 — no shim, no re-export).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && test ! -e backend/app/modules/settings/models.py && bash -c 'git grep -n "app\.modules\.settings\.models" -- backend/; test $? -eq 1' && (cd backend && uv run pytest tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_hybrid_search.py tests/test_validation.py tests/test_ai_send_sample_values.py -x --tb=short -q)</automated>
  </verify>
  <acceptance_criteria>
    - `test ! -e backend/app/modules/settings/models.py` exits 0 (file does not exist).
    - `git status` shows `deleted: backend/app/modules/settings/models.py` staged.
    - `git grep -n "app\.modules\.settings\.models" -- backend/` returns ZERO matches (combined gate covering both Pattern A and Pattern B from Task 02-01).
    - `git diff backend/app/modules/settings/__init__.py` shows zero changes.
    - The smoke test slice (`pytest tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_hybrid_search.py tests/test_validation.py tests/test_ai_send_sample_values.py -x`) exits 0.
    - `cd backend && uv run alembic check` either exits 0 with "No new upgrade operations" or fails with a connection error (NOT a `ModuleNotFoundError`).
  </acceptance_criteria>
  <done>
    `backend/app/modules/settings/models.py` is deleted (staged via `git rm`). The smoke test slice passes. Alembic resolves the new module path successfully (no `ModuleNotFoundError`). The boundary repair surface is complete; Plan 03 adds the regression guard.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan moves an ORM-model import path across 9 files and deletes one file. The relocation is byte-equivalent at the database level — `__tablename__` and `__table_args__` are unchanged, so `Base.metadata` registers the same `(catalog, app_settings)` table identity as before. No new trust boundaries are introduced; an existing boundary (the `core/` ↔ `modules/settings/` layering line) is *enforced more strictly* by removing the inversion.

| Boundary | Description |
|----------|-------------|
| `core/` -> `modules/settings/` (BEFORE) | The audit's identified layering inversion: `core/persistent_config.py` and `core/public_urls.py` reach into a domain module for an ORM model. After this plan, this boundary is no longer crossed. |
| `core/` -> `core/db/` (AFTER) | All AppSetting consumers now depend on a peer file inside `core/`. Same trust level (both are core), no inversion. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-212-01 | T (Tampering) — stale-import / runtime ImportError | All 9 caller files + `backend/alembic/env.py` | mitigate | Task 02-01 acceptance criteria includes `git grep` gates for both the OLD path (zero matches) AND the NEW path (exactly 11 matches), plus a pytest collection check (`uv run pytest --collect-only` is implicit in the smoke slice) and a Python import smoke test (`python -c "import app.core.persistent_config; ..."`). Task 02-02 reruns the gate as a fail-safe before deletion and runs `alembic check` to surface Pitfall 1 (missed alembic env.py edit) loudly. |
| T-212-03 | INFO — no new external surface | `app_settings` table; settings HTTP routes; auth flows | accept | Table schema, API endpoint contracts, auth flows all unchanged. SQLAlchemy identifies tables by `__tablename__`+`__table_args__`, which are byte-identical between old and new module. No new attack surface is introduced by relocation. |
</threat_model>

<verification>
- `git grep -n "app\.modules\.settings\.models" -- backend/` returns ZERO matches (both Pattern A and Pattern B sites migrated).
- `git grep -nc "from app\.core\.db\.models import AppSetting" -- backend/` reports exactly 11 matches across the 8 files (the `import app.core.db.models` in alembic env.py is the 12th and final migrated site, counted by `grep -c "^import app\.core\.db\.models" backend/alembic/env.py` = 1).
- `test ! -e backend/app/modules/settings/models.py` succeeds.
- `cd backend && uv run pytest tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_hybrid_search.py tests/test_validation.py tests/test_ai_send_sample_values.py -x --tb=short` exits 0.
- `cd backend && uv run alembic check` exits 0 with "No new upgrade operations" (or a database-connection error in environments without a live DB; in CI / Plan 04, the live DB is used and this MUST succeed).
- `cd backend && uv run ruff check app/ tests/ alembic/` exits 0.
</verification>

<success_criteria>
- LAYER-01 (specifically the audit's two findings: `core/persistent_config.py:30` and `core/public_urls.py:14`) no longer reproduces — `git grep -n "from app\.modules\.settings" -- backend/app/core/` returns zero matches.
- The full caller inventory from RESEARCH.md (9 files, 12 sites) is migrated; the comprehensive `git grep` for the old path returns zero.
- The old file `backend/app/modules/settings/models.py` is deleted (D-05; no shim).
- The settings module's `__init__.py` is unchanged.
- The smoke test slice (PersistentConfig, settings router, admin endpoint, public URLs, hybrid search, validation, AI sample values) passes — preserving the "no behavior change" promise of CONTEXT.md.
- Alembic env.py resolves the new module successfully (Pitfall 1 mitigated).
</success_criteria>

<output>
After completion, create `.planning/phases/212-core-settings-decouple/212-02-SUMMARY.md` documenting:
- The exhaustive list of edited files with line numbers and the diff style applied (Pattern A vs Pattern B).
- Confirmation that `backend/app/modules/settings/models.py` was deleted via `git rm` and that `git status` shows the deletion staged.
- The smoke-slice pytest output (pass count, fail count, runtime).
- The `alembic check` output (success or connection error — NOT a `ModuleNotFoundError`).
- Any deviations from the plan (e.g., if a site was found that wasn't in the inventory, document the new site and the grep that surfaced it).
</output>

# Phase 212: core-settings-decouple - Research

**Researched:** 2026-04-26
**Domain:** Backend Python refactor (SQLAlchemy ORM model relocation, layering enforcement)
**Confidence:** HIGH

## Summary

Phase 212 is a mechanical Python-only refactor. The `AppSetting` SQLAlchemy ORM model moves from `backend/app/modules/settings/models.py` to a new `backend/app/core/db/models.py`; every importer in the repo updates its import path; the old file is deleted; and a CI-enforced architecture-guard test prevents the layering inversion from being reintroduced.

CONTEXT.md locked the approach: relocate (D-01), full migration with no shim (D-04, D-05), `git grep` based architecture-guard (D-06), `alembic check` as the no-migration proof (D-08), and the 1965-test baseline as the acceptance gate (D-09). All locked decisions remain valid given the codebase as it is today.

The most important new finding for the planner: **the actual caller inventory is 9 files (not the 5 listed in CONTEXT.md)**. CONTEXT.md missed `backend/alembic/env.py` (the autogenerate registration import), `backend/tests/test_persistent_config.py` (5 separate import sites), and `backend/tests/test_ai_send_sample_values.py`. CONTEXT.md's D-04 explicitly anticipated this ("Any other imports surfaced by `grep ...` during planning — planner must run this grep and migrate every hit"); this research did the grep and the planner now has the full list. There is also one indirect importer — `backend/tests/test_settings_router.py:130` does `from app.modules.settings import router as settings_router`, which goes through `__init__.py`, not `models.py`, so it is unaffected by this phase.

**Primary recommendation:** Execute the relocation in 4 atomic commits — (1) introduce `core/db/models.py` containing `AppSetting` (no callers changed yet, both old and new modules export the same class until commit 2 lands; technically possible to skip this transitional state but it makes the diff easier to review); (2) migrate all 9 caller files in one pass + delete `backend/app/modules/settings/models.py`; (3) update `backend/alembic/env.py` line 22 to reference the new module path; (4) add `backend/tests/test_layering.py` with a `subprocess.run(["git", "grep", ...])` guard. Verify with full pytest and `cd backend && uv run alembic check`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `AppSetting` ORM definition | Backend / `app.core.db` | — | DB-backed configuration is a core platform concern (used by `core/persistent_config.py` and `core/public_urls.py`); per audit, `core/` must own it rather than depend on `modules/settings/`. |
| `app_settings` table schema | Database (PostgreSQL `catalog` schema) | Alembic migrations | Table identity is by `__tablename__`+`__table_args__`, not Python module path. No DB changes in this phase. |
| Settings HTTP routes (GET/PUT `/settings/`) | Backend / `app.modules.settings` | — | The router stays in `modules/settings/`; only its import of `AppSetting` changes. |
| Layering-rule enforcement | Backend / `tests/test_layering.py` | CI workflow | Pytest-runnable static check (no runtime side effects). |

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Relocate `AppSetting` SQLAlchemy model from `backend/app/modules/settings/models.py` to a new `backend/app/core/db/models.py`. Do NOT introduce a `ConfigProvider` Protocol — the alternative was rejected.
- **D-02:** `core/db/models.py` is a new file. It holds `AppSetting` only at this phase. No pre-emptive moves of other models.
- **D-03:** The `app_settings` table schema is unchanged (`schema="catalog"`, `key TEXT PK`, `value JSONB NOT NULL`). The Python class moves; the table does not.
- **D-04:** Migrate ALL callers in one shot. No backward-compat re-export shim in `modules/settings/models.py`.
- **D-05:** `backend/app/modules/settings/models.py` is **deleted** entirely (no shim, no re-export).
- **D-06:** Add a regression guard test under `backend/tests/test_layering.py` that asserts `core/` never imports from `modules/settings/` (and ideally never from `modules/<anything>` at module-import time).
- **D-07:** The guard test SHOULD be skippable in dev (`pytest -m architecture` opt-out path) but MUST run in CI.
- **D-08:** No Alembic migration is generated. Proof: run `cd backend && uv run alembic check` and confirm "no new operations."
- **D-09:** The 1965-test backend baseline is the acceptance gate. Plan must include a full `pytest` run.
- **D-10:** Frontend has no involvement. The settings router's HTTP contract is unchanged.

### Claude's Discretion

- Exact filename: `core/db/models.py` (audit's wording, aligns with SQLAlchemy convention) vs. `core/db/app_settings.py`. Use `core/db/models.py` unless there's a strong reason otherwise.
- Exact form of the architecture guard test: `subprocess git grep` vs. AST walk vs. import-graph library. Pick `subprocess git grep` (simplest) unless there's a strong reason to do otherwise.
- Commit decomposition — likely 3–4 atomic commits. Planner may collapse or split as appropriate.

### Deferred Ideas (OUT OF SCOPE)

- `ConfigProvider` Protocol in core (the audit's second option — explicitly rejected for v13.1).
- Generalizing `core/db/models.py` for other catalog models (scope creep into Phase 213's territory).
- Splitting `persistent_config.py` (680 lines, worth a tidy-up but not this phase).
- OpenAPI/SDK regeneration (happens in Phase 215).
- Any frontend work.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LAYER-01 | `core/persistent_config.py` and `core/public_urls.py` no longer import `AppSetting` from `modules/settings`. | Verified both import sites (`persistent_config.py:30`, `public_urls.py:14`); discovered 7 additional callers across tests + alembic env (see Caller Inventory). All migrate to `from app.core.db.models import AppSetting`. |

## Project Constraints (from CLAUDE.md)

The repo CLAUDE.md (root) is empty/missing — only the user-global `~/.claude/CLAUDE.md` applies. Active directives for this phase:

- **Version control:** Never indicate AI/Bot activity in commit messages.
- **Code style:** Prefer simple, readable code over clever abstractions. Follow existing project conventions when editing files. (D-01's rejection of a `ConfigProvider` Protocol is consistent with this.)
- **Communication:** Direct and concise; ask before assuming.

From auto-memory `MEMORY.md`:
- Backend stack: FastAPI + SQLAlchemy + asyncpg + Alembic; tests via `docker compose exec api uv run pytest`.
- 1.0.0 public release shipped 2026-04-01; baseline test count 1965 restored 2026-04-26 by quick task `260425-sl1`.
- Active milestone: v13.1 Open-Core Separation P1.

## Caller Inventory (Comprehensive)

This is the authoritative migration list — **9 files, 14 import statements**. CONTEXT.md's D-04 listed 5 sites; this research found 4 more (alembic env, test_persistent_config with 5 sites, test_ai_send_sample_values, plus 4 additional sites within test_persistent_config that CONTEXT.md grouped under one). All must migrate.

### Production code (3 files)

| File:Line | Import statement | Notes |
|-----------|------------------|-------|
| `backend/app/core/persistent_config.py:30` | `from app.modules.settings.models import AppSetting` | The primary target of LAYER-01. Module-level import. |
| `backend/app/core/public_urls.py:14` | `from app.modules.settings.models import AppSetting` | The other primary target. Module-level import. |
| `backend/app/modules/settings/router.py:33` | `from app.modules.settings.models import AppSetting` | In-domain caller — also migrated to `core.db.models` (per D-04). |

### Alembic registration (1 file)

| File:Line | Import statement | Notes |
|-----------|------------------|-------|
| `backend/alembic/env.py:22` | `import app.modules.settings.models  # noqa: F401 -- register models for autogenerate` | **NOT in CONTEXT.md's D-04 list.** Must be updated to `import app.core.db.models  # noqa: F401`. Without this update, `alembic check` will lose the table from `Base.metadata` and erroneously report a deletion. **CRITICAL — must not be missed.** |

### Test files (5 files, 9 import statements)

| File:Line | Import statement | Notes |
|-----------|------------------|-------|
| `backend/tests/test_hybrid_search.py:24` | `from app.modules.settings.models import AppSetting` | Module-level import. Used at lines 103, 122, 126, 348, 352, 385. |
| `backend/tests/test_validation.py:221` | `from app.modules.settings.models import AppSetting` | Function-scoped deferred import. Used at lines 227, 248. |
| `backend/tests/test_persistent_config.py:18` | `from app.modules.settings.models import AppSetting` | Function-scoped (in `_clean_settings` autouse fixture). Used at line 21. |
| `backend/tests/test_persistent_config.py:942` | `from app.modules.settings.models import AppSetting` | Function-scoped. **NOT in CONTEXT.md's D-04 list.** |
| `backend/tests/test_persistent_config.py:985` | `from app.modules.settings.models import AppSetting` | Function-scoped. **NOT in CONTEXT.md's D-04 list.** |
| `backend/tests/test_persistent_config.py:1021` | `from app.modules.settings.models import AppSetting` | Function-scoped. **NOT in CONTEXT.md's D-04 list.** |
| `backend/tests/test_persistent_config.py:1079` | `from app.modules.settings.models import AppSetting` | Function-scoped. **NOT in CONTEXT.md's D-04 list.** |
| `backend/tests/test_ai_send_sample_values.py:22` | `from app.modules.settings.models import AppSetting` | Function-scoped (in `_clean_settings` autouse fixture). **NOT in CONTEXT.md's D-04 list.** Used at line 25. |

### Indirect imports (verified safe — no migration needed)

| File:Line | Import statement | Notes |
|-----------|------------------|-------|
| `backend/tests/test_settings_router.py:130` | `from app.modules.settings import router as settings_router` | Imports the `router` module via `app.modules.settings.__init__` (which is empty docstring only). Does NOT touch `models.py`. **Safe — no change required.** |

### Settings module `__init__.py`

`backend/app/modules/settings/__init__.py` contains only `"""Settings module namespace."""`. It does NOT re-export `AppSetting`, so removing `models.py` does not break any `from app.modules.settings import AppSetting` style import (none exist anyway — verified by `grep -rn "from app.modules.settings import.*AppSetting"` returning zero hits).

[VERIFIED: `grep -rn "from app.modules.settings.models\|app.modules.settings import\|app.modules.settings.AppSetting" backend/` 2026-04-26]

## Standard Stack

### Core (already installed; this phase adds no dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.25+ | ORM, declarative base | The repo's `Base` lives at `backend/app/core/db/session.py:29`. `AppSetting(Base)` is unchanged — only its file location moves. `__tablename__` + `__table_args__` are SQLAlchemy's identity for autogenerate, not module path. [VERIFIED: SQLAlchemy 2.0 docs] |
| Alembic | 1.13.0+ | Migrations + autogenerate diff | `alembic check` (introduced Alembic 1.9, available in installed 1.13.0+) reports pending autogenerate operations without writing a file — perfect for D-08's no-migration proof. [VERIFIED: `cd backend && uv run alembic --help` 2026-04-26 shows `check` subcommand] |
| pytest | 9.0.3+ | Test runner | Existing 1965-test baseline. New `test_layering.py` lives here. |

### No new packages required.

This is a pure relocation refactor.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ BEFORE                                                              │
│                                                                     │
│  app.core.persistent_config ─┐                                      │
│                               ├──► app.modules.settings.models ──► AppSetting
│  app.core.public_urls ───────┘    (LAYERING INVERSION)              │
│                                                                     │
│  app.modules.settings.router ────► app.modules.settings.models      │
│  backend/alembic/env.py ────────►  app.modules.settings.models      │
│  tests/test_*.py ───────────────►  app.modules.settings.models      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ AFTER                                                               │
│                                                                     │
│  app.core.db.session.Base ◄──── app.core.db.models.AppSetting       │
│                                                                     │
│  app.core.persistent_config ─┐                                      │
│                               ├──► app.core.db.models ──► AppSetting│
│  app.core.public_urls ───────┘    (CLEAN: core depends on core)     │
│                                                                     │
│  app.modules.settings.router ────► app.core.db.models               │
│  backend/alembic/env.py ────────►  app.core.db.models               │
│  tests/test_*.py ───────────────►  app.core.db.models               │
│                                                                     │
│  app.modules.settings.models  ◄── DELETED                           │
│                                                                     │
│  tests/test_layering.py: subprocess git grep guard                  │
│   asserts: backend/app/core/ has zero `from app.modules.<X>` imports│
└─────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
backend/
├── app/
│   ├── core/
│   │   └── db/
│   │       ├── __init__.py        # already re-exports Base, async_session, engine
│   │       ├── session.py         # holds Base, engine, async_session
│   │       └── models.py          # NEW (this phase) — AppSetting only
│   └── modules/
│       └── settings/
│           ├── __init__.py        # unchanged (docstring only)
│           ├── router.py          # import path updated only
│           ├── schemas.py         # unchanged
│           └── models.py          # DELETED (D-05)
├── alembic/
│   └── env.py                     # line 22 updated to import core.db.models
└── tests/
    ├── test_layering.py           # NEW (this phase) — git grep guard
    ├── test_hybrid_search.py      # import path updated
    ├── test_validation.py         # import path updated
    ├── test_persistent_config.py  # 5 import paths updated
    └── test_ai_send_sample_values.py  # import path updated
```

### Pattern 1: Relocate-only ORM model file

**What:** Move a `Base` subclass to a new module, keep table schema identical, update all `import` statements.
**When to use:** When the model lives in the wrong layer/package and you want the relocation to be a Python-only no-op for the database.
**Example (the new file):**
```python
# backend/app/core/db/models.py
# Source: existing backend/app/modules/settings/models.py (verbatim, only file path differs)
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base  # NOTE: same Base, no re-import path change


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": "catalog"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
```

[CITED: `backend/app/modules/settings/models.py` lines 1–13]

### Pattern 2: Architecture guard via subprocess `git grep`

**What:** A pytest test that shells out to `git grep` to assert a specific import pattern is absent from a directory.
**When to use:** When you need a CI-enforced layering rule that is fast (~50ms) and explicit about what it forbids.
**Example:**
```python
# backend/tests/test_layering.py
"""Layering rules: core/ must not depend on modules/.

Enforces the open-core boundary that v13.1 Phase 212 established. If this test
fails, a `from app.modules.<anything>` import was introduced in `backend/app/core/`,
which violates the rule that modules depend on core, not the reverse.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.architecture
def test_core_does_not_import_from_modules() -> None:
    """`backend/app/core/` must never import from `app.modules.*`."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"^\s*(from|import)\s+app\.modules\.",
            "--",
            "backend/app/core/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:  # git grep returns 0 when matches found
        pytest.fail(
            "Layering violation: backend/app/core/ contains the following "
            "imports from app.modules.* (modules must depend on core, not the "
            "reverse):\n" + result.stdout
        )
    if result.returncode not in (0, 1):  # 1 = no matches; anything else = git error
        pytest.fail(f"git grep failed: rc={result.returncode}\n{result.stderr}")
```

Register the marker in `pyproject.toml` under `[tool.pytest.ini_options]` `markers`:
```toml
markers = [
    "perf: ...",
    "requires_ogr2ogr: ...",
    "architecture: layering / boundary tests; opt-out with `-m 'not architecture'` for fast local TDD",
]
```

[VERIFIED: `pyproject.toml` markers section at line 75–78; new marker is additive.]

### Anti-Patterns to Avoid

- **Leave a re-export shim in `modules/settings/models.py`** — explicitly forbidden by D-05. The repo is closed-set; a one-shot migration with no shim is the convention (CONTEXT.md "Established Patterns").
- **Add `AppSetting` to `core/db/__init__.py` re-exports** — D-04 says callers import from `core.db.models` directly. Adding it to `__init__.py` would create a second import path that the guard test would have to special-case.
- **Pre-emptively move other ORM models to `core/db/models.py`** — D-02 explicitly forbids this scope creep.
- **Forget to update `backend/alembic/env.py:22`** — the import there exists solely to register `AppSetting` into `Base.metadata` for autogenerate. If the line still says `import app.modules.settings.models` after `models.py` is deleted, alembic env will `ImportError` on startup.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting dead/missing imports | Custom AST scanner | Existing `ruff check` (already in CI at `.github/workflows/ci.yml:70`) | Ruff's F401/F821 will catch missed import-path updates as hard errors before merge. CONTEXT.md "Established Patterns" notes this is the project's existing safety net. |
| Layering enforcement | Custom AST walker, `importlab`, `import-graph` | `subprocess.run(["git", "grep", ...])` (D-06) | One-line, no new dependency, faster than AST walk for a 100k-LOC repo, output format is already self-explanatory in failure messages. |
| Verifying no schema drift after the move | Generate a real migration and inspect the diff | `alembic check` (D-08) | Built-in subcommand (verified available in installed alembic 1.13.0+). Reports zero pending operations when `Base.metadata` matches the live DB. Generates no file. |
| Multi-import-statement migration | A custom `sed` script | A single `Edit`/`Read`+`Write` pass per file (9 files total) | The set is small and bounded; manual edits are auditable in the commit diff. |

**Key insight:** This phase is deliberately mechanical. Every "we could automate this" temptation either has an existing tool (ruff, alembic, git grep) or is too small to be worth automating (9 files).

## Runtime State Inventory

> Phase 212 is a Python-only refactor with no DB changes. The relocation does NOT alter runtime state — but the canonical questions deserve explicit answers.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | None — `app_settings` table identity is `(catalog, app_settings)` per `__tablename__`+`__table_args__`, not the Python module path. Existing rows persist verbatim. | None. The 16 PersistentConfig instances continue reading their existing rows. |
| **Live service config** | None. The settings HTTP API (`/settings/`, `/settings/all/`, `/settings/reset/`, etc.) is unchanged at the wire level. | None. Frontend continues hitting the same endpoints with the same payload shape (D-10). |
| **OS-registered state** | None. No systemd / pm2 / Task Scheduler / launchd registrations reference Python module paths. | None. |
| **Secrets and env vars** | None. `JWT_SECRET_KEY`, `GEOLENS_ADMIN_USERNAME`, etc. are set via env, not via `app_settings` rows; relocation does not change env-var names or shapes. | None. |
| **Build artifacts / installed packages** | `backend/.venv/` and `backend/__pycache__/` will contain stale `.pyc` references to `app.modules.settings.models` after the file is deleted. These regenerate on next import; no manual cleanup required, but if local devs hit weird `ImportError` issues, `find backend -name __pycache__ -exec rm -rf {} +` is the workaround. | None for CI (clean checkout). Note in plan: "if any local pytest run fails strangely, clear `__pycache__/`." |

**Canonical question:** *After every file in the repo is updated, what runtime systems still have the old string cached, stored, or registered?* Answer: **nothing**. SQLAlchemy identifies tables by `__tablename__`+`__table_args__`, not import path; alembic's `Base.metadata` repopulates on next env.py import (which we update); the JSONB scalar-wrapping convention (`{"v": value}` for non-dict scalars; persistent_config.py:189–193 / unwrap at 152–154) is logic-only and not affected.

## Common Pitfalls

### Pitfall 1: Forgetting `backend/alembic/env.py:22`

**What goes wrong:** After deleting `backend/app/modules/settings/models.py` (D-05), alembic env.py's `import app.modules.settings.models  # noqa: F401` raises `ModuleNotFoundError`. Every alembic invocation fails — `alembic check`, `alembic upgrade head`, `alembic revision`. CI breaks loudly but late.
**Why it happens:** CONTEXT.md's D-04 caller list omits `backend/alembic/env.py`. A planner taking D-04 as exhaustive would miss it.
**How to avoid:** Treat `alembic env.py` as a first-class caller. The plan must explicitly include "update `backend/alembic/env.py:22` from `import app.modules.settings.models` to `import app.core.db.models`."
**Warning signs:** First `alembic check` after refactor returns non-zero with `ModuleNotFoundError` (not a schema diff).

### Pitfall 2: `__init__.py` re-export drift

**What goes wrong:** Adding `AppSetting` to `backend/app/core/db/__init__.py` for "convenience." Now there are two import paths (`from app.core.db import AppSetting` and `from app.core.db.models import AppSetting`); the guard test only forbids `from app.modules.settings`, so future code can drift to either path.
**Why it happens:** SQLAlchemy convention is sometimes to re-export at package level. CONTEXT.md "Reusable Assets" explicitly says **no** re-export of `AppSetting` at the package level.
**How to avoid:** Leave `backend/app/core/db/__init__.py` exactly as it is today (`__all__ = ["Base", "async_session", "engine"]`). The new file is `core/db/models.py`; callers do `from app.core.db.models import AppSetting`.
**Warning signs:** `git diff backend/app/core/db/__init__.py` shows changes — it shouldn't.

### Pitfall 3: `alembic check` reports a diff

**What goes wrong:** `cd backend && uv run alembic check` reports pending autogenerate operations on `app_settings`. Common causes: (a) the `__table_args__` dict was changed accidentally; (b) the `key`/`value` column types differ; (c) a missing import in the new module forgot to evaluate `Base` registration.
**Why it happens:** The new `models.py` was hand-written rather than copy-pasted from the old one.
**How to avoid:** Copy the old file's body verbatim. The only line that may differ is the `Base` import comment — `from app.core.db import Base` is unchanged.
**Warning signs:** `alembic check` exit code != 0 with output like `"Detected operations: AddColumn / DropTable"`.

### Pitfall 4: The architecture guard test fires inside the test environment of a fresh clone

**What goes wrong:** `subprocess.run(["git", "grep", ...])` requires a `.git/` directory. CI runs from a fresh `actions/checkout@v4` (which produces `.git/`), so this is fine on CI. But Docker container test runs (`docker compose exec api uv run pytest`) may run from a path where `.git/` was excluded by `.dockerignore`.
**Why it happens:** Project's `.dockerignore` may exclude `.git/`. [Not verified — planner should check `cat .dockerignore`.]
**How to avoid:** (a) Have the test detect missing `.git/` and `pytest.skip` (preferred — keeps `make test` working in containers). (b) Use a glob-walk fallback when git is unavailable. (c) Mark with `@pytest.mark.architecture` and exclude from container `pytest` invocations.
**Warning signs:** `git grep: not a git repository` in `make test` output.
**Recommended pattern** (minimal addition to the example in Pattern 2 above):
```python
def _has_git_metadata() -> bool:
    return (REPO_ROOT / ".git").exists()


@pytest.mark.architecture
def test_core_does_not_import_from_modules() -> None:
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    # ... existing body
```

### Pitfall 5: Settings router's existing import shape

**What goes wrong:** `backend/app/modules/settings/router.py:33` is `from app.modules.settings.models import AppSetting`. A naive find/replace might leave it dangling because the file is **inside** `modules/settings/`. The migration is mechanical but not "core only" — D-04 explicitly says the router migrates too.
**Why it happens:** Easy to assume "I'm fixing the cross-module import; same-module imports are fine." But D-05 deletes `models.py`, so the in-module relative import fails too.
**How to avoid:** Treat the migration as "every file that names `app.modules.settings.models`," not "every file in `app.core/`."
**Warning signs:** Test failures in `test_settings_admin.py`, `test_settings_router.py` with `ModuleNotFoundError: app.modules.settings.models`.

### Pitfall 6: Stale `__pycache__` after local file deletion

**What goes wrong:** Local pytest run after refactor: tests pass weirdly because `__pycache__/models.cpython-313.pyc` for the old module is still resolvable on Python's importlib path.
**Why it happens:** Python sometimes resolves `__pycache__/<module>.pyc` even when the source `.py` is deleted (rare but documented).
**How to avoid:** First test run after the refactor: `find backend -type d -name __pycache__ -exec rm -rf {} +` (or `make clean` if defined). CI is unaffected (fresh checkout).
**Warning signs:** Local tests pass but CI fails with `ModuleNotFoundError`.

## Code Examples

### The new file (verbatim copy from the old)
```python
# backend/app/core/db/models.py
# Source: backend/app/modules/settings/models.py (current location, this phase relocates it)
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": "catalog"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
```

### The single-import-statement diff applied to all 9 caller files
```diff
-from app.modules.settings.models import AppSetting
+from app.core.db.models import AppSetting
```

### `backend/alembic/env.py` diff (line 22)
```diff
-import app.modules.settings.models  # noqa: F401
+import app.core.db.models  # noqa: F401
```

### Verification commands
```bash
# 1. Confirm no remaining caller of the old path
cd /Users/ishiland/Code/geolens
grep -rn "from app.modules.settings.models\|app.modules.settings.models" backend/ \
  --exclude-dir=__pycache__ --exclude-dir=.venv --exclude="*.pyc"
# Expected: no matches

# 2. Confirm no core->modules imports remain
grep -rn "^\s*\(from\|import\)\s\+app\.modules" backend/app/core/
# Expected: no matches

# 3. Verify alembic sees no schema diff
cd /Users/ishiland/Code/geolens/backend && uv run alembic check
# Expected: "No new upgrade operations detected." (or equivalent zero-diff message)

# 4. Run full backend test suite
docker compose exec api uv run pytest -v --tb=short
# Expected: 1965 passed (the existing baseline)

# 5. Linting / format
cd /Users/ishiland/Code/geolens/backend && uv run ruff check . && uv run ruff format --check .
# Expected: zero errors
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `models.py` per domain module owns all that domain's ORM | Domain-owned `models.py` for domain-specific models; `core/db/models.py` for cross-cutting / platform-level models that core depends on | This phase (Phase 212) | Aligns with the open-core boundary: code that core depends on lives in core. |
| Layering enforcement via "I'll-just-trust-reviewers" | Layering enforcement via CI-runnable architecture-guard test | This phase (D-06) | Audit's §5 finding stops being silently re-introducible. |

**Deprecated/outdated:**
- `backend/app/modules/settings/models.py` — deleted entirely. No shim retained per D-05.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `.dockerignore` excludes `.git/`, so the architecture test must skip when run inside the api container. | Pitfall 4 | Test fails with "not a git repository" inside `docker compose exec api uv run pytest`. **Mitigation:** the recommended `_has_git_metadata()` skip already handles either case — assumption is irrelevant if planner uses the recommended pattern. [ASSUMED] — planner should `cat .dockerignore` to confirm and adjust. |
| A2 | The 1965-test baseline is exactly the current count; relocation introduces zero new test failures. | D-09 / Step 5 | If the baseline drifts during research (e.g., another quick task lands), the plan needs to re-baseline before claiming "all green." [ASSUMED based on `STATE.md` line 71 confirming 1965/1965 restored 2026-04-26.] |
| A3 | No `geolens-enterprise` overlay code imports `from app.modules.settings.models`. | Caller Inventory | If the enterprise overlay (sibling repo) imports `AppSetting` from the modules path, deleting it breaks the overlay's CI. [ASSUMED — out of scope per phase brief; user-confirmed by setting "Frontend has no involvement" / D-10 and the fact that v13.0 enterprise scope was identity, not settings. Planner may want to grep the enterprise overlay if accessible.] |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.
**Three claims need confirmation; planner should check `.dockerignore` (A1), re-baseline test count if planning is delayed (A2), and grep the enterprise overlay repo for `app.modules.settings` (A3).**

## Open Questions

1. **Should the architecture guard also forbid `from app.modules.<anything>` (broader rule), or just `from app.modules.settings` (narrow rule that maps 1:1 to LAYER-01)?**
   - What we know: D-06 says "no module under `backend/app/core/` does `from app.modules.<anything>` at import time" — that's the broader rule, and CONTEXT.md endorses it.
   - What's unclear: Phase 213 (catalog-authz-relocate) and Phase 214 (identity-protocol-extract) will further reduce `core` → `modules` coupling, but it's not zero today. If we enforce the broader rule now, Phase 212 might pull in violations that belong to 213/214's scope. (Audit-grade item that's scoped to LAYER-01 should not break CI for unrelated reasons.)
   - Recommendation: **Implement the broader rule in code** (better long-term posture), **but first** run the `git grep` manually to discover any remaining `core` → `modules` imports today. If others exist, the planner has two options:
     - (a) Scope the guard test narrowly to just `from app.modules.settings` for Phase 212; broaden it in Phase 213 / 214 / 218.
     - (b) Have the test enumerate known-tolerated exceptions explicitly (worst — adds bookkeeping).
   - Strong default: option (a). Verify by running `grep -rn "^\s*\(from\|import\)\s\+app\.modules" backend/app/core/` after the relocation; if it returns ONLY the lines this phase removes, broaden to `from app.modules.<anything>`.

2. **Add a `make migrations-check` Makefile target for ergonomic invocation, or just document the `cd backend && uv run alembic check` command?**
   - What we know: No `make migrations-check` target exists today. CONTEXT.md D-08 mentions it as "(or the project's equivalent — `make migrations-check` if defined)" — i.e., already anticipates that it doesn't exist.
   - What's unclear: Phase 218 (oc-audit close) re-runs the audit; if `alembic check` is well-trodden, it's worth a Makefile target, but adding it is technically scope creep into "tooling." 
   - Recommendation: **Out of scope for this phase**. Document the raw command in the plan's verification step. If the team wants the target, that's a one-line follow-up (a `migrations-check` Makefile target) and not blocking.

3. **Should the new `core/db/models.py` include a module-level docstring describing what belongs there?**
   - What we know: D-02 says the file holds only `AppSetting` for now; future "core-owned ORM models can land here."
   - What's unclear: Without a docstring saying "core-owned platform models only," the next contributor might dump unrelated catalog models in here.
   - Recommendation: **Yes — add a 3-line docstring** establishing the convention. Cheap, prevents drift. Suggested: `"""Core-owned ORM models. Place here only models the open-core layer owns directly (e.g., DB-backed configuration). Domain-specific models stay in their domain package."""`

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | 3.13 (per `pyproject.toml` `requires-python = ">=3.13"`) | — |
| `uv` | Build/test invocation | ✓ | 0.10.2 (per `.github/workflows/ci.yml:58`) | — |
| `alembic` (in installed `backend/.venv/`) | D-08 verification | ✓ | 1.13.0+ (per `pyproject.toml`); `alembic check` subcommand verified present 2026-04-26 | — |
| `ruff` | Lint check | ✓ | included in `[dependency-groups] dev` | — |
| `pytest` | Test suite | ✓ | 9.0.3+ in `[dependency-groups] dev` | — |
| `git` (CLI binary on PATH) | Architecture guard test (D-06) | ✓ | required for any worktree; CI uses `actions/checkout@v4` which provides `.git/` | If not available (e.g., dockerized test run with `.git/` excluded by `.dockerignore`), the test should `pytest.skip` — see Pitfall 4. |
| Docker compose | `make test` invocation per Makefile | ✓ | Project standard (per Makefile `docker compose exec api`) | Direct `cd backend && uv run pytest` works on host if `.venv` is hydrated. |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — the only edge case is `.git/` inside the container, which is handled by the recommended `_has_git_metadata()` skip in Pitfall 4.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3+ (with `pytest-anyio` `anyio_mode = "auto"` for async tests) |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` (lines 67–80) |
| Quick run command (local, single test) | `cd backend && uv run pytest tests/test_layering.py -v` |
| Quick run command (smoke for this refactor) | `cd backend && uv run pytest tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_layering.py tests/test_validation.py tests/test_hybrid_search.py tests/test_ai_send_sample_values.py -v` |
| Full suite command | `docker compose exec api uv run pytest -v --tb=short` (Makefile `make test`) — or in CI: `uv run pytest -v --tb=short -m 'not perf' --cov=app --cov-fail-under=58.5` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LAYER-01 (a) — `core/persistent_config.py` no longer imports from `modules/settings` | Static import inspection | unit (architecture) | `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_modules -v` | ❌ Wave 0 (new file) |
| LAYER-01 (b) — `core/public_urls.py` no longer imports from `modules/settings` | Same guard test covers this | unit (architecture) | (same as above) | ❌ Wave 0 |
| LAYER-01 (c) — PersistentConfig get/set behavior preserved | get/set DB round-trip with cache invalidation | integration | `cd backend && uv run pytest tests/test_persistent_config.py -v` | ✅ existing (covers all 16 PersistentConfig instances + cache + audit) |
| LAYER-01 (d) — Public URL precedence preserved (request → DB → env) | URL resolution across precedence cases | integration | `cd backend && uv run pytest tests/test_public_urls.py -v` | ✅ existing |
| LAYER-01 (e) — Settings router HTTP contract unchanged | GET/PUT/POST `/settings/*` | integration | `cd backend && uv run pytest tests/test_settings_router.py tests/test_settings_admin.py -v` | ✅ existing (all 16 PersistentConfig instances exercised via `/settings/all/` and `/settings/`) |
| LAYER-01 (f) — Alembic schema diff is empty | `alembic check` exits 0 with no operations | smoke (CLI) | `cd backend && uv run alembic check` | ✅ alembic CLI exists; new ad-hoc check command |
| LAYER-01 (g) — Test baseline preserved | Full pytest run | full suite | `docker compose exec api uv run pytest -v --tb=short` | ✅ existing 1965 tests |
| Cache invariants — `_get_cache_safe`, `_sync_rate_limit_cache`, `_PUBLIC_URL_CACHE` unaffected | Cache tests | integration | `cd backend && uv run pytest tests/test_cache.py tests/test_persistent_config.py tests/test_public_urls.py -v` | ✅ existing |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_layering.py tests/test_persistent_config.py tests/test_public_urls.py tests/test_settings_router.py tests/test_settings_admin.py -v` (~30s estimated)
- **Per wave merge (full settings/persistent-config slice):** `cd backend && uv run pytest tests/test_layering.py tests/test_persistent_config.py tests/test_settings_router.py tests/test_settings_admin.py tests/test_public_urls.py tests/test_validation.py tests/test_hybrid_search.py tests/test_ai_send_sample_values.py tests/test_branding_settings.py -v`
- **Phase gate:** Full suite green (`docker compose exec api uv run pytest -v`) AND `cd backend && uv run alembic check` returns no operations BEFORE `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `backend/tests/test_layering.py` — covers LAYER-01 architecture guard (D-06). New file. See Pattern 2 in Architecture Patterns.
- [ ] `[tool.pytest.ini_options].markers` in `backend/pyproject.toml` — register the `architecture` marker so `pytest -m architecture` and `pytest -m 'not architecture'` both work without warnings.
- [ ] (Optional) Makefile target `migrations-check`: `cd backend && uv run alembic check`. Out of scope per Open Question 2; document the raw command in the plan instead.

## Security Domain

> Phase is a Python-only refactor with no auth surface, no input parsing, and no cryptographic code. ASVS impact is bounded.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Refactor does not touch JWT, OAuth, or API key code. |
| V3 Session Management | no | No session-handling changes. |
| V4 Access Control | no | `require_permission("manage_settings")` in `router.py:174` is unchanged. |
| V5 Input Validation | no | The `SETTING_VALIDATORS` registry and per-key validators in `modules/settings/schemas.py` are unchanged. The `_validate_or_fallback` helper in `persistent_config.py:65–90` is unchanged. |
| V6 Cryptography | no | No crypto code. |

### Known Threat Patterns for {SQLAlchemy / FastAPI Python backend}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via dynamic query building | Tampering | All queries use SQLAlchemy parameterized expressions (`select(AppSetting).where(AppSetting.key == self.key)`). Unchanged by relocation. |
| Information disclosure via cache-key collision | Information Disclosure | `_CACHE_PREFIX = "config:"` namespacing in `persistent_config.py:37`. Unchanged. |
| Audit log bypass | Repudiation | `await log_action(...)` invocations in `persistent_config.py:201–212` and `:247–258` and in `settings/router.py`. Unchanged. |

**Specific note:** `persistent_config.py:78–80` warns that `exc.errors()` (Pydantic ValidationError) includes the offending input value; current registered configs do not store secrets, but this caveat is unchanged by the relocation. Phase 212 does not modify this code path.

## Sources

### Primary (HIGH confidence)
- [Repo grep] `grep -rn "from app.modules.settings.models\|app.modules.settings.models" backend/` 2026-04-26 — confirms 9 callers, 14 import statements
- [Repo grep] `grep -rn "AppSetting" backend/` 2026-04-26 — confirms ~40 usage sites across 9 importing files
- [`backend/app/modules/settings/models.py`] (10-line file, full content read) — current model definition
- [`backend/app/core/db/session.py`] lines 1–32 — `Base = DeclarativeBase` confirmed; same `Base` used by `AppSetting`
- [`backend/app/core/db/__init__.py`] lines 1–6 — `__all__ = ["Base", "async_session", "engine"]`; no `AppSetting` re-export
- [`backend/app/modules/settings/__init__.py`] line 1 — empty docstring only; no re-export
- [`backend/app/core/persistent_config.py`] lines 1–680 (full file) — confirms cache → DB → env precedence, JSONB unwrap (`{"v": value}`), 16 PersistentConfig registry instances, sync rate-limit cache
- [`backend/app/core/public_urls.py`] lines 1–246 (full file) — confirms 60s `_PUBLIC_URL_CACHE`, request → DB → env precedence
- [`backend/app/modules/settings/router.py`] lines 1–80, 170–210 — confirms `from app.modules.settings.models import AppSetting` at line 33; usage at line 184
- [`backend/alembic/env.py`] lines 1–103 (full file) — confirms `import app.modules.settings.models  # noqa: F401` at line 22 (NEW caller not in CONTEXT.md D-04)
- [`backend/tests/conftest.py`] lines 1–179 — confirms test session lifecycle uses `command.upgrade(alembic_cfg, "head")`; no direct `AppSetting` usage in conftest
- [`backend/pyproject.toml`] lines 1–80 — confirms `[tool.pytest.ini_options].markers` extensibility, alembic version, no mypy/pyright
- [`backend/Makefile` (root)] lines 1–43 — confirms `make test` is `docker compose exec api uv run pytest`; no `migrations-check` target
- [`.github/workflows/ci.yml`] lines 105–197 — confirms CI command: `uv run alembic upgrade head` then `uv run pytest`
- [Alembic CLI 1.13.0+] `cd backend && uv run alembic --help` 2026-04-26 — confirms `check` subcommand: "Check if revision command with autogenerate has pending upgrade ops"

### Secondary (MEDIUM confidence)
- [audit] `docs-internal/audits/oc-separation-audit-20260426-b.md` lines 13, 236, 249, 269, 365 — all mention the `core ↔ settings` inversion; original LAYER-01 source
- [audit] `docs-internal/audits/oc-separation-deferred-items-20260426.md` line 14 — "Either move `AppSetting` to `core/db/models.py` or invert by registering a config provider into core at startup" (option A chosen per D-01)

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies already installed and verified via direct CLI invocation
- Architecture: HIGH — repo conventions confirmed by reading actual files (no extrapolation)
- Pitfalls: HIGH for Pitfalls 1–3, 5; MEDIUM for Pitfall 4 (depends on `.dockerignore` content, flagged in Assumptions)
- Caller inventory: HIGH — exhaustive grep with no excluded patterns
- Validation Architecture: HIGH — existing tests verified to cover the behaviors

**Research date:** 2026-04-26
**Valid until:** 2026-05-26 (30 days; the codebase is stable, but `STATE.md`'s 1965-test baseline could drift if other quick tasks land in the meantime)

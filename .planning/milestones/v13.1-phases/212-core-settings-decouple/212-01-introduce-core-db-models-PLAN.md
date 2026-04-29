---
phase: 212-core-settings-decouple
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/core/db/models.py
autonomous: true
requirements: [LAYER-01]
requirements_addressed: [LAYER-01]
tags: [refactor, layering, sqlalchemy, open-core]

must_haves:
  truths:
    - "`from app.core.db.models import AppSetting` succeeds at the Python level."
    - "The relocated `AppSetting` class has identical SQLAlchemy table identity (`__tablename__='app_settings'`, `__table_args__={'schema': 'catalog'}`) and identical columns (`key TEXT PK`, `value JSONB NOT NULL`) to the version in `backend/app/modules/settings/models.py`."
    - "The new file documents the convention so future contributors know what belongs in `core/db/models.py`."
  artifacts:
    - path: "backend/app/core/db/models.py"
      provides: "core-owned `AppSetting` SQLAlchemy ORM model + module-level docstring describing the convention"
      contains: "class AppSetting(Base):"
      min_lines: 14
  key_links:
    - from: "backend/app/core/db/models.py"
      to: "backend/app/core/db/session.py:Base"
      via: "from app.core.db import Base"
      pattern: "from app\\.core\\.db import Base"
---

<objective>
Introduce a new `backend/app/core/db/models.py` containing the `AppSetting` SQLAlchemy ORM model — a verbatim copy of the class currently at `backend/app/modules/settings/models.py`, plus a module-level docstring that establishes the "core-owned ORM models" convention.

Purpose: This is the foundation for breaking the `core ↔ settings` layering inversion (LAYER-01, D-01). After this plan lands, both the old and new modules expose the same class identity; downstream caller migration happens in Plan 02. Splitting the file-creation step from the import-migration step keeps the diff easy to review and lets the table identity comparison happen in isolation.

Output: A new 14-line file at `backend/app/core/db/models.py` with `AppSetting` defined against the existing `Base` from `app.core.db.session`. No callers move yet.
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
@backend/app/modules/settings/models.py
@backend/app/core/db/__init__.py
@backend/app/core/db/session.py

<interfaces>
<!-- Source-of-truth class definition that must be reproduced verbatim in the new file. -->
<!-- From backend/app/modules/settings/models.py (lines 1-13, full file): -->

```python
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

<!-- The `Base` import path `from app.core.db import Base` resolves through `backend/app/core/db/__init__.py` (which re-exports `Base, async_session, engine` from `session.py`). It is unchanged. -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 01-01: Create core/db/models.py with AppSetting (verbatim copy + docstring)</name>
  <files>backend/app/core/db/models.py</files>
  <read_first>
    - backend/app/modules/settings/models.py (the source of truth — copy this class definition verbatim)
    - backend/app/core/db/__init__.py (confirm `Base` is re-exported here; do NOT add `AppSetting` to `__all__`)
    - backend/app/core/db/session.py (confirm `Base = DeclarativeBase` lives here)
    - .planning/phases/212-core-settings-decouple/212-RESEARCH.md (Pitfall 2 — do not re-export AppSetting from `__init__.py`; Pitfall 3 — copy the class verbatim or `alembic check` will report drift)
  </read_first>
  <action>
Create `backend/app/core/db/models.py` (per D-01, D-02). The file MUST contain exactly the following content (the body is the verbatim 13 lines from `backend/app/modules/settings/models.py` plus a module-level docstring on top):

```python
"""Core-owned ORM models.

Place here only models the open-core layer owns directly (e.g., DB-backed
configuration). Domain-specific models stay in their domain package
(`app.modules.<domain>.<...>`).

Never import from `app.modules.*` in this module — `core/` must not depend on
`modules/`. The `tests/test_layering.py` architecture guard enforces this rule
(introduced in Phase 212, plan 03).
"""

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

Hard constraints (from RESEARCH.md and CONTEXT.md):
- The body of `AppSetting` MUST match `backend/app/modules/settings/models.py` byte-for-byte (same `__tablename__`, same `__table_args__` dict, same column types `Text` PK + `JSONB nullable=False` with same `Mapped` annotations). Any drift will cause `alembic check` to report a phantom migration (RESEARCH.md Pitfall 3).
- DO NOT modify `backend/app/core/db/__init__.py`. Specifically, DO NOT add `AppSetting` to its `__all__` list (RESEARCH.md Pitfall 2 / Anti-Patterns to Avoid). Callers will import directly from `app.core.db.models` per D-04.
- DO NOT delete `backend/app/modules/settings/models.py` in this plan — that happens in Plan 02. After this task, BOTH files exist and define `AppSetting` against the same `Base`. That is intentional; SQLAlchemy will see the same `__tablename__` registered twice on `Base.metadata`, but because both classes are byte-identical and Python imports are cached per-module, this transitional state does not produce duplicate-table errors at import time. Plan 02 deletes the old file before the next test run, so any duplicate-registration surface is sub-commit.
- DO NOT add this file to git ignore; it is a real source file that ships.
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.core.db.models import AppSetting; assert AppSetting.__tablename__ == 'app_settings', AppSetting.__tablename__; assert AppSetting.__table_args__ == {'schema': 'catalog'}, AppSetting.__table_args__; cols = {c.name: str(c.type) for c in AppSetting.__table__.columns}; assert cols['key'].upper().startswith('TEXT'), cols; assert cols['value'].upper().startswith('JSONB'), cols; print('OK', cols)"</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/app/core/db/models.py` exists.
    - `cd backend && uv run python -c "from app.core.db.models import AppSetting"` exits 0.
    - `AppSetting.__tablename__ == "app_settings"` and `AppSetting.__table_args__ == {"schema": "catalog"}` (asserted by the verify command).
    - The `key` column is `TEXT` primary key; the `value` column is `JSONB NOT NULL` (asserted by the verify command).
    - `git diff backend/app/core/db/__init__.py` shows zero changes — `__init__.py` is NOT touched (RESEARCH.md Pitfall 2).
    - `cd backend && uv run ruff check app/core/db/models.py` exits 0.
    - The module docstring is present (the literal string `"""Core-owned ORM models."""` appears as the first statement, plus the multi-line body).
  </acceptance_criteria>
  <done>
    File created with exact 14-line `AppSetting` body matching `modules/settings/models.py` plus the multi-line `Core-owned ORM models` docstring. Old file at `backend/app/modules/settings/models.py` still exists and is unchanged (Plan 02 handles its deletion). `backend/app/core/db/__init__.py` is unchanged.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

This plan adds a single new Python module that defines an ORM mapping. There is no input parsing, no auth surface, no I/O at module-import time beyond SQLAlchemy's `Base.metadata` registration (which is identical to what the existing `modules/settings/models.py` already does). No new trust boundaries are introduced or moved.

| Boundary | Description |
|----------|-------------|
| (none) | Pure Python class declaration; no untrusted input crosses any new boundary. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-212-03 | INFO | New `core/db/models.py` module | accept | No new external attack surface — the table schema, API endpoints, auth flows, and runtime data are unchanged. SQLAlchemy identifies tables by `__tablename__`+`__table_args__`, not by Python module path; the new file produces the identical metadata registration as the old one. |
</threat_model>

<verification>
- `cd backend && uv run python -c "from app.core.db.models import AppSetting; print(AppSetting.__tablename__, AppSetting.__table_args__)"` prints `app_settings {'schema': 'catalog'}`.
- `cd backend && uv run ruff check app/core/db/models.py` exits 0.
- `git diff backend/app/core/db/__init__.py` shows zero changes (the file is NOT modified — RESEARCH.md Pitfall 2).
- `git diff backend/app/modules/settings/models.py` shows zero changes (still present, untouched, deleted in Plan 02).
</verification>

<success_criteria>
- The file `backend/app/core/db/models.py` exists with the `AppSetting` class and the module docstring (3-line+ description establishing the "core-owned ORM models" convention per RESEARCH.md Open Question 3).
- The class is byte-equivalent to the source at `backend/app/modules/settings/models.py` (same imports, same parent `Base`, same `__tablename__`, same `__table_args__`, same column declarations).
- `__init__.py` is untouched.
- The plan introduces zero behavior change — no callers migrated yet, no schema diff, no new dependencies. Verifiable via `cd backend && uv run alembic check` returning the same result it returns today (Plan 04 runs this; this plan does not need to).
</success_criteria>

<output>
After completion, create `.planning/phases/212-core-settings-decouple/212-01-SUMMARY.md` documenting:
- What was created (the new file path)
- The verbatim class definition that was copied
- Confirmation that `__init__.py` was not modified and the old file at `backend/app/modules/settings/models.py` is still present
- Any deviation from the verbatim copy (there should be none — only the docstring is additive)
</output>

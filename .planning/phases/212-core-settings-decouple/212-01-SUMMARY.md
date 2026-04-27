---
phase: 212-core-settings-decouple
plan: "01"
subsystem: backend/core/db
tags: [refactor, layering, sqlalchemy, open-core]
dependency_graph:
  requires: []
  provides: [core/db/models.py with AppSetting]
  affects: [backend/app/core/db/]
tech_stack:
  added: []
  patterns: [core-owned ORM model file separate from session.py]
key_files:
  created:
    - backend/app/core/db/models.py
  modified: []
decisions:
  - "D-01: Relocated AppSetting from modules/settings/models.py to core/db/models.py (file creation only; callers migrate in Plan 02)"
  - "D-02: core/db/models.py holds AppSetting only; no pre-emptive other model moves"
  - "Pitfall 2 avoided: core/db/__init__.py not modified; no AppSetting re-export added"
metrics:
  duration: "~3 minutes"
  completed: "2026-04-27"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 212 Plan 01: Introduce core/db/models.py Summary

New `backend/app/core/db/models.py` created with verbatim `AppSetting` SQLAlchemy model + convention docstring, establishing the core-owned ORM models location with no caller changes.

## What Was Created

**`backend/app/core/db/models.py`** (24 lines) — new file containing:
1. A module-level docstring establishing the "core-owned ORM models" convention (warns against importing from `app.modules.*`).
2. The `AppSetting` class copied verbatim from `backend/app/modules/settings/models.py`.

## Verbatim Class Definition Copied

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

## Confirmation of Invariants

- `backend/app/core/db/__init__.py` — **not modified** (`git diff` returned empty; Pitfall 2 avoided).
- `backend/app/modules/settings/models.py` — **still present and unchanged** (deletion is Plan 02 scope per D-05).
- No callers were migrated in this plan (Plan 02 scope per D-04).
- `ruff check app/core/db/models.py` — 0 errors.

## Verification Output

```
OK {'key': 'TEXT', 'value': 'JSONB'}
```

Command: `cd backend && uv run python -c "from app.core.db.models import AppSetting; assert AppSetting.__tablename__ == 'app_settings'; assert AppSetting.__table_args__ == {'schema': 'catalog'}; cols = {c.name: str(c.type) for c in AppSetting.__table__.columns}; assert cols['key'].upper().startswith('TEXT'); assert cols['value'].upper().startswith('JSONB'); print('OK', cols)"`

## Deviations from Plan

None — plan executed exactly as written. The file body matches the source at `modules/settings/models.py` byte-for-byte; only the additive docstring differs.

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 01-01: Create core/db/models.py | `567c9cb3` | backend/app/core/db/models.py (created) |

## Self-Check: PASSED

- `backend/app/core/db/models.py` exists: FOUND
- Commit `567c9cb3` exists: FOUND
- `core/db/__init__.py` unchanged: CONFIRMED (zero git diff)
- `modules/settings/models.py` still present: CONFIRMED

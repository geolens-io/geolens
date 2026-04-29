# Phase 212: core-settings-decouple - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 212-core-settings-decouple
**Mode:** `--auto --chain` (Claude auto-selected recommended options for every gray area)
**Areas discussed:** Decoupling approach, Caller migration, Regression prevention, Migration & verification

---

## Decoupling approach

| Option | Description | Selected |
|--------|-------------|----------|
| Relocate `AppSetting` → `core/db/models.py` | Move the SQLAlchemy class out of `modules/settings/models.py` and into a new `core/db/models.py`. Pure Python relocation; the `app_settings` table is unchanged. Mechanical, audit-suggested simpler path. | ✓ |
| Invert via `ConfigProvider` Protocol in `core/` | Define an abstract `ConfigProvider` in `core/`; have `modules/settings/` register a concrete impl at app startup. Adds a new extension seam. | |

**User's choice (auto):** Relocate to `core/db/models.py`.
**Notes:** The audit explicitly offered both options and called the relocation simpler. Phase 214 already introduces a Protocol-based extension pattern (`IdentityProtocol`); duplicating that pattern here would be premature abstraction. v13.1's job is to close boundary debts with minimum correct change.

---

## Caller migration

| Option | Description | Selected |
|--------|-------------|----------|
| Full migration, no shim | Update every importer in the repo (3 prod files + 2 tests + any others) to `from app.core.db.models import AppSetting`; delete `backend/app/modules/settings/models.py`. | ✓ |
| Keep re-export shim in `modules/settings/models.py` | Leave a `from app.core.db.models import AppSetting` re-export so external callers and slow migrations don't break. | |

**User's choice (auto):** Full migration, no shim.
**Notes:** Closed-set codebase, all importers known and inside this repo. Type checker + tests catch any miss before merge. Shims rot.

---

## Regression prevention

| Option | Description | Selected |
|--------|-------------|----------|
| Add architecture guard test | A test under `backend/tests/test_layering.py` (or extension of an existing arch test) that asserts `core/` never imports from `modules/settings/`. CI-enforced. | ✓ |
| Rely on existing baseline + audit re-run | Trust the 1965-test baseline + Phase 218's `/oc-audit` re-run to catch regressions. | |

**User's choice (auto):** Add guard test.
**Notes:** The audit caught this exact pattern. Without an automated guard, the next contributor's "convenient" core import will reopen the finding. The guard is one cheap subprocess call.

---

## Migration & verification

| Option | Description | Selected |
|--------|-------------|----------|
| Pure Python relocation, no Alembic migration | The `app_settings` table is unchanged; only the model's Python file location moves. `alembic check` proves no schema diff. | ✓ |
| Generate a migration anyway | Belt-and-braces: produce an empty/no-op migration to mark the refactor in version history. | |

**User's choice (auto):** Pure Python relocation; verify with `alembic check`.
**Notes:** Alembic identifies tables via `Base.metadata` (populated by import side effects), not by import path. Moving the class doesn't change the schema. A no-op migration would be noise.

---

## Claude's Discretion

- Exact filename in `core/db/` (`models.py` vs `app_settings.py`) — defaulting to `models.py` per audit wording and SQLAlchemy convention.
- Exact form of the architecture guard (subprocess `git grep` vs AST walk vs import-graph library) — planner picks the simplest form that fits existing test conventions.
- Commit decomposition (likely 3 atomic commits: introduce file, migrate callers + delete old, add guard).

## Deferred Ideas

- `ConfigProvider` Protocol in core — defer to a future phase if a non-`AppSetting` config backend ever materializes.
- Generalizing `core/db/models.py` to host other catalog models — scope creep; each domain owns its own models.
- Splitting the 680-line `persistent_config.py` — out of scope for a mechanical refactor.

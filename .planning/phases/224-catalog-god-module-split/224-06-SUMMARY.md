---
phase: 224-catalog-god-module-split
plan: 06
subsystem: catalog
tags: [refactor, extract, service-create, decouple, final-extraction]

# Dependency graph
requires:
  - phase: 224-catalog-god-module-split
    provides: "224-05 fourth sub-module extraction (service_query.py) + the proven 5-iteration sub-module extraction recipe"
provides:
  - "backend/app/modules/catalog/datasets/domain/service_create.py — 2 public creation coroutines (create_empty_dataset, create_dataset) + __all__ + cross-module imports for _safe_table_ref (service_lifecycle) and auto_detect_relationships (service_relationships)"
  - "service.py shim block re-exporting both create symbols (DECOUPLE-01 preservation)"
  - "Final sub-module extraction in the 224 5-way split — all 5 sub-modules now exist"
  - "service.py at 47 LOC — already <250 LOC façade target (DECOUPLE-02 effectively reached pre-Plan 07)"
affects:
  - 224-07 (façade conversion — service.py is now essentially 5 import blocks; Plan 07 work reduces to revising the docstring + adding __all__)
  - 224-08 (architecture-guard test — service_create.py joins the allow-list as the 5th sub-module)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sub-module extraction recipe applied verbatim for the FIFTH and FINAL time — pattern fully proven across all 5 iterations"
    - "Cross-module imports per D-05: create_create.py imports auto_detect_relationships AND _safe_table_ref via the canonical `app.modules.catalog.datasets.domain.service_X` absolute path (NOT relative `from .service_X`) — anchors the Plan 08 architecture-guard pattern"
    - "service.py reduced to 47 LOC (5 re-export blocks + 1 module docstring) — no implementation remains"

key-files:
  created:
    - backend/app/modules/catalog/datasets/domain/service_create.py
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py

key-decisions:
  - "Two cross-module imports were required: `_safe_table_ref` (used by `create_empty_dataset` to safely quote the generated PostGIS table name) lives in `service_lifecycle.py`, and `auto_detect_relationships` (used by `create_dataset` for FK auto-detection on column_info) lives in `service_relationships.py`. Both imports use the canonical absolute path per D-02/D-05; the architecture-guard test in Plan 08 will allow these cross-imports BETWEEN sub-modules."
  - "Removed the entire body of service.py except the module docstring and 5 re-export blocks. The previous service.py-only artifacts (`_COLUMN_NAME_RE`, `_RESERVED_COLUMNS`, `_TYPE_MAP` regex/sets/dicts, `re`/`uuid`/`TYPE_CHECKING`/`func`/`text`/`AsyncSession`/`Identity`/`Dataset`/`Record` imports, and the inline TYPE_CHECKING block) all moved into service_create.py because they were exclusively consumed by the two creation coroutines. service.py post-Plan-06 is essentially a 5-block re-export façade waiting for the Plan 07 polish (docstring revision + __all__ enumerating the 23 public symbols)."
  - "No additional Rule 3 cleanup needed — unlike Plan 05 which had to drop 8 orphaned imports + a `logger` binding, this plan's only remaining service.py content was already destined to leave (every artifact was a `create_*` dependency). After deleting the 2 bodies, the only sensible service.py content was the module docstring + the 5 re-export blocks, which is exactly what was written."

patterns-established:
  - "**Recipe stability across 5 iterations:** the 'Phase 224 sub-module extraction recipe' has now been applied without modification five times in a row. The pattern is fully proven and will appear nowhere else in this codebase (Phase 224 is its only application)."
  - "**Final-extraction simplification:** because all callees were already in their final module locations BEFORE this plan ran (per D-02 ordering — least-coupled first), there were ZERO callee migrations underneath the orchestrator during this plan. create_dataset's two cross-module callees (_safe_table_ref, auto_detect_relationships) were imported from their already-stable Plan-04/Plan-02 locations. This validates D-02 (extract least-coupled first) as the correct ordering choice."
  - "**Cross-module import discipline:** all sub-modules so far that need a sibling's symbol use the canonical absolute path. Plan 08's git-grep allowlist regex can match `from app\\.modules\\.catalog\\.datasets\\.domain\\.service_(create|query|lifecycle|metadata|relationships)` exactly — no relative-form variants to handle."

requirements-completed: []  # DECOUPLE-01..04 are validated cumulatively at phase close (224-08).

# Metrics
duration: ~8min
completed: 2026-05-01
---

# Phase 224 Plan 06: Extract service_create.py Summary

**2 dataset creation coroutines (`create_empty_dataset`, `create_dataset`) extracted into `backend/app/modules/catalog/datasets/domain/service_create.py` (222 LOC, well under 500 ceiling). service.py reduced from 256 → 47 LOC (−209), now containing only the module docstring + 5 re-export blocks. This is the FINAL sub-module extraction; all 5 sub-modules now exist (service_create, service_query, service_lifecycle, service_metadata, service_relationships). Pytest 2045/2045 GREEN, identical to baseline. Cumulative service.py shrinkage from 224-01 baseline: 1407 → 47 LOC (−97%) — service.py is already well below the <250 LOC façade target (DECOUPLE-02 effectively satisfied before Plan 07's polish work).**

## Performance

- **Duration:** ~8 min wall (~6.6 min of which is the full pytest preservation gate)
- **Tasks:** 3/3
- **Files created:** 1 (service_create.py)
- **Files modified:** 1 (service.py)
- **Atomic commits:** 1 (`3ca0bb99`) — Tasks 1+2+3 bundled per the plan template

## LOC Accounting

| File | After 224-05 | After 224-06 | Delta |
|---|---|---|---|
| `service.py` | 256 | **47** | **−209** |
| `service_create.py` | n/a (did not exist) | **222** | +222 |
| `service_lifecycle.py` | 158 | 158 | 0 |
| `service_metadata.py` | 384 | 384 | 0 |
| `service_query.py` | 356 | 356 | 0 |
| `service_relationships.py` | 423 | 423 | 0 |
| **Combined (6 files)** | 1577 | 1590 | +13 (`__all__`, module docstring on the new file, deduplicated cross-module imports) |

`service.py` cumulative shrinkage from the 224-01 baseline: **1407 → 47 LOC (−97%, far ahead of the <250 LOC façade target).** Plan 224-07's façade-conversion work is now reduced to: revise the module docstring (1 paragraph), add an explicit `__all__` listing the 23 public symbols, and confirm ruff cleanliness — no LOC reduction needed (already there).

### Per-Sub-Module Final LOC (preview for Plan 224-07)

```
  47 backend/app/modules/catalog/datasets/domain/service.py            (façade)
 222 backend/app/modules/catalog/datasets/domain/service_create.py     (NEW — Plan 06)
 356 backend/app/modules/catalog/datasets/domain/service_query.py
 158 backend/app/modules/catalog/datasets/domain/service_lifecycle.py
 384 backend/app/modules/catalog/datasets/domain/service_metadata.py
 423 backend/app/modules/catalog/datasets/domain/service_relationships.py
1590 total
```

Each sub-module is well under the 500 LOC ceiling (DECOUPLE-03), and the façade at 47 LOC is already below the 250 LOC target (DECOUPLE-02). All 5 sub-modules now exist — the Plan 07 façade conversion is largely a polish step.

## Public-Surface Preservation (DECOUPLE-01)

**Consumer-side import-surface diff: empty.**

```bash
diff <(sort .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt) \
     <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' \
       | grep -v 'datasets/domain/service\.py:\|datasets/domain/service_' \
       | sort)
# exit 0 — 22 consumer lines unchanged
```

The unfiltered grep gains 2 new lines, both inside the new sub-module structure (per D-05 cross-imports between sub-modules are allowed):

1. `service.py` — shim block `from app.modules.catalog.datasets.domain.service_create import (create_dataset, create_empty_dataset)` re-exporting both create symbols
2. `service_create.py` — cross-module imports of `_safe_table_ref` (service_lifecycle) and `auto_detect_relationships` (service_relationships) via the canonical absolute path

## Pytest Preservation (D-09)

```
2045 passed, 19 skipped, 5 deselected, 29 warnings in 397.08s (0:06:37)
```

**Identical** to the 224-01 baseline (`2045 passed, 19 skipped, 5 deselected`), to 224-02, 224-03, 224-04, and 224-05. Zero new failures, zero new skips. The mechanical-move guarantee held for the FIFTH and FINAL time.

## Smoke Tests

- **Public-surface importability:** `from app.modules.catalog.datasets.domain.service import (create_dataset, create_empty_dataset)` → prints `OK`
- **Full public surface (23 symbols):** all 23 names importable through service.py — `create_empty_dataset`, `create_dataset` (NEW shim from service_create); 5 query symbols (shim from service_query); 4 lifecycle symbols (shim from service_lifecycle); 7 metadata symbols (shim from service_metadata); 6 relationship symbols (shim from service_relationships) — prints `all 23 OK`
- **Application boot:** `from app.api.main import app` → prints `boot OK` (with the unrelated authlib `joserfc` deprecation warning that exists on every boot — pre-existing, out of scope)
- **All 5 sub-modules confirmed:** `ls backend/app/modules/catalog/datasets/domain/service_*.py | wc -l` returns `5`
- **Ruff:** clean across both modified/created files

## Task Commits

1. **Task 1: Create service_create.py with 2 creation coroutines** — included in `3ca0bb99`
2. **Task 2: Update service.py — remove 2 moved bodies + all create-only artifacts (regex/sets/dicts/imports), add re-export shim** — included in `3ca0bb99`
3. **Task 3: Verify gate (pytest, import-surface diff, boot smoke, all-5-submodules check) + atomic commit** — `3ca0bb99`

Per the plan's commit template, all three task outputs ship as a single atomic commit titled `refactor(224-06): extract service_create from datasets/domain/service.py`. Splitting Tasks 1 and 2 would leave the codebase in a broken intermediate state (service.py would reference deleted bodies).

**Plan metadata commit:** `docs(224-06): plan summary` (separate, follows this file's write).

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/service_create.py` — **new**, 222 LOC, 2 public coroutines (`create_empty_dataset`, `create_dataset`) + `__all__` listing both names. Imports: `re`, `uuid`, `TYPE_CHECKING`, `CreateEmptyDatasetRequest` (TYPE_CHECKING), `func`/`text` from sqlalchemy, `AsyncSession`, `Identity`, `Dataset`/`Record` models, plus 2 cross-module imports via canonical absolute path: `_safe_table_ref` from `service_lifecycle` and `auto_detect_relationships` from `service_relationships`. Module-level constants `_COLUMN_NAME_RE`, `_RESERVED_COLUMNS`, `_TYPE_MAP` moved with the bodies (only consumers were `create_empty_dataset`). Module docstring: `"Dataset creation paths: empty + materialized (extracted from service.py — Phase 224)."`
- `backend/app/modules/catalog/datasets/domain/service.py` — modified: removed 2 function bodies (`create_empty_dataset`, `create_dataset`), 3 module-level constants (`_COLUMN_NAME_RE`, `_RESERVED_COLUMNS`, `_TYPE_MAP`), and 8 imports (`re`, `uuid`, `TYPE_CHECKING`, `CreateEmptyDatasetRequest` block, `func`, `text`, `AsyncSession`, `Identity`, `Dataset`, `Record`); added a 4-line re-export shim block for the 2 create symbols. Final state: module docstring + `from __future__ import annotations` + 5 re-export blocks (47 LOC).

## Decisions Made

- **No additional orphaned-import cleanup needed beyond the bodies themselves** — unlike Plan 05 which dropped 8 imports + a `logger` binding via Rule 3, this plan had no orphan-cleanup work because EVERY remaining artifact in service.py was already a `create_*` dependency. After deleting the 2 bodies, the only sensible content was the module docstring + 5 re-export blocks, which is exactly what was written. Ruff was clean on the first pass.
- **Cross-module imports use the canonical absolute path per D-05** — `from app.modules.catalog.datasets.domain.service_lifecycle import _safe_table_ref` and `from app.modules.catalog.datasets.domain.service_relationships import auto_detect_relationships`, NOT the relative `from .service_X` form. The Plan 08 architecture-guard regex pattern is keyed to the canonical absolute path; using relative imports would defeat the cohesion check.
- **`# noqa: E402,F401` on the shim block** — same canonical convention as 224-02/03/04/05. Re-exports are by design module-level "unused"; they exist solely to expose names to consumers via service.py. `E402` allows the module-level import after `from __future__ import annotations`.

## Deviations from Plan

None — plan executed substantively as written.

## Issues Encountered

None blocking.

## Next Phase Readiness

- **Plan 224-07 (façade conversion)** is unblocked. service.py is already at 47 LOC (well below the <250 LOC target). Plan 07's work simplifies to: revise the module docstring (~1 paragraph describing the 5-way split + cross-import discipline), add an explicit `__all__` listing the 23 public symbols, and confirm ruff cleanliness. No LOC reduction needed — DECOUPLE-02 effectively satisfied.
- **Plan 224-08 (architecture-guard test)** is unblocked. The allow-list (D-05) is now finalized: `service_create.py`, `service_query.py`, `service_lifecycle.py`, `service_metadata.py`, `service_relationships.py`, `service.py`, and `backend/tests/test_layering.py`. The git-grep regex pattern needs to match `from app\.modules\.catalog\.datasets\.domain\.service_(create|query|lifecycle|metadata|relationships)` and fail if any consumer outside the allow-list matches.
- **All 5 sub-modules now exist** — recipe-completion check satisfied. The 5-way split (per D-01) is complete. Phase 224 has 2 plans remaining (façade conversion + architecture-guard test), neither of which extracts new sub-modules.
- **Cumulative service.py shrinkage:** 1407 → 47 LOC (−97%). The <250 LOC façade target (DECOUPLE-02) is now satisfied before Plan 07 begins.

---

## Self-Check: PASSED

Verified post-write:

- `backend/app/modules/catalog/datasets/domain/service_create.py` exists, 222 LOC, contains both target coroutines (grep returns 2: `async def create_empty_dataset`, `async def create_dataset`)
- `__all__` lists exactly 2 public names (`["create_empty_dataset", "create_dataset"]`)
- Cross-module imports use canonical absolute path: `from app.modules.catalog.datasets.domain.service_lifecycle import _safe_table_ref` and `from app.modules.catalog.datasets.domain.service_relationships import auto_detect_relationships`
- `backend/app/modules/catalog/datasets/domain/service.py` modified to 47 LOC, contains the new shim line `from app.modules.catalog.datasets.domain.service_create import` (grep returns 1)
- All 5 sub-modules exist: `ls backend/app/modules/catalog/datasets/domain/service_*.py | wc -l` returns `5`
- Commit `3ca0bb99` exists in `git log`, message references 224-06 (`git log -1 --oneline | grep -c '224-06'` returns 1)
- Ruff clean: `cd backend && uv run ruff check app/modules/catalog/datasets/domain/service.py app/modules/catalog/datasets/domain/service_create.py` exits 0
- Smoke import OK: 2 create symbols importable through service.py shim; full 23-symbol public surface importable through service.py
- Pytest GREEN: `2045 passed, 19 skipped, 5 deselected` — identical to 224-01 baseline (5th iteration confirmation)
- Consumer-side import-surface diff against `224-01-baseline-imports.txt`: empty (22 lines unchanged) — using the precise grep filter
- Application boot: `from app.api.main import app` exits 0 with `boot OK`
- No file deletions in commit (post-commit deletion check confirmed clean)

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*

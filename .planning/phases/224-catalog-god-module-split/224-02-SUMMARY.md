---
phase: 224-catalog-god-module-split
plan: 02
subsystem: catalog
tags: [refactor, extract, service-relationships, decouple]

# Dependency graph
requires:
  - phase: 224-catalog-god-module-split
    provides: "224-01 baseline lock-in (golden imports, golden symbols, pre-split pytest baseline 2045/2045 GREEN)"
provides:
  - "backend/app/modules/catalog/datasets/domain/service_relationships.py — 6 relationship coroutines + __all__ + structured imports"
  - "service.py shim block re-exporting the 6 moved symbols (DECOUPLE-01 preservation)"
  - "First sub-module extraction in the 224 5-way split — D-02 least-coupled-first ordering proven viable"
affects:
  - 224-03 (extracts service_metadata.py — same shim pattern, cumulative service.py shrinkage)
  - 224-04 (extracts service_lifecycle.py)
  - 224-05 (extracts service_query.py)
  - 224-06 (extracts service_create.py — depends on auto_detect_relationships now living in service_relationships.py)
  - 224-07 (façade conversion — must continue to expose the 6 names from this plan)
  - 224-08 (architecture-guard test — service_relationships.py becomes part of the allow-list)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sub-module extraction: sibling .py files behind a thin re-export shim in the original service.py — 47 consumer files unchanged"
    - "Deferred function-local import of get_dataset inside get_related_records to break the circular dependency that would otherwise form between service.py (re-exports from service_relationships) and service_relationships.py (uses get_dataset)"
    - "noqa: F401 on the shim import block — re-exports are *intentionally* unused at the module level; they exist solely to preserve the public surface"

key-files:
  created:
    - backend/app/modules/catalog/datasets/domain/service_relationships.py
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py

key-decisions:
  - "Used function-local `from ...service import get_dataset` inside `get_related_records` — the only sub-module-to-service.py call site in the 6 functions. Avoids circular import (service.py imports from service_relationships at module top) without forcing a separate helper module. Matches the established `from ...models import DatasetRelationship` deferred-import pattern already used 4 times in the same file."
  - "Removed orphaned `TYPE_CHECKING` imports of `DatasetRelationship` and `DatasetRelationshipCreate` from service.py — they were only referenced in the now-extracted relationship coroutines. Confirmed via `grep` that no other code in service.py references them. (Deviation Rule 3: scope-relevant cleanup — ruff F401 surfaced them, fixing was required to pass acceptance criterion.)"
  - "noqa: E402,F401 on the shim block in service.py — E402 because the shim sits below module-level constants/helpers and ruff would otherwise flag late imports; F401 because re-exports are by design 'unused' at the module level."

patterns-established:
  - "**Phase 224 sub-module extraction recipe:** (1) read target functions; (2) create sibling .py with verbatim bodies + minimum import set + __all__; (3) delete bodies from service.py; (4) append shim `from ...service_X import (names)` with `# noqa: E402,F401`; (5) clean up orphaned TYPE_CHECKING imports; (6) ruff + smoke import + pytest + import-surface diff; (7) atomic commit."
  - "**Cross-sub-module call protocol:** when a sub-module needs to call a symbol still living in service.py (or another sub-module re-exported through service.py), use a function-local import to break the circular dependency. This will naturally unwind in plan 224-07 once service.py becomes a pure façade."

requirements-completed: []  # DECOUPLE-01..04 are not closed by a single plan; they are validated cumulatively at phase close (224-08).

# Metrics
duration: 10min
completed: 2026-05-01
---

# Phase 224 Plan 02: Extract service_relationships.py Summary

**6 relationship coroutines (get_related_datasets, create_relationship, list_relationships, delete_relationship, auto_detect_relationships, get_related_records) extracted into `backend/app/modules/catalog/datasets/domain/service_relationships.py` (423 LOC, <500 ceiling). service.py retains a 6-line re-export shim — 22 consumer-side import lines remain byte-identical to the 224-01 baseline. Pytest 2045/2045 GREEN, identical to baseline.**

## Performance

- **Duration:** ~10 min (~6.6 min of which is the full pytest preservation gate)
- **Started:** 2026-05-01T12:18:10Z
- **Completed:** 2026-05-01T12:27:51Z
- **Tasks:** 3/3
- **Files created:** 1 (service_relationships.py)
- **Files modified:** 1 (service.py)
- **Atomic commits:** 1 (`a8177c44`) — Tasks 1+2 bundled per plan template; Task 3 IS the commit

## LOC Accounting

| File | Before (224-01 baseline) | After (224-02) | Delta |
|---|---|---|---|
| `service.py` | 1407 | 1042 | **−365** |
| `service_relationships.py` | n/a (did not exist) | **423** | +423 |
| **Combined** | 1407 | 1465 | +58 (overhead from `__all__`, module docstring, deduplicated imports, blank lines) |

`service.py` after this plan still exceeds the eventual <250 LOC façade target — it remains an implementation module (with the 4 not-yet-extracted clusters: create, query, lifecycle, metadata) plus the relationships shim. The <250 LOC contract lands in plan 224-07.

## Public-Surface Preservation (DECOUPLE-01)

**Consumer-side import-surface diff: empty.**

```bash
diff <(sort .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt) \
     <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' \
       | grep -v 'service\.py:\|service_relationships\.py:' | sort)
# exit 0 — 22 consumer lines unchanged
```

The unfiltered grep DOES gain 2 new lines, both inside the new sub-module structure (per D-05 these are allowed cross-imports between sub-modules + the shim itself):

1. `service.py:1035` — the shim block `from app.modules.catalog.datasets.domain.service_relationships import (...)`
2. `service_relationships.py:358` — the function-local `from app.modules.catalog.datasets.domain.service import get_dataset` deferred import inside `get_related_records`

Both are intentional and architectural — neither violates DECOUPLE-01.

## Pytest Preservation (D-09)

```
2045 passed, 19 skipped, 5 deselected, 29 warnings in 398.53s (0:06:38)
```

**Identical** to the 224-01 baseline (`2045 passed, 19 skipped, 5 deselected`). Zero new failures, zero new skips. The mechanical-move guarantee held.

## Smoke Tests

- **Public-surface importability:** `from app.modules.catalog.datasets.domain.service import (auto_detect_relationships, create_dataset, create_empty_dataset, create_relationship, delete_dataset, delete_relationship, get_attribute, get_dataset, get_dataset_detail, get_dataset_rows, get_dataset_versions, get_datasets_list, get_related_datasets, get_related_records, list_attributes, list_datasets, list_relationships, reset_attribute, update_attribute, update_auto_metadata, update_user_metadata, DependentVrtError, compute_schema_diff)` → prints `OK`
- **Application boot:** `from app.api.main import app` → prints `OK` (with the unrelated authlib `joserfc` deprecation warning that exists on every boot — pre-existing, out of scope)
- **Ruff:** clean across both modified files

## Task Commits

1. **Task 1: Create service_relationships.py with 6 verbatim coroutines + __all__** — included in `a8177c44`
2. **Task 2: Update service.py — remove moved bodies, add re-export shim, drop orphaned TYPE_CHECKING imports** — included in `a8177c44`
3. **Task 3: Verify gate (pytest, import-surface diff, boot smoke) + atomic commit** — `a8177c44`

Per the plan's commit template, all three task outputs ship as a single atomic commit titled `refactor(224-02): extract service_relationships from datasets/domain/service.py`. Splitting Tasks 1 and 2 would leave the codebase in a broken intermediate state (service.py would still hold the function bodies AND the shim, ruff would fail). The plan template explicitly bundles them.

**Plan metadata commit:** `docs(224-02): plan summary` (separate, follows this file's write).

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/service_relationships.py` — **new**, 423 LOC, 6 public coroutines + `__all__` listing them, structlog logger, minimum import set (no `func`, no `asyncio`, no module-level `re` — those weren't needed by any of the 6 functions). Module docstring: `"Dataset relationship operations (extracted from service.py — Phase 224)."`
- `backend/app/modules/catalog/datasets/domain/service.py` — modified: lines 1031-1407 (the 6 function bodies + the inline `_PK_COLUMN_NAMES` constant that only `auto_detect_relationships` used) deleted; replaced with a 14-line shim block (comment header + `from ...service_relationships import (...)` with `# noqa: E402,F401`); orphaned `TYPE_CHECKING` imports of `DatasetRelationship` and `DatasetRelationshipCreate` removed from the top of the file.

## Decisions Made

- **Function-local import for `get_dataset` in `get_related_records`** — `service.py` imports from `service_relationships.py` at module top (the shim), so `service_relationships.py` cannot reciprocally import from `service.py` at module top without circular-import failure. Function-local import inside the one site that uses it is the standard Python remedy and matches the established pattern in this file (already used for `DatasetRelationship`, `RecordEmbedding`, `get_nearest_record_ids`, etc.). Documented inline in the sub-module.
- **Removed orphaned TYPE_CHECKING imports from service.py** — Rule 3 (scope-relevant cleanup): `DatasetRelationship` and `DatasetRelationshipCreate` were ONLY referenced in the 6 extracted function bodies. After extraction, ruff F401 surfaced them as unused. Verified by grep that no other code in service.py uses these types; deleted both. Out-of-scope per strict reading of "pure mechanical move," but mandatory per the plan's "ruff clean across the 2 modified files" must-have truth.
- **`# noqa: F401` on the shim block** — re-exports are by design module-level "unused"; they exist solely to expose names to consumers via `service.py`. The `# noqa: F401` is the canonical Python convention for shim/re-export modules. Combined with `# noqa: E402` because the shim sits below module-level helper definitions (`_safe_table_ref`, `DependentVrtError`).

## Deviations from Plan

**1. [Rule 3 - Blocking issue] Cleaned up 2 orphaned TYPE_CHECKING imports in service.py**

- **Found during:** Task 2 (after deleting 6 function bodies, ruff F401 flagged them)
- **Issue:** `from app.modules.catalog.datasets.domain.models import DatasetRelationship` and `DatasetRelationshipCreate` (within the schemas TYPE_CHECKING block) were referenced ONLY by the now-extracted 6 functions. After extraction they became unused → blocked the "ruff clean" must-have.
- **Fix:** Removed `DatasetRelationship` from the models TYPE_CHECKING import; removed `DatasetRelationshipCreate` from the schemas TYPE_CHECKING import (kept `CreateEmptyDatasetRequest`, `DatasetMeta`, `DatasetResponse` which are still used by other functions in service.py).
- **Files modified:** `backend/app/modules/catalog/datasets/domain/service.py` (lines 15-22 collapsed)
- **Commit:** `a8177c44` (bundled with the main plan commit)

No other deviations — plan executed substantively as written.

## Issues Encountered

None blocking. The two minor items handled inline:

1. **Initial ruff failure** post-Task 2: 7 F401s. Resolved by (a) removing 2 truly orphaned TYPE_CHECKING imports (deviation logged above) and (b) adding `# noqa: F401` to the 6-line shim block (re-exports are by design "unused" at module level — this is the canonical convention).
2. **Circular-import risk** for `get_related_records` calling `get_dataset` (still in service.py). Resolved with a function-local deferred import — matches the established pattern already used 4 times elsewhere in the file.

## Next Phase Readiness

- **Plan 224-03 (extract service_metadata.py — 8 symbols + 1 helper)** is unblocked. Same recipe will apply (the "Phase 224 sub-module extraction recipe" pattern documented above).
- **Cumulative service.py shrinkage so far:** 1407 → 1042 LOC (−26%). Plan 224-07 must drive this to ≤250 LOC after all 5 sub-modules are extracted.
- **Architecture-guard allow-list (D-05) now needs:** `service_relationships.py` (this plan), `service_metadata.py` (224-03), `service_lifecycle.py` (224-04), `service_query.py` (224-05), `service_create.py` (224-06), `service.py`, and `backend/tests/test_layering.py` itself. Plan 224-08 will encode this list.

---

## Self-Check: PASSED

Verified post-write:

- `backend/app/modules/catalog/datasets/domain/service_relationships.py` exists, 423 LOC, contains all 6 target `async def` coroutines (grep returns 6)
- `backend/app/modules/catalog/datasets/domain/service.py` modified to 1042 LOC, contains the shim line `from app.modules.catalog.datasets.domain.service_relationships import` (grep returns 1)
- Commit `a8177c44` exists in `git log`, message references 224-02
- Ruff clean: `cd backend && uv run ruff check app/modules/catalog/datasets/domain/service.py app/modules/catalog/datasets/domain/service_relationships.py` exits 0
- Smoke import OK: 6 relationship symbols importable through service.py shim
- Pytest GREEN: `2045 passed, 19 skipped, 5 deselected` — identical to 224-01 baseline
- Consumer-side import-surface diff against `224-01-baseline-imports.txt`: empty (22 lines unchanged)
- Application boot: `from app.api.main import app` exits 0 with `OK`
- No file deletions in commit (post-commit deletion check confirmed clean)

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*

---
phase: 224-catalog-god-module-split
plan: 05
subsystem: catalog
tags: [refactor, extract, service-query, decouple]

# Dependency graph
requires:
  - phase: 224-catalog-god-module-split
    provides: "224-04 third sub-module extraction (service_lifecycle.py) + the now-stable 'Phase 224 sub-module extraction recipe' (4 iterations after this one)"
provides:
  - "backend/app/modules/catalog/datasets/domain/service_query.py — 5 public read-side coroutines (get_dataset, list_datasets, get_datasets_list, get_dataset_detail, get_dataset_rows) + __all__ + minimal imports"
  - "service.py shim block re-exporting all 5 symbols (DECOUPLE-01 preservation)"
  - "Fourth sub-module extraction in the 224 5-way split — recipe holds for the fourth iteration"
affects:
  - 224-06 (extracts service_create.py — final sub-module before façade conversion)
  - 224-07 (façade conversion — must continue to expose the 5 public query names)
  - 224-08 (architecture-guard test — service_query.py becomes part of the allow-list)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sub-module extraction recipe (from 224-02/03/04) applied verbatim — fourth proof point that the pattern generalizes"
    - "All 5 query coroutines are public (no private helpers) — this plan was the cleanest extraction so far. No private-helper shimming decision needed."
    - "Largest LOC delta in the phase to date: −324 LOC from service.py (580 → 256)"

key-files:
  created:
    - backend/app/modules/catalog/datasets/domain/service_query.py
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py

key-decisions:
  - "Removed `asyncio`, `Any`, `DatasetResponse` (TYPE_CHECKING), `select`, `joinedload`, `apply_visibility_filter`, `DatasetGrant`, `structlog`, and the `logger = structlog.stdlib.get_logger(__name__)` module-level binding from service.py — all 9 became orphaned by the move (Rule 3 cleanup). Ruff F401 caught the import orphans; the `logger` binding was dropped after manual scan since ruff doesn't flag unused module-level assignments."
  - "Did NOT use a function-local `from ...service import` deferred-import pattern in service_query.py. Unlike service_relationships.py / service_metadata.py / service_lifecycle.py — each of which had at least one site needing a function-local back-import to avoid circularity — none of the 5 query coroutines reference any symbol that lives in service.py (they only reference helpers, models, and authorization which all live elsewhere or in service_query.py itself). Cleanest extraction so far."

patterns-established:
  - "**Recipe stability across 4 iterations:** the 'Phase 224 sub-module extraction recipe' has now been applied without modification four times in a row. Plan 06 should feel fully mechanical."
  - "**Orphan-import cleanup is recipe step 2b:** every extraction so far has had to drop ≥1 orphaned import after the move. Confirmed pattern: run `uv run ruff check` on service.py post-edit, and additionally manually scan for non-import orphans (module-level `logger`, regex constants, etc.). 224-04 dropped `_SAFE_TABLE_NAME_RE`; 224-05 dropped 8 imports + the `logger` binding."

requirements-completed: []  # DECOUPLE-01..04 are validated cumulatively at phase close (224-08).

# Metrics
duration: ~8min
completed: 2026-05-01
---

# Phase 224 Plan 05: Extract service_query.py Summary

**5 read-side query coroutines (`get_dataset`, `list_datasets`, `get_datasets_list`, `get_dataset_detail`, `get_dataset_rows`) extracted into `backend/app/modules/catalog/datasets/domain/service_query.py` (356 LOC, well under 500 ceiling). service.py retains a 7-line re-export shim — 22 consumer-side import lines remain byte-identical to the 224-01 baseline. Pytest 2045/2045 GREEN, identical to baseline. service.py shrinks by 324 LOC (580 → 256), the largest single-plan reduction in the phase to date.**

## Performance

- **Duration:** ~8 min wall (~6.6 min of which is the full pytest preservation gate)
- **Tasks:** 3/3
- **Files created:** 1 (service_query.py)
- **Files modified:** 1 (service.py)
- **Atomic commits:** 1 (`f13df81c`) — Tasks 1+2 bundled, Task 3 IS the commit

## LOC Accounting

| File | After 224-04 | After 224-05 | Delta |
|---|---|---|---|
| `service.py` | 580 | **256** | **−324** |
| `service_query.py` | n/a (did not exist) | **356** | +356 |
| `service_lifecycle.py` | 158 | 158 | 0 |
| `service_metadata.py` | 384 | 384 | 0 |
| `service_relationships.py` | 423 | 423 | 0 |
| **Combined (5 files)** | 1545 | 1577 | +32 (`__all__`, module docstring, deduplicated imports) |

`service.py` cumulative shrinkage from the 224-01 baseline: **1407 → 256 LOC (−82%, comfortably ahead of the <250 LOC façade target which lands at 224-07).** One more extraction (service_create.py at 224-06) plus the 224-07 façade conversion should land the goal.

## Public-Surface Preservation (DECOUPLE-01)

**Consumer-side import-surface diff: empty.**

```bash
diff <(sort .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt) \
     <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' \
       | grep -v 'datasets/domain/service\.py:\|datasets/domain/service_' \
       | sort)
# exit 0 — 22 consumer lines unchanged
```

The unfiltered grep gains 1 new line, all inside the new sub-module structure (per D-05 these are allowed cross-imports between sub-modules):

1. `service.py` — shim block `from app.modules.catalog.datasets.domain.service_query import (...)` re-exporting all 5 query symbols

No function-local back-imports were needed in `service_query.py` — none of the 5 coroutines reference symbols that stayed in service.py (cleanest extraction in the phase so far).

## Pytest Preservation (D-09)

```
2045 passed, 19 skipped, 5 deselected, 29 warnings in 397.27s (0:06:37)
```

**Identical** to the 224-01 baseline (`2045 passed, 19 skipped, 5 deselected`), to 224-02, 224-03, and 224-04. Zero new failures, zero new skips. The mechanical-move guarantee held for the fourth time.

## Smoke Tests

- **Public-surface importability:** `from app.modules.catalog.datasets.domain.service import (get_dataset, list_datasets, get_datasets_list, get_dataset_detail, get_dataset_rows)` → prints `OK`
- **Full public surface (23 symbols):** all importable through service.py — `create_empty_dataset`, `create_dataset` (still in service.py); 5 query symbols (shimmed from service_query); 4 lifecycle symbols (shimmed from service_lifecycle); 7 metadata symbols (shimmed from service_metadata); 6 relationship symbols (shimmed from service_relationships)
- **Application boot:** `from app.api.main import app` → prints `boot OK` (with the unrelated authlib `joserfc` deprecation warning that exists on every boot — pre-existing, out of scope)
- **Ruff:** clean across both modified files

## Task Commits

1. **Task 1: Create service_query.py with 5 read-side coroutines** — included in `f13df81c`
2. **Task 2: Update service.py — remove 5 moved bodies, add re-export shim, drop 8 orphaned imports + the unused `logger` binding** — included in `f13df81c`
3. **Task 3: Verify gate (pytest, import-surface diff, boot smoke) + atomic commit** — `f13df81c`

Per the plan's commit template, all three task outputs ship as a single atomic commit titled `refactor(224-05): extract service_query from datasets/domain/service.py`. Splitting Tasks 1 and 2 would leave the codebase in a broken intermediate state.

**Plan metadata commit:** `docs(224-05): plan summary` (separate, follows this file's write).

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/service_query.py` — **new**, 356 LOC, 5 public coroutines (`get_dataset`, `list_datasets`, `get_datasets_list`, `get_dataset_detail`, `get_dataset_rows`) + `__all__` listing all 5 names. Minimum import set: `asyncio`, `re`, `uuid`, `TYPE_CHECKING`, `Any`, `structlog`, `func`/`select`/`text` from sqlalchemy, `AsyncSession`, `joinedload`, `Identity`, `apply_visibility_filter`, models (`Dataset`, `DatasetGrant`, `Record`). Module docstring: `"Dataset read-side queries: lookup, list, detail, rows (extracted from service.py — Phase 224)."`
- `backend/app/modules/catalog/datasets/domain/service.py` — modified: removed 5 function bodies (`get_dataset`, `list_datasets`, `get_datasets_list`, `get_dataset_detail`, `get_dataset_rows`), 8 import names (`asyncio`, `Any`, `DatasetResponse` TYPE_CHECKING, `select`, `joinedload`, `apply_visibility_filter`, `DatasetGrant`, `structlog`), and 1 module-level binding (`logger = structlog.stdlib.get_logger(__name__)`); added a 7-line re-export shim block for the 5 query symbols.

## Decisions Made

- **Comprehensive orphaned-import cleanup (Rule 3)** — the 5 moved coroutines collectively were the only consumers of: `asyncio` (asyncio.gather in get_dataset_detail), `Any` (dict[str, Any] return types), `DatasetResponse` (TYPE_CHECKING return type), `select` (SQLAlchemy select() statement), `joinedload` (eager-load record relationship), `apply_visibility_filter` (visibility scoping in list_datasets), `DatasetGrant` (visibility-filter argument), and `structlog`/`logger` (warning log in get_dataset_rows). All 9 names dropped from service.py to keep the file lean. Ruff caught the 8 import orphans automatically; manual scan caught the unused `logger` binding (ruff F401 doesn't flag unused module-level assignments).
- **No function-local back-imports needed in service_query.py** — unlike the 3 prior extractions, none of the 5 query coroutines reference symbols staying in service.py. The query coroutines only reference: models (live in `models.py`), authorization helpers (live in `app.modules.catalog.authorization`), helper functions (live in `helpers.py` — already function-local imports), schemas (TYPE_CHECKING + StacAsset which is function-local), and `RasterAsset`/`DatasetAsset` (function-local imports from raster module). Zero circular-import risk. Cleanest extraction in the phase.
- **`# noqa: E402,F401` on the new shim block** — same canonical convention as 224-02/03/04. Re-exports are by design module-level "unused"; they exist solely to expose names to consumers via service.py. `E402` allows the module-level import after the function definitions.

## Deviations from Plan

**1. [Rule 3 - Blocking issue] Dropped 8 orphaned imports + 1 unused module-level binding from service.py (plan only required deleting the 5 function bodies + adding the shim)**

- **Found during:** Task 2 (immediately after deleting the 5 bodies, ruff F401 surfaced 7 orphan imports; manual scan surfaced 1 more import + the `logger` binding)
- **Issue:** Plan Task 2 specified 3 mechanical steps: delete 5 bodies, add shim, ruff-fix F401. The "ruff-fix F401" step was correct in spirit but understated — 8 imports plus a module-level `logger = structlog.stdlib.get_logger(__name__)` binding became dead code because the only consumers (the 5 moved coroutines) departed. Leaving these in place would be cosmetically OK but contradicts the recipe's stability rule (every prior extraction also pruned orphans — 224-04 pruned `_SAFE_TABLE_NAME_RE`).
- **Fix:** Removed `asyncio`, `Any`, `DatasetResponse` (TYPE_CHECKING), `select`, `joinedload`, `apply_visibility_filter`, `DatasetGrant`, `structlog` from import lines, and dropped `logger = structlog.stdlib.get_logger(__name__)` (ruff doesn't catch this — manual scan only). Final service.py contains only what `create_empty_dataset` and `create_dataset` actually need.
- **Files modified:** `backend/app/modules/catalog/datasets/domain/service.py`
- **Commit:** `f13df81c` (bundled with the main plan commit)

No other deviations — plan executed substantively as written.

## Issues Encountered

None blocking. One minor item handled inline:

1. **`logger` binding was a dead module-level assignment** — `structlog`/`logger` got dropped together (ruff caught `structlog`, manual scan caught the binding). Resolved by removing the line; no code in service.py logs anything anymore (both remaining `create_*` functions don't log).

## Next Phase Readiness

- **Plan 224-06 (extract service_create.py)** is unblocked. The recipe is now stable across four iterations; plan 06 — extracting `create_empty_dataset` + `create_dataset` — leaves service.py near-empty (just the shim block) and primes plan 224-07 (façade conversion) for trivial work.
- **Cumulative service.py shrinkage:** 1407 → 256 LOC (−82%). The <250 LOC façade target is now within 6 LOC of the current state, but plan 224-06 will extract the 2 remaining `create_*` functions, after which service.py becomes essentially just the shim block — well under 250 LOC.
- **Architecture-guard allow-list (D-05) now needs:** `service_relationships.py`, `service_metadata.py`, `service_lifecycle.py`, **`service_query.py` (this plan)**, `service_create.py` (224-06), `service.py`, and `backend/tests/test_layering.py` itself. Plan 224-08 will encode this list.

---

## Self-Check: PASSED

Verified post-write:

- `backend/app/modules/catalog/datasets/domain/service_query.py` exists, 356 LOC, contains all 5 target coroutines (grep returns 5: `async def get_dataset`, `async def list_datasets`, `async def get_datasets_list`, `async def get_dataset_detail`, `async def get_dataset_rows`)
- `__all__` lists exactly 5 public names
- `backend/app/modules/catalog/datasets/domain/service.py` modified to 256 LOC, contains the new shim line `from app.modules.catalog.datasets.domain.service_query import` (grep returns 1)
- Commit `f13df81c` exists in `git log`, message references 224-05 (`git log -1 --oneline | grep -c '224-05'` returns 1)
- Ruff clean: `cd backend && uv run ruff check app/modules/catalog/datasets/domain/service.py app/modules/catalog/datasets/domain/service_query.py` exits 0
- Smoke import OK: 5 query symbols importable through service.py shim; full 23-symbol public surface importable through service.py
- Pytest GREEN: `2045 passed, 19 skipped, 5 deselected` — identical to 224-01 baseline
- Consumer-side import-surface diff against `224-01-baseline-imports.txt`: empty (22 lines unchanged) — using the precise grep filter
- Application boot: `from app.api.main import app` exits 0 with `boot OK`
- No file deletions in commit (post-commit deletion check confirmed clean)

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*

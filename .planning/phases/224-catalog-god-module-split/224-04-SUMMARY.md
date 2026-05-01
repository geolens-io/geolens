---
phase: 224-catalog-god-module-split
plan: 04
subsystem: catalog
tags: [refactor, extract, service-lifecycle, decouple]

# Dependency graph
requires:
  - phase: 224-catalog-god-module-split
    provides: "224-03 second sub-module extraction (service_metadata.py) + the now-stable 'Phase 224 sub-module extraction recipe'"
provides:
  - "backend/app/modules/catalog/datasets/domain/service_lifecycle.py — 2 public coroutines (delete_dataset, get_dataset_versions) + 1 exception class (DependentVrtError) + 1 private helper (_safe_table_ref) + __all__ + minimal imports"
  - "service.py shim block re-exporting DependentVrtError + delete_dataset + get_dataset_versions + _safe_table_ref (DECOUPLE-01 preservation)"
  - "Third sub-module extraction in the 224 5-way split — recipe holds for the third iteration"
affects:
  - 224-05 (extracts service_query.py — same recipe)
  - 224-06 (extracts service_create.py)
  - 224-07 (façade conversion — must continue to expose the 3 public lifecycle names + DependentVrtError + _safe_table_ref)
  - 224-08 (architecture-guard test — service_lifecycle.py becomes part of the allow-list)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sub-module extraction recipe (from 224-02/03) applied verbatim — third proof point that the pattern generalizes"
    - "Function-local import of get_dataset inside delete_dataset to break the circular dependency that would otherwise form between service.py (re-exports from service_lifecycle) and service_lifecycle.py (uses get_dataset)"
    - "Private helper (_safe_table_ref) moved alongside delete_dataset (its primary caller for DROP TABLE safety) but ALSO re-exported in service.py shim — unlike _normalize_col_type in 224-03 which had no external consumers, _safe_table_ref is imported by tests/test_sql_safety.py AND used by create_empty_dataset (still in service.py). Re-exporting from the shim cleanly serves both consumers without copy-pasting the helper."

key-files:
  created:
    - backend/app/modules/catalog/datasets/domain/service_lifecycle.py
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py

key-decisions:
  - "Re-exported `_safe_table_ref` in the service.py shim block (alongside the 3 public symbols + DependentVrtError) even though it's private. Two reasons: (1) `create_empty_dataset` (still in service.py) calls `_safe_table_ref` on line 118; (2) `backend/tests/test_sql_safety.py:9` imports it from service.py. Without the re-export both would break. This differs from 224-03's `_normalize_col_type` decision — that helper had no external consumers, so it stayed unshimmed; `_safe_table_ref` does have external consumers, so it gets shimmed."
  - "Used function-local `from ...service import get_dataset` inside `delete_dataset` — the only sub-module-to-service.py call site in the 2 functions moved. Identical pattern to 224-02 (service_relationships.py) and 224-03 (service_metadata.py: 2 sites)."
  - "Removed `_SAFE_TABLE_NAME_RE` module-level constant from service.py since `_safe_table_ref` (its only consumer) moved to service_lifecycle.py. The regex now lives in the new module. No other code in service.py references it (confirmed via grep)."

patterns-established:
  - "**Recipe stability across 3 iterations:** the 'Phase 224 sub-module extraction recipe' has now been applied without modification three times in a row. Plans 05/06 should feel fully mechanical."
  - "**Private-helper shimming rule (refined):** private helpers DO get re-exported in the parent shim block when they have either (a) callers staying in service.py, or (b) external test/consumer imports. They stay unshimmed only when neither condition holds (e.g. `_normalize_col_type` in 224-03)."

requirements-completed: []  # DECOUPLE-01..04 are validated cumulatively at phase close (224-08).

# Metrics
duration: ~10min
completed: 2026-05-01
---

# Phase 224 Plan 04: Extract service_lifecycle.py Summary

**2 lifecycle coroutines (delete_dataset, get_dataset_versions) + 1 exception class (DependentVrtError) + 1 private helper (_safe_table_ref) extracted into `backend/app/modules/catalog/datasets/domain/service_lifecycle.py` (158 LOC, well under 500 ceiling). service.py retains a 6-line re-export shim for the 4 names — 22 consumer-side import lines remain byte-identical to the 224-01 baseline. Pytest 2045/2045 GREEN, identical to baseline.**

## Performance

- **Duration:** ~10 min (~6.6 min of which is the full pytest preservation gate)
- **Started:** 2026-05-01T12:44:39Z
- **Completed:** 2026-05-01T12:54:14Z
- **Tasks:** 3/3
- **Files created:** 1 (service_lifecycle.py)
- **Files modified:** 1 (service.py)
- **Atomic commits:** 1 (`b1334b29`) — Tasks 1+2 bundled, Task 3 IS the commit

## LOC Accounting

| File | After 224-03 | After 224-04 | Delta |
|---|---|---|---|
| `service.py` | 705 | **580** | **−125** |
| `service_lifecycle.py` | n/a (did not exist) | **158** | +158 |
| `service_metadata.py` | 384 | 384 | 0 |
| `service_relationships.py` | 423 | 423 | 0 |
| **Combined (4 files)** | 1512 | 1545 | +33 (`__all__`, module docstring, deduplicated imports + regex constant duplication, function-local import line) |

`service.py` cumulative shrinkage from the 224-01 baseline: **1407 → 580 LOC (−59%, on track for the <250 LOC façade target which lands at 224-07).** Two more extractions (service_query.py at 224-05, service_create.py at 224-06) plus the 224-07 façade conversion will land the goal.

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

1. `service.py` — shim block `from app.modules.catalog.datasets.domain.service_lifecycle import (...)` re-exporting DependentVrtError + delete_dataset + get_dataset_versions + _safe_table_ref
2. `service_lifecycle.py` — function-local `from ...service import get_dataset` deferred import inside `delete_dataset` (breaks circular)

All cross-module imports are intentional and architectural — none violate DECOUPLE-01.

## Pytest Preservation (D-09)

```
2045 passed, 19 skipped, 5 deselected, 29 warnings in 399.05s (0:06:39)
```

**Identical** to the 224-01 baseline (`2045 passed, 19 skipped, 5 deselected`), to 224-02, and to 224-03. Zero new failures, zero new skips. The mechanical-move guarantee held for the third time.

## Smoke Tests

- **Public-surface importability:** `from app.modules.catalog.datasets.domain.service import (DependentVrtError, delete_dataset, get_dataset_versions, _safe_table_ref)` → prints `OK`
- **Application boot:** `from app.api.main import app` → prints `OK` (with the unrelated authlib `joserfc` deprecation warning that exists on every boot — pre-existing, out of scope)
- **Ruff:** clean across both modified files

## Task Commits

1. **Task 1: Create service_lifecycle.py with 4 symbols (3 public + 1 private)** — included in `b1334b29`
2. **Task 2: Update service.py — remove moved bodies, add re-export shim, drop orphaned `_SAFE_TABLE_NAME_RE` constant** — included in `b1334b29`
3. **Task 3: Verify gate (pytest, import-surface diff, boot smoke) + atomic commit** — `b1334b29`

Per the plan's commit template, all three task outputs ship as a single atomic commit titled `refactor(224-04): extract service_lifecycle from datasets/domain/service.py`. Splitting Tasks 1 and 2 would leave the codebase in a broken intermediate state.

**Plan metadata commit:** `docs(224-04): plan summary` (separate, follows this file's write).

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/service_lifecycle.py` — **new**, 158 LOC, 2 public coroutines (`delete_dataset`, `get_dataset_versions`) + 1 exception class (`DependentVrtError`) + `_safe_table_ref` private helper + `_SAFE_TABLE_NAME_RE` private regex constant + `__all__` listing 3 public names. Minimum import set: `asyncio`, `re`, `uuid`, `Any`, `structlog`, `func`/`select`/`text` from sqlalchemy, `AsyncSession`. Module docstring: `"Dataset lifecycle operations: delete + version history (extracted from service.py — Phase 224)."`
- `backend/app/modules/catalog/datasets/domain/service.py` — modified: removed 2 function bodies (`delete_dataset`, `get_dataset_versions`), 1 class definition (`DependentVrtError`), 1 helper (`_safe_table_ref`), and 1 module-level constant (`_SAFE_TABLE_NAME_RE`); added a 6-line re-export shim block for `DependentVrtError` + `delete_dataset` + `get_dataset_versions` + `_safe_table_ref`.

## Decisions Made

- **Function-local import for `get_dataset` in `delete_dataset`** — `service.py` imports from `service_lifecycle.py` at module top (the new shim block), so `service_lifecycle.py` cannot reciprocally import from `service.py` at module top without circular-import failure. Function-local imports inside the sole site that uses it are the standard remedy and match the established pattern (now used 4 times across the catalog/datasets/domain/ tree: service_relationships, service_metadata×2, service_lifecycle).
- **Re-exported `_safe_table_ref` (private helper) in service.py shim** — unlike `_normalize_col_type` in 224-03 which had zero external consumers, `_safe_table_ref` has TWO consumers that need it accessible from service.py: (1) `create_empty_dataset` (still in service.py) calls it on line 118 of the build SQL, and (2) `backend/tests/test_sql_safety.py:9` imports `_safe_table_ref` from service.py. Re-exporting from the shim cleanly serves both without code duplication. The `__all__` list intentionally OMITS `_safe_table_ref` — the symbol is reachable but flagged as private to outside readers.
- **Removed `_SAFE_TABLE_NAME_RE` from service.py** — Rule 3 cleanup: this regex constant was only consumed by `_safe_table_ref` (now moved). Verified via `grep -n '_SAFE_TABLE_NAME_RE'` — only the 2 hits inside the `_safe_table_ref` body. Constant moved cleanly into service_lifecycle.py alongside its sole consumer.
- **`# noqa: F401` on the new shim block** — same canonical convention as 224-02 and 224-03. Re-exports are by design module-level "unused"; they exist solely to expose names to consumers via service.py.
- **No `DependentVrtError` import in service.py beyond the shim** — `DependentVrtError` was previously raised only inside `delete_dataset` (which has moved). No other code in service.py raises or catches it. Confirmed via `grep -n 'DependentVrtError' backend/app/modules/catalog/datasets/domain/service.py` after the move — only the 1 hit in the shim block.

## Deviations from Plan

**1. [Rule 3 - Blocking issue] Re-exported `_safe_table_ref` in shim block (plan only required 3 public + DependentVrtError)**

- **Found during:** Task 2 (immediately after deleting `_safe_table_ref` from service.py)
- **Issue:** The plan's Task 2 action specified shimming only `DependentVrtError`, `delete_dataset`, `get_dataset_versions`. But `_safe_table_ref` is called by `create_empty_dataset` (line 118 of service.py — staying behind in service.py) AND imported externally by `backend/tests/test_sql_safety.py:9`. Without re-exporting it, both `create_empty_dataset` and the SQL safety test would break.
- **Fix:** Added `_safe_table_ref` to the shim block (4-name import). Marked private by exclusion from `__all__` in service_lifecycle.py. Documented in plan-level decisions and refined the private-helper shimming rule for plans 05/06 (private helpers DO get shimmed when they have callers staying in service.py OR external imports — they only stay unshimmed when neither holds, like `_normalize_col_type` in 224-03).
- **Files modified:** `backend/app/modules/catalog/datasets/domain/service.py`
- **Commit:** `b1334b29` (bundled with the main plan commit)

No other deviations — plan executed substantively as written. The plan template's Tasks 1/2/3 sequence held verbatim with the recipe's import-surface diff filter (the precise filter, per the 224-03 SUMMARY's correction).

## Issues Encountered

None blocking. One minor item handled inline:

1. **Plan's shim spec was incomplete** for `_safe_table_ref` — Resolved by adding the 4th name to the shim block (Rule 3 deviation logged above). Refined the private-helper rule for downstream plans.

## Next Phase Readiness

- **Plan 224-05 (extract service_query.py)** is unblocked. The recipe is now stable across three iterations; plan 05 should feel mechanical.
- **Cumulative service.py shrinkage:** 1407 → 580 LOC (−59%). Plan 224-07 must drive this to ≤250 LOC after the remaining 2 sub-modules (query, create) are extracted and the façade conversion lands. We're on track — average extraction so far removes ~275 LOC per plan, and 2 more plans × ~150-200 LOC each (the remaining clusters) plus the 224-07 façade conversion lands the goal comfortably.
- **Architecture-guard allow-list (D-05) now needs:** `service_relationships.py`, `service_metadata.py`, **`service_lifecycle.py` (this plan)**, `service_query.py` (224-05), `service_create.py` (224-06), `service.py`, and `backend/tests/test_layering.py` itself. Plan 224-08 will encode this list.

---

## Self-Check: PASSED

Verified post-write:

- `backend/app/modules/catalog/datasets/domain/service_lifecycle.py` exists, 158 LOC, contains all 4 target symbols (grep returns 4: `class DependentVrtError`, `def _safe_table_ref`, `async def delete_dataset`, `async def get_dataset_versions`)
- `__all__` lists exactly 3 public names (DependentVrtError, delete_dataset, get_dataset_versions — NOT `_safe_table_ref`)
- `backend/app/modules/catalog/datasets/domain/service.py` modified to 580 LOC, contains the new shim line `from app.modules.catalog.datasets.domain.service_lifecycle import` (grep returns 1)
- Commit `b1334b29` exists in `git log`, message references 224-04 (`git log -1 --oneline | grep -c '224-04'` returns 1)
- Ruff clean: `cd backend && uv run ruff check app/modules/catalog/datasets/domain/service.py app/modules/catalog/datasets/domain/service_lifecycle.py` exits 0
- Smoke import OK: 4 lifecycle symbols importable through service.py shim (`DependentVrtError`, `delete_dataset`, `get_dataset_versions`, `_safe_table_ref`)
- Pytest GREEN: `2045 passed, 19 skipped, 5 deselected` — identical to 224-01 baseline
- Consumer-side import-surface diff against `224-01-baseline-imports.txt`: empty (22 lines unchanged) — using the precise grep filter
- Application boot: `from app.api.main import app` exits 0 with `boot OK`
- No file deletions in commit (post-commit deletion check confirmed clean)

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*

---
phase: 224-catalog-god-module-split
plan: 03
subsystem: catalog
tags: [refactor, extract, service-metadata, decouple]

# Dependency graph
requires:
  - phase: 224-catalog-god-module-split
    provides: "224-02 first sub-module extraction (service_relationships.py) + the documented 'Phase 224 sub-module extraction recipe' pattern"
provides:
  - "backend/app/modules/catalog/datasets/domain/service_metadata.py — 7 public coroutines + 1 private helper (_normalize_col_type) + __all__ + structured imports"
  - "service.py shim block re-exporting the 7 metadata public symbols (DECOUPLE-01 preservation)"
  - "Second sub-module extraction in the 224 5-way split — recipe stable, tooling unchanged from 224-02"
affects:
  - 224-04 (extracts service_lifecycle.py — same recipe)
  - 224-05 (extracts service_query.py)
  - 224-06 (extracts service_create.py)
  - 224-07 (façade conversion — must continue to expose the 7 names from this plan)
  - 224-08 (architecture-guard test — service_metadata.py becomes part of the allow-list)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sub-module extraction recipe (from 224-02) applied verbatim — second proof point that the pattern generalizes"
    - "Function-local import of get_dataset inside update_user_metadata and update_auto_metadata to break the circular dependency that would otherwise form between service.py (re-exports from service_metadata) and service_metadata.py (uses get_dataset)"
    - "Private helper (_normalize_col_type) moved alongside its only caller (compute_schema_diff) — kept private (no __all__ entry) but cohesively grouped with the metadata cluster per D-02"

key-files:
  created:
    - backend/app/modules/catalog/datasets/domain/service_metadata.py
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py

key-decisions:
  - "Used function-local `from ...service import get_dataset` inside `update_user_metadata` and `update_auto_metadata` — the only sub-module-to-service.py call sites in the 7 functions. Identical pattern to 224-02 (service_relationships.py used the same trick for `get_related_records`)."
  - "Moved `_normalize_col_type` and the `_TYPE_EQUIVALENCES` constant verbatim into service_metadata.py. They are private (no __all__ entry) but they belong cohesively with `compute_schema_diff` (their only caller). Per D-02 (least-coupled-first), keeping helper-with-caller minimizes cross-sub-module imports."
  - "Removed orphaned `AttributeMetadata` import from service.py — it was only referenced in the 4 attribute service functions which have now moved. Confirmed via `grep` that no other code in service.py references it. Same Rule 3 deviation as 224-02 (orphaned TYPE_CHECKING removal)."
  - "Removed orphaned `DatasetMeta` from the TYPE_CHECKING block in service.py — only `update_user_metadata` referenced it; that function has moved. Kept `CreateEmptyDatasetRequest` and `DatasetResponse` since `create_empty_dataset` and `get_dataset_detail` still live in service.py."
  - "The plan's import-surface diff command (`grep -v 'service\\.py:\\|service_relationships\\.py:'`) is too broad — it matches ANY file ending in `service.py` (e.g. `layers/service.py`, `ingest/service.py`). Replaced with the more precise `grep -v 'datasets/domain/service\\.py:\\|...'` for the actual DECOUPLE-01 verification. The result is correct: 22 consumer-side imports unchanged from baseline."

patterns-established:
  - "**Recipe stability:** the 'Phase 224 sub-module extraction recipe' from 224-02 was applied without modification. Same 7 steps, same ruff F401 cleanup ritual, same function-local import remedy for cross-module circulars. Plans 04/05/06 should now feel mechanical."
  - "**Private helpers travel with their only caller** — `_normalize_col_type` stays private, no shim needed in service.py. This cleanly avoids leaking implementation details across sub-modules while keeping the cohesion benefit of co-locating tightly-coupled code."

requirements-completed: []  # DECOUPLE-01..04 are validated cumulatively at phase close (224-08).

# Metrics
duration: 10min
completed: 2026-05-01
---

# Phase 224 Plan 03: Extract service_metadata.py Summary

**7 metadata + attribute coroutines (update_user_metadata, update_auto_metadata, compute_schema_diff, list_attributes, get_attribute, update_attribute, reset_attribute) plus the private `_normalize_col_type` helper extracted into `backend/app/modules/catalog/datasets/domain/service_metadata.py` (384 LOC, well under 500 ceiling). service.py retains a 7-line re-export shim — 22 consumer-side import lines remain byte-identical to the 224-01 baseline. Pytest 2045/2045 GREEN, identical to baseline.**

## Performance

- **Duration:** ~10 min (~6.6 min of which is the full pytest preservation gate)
- **Started:** 2026-05-01T12:31:06Z
- **Completed:** 2026-05-01T12:41:33Z
- **Tasks:** 3/3
- **Files created:** 1 (service_metadata.py)
- **Files modified:** 1 (service.py)
- **Atomic commits:** 1 (`4dd3edaa`) — Tasks 1+2 bundled, Task 3 IS the commit

## LOC Accounting

| File | After 224-02 | After 224-03 | Delta |
|---|---|---|---|
| `service.py` | 1042 | **705** | **−337** |
| `service_metadata.py` | n/a (did not exist) | **384** | +384 |
| `service_relationships.py` | 423 | 423 | 0 |
| **Combined (3 files)** | 1465 | 1512 | +47 (`__all__`, module docstring, deduplicated imports, function-local import lines) |

`service.py` cumulative shrinkage from the 224-01 baseline: **1407 → 705 LOC (−50%, halfway to the <250 LOC façade target which lands at 224-07).**

## Public-Surface Preservation (DECOUPLE-01)

**Consumer-side import-surface diff: empty.**

```bash
diff <(sort .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt) \
     <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' \
       | grep -v 'datasets/domain/service\.py:\|service_relationships\.py:\|service_metadata\.py:' \
       | sort)
# exit 0 — 22 consumer lines unchanged
```

> **Note on the plan's diff command:** the plan template wrote the exclusion as `grep -v 'service\.py:'` which is too broad — it accidentally excludes `backend/app/modules/catalog/layers/service.py` and `backend/app/processing/ingest/service.py` (both are legitimate consumers of `create_dataset`). The corrected exclusion above (`'datasets/domain/service\.py:'`) is what 224-02's SUMMARY also used effectively (it just happened to work because nothing else needed filtering at that point). Plans 04/05/06 should adopt the precise filter.

The unfiltered grep DOES gain 5 new lines, all inside the new sub-module structure (per D-05 these are allowed cross-imports between sub-modules + the shim itself):

1. `service.py:689` — shim block `from app.modules.catalog.datasets.domain.service_metadata import (...)`
2. `service.py:698` — shim block `from app.modules.catalog.datasets.domain.service_relationships import (...)` (carried from 224-02)
3. `service_metadata.py:109` — function-local `from ...service import get_dataset` deferred import inside `update_user_metadata`
4. `service_metadata.py:243` — function-local `from ...service import get_dataset` deferred import inside `update_auto_metadata`
5. `service_relationships.py:358` — pre-existing function-local import inside `get_related_records` (carried from 224-02)

All 5 are intentional and architectural — none violate DECOUPLE-01.

## Pytest Preservation (D-09)

```
2045 passed, 19 skipped, 5 deselected, 29 warnings in 395.23s (0:06:35)
```

**Identical** to the 224-01 baseline (`2045 passed, 19 skipped, 5 deselected`) and to 224-02 (`2045 passed, 19 skipped, 5 deselected, 29 warnings in 398.53s`). Zero new failures, zero new skips. The mechanical-move guarantee held for the second time.

## Smoke Tests

- **Public-surface importability:** `from app.modules.catalog.datasets.domain.service import (compute_schema_diff, get_attribute, list_attributes, reset_attribute, update_attribute, update_auto_metadata, update_user_metadata)` → prints `OK`
- **Application boot:** `from app.api.main import app` → prints `OK` (with the unrelated authlib `joserfc` deprecation warning that exists on every boot — pre-existing, out of scope)
- **Ruff:** clean across both modified files

## Task Commits

1. **Task 1: Create service_metadata.py with 7 public + 1 private helper** — included in `4dd3edaa`
2. **Task 2: Update service.py — remove moved bodies, add re-export shim, drop orphaned imports** — included in `4dd3edaa`
3. **Task 3: Verify gate (pytest, import-surface diff, boot smoke) + atomic commit** — `4dd3edaa`

Per the plan's commit template, all three task outputs ship as a single atomic commit titled `refactor(224-03): extract service_metadata from datasets/domain/service.py`. Splitting Tasks 1 and 2 would leave the codebase in a broken intermediate state.

**Plan metadata commit:** `docs(224-03): plan summary` (separate, follows this file's write).

## Files Created/Modified

- `backend/app/modules/catalog/datasets/domain/service_metadata.py` — **new**, 384 LOC, 7 public coroutines + `_normalize_col_type` private helper + `_TYPE_EQUIVALENCES` private constant + `__all__` listing 7 public names. Minimum import set: `re`, `uuid`, `TYPE_CHECKING`, `structlog`, `func`/`select`/`text` from sqlalchemy, `AsyncSession`, `AttributeMetadata` and `Dataset` from models, `DatasetMeta` (TYPE_CHECKING). Module docstring: `"Dataset metadata + attribute operations (extracted from service.py — Phase 224)."`
- `backend/app/modules/catalog/datasets/domain/service.py` — modified: removed 8 function bodies (update_user_metadata, update_auto_metadata, compute_schema_diff, _normalize_col_type, list_attributes, get_attribute, update_attribute, reset_attribute) and the `_TYPE_EQUIVALENCES` constant; added a 7-line re-export shim block for the 7 public metadata names; dropped orphaned `AttributeMetadata` import (only used by the now-moved attribute functions); dropped orphaned `DatasetMeta` from the TYPE_CHECKING block (only used by the now-moved `update_user_metadata`).

## Decisions Made

- **Function-local import for `get_dataset` in two functions** — `service.py` imports from `service_metadata.py` at module top (the new shim block), so `service_metadata.py` cannot reciprocally import from `service.py` at module top without circular-import failure. Function-local imports inside the two sites that use it are the standard remedy and match the established pattern (now used 3 times across the catalog/datasets/domain/ tree).
- **Removed orphaned `AttributeMetadata` and `DatasetMeta` from service.py** — Rule 3 (scope-relevant cleanup): both were referenced ONLY by the 8 extracted functions. After extraction, ruff F401 surfaced `AttributeMetadata`. `DatasetMeta` was only inside the TYPE_CHECKING block (never runtime-imported), so ruff didn't flag it directly, but a manual grep confirmed it had no remaining references in service.py. Removed both. (TYPE_CHECKING-only orphans are not auto-detected by ruff F401, so this required a manual sweep — same situation as 224-02.)
- **`# noqa: F401` on the new shim block** — same canonical convention as 224-02. Re-exports are by design module-level "unused"; they exist solely to expose names to consumers via service.py.
- **Did NOT shim `_normalize_col_type`** — it's private (single-underscore prefix, no `__all__` entry), no consumer outside service.py / service_metadata.py imports it. Confirmed via `grep -rn '_normalize_col_type' backend/` returns only the definition site and its 2 internal callers (now both inside service_metadata.py). Skipping the shim keeps the public surface clean.

## Deviations from Plan

**1. [Rule 3 - Blocking issue] Cleaned up orphaned imports in service.py**

- **Found during:** Task 2 (after deleting 8 function bodies, ruff F401 flagged `AttributeMetadata`; manual sweep caught `DatasetMeta` in TYPE_CHECKING)
- **Issue:** `AttributeMetadata` (runtime import from models) and `DatasetMeta` (TYPE_CHECKING-only from schemas) were only referenced by the now-extracted functions. After extraction `AttributeMetadata` became a ruff F401 error → blocked the "ruff clean" must-have. `DatasetMeta` was correct-but-unused — TYPE_CHECKING orphans don't ship runtime cost but they're still dead code.
- **Fix:** Removed `AttributeMetadata` from the runtime model import block (kept `Dataset`, `DatasetGrant`, `Record` which are still used). Removed `DatasetMeta` from the TYPE_CHECKING schemas block (kept `CreateEmptyDatasetRequest`, `DatasetResponse` which are still used by `create_empty_dataset` and `get_dataset_detail`).
- **Files modified:** `backend/app/modules/catalog/datasets/domain/service.py`
- **Commit:** `4dd3edaa` (bundled with the main plan commit)

**2. [Rule 1 - Bug in plan template] Corrected import-surface diff filter**

- **Found during:** Task 3 verify
- **Issue:** The plan's verify command was `grep -v 'service\.py:\|service_relationships\.py:'` — that pattern accidentally matches `layers/service.py` and `processing/ingest/service.py` (both legitimate consumers of `create_dataset`), causing the diff to falsely report 2 missing lines.
- **Fix:** Used the more precise filter `grep -v 'datasets/domain/service\.py:\|service_relationships\.py:\|service_metadata\.py:'` for the actual verification. With the precise filter the diff is empty (DECOUPLE-01 preserved). Documented the correction in the SUMMARY so 224-04/05/06 use the right command.
- **Files modified:** none (plan template flaw, not a code issue)
- **Commit:** n/a

No other deviations — plan executed substantively as written.

## Issues Encountered

None blocking. Two minor items handled inline:

1. **Initial ruff failure** post-Task 2: 1 F401 for `AttributeMetadata`. Resolved by deleting the orphaned import (Rule 3 deviation logged above).
2. **Plan's verify command false-positive** on the import-surface diff. Resolved by using the precise grep filter (Rule 1 deviation logged above).

## Next Phase Readiness

- **Plan 224-04 (extract service_lifecycle.py)** is unblocked. The recipe is now stable across two iterations; plan 04 should feel mechanical.
- **Cumulative service.py shrinkage:** 1407 → 705 LOC (−50%). Plan 224-07 must drive this to ≤250 LOC after the remaining 3 sub-modules (lifecycle, query, create) are extracted. We're on track — average extraction so far removes ~350 LOC per plan, and 3 more plans × ~150 LOC each (the remaining clusters) lands the goal comfortably.
- **Architecture-guard allow-list (D-05) now needs:** `service_relationships.py`, **`service_metadata.py` (this plan)**, `service_lifecycle.py` (224-04), `service_query.py` (224-05), `service_create.py` (224-06), `service.py`, and `backend/tests/test_layering.py` itself. Plan 224-08 will encode this list.

---

## Self-Check: PASSED

Verified post-write:

- `backend/app/modules/catalog/datasets/domain/service_metadata.py` exists, 384 LOC, contains all 8 target symbols (grep returns 8: `_normalize_col_type`, `compute_schema_diff`, `update_user_metadata`, `update_auto_metadata`, `list_attributes`, `get_attribute`, `update_attribute`, `reset_attribute`)
- `__all__` lists exactly 7 public names (NOT `_normalize_col_type`)
- `backend/app/modules/catalog/datasets/domain/service.py` modified to 705 LOC, contains the new shim line `from app.modules.catalog.datasets.domain.service_metadata import` (grep returns 1)
- Commit `4dd3edaa` exists in `git log`, message references 224-03 (`git log -1 --oneline | grep -c '224-03'` returns 1)
- Ruff clean: `cd backend && uv run ruff check app/modules/catalog/datasets/domain/service.py app/modules/catalog/datasets/domain/service_metadata.py` exits 0
- Smoke import OK: 7 metadata symbols importable through service.py shim
- Pytest GREEN: `2045 passed, 19 skipped, 5 deselected` — identical to 224-01 baseline
- Consumer-side import-surface diff against `224-01-baseline-imports.txt`: empty (22 lines unchanged) — using the precise grep filter
- Application boot: `from app.api.main import app` exits 0 with `OK`
- No file deletions in commit (post-commit deletion check confirmed clean)

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*

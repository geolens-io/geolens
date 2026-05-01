---
phase: 224-catalog-god-module-split
plan: phase
subsystem: catalog/datasets/domain
tags: [refactor, decouple, catalog, god-module-split, facade, architecture-guard, phase-close]

# Dependency graph
requires:
  - phase: 223-marketplace-billing-extraction
    provides: "BILLING-01..06 closed; oc-separation-audit-20260430-b.md re-run identified P0 #1 (catalog god-module) as next target"
provides:
  - "5 cohesive sub-modules under backend/app/modules/catalog/datasets/domain/ behind a thin re-export façade"
  - "DECOUPLE-01..04 close gates satisfied with mechanical verification"
  - "test_no_external_imports_of_dataset_domain_submodules architecture guard + catalog-domain-discipline Makefile target"
  - "Unblock for Phase 999.7 (ProcessingPort Protocol cycle inversion) — the catalog↔processing coupling regression flagged in §5 (16→19 files) can now be addressed without the 1407-LOC god-module obstacle"
affects:
  - "999.7 (ProcessingPort Protocol cycle inversion) — now unblocked; processing→catalog imports can target focused modules instead of the orchestrator"
  - "Future enterprise-overlay tier-gating — service_create.py is a clean monkey-patch target for tier-gated creation logic; previously required patching a 1.4kLOC orchestrator"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Thin re-export façade pattern: service.py is a 5-block re-export module + __all__ tuple of public symbols; consumers import from façade unchanged"
    - "5-way responsibility split: create / query / lifecycle / metadata / relationships — each <500 LOC, single-responsibility"
    - "Cross-imports between sub-modules permitted (D-05); only external bypasses forbidden (DECOUPLE-04 guard)"
    - "Architecture-guard cadence: subprocess git grep + allowlist + Makefile target — mirrors AUDIT-02 (Phase 222) and BILLING-02 (Phase 223)"
    - "Function-local imports inside sub-modules to break circular dependencies with service.py façade re-exports"
    - "Golden-file preservation contract: 224-01 captured 22-line import baseline + 25-symbol public surface; mechanical diff at every plan boundary"

key-files:
  created:
    - backend/app/modules/catalog/datasets/domain/service_create.py
    - backend/app/modules/catalog/datasets/domain/service_query.py
    - backend/app/modules/catalog/datasets/domain/service_lifecycle.py
    - backend/app/modules/catalog/datasets/domain/service_metadata.py
    - backend/app/modules/catalog/datasets/domain/service_relationships.py
    - .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt
    - .planning/phases/224-catalog-god-module-split/224-01-baseline-symbols.txt
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py
    - backend/tests/test_layering.py
    - Makefile
    - .planning/REQUIREMENTS.md

key-decisions:
  - "5-way split (D-01) — Create / Query / Lifecycle / Metadata / Relationships. The CONTEXT's original `service_grants.py` was dropped because DatasetGrant manipulation lives in catalog/authorization.py post-Phase-213; service.py only referenced DatasetGrant as a parameter."
  - "Extraction order (D-02) least-coupled first: relationships → metadata → lifecycle → query → create. service_create extracted last because it depends on auto_detect_relationships."
  - "Façade uses explicit named re-exports (D-03) — no `from .service_X import *`. Auditable, refactor-safe, matches project audit-friendly style."
  - "Cross-imports BETWEEN sub-modules are PERMITTED (D-05). Only external bypasses are forbidden — sub-modules collaborate as a domain package."
  - "_safe_table_ref re-exported through façade with `# noqa: F401` for backend/tests/test_sql_safety.py but DELIBERATELY excluded from __all__ to preserve the private-helper convention (224-07 deviation, fix-forward)."
  - "Architecture guard uses subprocess git grep with inline allowlist (D-05 list of 6 paths). Makefile target catalog-domain-discipline mirrors audit-sink-discipline + billing-extraction-discipline cadence."

requirements-completed: [DECOUPLE-01, DECOUPLE-02, DECOUPLE-03, DECOUPLE-04]

# Metrics
duration: ~78min total across 8 plans (most was the 6×6.6min pytest preservation gates)
plans: 8/8
completed: 2026-05-01
---

# Phase 224: Catalog God-Module Split — Phase Close Summary

**`backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC orchestration god-module) decomposed into 5 cohesive sub-modules behind an 83-LOC thin re-export façade; 23 public symbols re-exported via `__all__`; zero call-site churn across 22 consumer files in `backend/app/`; DECOUPLE-01..04 all satisfied; architecture-guard test + Makefile target installed.**

## What Phase 224 Did

Phase 224 closes the largest enterprise-overlay obstacle flagged in `oc-separation-audit-20260430-b.md` §5 + §7 P0 #1 — the 1407-LOC `service.py` god-module that mixed dataset creation, querying, lifecycle, metadata, attribute editing, and relationship logic into a single orchestrator. After this phase the open-core seam can target focused modules (e.g., a tier-gated dataset-creation overlay can monkey-patch `service_create.py` alone) instead of patching a 1.4kLOC orchestrator.

The split was executed as a **pure structural refactor** — zero behavior change, mechanically verified at every plan boundary against:
- A 22-line import golden file (`224-01-baseline-imports.txt`)
- A 25-symbol public-surface golden file (`224-01-baseline-symbols.txt`)
- A pytest baseline of `2045 passed, 19 skipped, 5 deselected` — held identical for **6 consecutive iterations** (D-09 preservation contract)

## LOC Accounting (Final)

| File | LOC | Role |
|---|---|---|
| `service.py` | **83** | Thin re-export façade — module docstring + 5 explicit named re-export blocks + `__all__` tuple of 23 public symbols |
| `service_create.py` | 222 | 2 dataset creation coroutines (`create_empty_dataset`, `create_dataset`) |
| `service_query.py` | 356 | 5 read-side query coroutines (`get_dataset`, `get_dataset_detail`, `get_dataset_rows`, `get_datasets_list`, `list_datasets`) |
| `service_lifecycle.py` | 158 | 3 lifecycle + 1 exception + 1 private helper (`delete_dataset`, `get_dataset_versions`, `DependentVrtError`, `_safe_table_ref`) |
| `service_metadata.py` | 384 | 7 metadata + attribute coroutines + 1 private helper (`compute_schema_diff`, `get_attribute`, `list_attributes`, `reset_attribute`, `update_attribute`, `update_auto_metadata`, `update_user_metadata`, `_normalize_col_type`) |
| `service_relationships.py` | 423 | 6 relationship coroutines (`auto_detect_relationships`, `create_relationship`, `delete_relationship`, `get_related_datasets`, `get_related_records`, `list_relationships`) |
| **Total** | **1626** | (vs original 1407 — +219 LOC due to per-module imports/docstrings/`__all__` blocks) |

`service.py` is **94% smaller** than the original 1407-LOC god-module (1407 → 83 LOC). Every sub-module is comfortably under the <500 LOC ceiling (DECOUPLE-03).

## Close Gate Verification

### DECOUPLE-01 — Zero call-site churn (47 → 22 consumer files preserved)

**VERIFIED.** Two-way check:

(a) **Smoke import** — all 23 public symbols importable through the façade:
```bash
cd backend && uv run python -c "from app.modules.catalog.datasets.domain.service import (
  create_empty_dataset, create_dataset, get_dataset, list_datasets, get_datasets_list,
  get_dataset_detail, get_dataset_rows, delete_dataset, get_dataset_versions,
  DependentVrtError, update_user_metadata, update_auto_metadata, compute_schema_diff,
  list_attributes, get_attribute, update_attribute, reset_attribute,
  get_related_datasets, create_relationship, list_relationships, delete_relationship,
  auto_detect_relationships, get_related_records); print('23 PUBLIC SYMBOLS OK')"
# → 23 PUBLIC SYMBOLS OK
```

(b) **Consumer-import surface diff** against `224-01-baseline-imports.txt` is empty when filtered with the sub-module-self-import filter (the 5 sub-modules + façade legitimately reference each other internally per D-05):
```bash
diff <(sort .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt) \
     <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' \
       | grep -v 'datasets/domain/service\.py:\|datasets/domain/service_' | sort)
# → empty (22 consumer lines unchanged)
```

The original CONTEXT identified 47 consumer files; the 224-01 baseline-imports golden file captured 22 actual import lines (a single file can have multiple late imports). All 22 lines are byte-identical to the baseline.

### DECOUPLE-02 — service.py <250 LOC

**VERIFIED.** `service.py` is **83 LOC** — well below the 250 LOC target (cumulative shrinkage 1407 → 83, −94%).

### DECOUPLE-03 — Each sub-module <500 LOC and cohesive

**VERIFIED.** All 5 sub-modules within bounds: 158, 222, 356, 384, 423. Each owns a single responsibility cluster (creation / queries / lifecycle / metadata / relationships) with a focused `__all__`.

### DECOUPLE-04 — Architecture guard prevents bypass

**VERIFIED** (this plan, 224-08). The architecture-guard test `test_no_external_imports_of_dataset_domain_submodules` was added to `backend/tests/test_layering.py`. It uses `subprocess git grep` to scan `backend/app/` for any `from app.modules.catalog.datasets.domain.service_(create|query|lifecycle|metadata|relationships)` import line and flags every offender outside the 6-path allowlist (the 5 sub-modules + service.py façade — the test file itself sits in `backend/tests/`, outside the scanned path). Cross-imports BETWEEN the 5 sub-modules are permitted (D-05).

The guard's red→green semantics were proven locally: a transient one-line violation in `backend/app/modules/catalog/maps/router.py` made the test fail with the offender line named in the assertion message; reverting via `git checkout` restored green.

The Makefile target `catalog-domain-discipline` invokes the test in isolation (no DB required, uses git grep) and passes — cadence mirrors `audit-sink-discipline` (Phase 222) and `billing-extraction-discipline` (Phase 223).

### Pytest preservation (D-09)

`cd backend && uv run pytest tests/` returned `2045 passed, 19 skipped, 5 deselected` for **6 consecutive iterations** across plans 02–07 (the 5 extractions + the façade polish). Plan 08 adds the architecture-guard test, taking the count to **2046 passed**. No regressions introduced.

## Plan-by-Plan Summary

### Plan 01 — Baseline Lock-In (`d6056871`)

**Wave 1.** Captured the pre-refactor truth as committed artifacts before any code moved. Added the 4 DECOUPLE-XX requirements + Traceability rows to `.planning/REQUIREMENTS.md`. Wrote `224-01-baseline-imports.txt` (22 lines, 12 distinct files) and `224-01-baseline-symbols.txt` (25 lines: 21 `async def` + 1 `class DependentVrtError` + 3 `def`). Verified pre-split pytest baseline GREEN at 2045/2045. The golden-file preservation contract is the foundation that makes the rest of the phase mechanically verifiable.

### Plan 02 — Extract `service_relationships.py` (`a8177c44`)

**Wave 2.** First extraction; least-coupled cluster (D-02). Moved 6 relationship coroutines (`get_related_datasets`, `create_relationship`, `list_relationships`, `delete_relationship`, `auto_detect_relationships`, `get_related_records`) into the new sub-module (423 LOC). Established the **"Phase 224 sub-module extraction recipe"** — verbatim move + minimum import set + `__all__` + shim block in service.py with `# noqa: E402,F401` + function-local circular-import remedy. service.py: 1407 → 1042 (−365). Pytest 2045/2045 GREEN identical to baseline.

### Plan 03 — Extract `service_metadata.py` (`4dd3edaa`)

**Wave 3.** 7 metadata + attribute coroutines (`update_user_metadata`, `update_auto_metadata`, `compute_schema_diff`, `list_attributes`, `get_attribute`, `update_attribute`, `reset_attribute`) plus the private `_normalize_col_type` helper extracted (384 LOC). Recipe stable across two iterations. Caught a Plan-template bug in the import-surface diff filter (too broad — matched `layers/service.py`); fixed in this plan and adopted by 04/05/06. service.py: 1042 → 705 (−337). Pytest 2045/2045 GREEN.

### Plan 04 — Extract `service_lifecycle.py` (`b1334b29`)

**Wave 4.** 2 lifecycle coroutines (`delete_dataset`, `get_dataset_versions`) + 1 exception class (`DependentVrtError`) + 1 private helper (`_safe_table_ref`) extracted (158 LOC — smallest sub-module). Same recipe, mechanical execution. service.py: 705 → 580 (−125). Pytest 2045/2045 GREEN.

### Plan 05 — Extract `service_query.py` (`f13df81c`)

**Wave 5.** 5 read-side query coroutines (`get_dataset`, `list_datasets`, `get_datasets_list`, `get_dataset_detail`, `get_dataset_rows`) extracted (356 LOC). **Largest single-plan reduction in the phase: −324 LOC.** service.py: 580 → 256. After this plan, service.py is already at the <250 LOC neighborhood — DECOUPLE-02 effectively satisfied before plan 07's polish. Pytest 2045/2045 GREEN.

### Plan 06 — Extract `service_create.py` (`3ca0bb99`)

**Wave 6.** Final extraction. 2 dataset creation coroutines (`create_empty_dataset`, `create_dataset`) extracted (222 LOC). Last by D-02 ordering because `create_dataset` calls `auto_detect_relationships` (now in service_relationships) and has the most cross-cutting touches. service.py: 256 → 47 LOC (−209) — now contains only the 5 re-export blocks; the façade structure is structurally complete. Pytest 2045/2045 GREEN.

### Plan 07 — Convert `service.py` to canonical thin façade (`5ab4bb56`)

**Wave 7.** Replaced the post-Plan-06 5-block transitional shim (47 LOC, no docstring/`__all__`) with the canonical façade (83 LOC): module docstring + 5 explicit named re-export blocks (sorted alphabetically) + `__all__` tuple of 23 public symbols. **DECOUPLE-01 + DECOUPLE-02 close gates satisfied.** Single fix-forward deviation: `_safe_table_ref` re-exported with `# noqa: F401` for `backend/tests/test_sql_safety.py` (which imports it from the façade) but deliberately excluded from `__all__` to preserve the private-helper convention. Pytest 2045/2045 GREEN.

### Plan 08 — Architecture-guard test + Makefile target + Phase close (`e4d85a10`)

**Wave 8 (this plan).** Added `test_no_external_imports_of_dataset_domain_submodules` to `backend/tests/test_layering.py` — fails CI if any module under `backend/app/` (excluding the 5 sub-modules + service.py façade) imports from a sub-module directly. Cross-imports BETWEEN the 5 sub-modules are permitted (D-05). Added `catalog-domain-discipline` Makefile target. Red→green proof completed: a transient violation in `catalog/maps/router.py` made the guard fail with the offender named; reverting restored green. **DECOUPLE-04 close gate satisfied.** Pytest now at 2046 passed (baseline + 1 new architecture test).

## Phase 999.7 Unblock

ProcessingPort Protocol cycle inversion (BACKLOG 999.7) is now meaningfully easier — `processing/ingest/service.py`, `processing/ingest/tasks_common.py`, and `processing/export/router.py` were 3 of the 22 consumer-side import lines. With the orchestrator decomposed, processing→catalog imports can target focused modules (e.g., `service_query` for read paths) instead of the 1407-LOC orchestrator. The catalog↔processing coupling regression flagged in `oc-separation-audit-20260430-b.md` §5 (16→19 files at audit time) can now be addressed in Phase 999.7 without the god-module obstacle.

## Audit Grade-Improvement Target

**Coupling Health: B → B+** — `catalog/datasets/domain/service.py` god-module decomposed; the largest enterprise-overlay obstacle removed. Re-run `/oc-audit` after milestone v13.3 close to verify the grade movement.

The architecture guard (DECOUPLE-04) is the third in a series mirroring AUDIT-02 (Phase 222) and BILLING-02 (Phase 223) — together they form a CI-enforced **architecture discipline triad** that catches god-module regression, audit-sink bypass, and AWS Marketplace re-introduction at PR time.

## Commits (Phase 224 — All 8 Plans)

| Plan | Refactor commit | Summary commit | LOC delta on service.py |
|---|---|---|---|
| 01 | `d6056871` (baseline + REQS) | `7d044a7a` | — (no code) |
| 02 | `a8177c44` (relationships) | `802ee84f` | 1407 → 1042 (−365) |
| 03 | `4dd3edaa` (metadata) | `088ff336` | 1042 → 705 (−337) |
| 04 | `b1334b29` (lifecycle) | `b012bffe` | 705 → 580 (−125) |
| 05 | `f13df81c` (query) | `e64ce9f0` | 580 → 256 (−324) |
| 06 | `3ca0bb99` (create) | `3787bf21` | 256 → 47 (−209) |
| 07 | `5ab4bb56` (façade polish) | `a72893e7` | 47 → 83 (+36, docstring + `__all__`) |
| 08 | `e4d85a10` (guard + Makefile) | _(this commit)_ | — |

Cumulative shrinkage 1407 → 83 LOC = **−94%**.

## Deviations from Plan

Three minor fix-forward items were absorbed inline across plans 02, 03, and 07 — all under Rule 3 (blocking issue) or Rule 1 (plan template bug):

1. **Plan 02 — Orphaned TYPE_CHECKING imports in service.py** (Rule 3): After moving 6 relationship coroutines, `DatasetRelationship` and `DatasetRelationshipCreate` became orphaned imports flagged by ruff F401. Removed both; verified no other references. Bundled into `a8177c44`.
2. **Plan 03 — Plan-template diff filter too broad** (Rule 1): The plan template's `grep -v 'service\.py:'` accidentally excluded `layers/service.py` and `processing/ingest/service.py`. Replaced with the precise `'datasets/domain/service\.py:'` filter for the actual verification; documented in 224-03 SUMMARY so 04/05/06 use the right command.
3. **Plan 07 — `_safe_table_ref` re-export for tests** (Rule 3): `backend/tests/test_sql_safety.py:9` imports `_safe_table_ref` from the façade. Removing the re-export would break the test. Kept the import in service.py with `# noqa: F401 -- re-exported for tests/test_sql_safety.py` but deliberately excluded from `__all__` to preserve the private-helper convention. The plan's executor prompt anticipated this exact case.

No deviations on plans 01, 04, 05, 06, or 08. All plans executed substantively as written.

## Auth Gates

None — pure structural refactor, no external service interaction.

## What's Next

- **`/gsd-complete-milestone v13.3`** — milestone close audit and tagging. Phase 224 + Phase 223 (Marketplace billing extraction) + Phase 222 (Audit sink protocol) form the three architecture-discipline pillars of v13.3.
- **Phase 999.7 unblocked** — ProcessingPort Protocol cycle inversion can now target focused modules.
- **Future enterprise-overlay tier-gating** — `service_create.py` is a clean monkey-patch target.

## Self-Check: PASSED

Verified post-write:

- `backend/app/modules/catalog/datasets/domain/service.py` exists, 83 LOC
- All 5 sub-module files exist with correct LOC counts (222, 356, 158, 384, 423)
- `backend/tests/test_layering.py` contains `test_no_external_imports_of_dataset_domain_submodules`
- `Makefile` contains `catalog-domain-discipline` target
- Commit `e4d85a10` exists (`git log` confirmed) — test + Makefile commit
- All 8 plan commits exist in `git log` with the expected refactor/test/docs prefixes
- Architecture guard runs and passes (`make catalog-domain-discipline` exits 0)
- Pytest 2046 passed (baseline 2045 + 1 new architecture test) — D-09 preservation contract held + 1 intentional addition
- Smoke import OK: 23 public symbols importable through service.py façade
- Consumer-import surface diff against `224-01-baseline-imports.txt`: empty (22 lines unchanged) with sub-module filter

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*
*DECOUPLE-01..04: ALL SATISFIED*

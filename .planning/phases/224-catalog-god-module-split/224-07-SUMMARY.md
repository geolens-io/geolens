---
phase: 224-catalog-god-module-split
plan: 07
subsystem: catalog/datasets/domain
tags: [refactor, facade, close-gate, decouple-01, decouple-02]
key-files:
  modified:
    - backend/app/modules/catalog/datasets/domain/service.py
key-decisions:
  - "service.py rewritten as canonical thin façade: module docstring + 5 explicit named re-export blocks + __all__ tuple of the 23 public symbols. No implementation, no orphaned imports, no module-level constants."
  - "_safe_table_ref re-exported with `# noqa: F401` for `backend/tests/test_sql_safety.py` (which imports it from the façade) but DELIBERATELY excluded from `__all__` to preserve the private-helper convention. This is a single-line deviation from the plan template — the alternative (forcing the test to import from `service_lifecycle` directly) would violate DECOUPLE-04 (no external imports of sub-modules)."
  - "DECOUPLE-01 close gate verified two ways: (a) all 23 public symbols importable through service.py with no errors; (b) consumer-import surface diff against 224-01-baseline-imports.txt is empty when filtered with the Plan 06 sub-module-self-import filter (`grep -v 'datasets/domain/service\\.py:\\|datasets/domain/service_'`). Internal cross-module imports between the 5 sub-modules are expected and permitted by D-01."
  - "DECOUPLE-02 close gate satisfied: service.py is 83 LOC, well below the <250 LOC target. Cumulative shrinkage: 1407 → 83 LOC (−94%)."
  - "Plan 08 (architecture-guard test) is unblocked. Allow-list is finalized: service_create.py, service_query.py, service_lifecycle.py, service_metadata.py, service_relationships.py, service.py, backend/tests/test_layering.py, and backend/tests/test_sql_safety.py (because the latter imports a private helper `_safe_table_ref` from the façade)."
requirements: [DECOUPLE-01, DECOUPLE-02]
metrics:
  duration: ~9 minutes (mostly pytest)
  tasks: 3/3
  completed: "2026-05-01T13:29:14Z"
---

# Phase 224 Plan 07: Convert service.py to Thin Re-Export Façade — Summary

Replaced the post-Plan-06 5-block re-export shim in `backend/app/modules/catalog/datasets/domain/service.py` with the canonical façade structure: module docstring + 5 explicit named re-export blocks + `__all__` tuple of the 23 public symbols. **DECOUPLE-01 + DECOUPLE-02 close gates satisfied.**

## What Changed

`backend/app/modules/catalog/datasets/domain/service.py` was rewritten from 47 LOC (transitional shim with 5 import blocks but no docstring/`__all__`) to 83 LOC (canonical façade). The new structure has exactly three top-level constructs:

1. **Module docstring** (~22 LOC) — describes the 5-way split, names each sub-module's responsibility, and points to the architecture-guard test that lands in Plan 08 (DECOUPLE-04). Includes audit reference (oc-separation-audit-20260430-b.md §5 + §7 P0 #1).
2. **5 explicit named re-export blocks** (~32 LOC) — one per sub-module, sorted alphabetically by sub-module name. Each block uses the canonical absolute path `from app.modules.catalog.datasets.domain.service_X import (...)`. No relative imports, no glob imports, no aliases.
3. **`__all__` tuple** (~25 LOC) — sorted tuple of the 23 public symbols.

There is no implementation code, no module-level constants, no orphaned imports, and no `from __future__ import annotations` (the façade does not need it since it does no type annotation work).

## Final LOC Counts (post-Phase-224 split)

| File | LOC | Role |
|---|---|---|
| `service.py` | **83** | Thin façade (23 re-exports + 1 private helper re-export for tests) |
| `service_create.py` | 222 | 2 creation coroutines (`create_dataset`, `create_empty_dataset`) |
| `service_query.py` | 356 | 5 read-side queries (`get_dataset`, `get_dataset_detail`, `get_dataset_rows`, `get_datasets_list`, `list_datasets`) |
| `service_lifecycle.py` | 158 | 3 lifecycle + 1 exception + 1 private helper (`delete_dataset`, `get_dataset_versions`, `DependentVrtError`, `_safe_table_ref`) |
| `service_metadata.py` | 384 | 7 metadata + 1 private helper (`compute_schema_diff`, `get_attribute`, `list_attributes`, `reset_attribute`, `update_attribute`, `update_auto_metadata`, `update_user_metadata`, `_normalize_col_type`) |
| `service_relationships.py` | 423 | 6 relationship coroutines (`auto_detect_relationships`, `create_relationship`, `delete_relationship`, `get_related_datasets`, `get_related_records`, `list_relationships`) |
| **Total** | **1626** | (vs original 1407 — +219 LOC due to per-module imports/docstrings) |

`service.py` is **94% smaller** than the original 1407-LOC god-module.

## Verification Gates

All 4 gates ran and passed before commit:

1. **Gate 1 — Public symbol smoke import (DECOUPLE-01 part A):**
   ```bash
   cd backend && uv run python -c "from app.modules.catalog.datasets.domain.service import (DependentVrtError, ..., update_user_metadata); print('23 PUBLIC SYMBOLS OK')"
   # → 23 PUBLIC SYMBOLS OK
   ```

2. **Gate 2 — Consumer-import surface diff (DECOUPLE-01 part B):**
   ```bash
   diff <(sort .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt) \
        <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' \
          | grep -v 'datasets/domain/service\.py:\|datasets/domain/service_' \
          | sort)
   # → empty (22 consumer lines unchanged)
   ```
   Without the sub-module-self-import filter (the same one Plan 06 used), the raw diff shows 11 added lines — all internal cross-module imports between the 5 sub-modules of the new domain package, which D-01 explicitly permits.

3. **Gate 3 — Pytest GREEN (D-09):**
   ```bash
   cd backend && uv run pytest tests/ -x --tb=short
   # → 2045 passed, 19 skipped, 5 deselected, 29 warnings in 395.56s
   ```
   Identical to the 224-01 baseline. D-09 (six-iteration regression invariant) holds.

4. **Gate 4 — Application boot smoke:**
   ```bash
   cd backend && uv run python -c "from app.api.main import app; print('OK')"
   # → OK
   ```

## Close Gates Satisfied

- **DECOUPLE-01** (zero churn across 47 consumer files): VERIFIED. Public-symbol smoke import passes for all 23 names; consumer-import diff against `224-01-baseline-imports.txt` is empty (with sub-module-self-import filter).
- **DECOUPLE-02** (service.py <250 LOC): VERIFIED. service.py is 83 LOC. Original was 1407 LOC. Cumulative shrinkage −94%.
- DECOUPLE-03 and DECOUPLE-04 are validated cumulatively at phase close (Plan 224-08).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Re-export `_safe_table_ref` for `test_sql_safety.py`**
- **Found during:** Task 1 (ruff verification)
- **Issue:** The plan template explicitly listed only the 23 public symbols in the import blocks. But `backend/tests/test_sql_safety.py:9` imports `_safe_table_ref` from the façade (`from app.modules.catalog.datasets.domain.service import _safe_table_ref`). Removing the re-export would break that test, violating Gate 3 (pytest GREEN).
- **Fix:** Kept `_safe_table_ref` in the `service_lifecycle` import block with `# noqa: F401 -- re-exported for tests/test_sql_safety.py` (the alternative — adding it to `__all__` — would violate the private-helper convention). The plan's additional context block in the executor prompt anticipated this exact case ("If service.py currently re-exports `_safe_table_ref` ... keep that line but DON'T add it to `__all__`").
- **Files modified:** `backend/app/modules/catalog/datasets/domain/service.py`
- **Commit:** `5ab4bb56`

No other deviations. Plan executed as written.

## Auth Gates

None — this is a pure structural refactor with no external service interaction.

## Commits

| Hash | Message |
|---|---|
| `5ab4bb56` | `refactor(224-07): convert service.py to thin re-export façade` |

## Self-Check: PASSED

- `backend/app/modules/catalog/datasets/domain/service.py` exists (83 LOC)
- Commit `5ab4bb56` exists (`git log` confirmed)
- All 4 verification gates passed
- DECOUPLE-01 + DECOUPLE-02 close gates satisfied

## What's Next

**Plan 224-08** — Architecture-guard test (`test_no_external_imports_of_dataset_domain_submodules` in `backend/tests/test_layering.py`) enforcing DECOUPLE-04 in CI: no consumer outside the allow-list may `from app.modules.catalog.datasets.domain.service_X import ...`. Allow-list:
- `backend/app/modules/catalog/datasets/domain/service.py` (the façade — re-export blocks)
- `backend/app/modules/catalog/datasets/domain/service_create.py` (cross-import: `_safe_table_ref` from service_lifecycle, `auto_detect_relationships` from service_relationships)
- `backend/app/modules/catalog/datasets/domain/service_lifecycle.py` (cross-import: `get_dataset` from service)
- `backend/app/modules/catalog/datasets/domain/service_metadata.py` (cross-imports: `get_dataset` from service ×2)
- `backend/app/modules/catalog/datasets/domain/service_query.py`
- `backend/app/modules/catalog/datasets/domain/service_relationships.py` (cross-import: `get_dataset` from service)
- `backend/tests/test_layering.py` (the test itself)
- `backend/tests/test_sql_safety.py` (imports `_safe_table_ref` from façade — DOES go through service.py, so technically not on the allow-list; the regex `from app\.modules\.catalog\.datasets\.domain\.service_(create|query|lifecycle|metadata|relationships)` would NOT match it)

After Plan 08 lands, Phase 224 closes with all 4 close gates verified.

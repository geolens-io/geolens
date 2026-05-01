---
phase: 224-catalog-god-module-split
plan: 01
subsystem: planning
tags: [baseline, requirements, golden-file, refactor, decouple, catalog]

# Dependency graph
requires:
  - phase: 223-marketplace-billing-extraction
    provides: "BILLING-01..06 closed; oc-separation-audit-20260430-b.md re-run identified P0 #1 (catalog god-module) as next target — feeds Phase 224 scope"
provides:
  - "DECOUPLE-01..04 requirements + Traceability rows in .planning/REQUIREMENTS.md"
  - "224-01-baseline-imports.txt golden file (22 import lines from backend/app/)"
  - "224-01-baseline-symbols.txt golden file (25 top-level symbols from service.py: 23 public + 2 private)"
  - "Pre-split pytest baseline confirmed GREEN: 2045 passed, 19 skipped, 5 deselected"
affects:
  - 224-02 (extracts service_relationships.py — diffs against golden imports/symbols)
  - 224-03 (extracts service_metadata.py)
  - 224-04 (extracts service_lifecycle.py)
  - 224-05 (extracts service_query.py)
  - 224-06 (extracts service_create.py)
  - 224-07 (façade conversion — must preserve symbol set in golden file)
  - 224-08 (architecture-guard test + close gate — verifies DECOUPLE-01..04)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Golden-file preservation contract: capture pre-refactor surface (imports + symbols) as sorted text files; diff at each plan boundary"
    - "Pre-refactor pytest baseline captured before any code moves — guarantees later plans can detect regressions deterministically"

key-files:
  created:
    - .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt
    - .planning/phases/224-catalog-god-module-split/224-01-baseline-symbols.txt
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Captured 22 consumer import lines across backend/app/ (excludes tests by path scope per plan spec — tests import via the same façade and are out of DECOUPLE-01's direct scope)"
  - "Captured 25 top-level symbols (23 public + 2 private helpers _safe_table_ref + _normalize_col_type + DependentVrtError class). Matches plan expectation exactly."
  - "Pre-split pytest baseline is unambiguously GREEN — no pre-existing failures attributable to Phase 224 to document. Later plans must preserve same pass count."

patterns-established:
  - "Golden-file preservation contract: golden artifacts under `.planning/phases/<phase>/` provide mechanical diff verification at every plan boundary"
  - "Phase-baseline lock-in plan: a wave-1 plan that ships zero code changes but captures the pre-refactor truth as committed artifacts before any moves begin"

requirements-completed: []  # DECOUPLE-01..04 are *introduced* by this plan; they will be marked complete by Phase 224 close (plan 08), not by this plan.

# Metrics
duration: 8min
completed: 2026-05-01
---

# Phase 224 Plan 01: Baseline Lock-In Summary

**DECOUPLE-01..04 requirements + 22-line import golden file + 25-symbol public-surface golden file captured; pre-split pytest baseline GREEN at 2045/2045 — refactor preservation contract is now mechanically verifiable at every later plan boundary.**

## Performance

- **Duration:** ~8 min (plus ~6.5 min pytest baseline run)
- **Started:** 2026-05-01T12:06:37Z
- **Completed:** 2026-05-01T12:15:57Z
- **Tasks:** 3/3
- **Files modified:** 1 (REQUIREMENTS.md)
- **Files created:** 2 (golden files)

## Accomplishments

- Added 4 new DECOUPLE-XX requirements to `.planning/REQUIREMENTS.md` with a milestone-goal note + Traceability rows mapping each to Phase 224.
- Captured **22 consumer import lines** across `backend/app/` referencing `from app.modules.catalog.datasets.domain.service` — the golden file for DECOUPLE-01 verification.
- Captured **25 top-level symbols** in `service.py` (21 `async def` + 1 `class DependentVrtError` + 3 `def` including the 2 private helpers `_safe_table_ref` and `_normalize_col_type`) — matches plan expectation exactly.
- Verified **pre-split pytest baseline is GREEN**: `2045 passed, 19 skipped, 5 deselected, 29 warnings in 397.58s` — clean baseline; no pre-existing failures to document. Same set must pass after every later plan in this phase (D-09 preservation contract).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DECOUPLE-01..04 requirements + Traceability rows** — bundled into `d6056871`
2. **Task 2: Capture baseline-imports.txt and baseline-symbols.txt golden files** — bundled into `d6056871`
3. **Task 3: Atomic commit `docs(224-01): ...`** — `d6056871`

Note: Per the plan spec, all 3 task outputs are bundled into one atomic `docs(224-01): ...` commit (the plan's deliverable is described as "1 commit"). No separate per-task commits were created — the plan explicitly defines task 3 as the commit step that bundles tasks 1 and 2.

**Plan metadata commit:** (separate `docs(224-01): plan summary` will follow)

## Files Created/Modified

- `.planning/REQUIREMENTS.md` — added "Catalog God-Module Decoupling" section with DECOUPLE-01..04, milestone-goal note appended, 4 new Traceability rows
- `.planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt` — 22 sorted lines, golden file for DECOUPLE-01 import-surface diff
- `.planning/phases/224-catalog-god-module-split/224-01-baseline-symbols.txt` — 25 sorted lines, golden file for DECOUPLE-01 importability smoke test

## Golden File Contents

**224-01-baseline-imports.txt** — 22 lines, 12 distinct files:
- `backend/app/modules/catalog/datasets/api/router.py` (1)
- `backend/app/modules/catalog/datasets/api/router_data.py` (1)
- `backend/app/modules/catalog/datasets/api/router_export.py` (1)
- `backend/app/modules/catalog/datasets/api/router_metadata.py` (11 — incl. inline late imports)
- `backend/app/modules/catalog/datasets/api/router_reupload.py` (1)
- `backend/app/modules/catalog/datasets/api/router_vrt.py` (1)
- `backend/app/modules/catalog/features/router.py` (1)
- `backend/app/modules/catalog/layers/router.py` (1)
- `backend/app/modules/catalog/layers/service.py` (1)
- `backend/app/processing/export/router.py` (1)
- `backend/app/processing/ingest/service.py` (1)
- `backend/app/processing/ingest/tasks_common.py` (1)

**224-01-baseline-symbols.txt** — 25 lines:
- 21 `async def` functions (the public dataset orchestration API)
- 1 `class DependentVrtError(Exception)`
- 3 `def` (1 public: `compute_schema_diff`; 2 private: `_normalize_col_type`, `_safe_table_ref`)

## Decisions Made

- **Bundled all 3 task changes into one atomic commit per plan spec.** Task 3's `<action>` block explicitly stages tasks 1 + 2 outputs together. Splitting would violate the plan's "1 commit" deliverable count.
- **Did NOT stage `STATE.md` or SAML test fixtures** that pytest run modified — STATE.md is updated by the orchestrator at plan close (separate metadata commit), and SAML fixture rotation is unrelated to plan 224-01 (pre-existing churn from test-suite execution; out of scope per executor scope rules).

## Deviations from Plan

None — plan executed exactly as written. All three task acceptance criteria pass; golden file LOC counts match the plan's stated expectations (22 imports, 25 symbols).

## Issues Encountered

None. Pre-split pytest baseline is unambiguously GREEN (2045 passed, no failures), so the D-09 preservation contract for downstream plans has a clean reference point.

## Next Phase Readiness

- **Plan 224-02 (extract service_relationships.py)** is unblocked. The extraction sequence (D-02: relationships → metadata → lifecycle → query → create) starts with the least-coupled module so each step has a small delta surface.
- **Diff command for plan-boundary verification:**
  - Imports: `diff -u .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt <(grep -rn 'from app\.modules\.catalog\.datasets\.domain\.service' backend/app/ --include='*.py' | sort)` — exit 0 (or only line numbers shifted within unchanged files).
  - Symbols: `cd backend && uv run python -c "from app.modules.catalog.datasets.domain.service import (auto_detect_relationships, create_dataset, create_empty_dataset, create_relationship, delete_dataset, delete_relationship, get_attribute, get_dataset, get_dataset_detail, get_dataset_rows, get_dataset_versions, get_datasets_list, get_related_datasets, get_related_records, list_attributes, list_datasets, list_relationships, reset_attribute, update_attribute, update_auto_metadata, update_user_metadata, DependentVrtError, compute_schema_diff); print('OK')"` — exit 0.
- **Pytest preservation target:** every later plan must close at `2045 passed, 19 skipped, 5 deselected` (or the same pass-count drift only on intentional, documented additions like the architecture-guard test in plan 08).

---

## Self-Check: PASSED

Verified post-write:

- `.planning/REQUIREMENTS.md` contains DECOUPLE-01..04 (`grep -c` returned 4)
- 4 Traceability rows for `DECOUPLE-0[1-4] | Phase 224 |` (`grep -c` returned 4)
- `.planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt` exists, 22 lines
- `.planning/phases/224-catalog-god-module-split/224-01-baseline-symbols.txt` exists, 25 lines
- Commit `d6056871` exists in `git log`, references 224-01
- Pre-split pytest baseline GREEN (2045 passed)

---

*Phase: 224-catalog-god-module-split*
*Completed: 2026-05-01*

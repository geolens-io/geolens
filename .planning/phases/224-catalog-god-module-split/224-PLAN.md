---
phase: 224-catalog-god-module-split
plan: phase
type: execute
wave: 0
depends_on: []
files_modified: []
autonomous: true
requirements: [DECOUPLE-01, DECOUPLE-02, DECOUPLE-03, DECOUPLE-04]
tags: [refactor, decouple, catalog, god-module-split, facade, architecture-guard]
must_haves:
  truths:
    - "backend/app/modules/catalog/datasets/domain/service.py is <250 LOC after the refactor (thin façade only) — DECOUPLE-02"
    - "Five new sub-modules exist under backend/app/modules/catalog/datasets/domain/ — each <500 LOC and cohesive (DECOUPLE-03)"
    - "Every symbol importable from app.modules.catalog.datasets.domain.service BEFORE the split remains importable from the same path AFTER (zero call-site churn) — DECOUPLE-01"
    - "test_no_external_imports_of_dataset_domain_submodules in backend/tests/test_layering.py fails CI if any production module bypasses the façade — DECOUPLE-04"
    - "Existing backend test suite passes without modification — pure refactor, zero behavior change"
  artifacts:
    - path: "backend/app/modules/catalog/datasets/domain/service.py"
      provides: "Thin re-export façade — no implementation, just `from .service_X import name1, name2 ...` blocks + module docstring + __all__"
      contains: "from .service_create import"
    - path: "backend/app/modules/catalog/datasets/domain/service_create.py"
      provides: "create_empty_dataset, create_dataset"
      contains: "async def create_dataset"
    - path: "backend/app/modules/catalog/datasets/domain/service_query.py"
      provides: "get_dataset, list_datasets, get_datasets_list, get_dataset_detail, get_dataset_rows"
      contains: "async def get_dataset"
    - path: "backend/app/modules/catalog/datasets/domain/service_lifecycle.py"
      provides: "delete_dataset, get_dataset_versions, DependentVrtError, _safe_table_ref"
      contains: "class DependentVrtError"
    - path: "backend/app/modules/catalog/datasets/domain/service_metadata.py"
      provides: "update_user_metadata, update_auto_metadata, compute_schema_diff, _normalize_col_type, list_attributes, get_attribute, update_attribute, reset_attribute"
      contains: "def compute_schema_diff"
    - path: "backend/app/modules/catalog/datasets/domain/service_relationships.py"
      provides: "get_related_datasets, create_relationship, list_relationships, delete_relationship, auto_detect_relationships, get_related_records"
      contains: "async def auto_detect_relationships"
    - path: "backend/tests/test_layering.py"
      provides: "test_no_external_imports_of_dataset_domain_submodules @pytest.mark.architecture test"
      contains: "def test_no_external_imports_of_dataset_domain_submodules"
    - path: "Makefile"
      provides: "catalog-domain-discipline target invoking the architecture test in isolation"
      contains: "catalog-domain-discipline:"
  key_links:
    - from: "47 backend/app/ files importing from app.modules.catalog.datasets.domain.service"
      to: "backend/app/modules/catalog/datasets/domain/service.py (façade)"
      via: "explicit named re-export"
      pattern: "from app.modules.catalog.datasets.domain.service import"
    - from: "backend/app/modules/catalog/datasets/domain/service.py (façade)"
      to: "five sub-modules (service_create, service_query, service_lifecycle, service_metadata, service_relationships)"
      via: "explicit named re-export with __all__ listing the public surface"
      pattern: "from \\.service_(create|query|lifecycle|metadata|relationships) import"
    - from: "backend/tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules"
      to: "git grep -E 'from app\\.modules\\.catalog\\.datasets\\.domain\\.service_(create|query|lifecycle|metadata|relationships)' backend/app/ :!<the 5 sub-modules + service.py>"
      via: "subprocess via _git_grep helper"
      pattern: "git.*grep.*service_(create|query|lifecycle|metadata|relationships)"

decisions:
  - "D-01: 5-way split (not the 4 from CONTEXT). The 25 public symbols cluster into 5 cohesive responsibility groups (Create / Query / Lifecycle / Metadata / Relationships). The CONTEXT explicitly authorizes ≥5 modules if cohesion suggests it. The original `service_grants.py` from the CONTEXT has no symbols to populate — DatasetGrant manipulation already lives in `catalog/authorization.py` (Phase 213 relocation); service.py only references DatasetGrant as a parameter to apply_visibility_filter. Skipping service_grants.py."
  - "D-02: Extraction order = least-coupled first. Sequence: relationships → metadata → lifecycle → query → create. create_dataset is extracted last because it calls auto_detect_relationships (relationships) and the create flow has the most cross-cutting touches. By extracting downstream-only modules first, each step has a smaller delta surface."
  - "D-03: Façade uses explicit named re-exports with __all__ — NOT `from .service_X import *`. Explicit imports are auditable, refactor-safe, and match the project's audit-friendly style. The audit-guard test checks the import shape; star imports would defeat the cohesion check."
  - "D-04: Architecture-guard test name = test_no_external_imports_of_dataset_domain_submodules. Mirrors the cadence of test_no_log_action_calls_outside_audit_service (Phase 222 AUDIT-02)."
  - "D-05: Allowlist for the guard = the 5 sub-module files + service.py + the test file. Cross-imports BETWEEN sub-modules are PERMITTED (e.g., service_create.py imports auto_detect_relationships from service_relationships.py). The guard only fails on imports from CONSUMERS outside backend/app/modules/catalog/datasets/domain/."
  - "D-06: Makefile target name = catalog-domain-discipline. Mirrors audit-sink-discipline (Phase 222) and billing-extraction-discipline (Phase 223). Runs the architecture test alone — no DB required (uses git grep)."
  - "D-07: Atomic commit per task. Commit message convention: `refactor(224-NN): <verb> <object>`. Never use `git add -A` or `git add .` — stage explicit files per CLAUDE.md user feedback."
  - "D-08: Import-surface invariant verification = `grep -rn 'from app.modules.catalog.datasets.domain.service' backend/app/` produces an unchanged set of import lines after each plan. Captured as a baseline artifact in Plan 01 and re-checked at every plan boundary."
  - "D-09: cd backend && uv run pytest tests/ MUST be green before each commit. No commit lands red. AUDIT-05-style preservation contract."
---

<objective>
Split `backend/app/modules/catalog/datasets/domain/service.py` (1407 LOC orchestration god-module) into 5 cohesive sub-modules behind a thin re-export façade. Pure refactor — zero behavior change. The public import surface (`from app.modules.catalog.datasets.domain.service import ...`) is preserved across 47 consumer files via explicit named re-exports in the slimmed-down `service.py`.

Closes Phase 224 (`oc-separation-audit-20260430-b.md` §5 + §7 P0 #1) — the largest enterprise-overlay obstacle. After this phase, the open-core seam can target focused modules (e.g., a tier-gated dataset-creation overlay can target `service_create.py` alone) instead of monkey-patching a 1.4kLOC orchestrator.

Purpose:
- DECOUPLE-01: zero call-site churn — `from app.modules.catalog.datasets.domain.service import create_dataset` continues to work, unchanged, in all 47 consumer files
- DECOUPLE-02: `service.py` <250 LOC after refactor (thin façade)
- DECOUPLE-03: each sub-module <500 LOC and single-responsibility
- DECOUPLE-04: architecture-guard test enforces the no-bypass invariant in CI

Output:
- 5 new sub-modules in `backend/app/modules/catalog/datasets/domain/`
- `service.py` rewritten as a thin façade
- 1 new architecture-guard test in `backend/tests/test_layering.py`
- 1 new `catalog-domain-discipline` Makefile target
- 4 new requirements added to `.planning/REQUIREMENTS.md` (DECOUPLE-01..04)
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/224-catalog-god-module-split/224-CONTEXT.md
@backend/app/modules/catalog/datasets/domain/service.py
@backend/tests/test_layering.py
@Makefile
</context>

<plans>

| Wave | Plan | Objective | Depends on | Files |
|------|------|-----------|------------|-------|
| 1 | 224-01 | Inventory baseline + add DECOUPLE-01..04 to REQUIREMENTS.md | — | .planning/REQUIREMENTS.md, .planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt, .planning/phases/224-catalog-god-module-split/224-01-baseline-symbols.txt |
| 2 | 224-02 | Extract service_relationships.py (least-coupled — 6 symbols) | 01 | service_relationships.py (new), service.py |
| 3 | 224-03 | Extract service_metadata.py (8 symbols + 1 helper) | 02 | service_metadata.py (new), service.py |
| 4 | 224-04 | Extract service_lifecycle.py (3 symbols + 1 helper) | 03 | service_lifecycle.py (new), service.py |
| 5 | 224-05 | Extract service_query.py (5 symbols) | 04 | service_query.py (new), service.py |
| 6 | 224-06 | Extract service_create.py (2 symbols — last because auto_detect_relationships dependency) | 05 | service_create.py (new), service.py |
| 7 | 224-07 | Convert service.py to thin façade (<250 LOC, explicit __all__, module docstring) | 06 | service.py |
| 8 | 224-08 | Architecture-guard test + Makefile target + Phase 224 close gate | 07 | backend/tests/test_layering.py, Makefile |

</plans>

<verification>

After all 8 plans complete:

1. **DECOUPLE-01 (zero churn):** `diff <(git show HEAD~8:.planning/phases/224-catalog-god-module-split/224-01-baseline-imports.txt | sort) <(grep -rn 'from app.modules.catalog.datasets.domain.service' backend/app/ --include='*.py' | sort)` — exit code 0 (or only line numbers shifted within unchanged files).
2. **DECOUPLE-02 (façade <250 LOC):** `wc -l backend/app/modules/catalog/datasets/domain/service.py` returns ≤250.
3. **DECOUPLE-03 (each sub-module <500 LOC):** `wc -l backend/app/modules/catalog/datasets/domain/service_*.py` — each line ≤500.
4. **DECOUPLE-04 (architecture guard):** `cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -v` exits 0; `make catalog-domain-discipline` exits 0.
5. **Public surface preserved (smoke):** `cd backend && uv run python -c "from app.modules.catalog.datasets.domain.service import (create_empty_dataset, create_dataset, get_dataset, list_datasets, get_datasets_list, get_dataset_detail, get_dataset_rows, delete_dataset, get_dataset_versions, DependentVrtError, update_user_metadata, update_auto_metadata, compute_schema_diff, list_attributes, get_attribute, update_attribute, reset_attribute, get_related_datasets, create_relationship, list_relationships, delete_relationship, auto_detect_relationships, get_related_records); print('OK')"` exits 0 and prints `OK`.
6. **Behavior preserved:** `cd backend && uv run pytest -v --tb=short` exits 0 (full suite, baseline + 1 new architecture test = baseline+1).
7. **Application boot smoke:** `cd backend && uv run python -c "from app.api.main import app; print('OK')"` exits 0.
8. **Ruff clean** across all 7 modified/new files.

</verification>

<success_criteria>
- [ ] All 4 DECOUPLE-XX requirements added to .planning/REQUIREMENTS.md and traceable to Phase 224
- [ ] 5 sub-module files exist with the correct symbol distribution per D-01
- [ ] service.py is a thin re-export façade (<250 LOC, explicit __all__)
- [ ] No call-site outside the 5 sub-modules + service.py + test_layering.py imports from `service_create|service_query|service_lifecycle|service_metadata|service_relationships`
- [ ] Full backend pytest suite GREEN
- [ ] catalog-domain-discipline Makefile target exists and passes
- [ ] Application boot smoke OK
- [ ] All 8 plan commits land atomically (one task = one commit, message format `refactor(224-NN): ...`)
- [ ] Phase 999.7 (ProcessingPort Protocol) is now unblocked — easier to invert imports against focused modules
</success_criteria>

<output>
After phase completion, create `.planning/phases/224-catalog-god-module-split/224-SUMMARY.md` aggregating each plan's SUMMARY:
- Final LOC counts per sub-module + façade
- Confirmed unchanged import surface (DECOUPLE-01)
- Architecture-guard test passing in CI (DECOUPLE-04)
- Phase 999.7 unblock note
- Grade-improvement target: Coupling Health B → B+ (catalog god-module decomposed)
</output>

---
phase: 238-boundary-guards-and-contract-stabilization
plan: 02
type: execute
wave: 2
depends_on:
  - 238-01
files_modified:
  - backend/tests/test_layering.py
autonomous: true
requirements:
  - BOUND-02
  - BOUND-03
must_haves:
  truths:
    - "Maps/search facades fail architecture tests if they grow back toward god-module shape."
    - "Maps/search private service modules fail architecture tests when they exceed the default size budget unless an explicit per-file allowlist cap documents the exception."
    - "The guard starts from current measured sizes: maps facade 76 lines, search facade 44 lines, largest private modules maps public 526, maps CRUD 488, search records 456."
    - "Existing catalog<->processing guards still pass after the size-budget guard lands."
  artifacts:
    - path: backend/tests/test_layering.py
      provides: "Line-count budget guard for maps/search facades and private modules"
      contains: "test_maps_search_service_modules_stay_within_size_budgets"
  key_links:
    - from: "backend/tests/test_layering.py"
      to: "backend/app/modules/catalog/maps/service.py"
      via: "facade line-count cap"
      pattern: "backend/app/modules/catalog/maps/service.py"
    - from: "backend/tests/test_layering.py"
      to: "backend/app/modules/catalog/search/service.py"
      via: "facade line-count cap"
      pattern: "backend/app/modules/catalog/search/service.py"
---

<objective>
Add an architecture guard that keeps the new maps/search service split from regressing into god modules.

Purpose: enforce thin public facades and bounded private modules with explicit exceptions for the already-large legacy chunks that were split in Phases 236 and 237.
Output: a line-count budget guard in `backend/tests/test_layering.py`.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/238-boundary-guards-and-contract-stabilization/238-01-SUMMARY.md
@backend/tests/test_layering.py
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/service_shared.py
@backend/app/modules/catalog/maps/service_crud.py
@backend/app/modules/catalog/maps/service_layers.py
@backend/app/modules/catalog/maps/service_public.py
@backend/app/modules/catalog/search/service.py
@backend/app/modules/catalog/search/service_filters.py
@backend/app/modules/catalog/search/service_facets.py
@backend/app/modules/catalog/search/service_collections.py
@backend/app/modules/catalog/search/service_semantic.py
@backend/app/modules/catalog/search/service_datasets.py
@backend/app/modules/catalog/search/service_records.py

<discovery_notes>
Measured line counts before planning:
- `backend/app/modules/catalog/maps/service.py`: 76
- `backend/app/modules/catalog/search/service.py`: 44
- `backend/app/modules/catalog/maps/service_public.py`: 526
- `backend/app/modules/catalog/maps/service_crud.py`: 488
- `backend/app/modules/catalog/search/service_records.py`: 456
- all other maps/search private service modules are 255 lines or smaller.
</discovery_notes>

<interfaces>
Add one architecture test:

```python
@pytest.mark.architecture
def test_maps_search_service_modules_stay_within_size_budgets() -> None: ...
```

Recommended constants:
```python
FACADE_LINE_BUDGETS = {
    "backend/app/modules/catalog/maps/service.py": 100,
    "backend/app/modules/catalog/search/service.py": 80,
}
PRIVATE_SERVICE_DEFAULT_LINE_BUDGET = 350
PRIVATE_SERVICE_LINE_BUDGET_ALLOWLIST = {
    "backend/app/modules/catalog/maps/service_crud.py": 550,
    "backend/app/modules/catalog/maps/service_public.py": 575,
    "backend/app/modules/catalog/search/service_records.py": 500,
}
```

The allowlist is an explicit cap, not an exemption. A listed file still fails when it grows beyond its documented cap.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Add facade and private-module size budget guard</name>
  <files>backend/tests/test_layering.py</files>
  <action>Add `test_maps_search_service_modules_stay_within_size_budgets`. Count physical lines with `Path.read_text().splitlines()` for the two facades and every `service_*.py` private module under `backend/app/modules/catalog/maps/` and `backend/app/modules/catalog/search/`. Enforce facade caps separately from private-module caps. Use `PRIVATE_SERVICE_DEFAULT_LINE_BUDGET = 350` for unlisted private modules and `PRIVATE_SERVICE_LINE_BUDGET_ALLOWLIST` for the three known large modules discovered above. Failure output must include the file path, observed line count, cap, and instruction to split the module or add a reviewed explicit cap only when the growth is intentional.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py::test_maps_search_service_modules_stay_within_size_budgets -q</automated>
  </verify>
  <done>The current maps/search service files pass the guard with explicit caps for the three known large private modules.</done>
</task>

<task type="auto">
  <name>Run size guard with import and cycle guards</name>
  <files>backend/tests/test_layering.py</files>
  <action>Run the new budget guard together with the Phase 238 private import guards from Plan 01 and the existing Phase 225/230 catalog-processing guards. Fix only issues in `test_layering.py` introduced by this plan. Do not loosen existing catalog/processing import patterns or add allowlists to those existing guards.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_maps_private_service_modules tests/test_layering.py::test_no_external_imports_of_search_private_service_modules tests/test_layering.py::test_maps_search_service_modules_stay_within_size_budgets tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q</automated>
  </verify>
  <done>Import guards, size-budget guard, and existing catalog/processing guards all pass together.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_maps_private_service_modules tests/test_layering.py::test_no_external_imports_of_search_private_service_modules tests/test_layering.py::test_maps_search_service_modules_stay_within_size_budgets tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q
- cd backend && uv run ruff check tests/test_layering.py
- cd backend && uv run ruff format --check tests/test_layering.py
</verification>

<success_criteria>
- BOUND-02 is satisfied: facades and private modules have executable size-budget protection.
- BOUND-03 remains true: catalog/processing boundary guards still pass.
</success_criteria>

<output>
After completion, create `.planning/phases/238-boundary-guards-and-contract-stabilization/238-02-SUMMARY.md`.
</output>

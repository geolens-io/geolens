---
phase: 238-boundary-guards-and-contract-stabilization
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/tests/test_layering.py
autonomous: true
requirements:
  - BOUND-01
  - BOUND-03
must_haves:
  truths:
    - "External backend application modules import maps/search behavior only through app.modules.catalog.maps.service and app.modules.catalog.search.service."
    - "Private maps/search service split modules may import sibling private modules, and the public facade may re-export them, without creating false-positive guard failures."
    - "Existing catalog<->processing architecture guards remain green after the new maps/search guard is added."
  artifacts:
    - path: backend/tests/test_layering.py
      provides: "Maps/search private service import architecture guards"
      contains: "test_no_external_imports_of_maps_private_service_modules"
    - path: backend/tests/test_layering.py
      provides: "Search private service import architecture guard"
      contains: "test_no_external_imports_of_search_private_service_modules"
  key_links:
    - from: "backend/app/modules/catalog/maps/service.py"
      to: "backend/app/modules/catalog/maps/service_{shared,crud,layers,public}.py"
      via: "allowed facade re-export imports"
      pattern: "from (backend.)?app.modules.catalog.maps.service_..., import (backend.)?app.modules.catalog.maps.service_..., and from (backend.)?app.modules.catalog.maps import service_..."
    - from: "backend/app/modules/catalog/search/service.py"
      to: "backend/app/modules/catalog/search/service_{filters,facets,collections,semantic,datasets,records}.py"
      via: "allowed facade re-export imports"
      pattern: "from (backend.)?app.modules.catalog.search.service_..., import (backend.)?app.modules.catalog.search.service_..., and from (backend.)?app.modules.catalog.search import service_..."
---

<objective>
Add architecture guards that prevent backend application code from bypassing the new maps/search public facades.

Purpose: make `app.modules.catalog.maps.service` and `app.modules.catalog.search.service` the only public import surfaces for the decomposed services while preserving permitted sibling-module collaboration inside each domain package.
Output: focused architecture tests in `backend/tests/test_layering.py`.
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
@.planning/phases/236-maps-service-decomposition/236-VERIFICATION.md
@.planning/phases/237-search-service-decomposition/237-VERIFICATION.md
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
Current external backend app imports already use the public facades: maps callers include `maps/router.py`, admin, embed tokens, dataset metadata/data routers, and platform defaults; search callers include search router/cache, STAC router, AI service, platform defaults, and tests.

Current private-module imports are internal to the maps/search packages plus their facades:
- maps: `service.py`, `service_crud.py`, `service_layers.py`, `service_public.py`
- search: `service.py`, `service_datasets.py`, `service_facets.py`, `service_semantic.py`
</discovery_notes>

<interfaces>
Add two guard tests mirroring `test_no_external_imports_of_dataset_domain_submodules`:

```python
@pytest.mark.architecture
def test_no_external_imports_of_maps_private_service_modules() -> None: ...

@pytest.mark.architecture
def test_no_external_imports_of_search_private_service_modules() -> None: ...
```

Guard scope: `backend/app/` production code. Tests may import or patch helper modules for focused regression coverage; production modules outside the owning maps/search package must go through the public facade.

Maps private-module import patterns must catch every bypass shape, including both repo import roots:
```python
MAPS_PRIVATE_MODULES = "service_(shared|crud|layers|public)"
MAPS_PRIVATE_IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"from\s+(?:backend\.)?app\.modules\.catalog\.maps\."
    r"service_(?:shared|crud|layers|public)\s+import\b|"
    r"import\s+(?:backend\.)?app\.modules\.catalog\.maps\."
    r"service_(?:shared|crud|layers|public)(?:\s+as\b|\s*,|\s*$)|"
    r"from\s+(?:backend\.)?app\.modules\.catalog\.maps\s+import\s+.*\b"
    r"service_(?:shared|crud|layers|public)\b"
    r")"
)
```

Search private-module import patterns must mirror maps and catch:
```python
SEARCH_PRIVATE_MODULES = "service_(filters|facets|collections|semantic|datasets|records)"
SEARCH_PRIVATE_IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"from\s+(?:backend\.)?app\.modules\.catalog\.search\."
    r"service_(?:filters|facets|collections|semantic|datasets|records)\s+import\b|"
    r"import\s+(?:backend\.)?app\.modules\.catalog\.search\."
    r"service_(?:filters|facets|collections|semantic|datasets|records)(?:\s+as\b|\s*,|\s*$)|"
    r"from\s+(?:backend\.)?app\.modules\.catalog\.search\s+import\s+.*\b"
    r"service_(?:filters|facets|collections|semantic|datasets|records)\b"
    r")"
)
```

An AST-based import scan is also acceptable and preferred if it keeps the test simpler; it must flag the same three import forms:
- `from app.modules.catalog.maps.service_crud import get_map`
- `import app.modules.catalog.maps.service_crud as maps_crud`
- `from app.modules.catalog.maps import service_crud`

The same three shapes must fail for search private modules, and both `app...` and `backend.app...` roots must be treated as equivalent.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Add maps private-module import guard</name>
  <files>backend/tests/test_layering.py</files>
  <action>Add `test_no_external_imports_of_maps_private_service_modules` near the existing Phase 224 dataset-domain private-module guard. Use either an AST import scan or `git grep -n -E` over `backend/app/` plus Python filtering. The guard must catch all direct private-module import shapes: `from (backend.)?app.modules.catalog.maps.service_{shared,crud,layers,public} import ...`, `import (backend.)?app.modules.catalog.maps.service_{shared,crud,layers,public} [as ...]`, and `from (backend.)?app.modules.catalog.maps import service_{shared,crud,layers,public}`. Allow only `backend/app/modules/catalog/maps/service.py` and files under `backend/app/modules/catalog/maps/service_*.py` to reference maps private service modules directly. Treat all other `backend/app/` matches as offenders and fail with a message that says external callers must import from `app.modules.catalog.maps.service`. Keep the guard production-code scoped; do not scan `backend/tests/`.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_maps_private_service_modules tests/test_layering.py::test_no_catalog_imports_processing -q</automated>
  </verify>
  <done>The maps guard passes in the current decomposed state and would fail for new production imports outside `catalog/maps/` using any of these forms: `from app.modules.catalog.maps.service_crud import get_map`, `import app.modules.catalog.maps.service_crud as maps_crud`, or `from app.modules.catalog.maps import service_crud`.</done>
</task>

<task type="auto">
  <name>Add search private-module import guard and run existing cycle guards</name>
  <files>backend/tests/test_layering.py</files>
  <action>Add `test_no_external_imports_of_search_private_service_modules` beside the maps guard. Use the same implementation style as the maps guard. The guard must catch all direct private-module import shapes: `from (backend.)?app.modules.catalog.search.service_{filters,facets,collections,semantic,datasets,records} import ...`, `import (backend.)?app.modules.catalog.search.service_{filters,facets,collections,semantic,datasets,records} [as ...]`, and `from (backend.)?app.modules.catalog.search import service_{filters,facets,collections,semantic,datasets,records}`. Allow only `backend/app/modules/catalog/search/service.py` and files under `backend/app/modules/catalog/search/service_*.py` to reference search private service modules directly. Fail with offending lines for every other `backend/app/` match and direct users to `app.modules.catalog.search.service`. After adding the guard, run the existing catalog/processing architecture tests unchanged to prove BOUND-03 still holds.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_search_private_service_modules tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q</automated>
  </verify>
  <done>The search guard passes in the current decomposed state, would fail for all three private import shapes outside `catalog/search/`, and the existing catalog/processing cycle guards still pass.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_maps_private_service_modules tests/test_layering.py::test_no_external_imports_of_search_private_service_modules tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py::test_no_catalog_imports_processing -q
- cd backend && uv run ruff check tests/test_layering.py
- cd backend && uv run ruff format --check tests/test_layering.py
</verification>

<success_criteria>
- BOUND-01 is satisfied: production code cannot import private maps/search service modules directly.
- BOUND-03 is preserved: existing catalog/processing boundary guards remain green.
</success_criteria>

<output>
After completion, create `.planning/phases/238-boundary-guards-and-contract-stabilization/238-01-SUMMARY.md`.
</output>

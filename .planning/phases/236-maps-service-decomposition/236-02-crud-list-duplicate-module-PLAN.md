---
phase: 236-maps-service-decomposition
plan: 02
type: execute
wave: 2
depends_on:
  - 236-01
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/maps/service_crud.py
autonomous: true
requirements:
  - MAPS-01
  - MAPS-02
  - MAPS-03
must_haves:
  truths:
    - "Map CRUD/list/read/update/delete/duplicate symbols remain importable from app.modules.catalog.maps.service."
    - "CRUD and duplicate behavior preserves ownership checks, visibility filtering, layer sort order, fork names, thumbnails, widgets, and response tuple shapes."
    - "Layer replacement in map update preserves default style generation and layer type inference."
    - "Private maps split modules never import from app.modules.catalog.maps.service; shared dependencies flow through sibling modules to avoid facade cycles."
  artifacts:
    - path: backend/app/modules/catalog/maps/service_crud.py
      provides: "Map CRUD, list, update, delete, duplicate implementation"
      contains: "async def duplicate_map"
    - path: backend/app/modules/catalog/maps/service.py
      provides: "Facade re-export for CRUD/list/duplicate functions"
      contains: "from app.modules.catalog.maps.service_crud import"
  key_links:
    - from: "backend/app/modules/catalog/maps/router.py"
      to: "backend/app/modules/catalog/maps/service.py"
      via: "unchanged imports"
      pattern: "from app.modules.catalog.maps.service import"
    - from: "backend/app/modules/catalog/maps/service_crud.py"
      to: "backend/app/modules/catalog/maps/service_shared.py"
      via: "LayerRow, _fetch_layer_rows_ordered, _infer_layer_type"
      pattern: "service_shared"
---

<objective>
Move the map CRUD/list/update/delete/duplicate implementation into a focused sibling module while preserving the public service facade.

Purpose: isolate the largest map-builder mutation/read concerns without changing API routes or external imports.
Output: `service_crud.py` plus facade re-exports.
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
@.planning/phases/236-maps-service-decomposition/236-01-SUMMARY.md
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/service_shared.py
@backend/app/modules/catalog/maps/router.py
@backend/tests/test_maps.py

<interfaces>
Move these existing functions as-is into `service_crud.py` and re-export them from `service.py`:

```python
async def check_map_ownership(map_obj: Map, user: Identity, db: AsyncSession) -> None: ...
async def create_map(session: AsyncSession, name: str, description: str | None, created_by: uuid.UUID, notes: str | None = None) -> Map: ...
async def get_map(session: AsyncSession, map_id: uuid.UUID) -> Map | None: ...
async def get_map_with_layers(session: AsyncSession, map_id: uuid.UUID) -> tuple[Map | None, list[LayerRow], str | None, str | None]: ...
async def list_maps(...) -> tuple[list[dict], int]: ...
async def update_map(...) -> tuple[Map, list[LayerRow], str | None, str | None]: ...
async def delete_map(session: AsyncSession, map_id: uuid.UUID) -> str: ...
async def bulk_check_dataset_access(session: AsyncSession, dataset_ids: list[uuid.UUID], user: Identity, user_roles: set[str]) -> set[uuid.UUID]: ...
async def duplicate_map(session: AsyncSession, map_id: uuid.UUID, user: Identity) -> tuple[Map, list[LayerRow], str | None, str | None, int]: ...
```

Temporary ownership rule for this plan: because `duplicate_map` calls `bulk_check_dataset_access`, move `bulk_check_dataset_access` into `service_crud.py` with `duplicate_map` in Plan 02 and re-export it from `service.py`. Plan 03 will move it onward from `service_crud.py` into `service_layers.py`.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Extract CRUD and listing implementation</name>
  <files>backend/app/modules/catalog/maps/service_crud.py, backend/app/modules/catalog/maps/service.py</files>
  <action>Create `service_crud.py` and move `check_map_ownership`, `create_map`, `get_map`, `get_map_with_layers`, `_replace_layers`, `list_maps`, `update_map`, `delete_map`, `_generate_fork_name`, `bulk_check_dataset_access`, and `duplicate_map` out of `service.py`. `bulk_check_dataset_access` must move with `duplicate_map` in this plan because `service.py` will import `service_crud.py`; `service_crud.py` must not import it back from the facade. Import shared helpers from `service_shared.py`. Preserve the current SQLAlchemy queries, exception messages, no-commit semantics, and return tuple shapes exactly. Hard rule: no private split module may import `app.modules.catalog.maps.service`.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps.py::TestCreateMap tests/test_maps.py::TestListMaps tests/test_maps.py::TestGetMap tests/test_maps.py::TestUpdateMap tests/test_maps.py::TestDeleteMap tests/test_maps.py::TestDuplicateMap tests/test_maps.py::test_update_map_layers_round_trip_sort_order -q</automated>
  </verify>
  <done>CRUD/list/update/delete/duplicate tests pass with implementation living in `service_crud.py`.</done>
</task>

<task type="auto">
  <name>Re-export CRUD surface from service facade</name>
  <files>backend/app/modules/catalog/maps/service.py</files>
  <action>Replace the moved function bodies in `service.py` with imports from `service_crud.py`, keeping the public names and `__all__` stable. Re-export `bulk_check_dataset_access` from the facade temporarily from `service_crud.py`; Plan 03 will change that re-export source to `service_layers.py`. Do not update `router.py`, `platform/extensions/defaults.py`, `embed_tokens/router.py`, admin modules, dataset modules, or tests to import from `service_crud.py`; external callers must keep using the facade.</action>
  <verify>
    <automated>cd backend && uv run python - <<'PY'
from app.modules.catalog.maps.service import create_map, get_map, get_map_with_layers, list_maps, update_map, delete_map, bulk_check_dataset_access, duplicate_map, check_map_ownership
assert create_map and get_map and get_map_with_layers and list_maps and update_map and delete_map and bulk_check_dataset_access and duplicate_map and check_map_ownership
PY</automated>
  </verify>
  <done>Every CRUD/list/duplicate/access-check symbol used by existing callers imports from `app.modules.catalog.maps.service` unchanged.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_maps.py::TestCreateMap tests/test_maps.py::TestListMaps tests/test_maps.py::TestGetMap tests/test_maps.py::TestUpdateMap tests/test_maps.py::TestDeleteMap tests/test_maps.py::TestDuplicateMap tests/test_maps.py::test_update_map_layers_round_trip_sort_order -q
- cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_crud.py
- cd backend && uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_crud.py
</verification>

<success_criteria>
- MAPS-03 behavior is preserved for create/list/read/update/duplicate/delete.
- MAPS-01 remains true: router, AI ProcessingPort defaults, embed-token, admin, and tests still import through `service.py`.
</success_criteria>

<output>
After completion, create `.planning/phases/236-maps-service-decomposition/236-02-SUMMARY.md`.
</output>

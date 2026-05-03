---
phase: 236-maps-service-decomposition
plan: 03
type: execute
wave: 3
depends_on:
  - 236-02
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/maps/service_crud.py
  - backend/app/modules/catalog/maps/service_layers.py
autonomous: true
requirements:
  - MAPS-01
  - MAPS-02
  - MAPS-04
must_haves:
  truths:
    - "Layer add/remove and dataset access helpers live in a focused module."
    - "Authenticated layer operations preserve dataset access checks, default styles, raster/vector layer type inference, popup config serialization, and no-commit semantics."
    - "Duplicate and layer-replacement paths use the same access/type helper behavior after the split."
  artifacts:
    - path: backend/app/modules/catalog/maps/service_layers.py
      provides: "Layer access and layer mutation implementation"
      contains: "async def add_layer"
    - path: backend/app/modules/catalog/maps/service_crud.py
      provides: "CRUD implementation importing layer access helper without facade cycle"
      contains: "from app.modules.catalog.maps.service_layers import bulk_check_dataset_access"
    - path: backend/app/modules/catalog/maps/service.py
      provides: "Facade re-export for layer functions"
      contains: "from app.modules.catalog.maps.service_layers import"
  key_links:
    - from: "backend/app/modules/catalog/maps/service_crud.py"
      to: "backend/app/modules/catalog/maps/service_layers.py"
      via: "bulk_check_dataset_access for duplicate_map"
      pattern: "from app.modules.catalog.maps.service_layers import"
    - from: "backend/app/modules/catalog/maps/router.py"
      to: "backend/app/modules/catalog/maps/service.py"
      via: "unchanged add_layer/remove_layer/bulk_check_dataset_access imports"
      pattern: "bulk_check_dataset_access"
---

<objective>
Extract layer access and mutation concerns into `service_layers.py`, then route CRUD duplicate logic to that helper module directly.

Purpose: separate layer-specific behavior from map CRUD while preserving the facade and all layer round-trip behavior.
Output: focused layer module plus adjusted CRUD imports.
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
@.planning/phases/236-maps-service-decomposition/236-02-SUMMARY.md
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/service_crud.py
@backend/app/modules/catalog/maps/service_shared.py
@backend/app/modules/catalog/maps/router.py
@backend/tests/test_maps.py

<interfaces>
Move/re-export this layer surface. `bulk_check_dataset_access` starts this plan in `service_crud.py` because Plan 02 moved it there with `duplicate_map`; move it from `service_crud.py` to `service_layers.py`, then update `service_crud.py` to import it from `service_layers.py`.

```python
async def bulk_check_dataset_access(session: AsyncSession, dataset_ids: list[uuid.UUID], user: Identity, user_roles: set[str]) -> set[uuid.UUID]: ...
async def add_layer(session: AsyncSession, map_id: uuid.UUID, body: MapLayerInput) -> MapLayer: ...
async def remove_layer(session: AsyncSession, layer_id: uuid.UUID) -> bool: ...
```

`service_crud.py` must import `bulk_check_dataset_access` from `service_layers.py` directly, not from the public facade, to avoid a circular import.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Extract layer access and mutation helpers</name>
  <files>backend/app/modules/catalog/maps/service_layers.py, backend/app/modules/catalog/maps/service.py</files>
  <action>Create `service_layers.py`. Move `bulk_check_dataset_access` from `service_crud.py` into `service_layers.py`, and move `add_layer` and `remove_layer` from the current service surface into `service_layers.py`. Import `get_dataset_meta`, `generate_default_style`, and `_infer_layer_type` from `service_shared.py`. Preserve restricted-dataset grant checks through `DatasetGrant` + `UserRole`, popup config `model_dump()`, raster empty paint/layout behavior, vector default style behavior, and delete rowcount behavior. Re-export `bulk_check_dataset_access`, `add_layer`, and `remove_layer` from `service.py` from `service_layers.py`.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps.py::TestMapLayers tests/test_maps.py::TestLayerTypeRoundTrip tests/test_maps.py::TestShowInLegendRoundTrip -q</automated>
  </verify>
  <done>Layer API tests pass with implementation in `service_layers.py` and public imports still going through `service.py`.</done>
</task>

<task type="auto">
  <name>Wire duplicate and replacement paths to layer helpers</name>
  <files>backend/app/modules/catalog/maps/service_crud.py</files>
  <action>Update `service_crud.py` so `duplicate_map` imports and calls `bulk_check_dataset_access` from `service_layers.py`. Keep `_replace_layers` in `service_crud.py` because it is the update-map layer replacement concern, but have it import `_infer_layer_type` and `generate_default_style` from `service_shared.py`. Do not import from `app.modules.catalog.maps.service` inside private split modules.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps.py::TestDuplicateMap::test_duplicate_rbac_filtering tests/test_maps.py::TestDuplicateMap::test_duplicate_admin_sees_all_layers tests/test_maps.py::TestLayerTypeRoundTrip::test_layer_type_auto_detect_via_put tests/test_maps.py::test_update_map_layers_round_trip_sort_order -q</automated>
  </verify>
  <done>Duplicate and layer replacement paths still preserve access filtering, layer type inference, and sort order.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_maps.py::TestMapLayers tests/test_maps.py::TestLayerTypeRoundTrip tests/test_maps.py::TestShowInLegendRoundTrip tests/test_maps.py::TestDuplicateMap -q
- cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py
- cd backend && uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py
</verification>

<success_criteria>
- MAPS-04 is satisfied through unchanged add/remove layer behavior and focused layer round-trip tests.
- MAPS-01 remains true for `bulk_check_dataset_access`, `add_layer`, and `remove_layer` facade imports.
</success_criteria>

<output>
After completion, create `.planning/phases/236-maps-service-decomposition/236-03-SUMMARY.md`.
</output>

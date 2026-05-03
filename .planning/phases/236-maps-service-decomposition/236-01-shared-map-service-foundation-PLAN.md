---
phase: 236-maps-service-decomposition
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/maps/service_shared.py
autonomous: true
requirements:
  - MAPS-01
  - MAPS-02
must_haves:
  truths:
    - "DatasetMeta and LayerRow remain importable from app.modules.catalog.maps.service."
    - "Default style generation and layer-row metadata queries preserve current return shapes."
    - "service.py begins the Phase 224-style facade split without changing router imports."
  artifacts:
    - path: backend/app/modules/catalog/maps/service_shared.py
      provides: "Shared maps service types and helpers"
      contains: "class DatasetMeta"
    - path: backend/app/modules/catalog/maps/service.py
      provides: "Stable public facade for shared helper exports"
      contains: "from app.modules.catalog.maps.service_shared import"
  key_links:
    - from: "backend/app/modules/catalog/maps/service.py"
      to: "backend/app/modules/catalog/maps/service_shared.py"
      via: "explicit imports and __all__ entries"
      pattern: "DatasetMeta"
---

<objective>
Extract the shared map service foundation behind the existing `app.modules.catalog.maps.service` import path.

Purpose: create the common contracts and helpers that later CRUD, layer, and sharing modules can import without cross-module cycles.
Output: `service_shared.py` plus a still-compatible service facade.
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
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/router.py
@backend/app/modules/catalog/maps/models.py
@backend/app/modules/catalog/maps/schemas.py
@backend/tests/test_maps.py

<interfaces>
Existing public symbols to keep importable from `app.modules.catalog.maps.service` after this plan:

```python
class DatasetMeta(NamedTuple): ...
class LayerRow(NamedTuple): ...
async def get_dataset_meta(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetMeta | None: ...
def generate_default_style(geometry_type: str | None) -> dict[str, dict]: ...
async def _fetch_layer_rows_ordered(session: AsyncSession, map_id: uuid.UUID) -> list[LayerRow]: ...
async def _resolve_save_response_metadata(session: AsyncSession, map_obj: Map) -> tuple[str | None, str | None, datetime | None]: ...
def _apply_map_visibility_filter(stmt: Select, user_id: uuid.UUID | None, is_admin: bool) -> Select: ...
def _infer_layer_type(record_type: str | None) -> str: ...
```
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Extract shared map service helpers</name>
  <files>backend/app/modules/catalog/maps/service_shared.py, backend/app/modules/catalog/maps/service.py</files>
  <action>Create `service_shared.py` and move the shared helper surface from `service.py`: `DatasetMeta`, `LayerRow`, `get_dataset_meta`, `generate_default_style`, `_fetch_layer_rows_ordered`, `_resolve_save_response_metadata`, `_apply_map_visibility_filter`, and `_infer_layer_type`. Preserve docstrings and query shapes. Keep imports minimal in the new module: SQLAlchemy query helpers, `Identity` only if needed, `User`, `Dataset`, `Record`, `Map`, and `MapLayer`. Update `service.py` to import these symbols from `service_shared.py` and continue using them locally. Do not move CRUD, layer mutation, sharing, token, thumbnail, or dataset-map functions in this plan.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps.py::TestMapLayers::test_add_layer tests/test_maps.py::test_update_map_layers_round_trip_sort_order -q</automated>
  </verify>
  <done>Shared helpers live in `service_shared.py`; the two focused tests still pass through router/service imports.</done>
</task>

<task type="auto">
  <name>Lock facade exports for shared symbols</name>
  <files>backend/app/modules/catalog/maps/service.py</files>
  <action>Add an explicit `__all__` list to `service.py` containing the existing public service API, including the shared symbols. Include all currently imported public functions used by routers, admin, embed tokens, dataset metadata, ProcessingPort defaults, and tests: `DatasetMeta`, `LayerRow`, `check_map_ownership`, `get_dataset_meta`, `generate_default_style`, `create_map`, `get_map`, `get_map_with_layers`, `list_maps`, `update_map`, `delete_map`, `bulk_check_dataset_access`, `duplicate_map`, `add_layer`, `remove_layer`, `validate_public_visibility`, `find_public_maps_using_dataset`, `create_share_token`, `update_share_token`, `get_active_share_token`, `get_shared_map`, `list_share_tokens`, `revoke_share_token`, `get_maps_for_dataset`, and `revoke_share_token_by_map`. Keep private helper names importable only if current in-module code still needs them; do not advertise them in `__all__` except the shared private helpers required by downstream split modules.</action>
  <verify>
    <automated>cd backend && uv run python - <<'PY'
from app.modules.catalog.maps.service import DatasetMeta, LayerRow, generate_default_style, get_dataset_meta
assert DatasetMeta and LayerRow and generate_default_style and get_dataset_meta
PY</automated>
  </verify>
  <done>Existing shared imports from the public service path work without router or test call-site churn.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_maps.py::TestMapLayers::test_add_layer tests/test_maps.py::test_update_map_layers_round_trip_sort_order -q
- cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py
- cd backend && uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py
</verification>

<success_criteria>
- MAPS-01 foundation is satisfied for shared helper imports.
- MAPS-02 foundation exists: shared types/helpers are no longer embedded in the god module.
</success_criteria>

<output>
After completion, create `.planning/phases/236-maps-service-decomposition/236-01-SUMMARY.md`.
</output>

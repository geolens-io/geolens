---
phase: 236-maps-service-decomposition
plan: 04
type: execute
wave: 4
depends_on:
  - 236-03
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/maps/service_public.py
autonomous: true
requirements:
  - MAPS-01
  - MAPS-02
  - MAPS-05
must_haves:
  truths:
    - "Sharing, public viewer, admin share-token listing, token revocation, visibility check, and dataset-in-use helpers live in a focused module."
    - "Share tokens preserve hashing, token hints, expiration Enterprise gates, revocation behavior, and expired-token return values."
    - "Shared map rendering preserves anonymous/authenticated visibility filtering and public/non-public tile URL selection."
  artifacts:
    - path: backend/app/modules/catalog/maps/service_public.py
      provides: "Sharing, public viewer, token, and dataset-in-use implementation"
      contains: "async def get_shared_map"
    - path: backend/app/modules/catalog/maps/service.py
      provides: "Facade re-export for public/sharing functions"
      contains: "from app.modules.catalog.maps.service_public import"
  key_links:
    - from: "backend/app/modules/catalog/maps/service_public.py"
      to: "app.platform.extensions.get_catalog_port"
      via: "RasterAsset ORM access for shared map DEM metadata"
      pattern: "get_catalog_port"
    - from: "backend/app/modules/catalog/datasets/domain/service_metadata.py"
      to: "backend/app/modules/catalog/maps/service.py"
      via: "find_public_maps_using_dataset facade import"
      pattern: "find_public_maps_using_dataset"
---

<objective>
Move sharing, public-viewer, token, visibility, and dataset-in-use concerns into `service_public.py`.

Purpose: isolate public map behavior from CRUD/layer internals while keeping all callers on the stable facade.
Output: focused public/sharing module plus facade re-exports.
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
@.planning/phases/236-maps-service-decomposition/236-03-SUMMARY.md
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/service_shared.py
@backend/app/modules/catalog/maps/service_crud.py
@backend/app/modules/catalog/maps/router.py
@backend/app/modules/admin/router.py
@backend/app/modules/admin/service.py
@backend/app/modules/catalog/datasets/domain/service_metadata.py
@backend/app/modules/catalog/datasets/api/router_data.py
@backend/tests/test_maps.py

<interfaces>
Move/re-export this public and sharing surface:

```python
async def validate_public_visibility(session: AsyncSession, map_id: uuid.UUID) -> list[str]: ...
async def find_public_maps_using_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> list[str]: ...
async def create_share_token(session: AsyncSession, map_id: uuid.UUID, created_by: uuid.UUID, expires_at: datetime | None = None) -> MapShareToken: ...
async def update_share_token(session: AsyncSession, map_id: uuid.UUID, expires_at: datetime | None) -> MapShareToken | None: ...
async def get_active_share_token(session: AsyncSession, map_id: uuid.UUID) -> MapShareToken | None: ...
async def get_shared_map(session: AsyncSession, token: str, user: Identity | None = None, user_roles: set[str] | None = None) -> tuple[dict, list[dict]] | str | None: ...
async def list_share_tokens(session: AsyncSession, skip: int = 0, limit: int = 50, search: str | None = None, status_filter: str | None = None) -> tuple[list[dict], int]: ...
async def revoke_share_token(session: AsyncSession, token_id: uuid.UUID) -> MapShareToken | None: ...
async def get_maps_for_dataset(...) -> tuple[list[dict], int]: ...
async def revoke_share_token_by_map(session: AsyncSession, map_id: uuid.UUID) -> bool: ...
```
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Extract sharing and public viewer implementation</name>
  <files>backend/app/modules/catalog/maps/service_public.py, backend/app/modules/catalog/maps/service.py</files>
  <action>Create `service_public.py` and move `validate_public_visibility`, `find_public_maps_using_dataset`, `create_share_token`, `update_share_token`, `get_active_share_token`, `_validate_share_token`, `_build_shared_layer_dict`, `get_shared_map`, `list_share_tokens`, `revoke_share_token`, `get_maps_for_dataset`, and `revoke_share_token_by_map` out of `service.py`. Import `_apply_map_visibility_filter` from `service_shared.py`; import `get_map` from `service_crud.py` directly for shared-map fallback checks. Keep the function-local `EmbedToken` import inside `list_share_tokens`. Preserve `ADVANCED_SHARING_ERROR`, `is_enterprise()`, hash/token hint behavior, `"expired"` sentinel returns, CatalogPort RasterAsset lookup, and public tile URL strings exactly.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps.py::TestShareToken tests/test_maps.py::TestShareTokenServiceGuards tests/test_maps.py::TestSharedMap tests/test_maps.py::TestUpdateShareToken tests/test_maps.py::TestAdminShareTokenListing tests/test_maps.py::TestVisibilityCheck tests/test_maps.py::TestDatasetMaps -q</automated>
  </verify>
  <done>Sharing/public/dataset-map tests pass with implementation in `service_public.py`.</done>
</task>

<task type="auto">
  <name>Preserve public facade imports for cross-domain callers</name>
  <files>backend/app/modules/catalog/maps/service.py</files>
  <action>Re-export all moved public/sharing functions from `service.py` and include them in `__all__`. Do not update `admin/router.py`, `admin/service.py`, `datasets/domain/service_metadata.py`, `datasets/api/router_data.py`, or `tests/test_maps.py` to import from `service_public.py`; those callers must continue using `app.modules.catalog.maps.service`.</action>
  <verify>
    <automated>cd backend && uv run python - <<'PY'
from app.modules.catalog.maps.service import create_share_token, update_share_token, get_active_share_token, get_shared_map, list_share_tokens, revoke_share_token, get_maps_for_dataset, find_public_maps_using_dataset, validate_public_visibility, revoke_share_token_by_map
assert create_share_token and update_share_token and get_active_share_token and get_shared_map and list_share_tokens and revoke_share_token and get_maps_for_dataset and find_public_maps_using_dataset and validate_public_visibility and revoke_share_token_by_map
PY</automated>
  </verify>
  <done>All public/sharing symbols remain importable from the stable facade.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_maps.py::TestShareToken tests/test_maps.py::TestShareTokenServiceGuards tests/test_maps.py::TestSharedMap tests/test_maps.py::TestUpdateShareToken tests/test_maps.py::TestAdminShareTokenListing tests/test_maps.py::TestVisibilityCheck tests/test_maps.py::TestDatasetMaps -q
- cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_public.py
- cd backend && uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_public.py
</verification>

<success_criteria>
- MAPS-05 is satisfied for public visibility, tokens, shared map rendering, thumbnails-adjacent visibility behavior, token revocation, and dataset-in-use helpers.
- MAPS-01 remains true for admin, dataset, router, and test callers.
</success_criteria>

<output>
After completion, create `.planning/phases/236-maps-service-decomposition/236-04-SUMMARY.md`.
</output>

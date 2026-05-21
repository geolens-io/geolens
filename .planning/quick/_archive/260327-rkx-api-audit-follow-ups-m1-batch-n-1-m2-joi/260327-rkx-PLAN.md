---
phase: 260327-rkx
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/collections/service.py
  - backend/app/collections/router.py
  - backend/app/maps/service.py
  - backend/app/maps/router.py
  - backend/app/datasets/router.py
  - backend/app/datasets/helpers.py
  - backend/app/datasets/router_reupload.py
  - backend/app/datasets/router_vrt.py
  - backend/app/datasets/router_metadata.py
  - backend/app/datasets/router_export.py
  - backend/app/datasets/router_data.py
  - backend/app/public_urls.py
  - backend/app/main.py
autonomous: true
requirements: [M1, M2, L4, L5]

must_haves:
  truths:
    - "GET /collections/ returns correct dataset counts and extents using 3 queries instead of 2N+1"
    - "GET /maps/{id} returns forked_from_name and owner_username without separate queries"
    - "PUT /maps/{id} and POST /maps/{id}/duplicate also return forked/owner names from the JOIN"
    - "Dataset tile connect URLs use DB-backed get_dataset_service_url() wrapper instead of header-derived _public_base_url"
    - "datasets/router.py is split into 6 focused files, each under 600 lines"
    - "All existing dataset endpoint tests pass unchanged"
  artifacts:
    - path: "backend/app/collections/service.py"
      provides: "batch_collection_extents and batch_collection_dataset_counts functions"
      contains: "GROUP BY"
    - path: "backend/app/maps/service.py"
      provides: "get_map_with_layers returns forked_from_name + owner_username"
      contains: "outerjoin"
    - path: "backend/app/public_urls.py"
      provides: "get_dataset_service_url wrapper per L4 decision"
      contains: "get_dataset_service_url"
    - path: "backend/app/datasets/helpers.py"
      provides: "Shared helpers extracted from router.py"
      contains: "_dataset_to_response"
    - path: "backend/app/datasets/router_reupload.py"
      provides: "Reupload + presigned reupload endpoints"
      contains: "APIRouter"
    - path: "backend/app/datasets/router_vrt.py"
      provides: "VRT endpoints"
      contains: "APIRouter"
    - path: "backend/app/datasets/router_metadata.py"
      provides: "Attributes, column-stats, relationships, versions"
      contains: "APIRouter"
    - path: "backend/app/datasets/router_export.py"
      provides: "DCAT + download-cog endpoints"
      contains: "APIRouter"
    - path: "backend/app/datasets/router_data.py"
      provides: "Rows, validate, related, maps, publication-status"
      contains: "APIRouter"
  key_links:
    - from: "backend/app/collections/router.py"
      to: "backend/app/collections/service.py"
      via: "batch extent/count functions called in list_collections_endpoint"
      pattern: "batch_collection_extents|batch_collection_dataset_counts"
    - from: "backend/app/maps/router.py"
      to: "backend/app/maps/service.py"
      via: "get_map_with_layers returns 4-tuple with forked_from_name, owner_username"
      pattern: "forked_from_name.*owner_username"
    - from: "backend/app/datasets/router*.py"
      to: "backend/app/datasets/helpers.py"
      via: "shared helpers imported from helpers module"
      pattern: "from app.datasets.helpers import"
    - from: "backend/app/datasets/router*.py"
      to: "backend/app/public_urls.py"
      via: "get_dataset_service_url called for tile connect URLs"
      pattern: "get_dataset_service_url"
    - from: "backend/app/main.py"
      to: "backend/app/datasets/router*.py"
      via: "all sub-routers registered in main.py"
      pattern: "include_router.*datasets"
---

<objective>
Resolve four deferred API audit findings: batch N+1 queries in collections listing (M1), JOIN forked_from_name + owner_username into map queries (M2), replace _public_base_url with a dedicated get_dataset_service_url wrapper (L4), and split the 2,231-line datasets/router.py into focused sub-routers (L5).

Purpose: Eliminate unnecessary database round-trips and decompose an oversized module for maintainability.
Output: Optimized collection/map queries + 6 focused dataset router files.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@backend/app/collections/router.py (N+1 loop at lines 191-197)
@backend/app/collections/service.py (compute_collection_extent, get_collection_dataset_count)
@backend/app/maps/service.py (get_map_with_layers at line 103, resolve_forked_from_name at line 540)
@backend/app/maps/router.py (_resolve_owner_username at line 131, 3 call sites at ~289, ~362, ~453)
@backend/app/datasets/router.py (full file — _public_base_url at line 131, all route definitions)
@backend/app/public_urls.py (get_public_app_url already exists at line 209)
@backend/app/main.py (router registration at lines 364-390)

<interfaces>
<!-- Key functions and types the executor needs -->

From backend/app/collections/service.py:
```python
async def compute_collection_extent(session, collection_id, user, user_roles) -> dict:
    # Returns {"extent_bbox": [...] | None, "temporal_start": ..., "temporal_end": ...}

async def get_collection_dataset_count(session, collection_id, user, user_roles) -> int:
```

From backend/app/maps/service.py:
```python
async def get_map_with_layers(session, map_id) -> tuple[Map | None, list[tuple]]:
    # Current return: (map_obj, [(layer, name, gt, tn, ext, col_info, feat_count, samples, rec_type), ...])

async def resolve_forked_from_name(session, forked_from_id) -> str | None:
```

From backend/app/maps/router.py:
```python
async def _resolve_owner_username(db, created_by) -> str | None:
```

From backend/app/public_urls.py:
```python
async def get_public_app_url(db, *, request=None) -> str:
    # Already exists — returns the app origin (no /api suffix)
```

From backend/app/datasets/router.py:
```python
def _public_base_url(request: Request) -> str:  # L4: to be replaced
def _build_raster_metadata(dataset, raster_asset, ..., base_url=None) -> RasterMetadata | None:
def _dataset_to_response(dataset, *, collections=None, actors_by_id=None, ...) -> DatasetResponse:
async def _load_actor_identities(db, actor_ids) -> dict[uuid.UUID, User]:
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Batch collection N+1 queries (M1) and JOIN map lookups (M2)</name>
  <files>
    backend/app/collections/service.py,
    backend/app/collections/router.py,
    backend/app/maps/service.py,
    backend/app/maps/router.py
  </files>
  <action>
**M1 — Collections N+1 batching (per user decision: batch queries — joinedload is inapplicable to aggregates):**

The user decision specified "SQLAlchemy eager loading / joinedload," but joinedload does not apply to aggregate queries (GROUP BY counts and spatial extents). The correct eager approach for this case is batched GROUP BY queries, which achieve the same goal of eliminating N+1 round-trips.

1. In `backend/app/collections/service.py`, add two new batch functions BELOW the existing single-collection versions (keep those — they are used by get_collection_endpoint and update_collection_endpoint):

```python
async def batch_collection_extents(
    session: AsyncSession,
    collection_ids: list[uuid.UUID],
    user: User | None,
    user_roles: set[str],
) -> dict[uuid.UUID, dict]:
```

This issues a single query with `GROUP BY CollectionDataset.collection_id` using the same SELECT aggregates as `compute_collection_extent` (ST_AsGeoJSON(ST_Envelope(ST_Collect(...))), min temporal_start, max temporal_end), filtered by `.where(CollectionDataset.collection_id.in_(collection_ids))`. Apply `apply_visibility_filter` identically. Parse results into `{coll_id: {"extent_bbox": [...], "temporal_start": ..., "temporal_end": ...}}`. Collections with zero visible datasets will NOT appear in the result — return the dict as-is and let the caller use `.get(id, default)`.

```python
async def batch_collection_dataset_counts(
    session: AsyncSession,
    collection_ids: list[uuid.UUID],
    user: User | None,
    user_roles: set[str],
) -> dict[uuid.UUID, int]:
```

Same pattern: single query, `func.count()`, GROUP BY collection_id, same visibility filter.

2. In `backend/app/collections/router.py`, replace the N+1 loop at lines 191-197 in `list_collections_endpoint`:

Before (N+1):
```python
for coll in collections:
    extent_data = await compute_collection_extent(db, coll.id, user, user_roles)
    ds_count = await get_collection_dataset_count(db, coll.id, user, user_roles)
    responses.append(_collection_to_response(coll, ds_count, extent_data))
```

After (batched):
```python
coll_ids = [c.id for c in collections]
extent_map = await batch_collection_extents(db, coll_ids, user, user_roles)
count_map = await batch_collection_dataset_counts(db, coll_ids, user, user_roles)
default_extent = {"extent_bbox": None, "temporal_start": None, "temporal_end": None}
responses = [
    _collection_to_response(coll, count_map.get(coll.id, 0), extent_map.get(coll.id, default_extent))
    for coll in collections
]
```

Import the two new batch functions. Keep existing imports for single-collection functions (used by other endpoints).

**M2 — Maps JOIN forked_from_name + owner_username (Claude's discretion):**

1. In `backend/app/maps/service.py`:
   - Add `from sqlalchemy.orm import aliased` to the import section at the top of the file (alongside existing sqlalchemy imports).
   - Add `from app.auth.models import User` import if not already present.
   - Modify `get_map_with_layers` — change the initial `get_map(session, map_id)` call to a custom query using `aliased` joins:
     ```python
     ForkedMap = aliased(Map)
     stmt = (
         select(Map, ForkedMap.name.label("forked_from_name"), User.username.label("owner_username"))
         .outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)
         .outerjoin(User, Map.created_by == User.id)
         .where(Map.id == map_id)
     )
     ```
   - Both MUST be `outerjoin` (forked_from is nullable; created_by can be NULL if user deleted).
   - Update the return type from `tuple[Map | None, list[tuple]]` to `tuple[Map | None, list[tuple], str | None, str | None]`.
   - Return `(None, [], None, None)` when map not found.
   - Return `(map_obj, layers, forked_from_name, owner_username)` on success.

2. In `backend/app/maps/router.py`, update all 3 call sites (~lines 270, 347, 438) to unpack the new return values:
   ```python
   map_obj, layer_tuples, forked_name, owner_username = await get_map_with_layers(db, map_id)
   ```
   Remove the two separate query calls:
   ```python
   # DELETE these two lines at each site:
   forked_name = await resolve_forked_from_name(db, map_obj.forked_from)
   owner_username = await _resolve_owner_username(db, map_obj.created_by)
   ```

3. Check if `resolve_forked_from_name` and `_resolve_owner_username` have any OTHER callers. If not, delete them. If they do, keep them.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T api python -m pytest tests/test_collections.py tests/test_maps.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    - list_collections_endpoint issues 3 queries (list + batched extent + batched count) instead of 2N+1
    - get_map_with_layers returns forked_from_name and owner_username from JOINs
    - All 3 map call sites (get, update, duplicate) unpack from service return
    - All existing collection and map tests pass
  </done>
</task>

<task type="auto">
  <name>Task 2: Create get_dataset_service_url wrapper (L4), replace _public_base_url, and split datasets/router.py into sub-routers (L5)</name>
  <files>
    backend/app/public_urls.py,
    backend/app/datasets/router.py,
    backend/app/datasets/helpers.py,
    backend/app/datasets/router_reupload.py,
    backend/app/datasets/router_vrt.py,
    backend/app/datasets/router_metadata.py,
    backend/app/datasets/router_export.py,
    backend/app/datasets/router_data.py,
    backend/app/main.py
  </files>
  <action>
**L4 first (per user decision: dedicated helper like get_dataset_service_url):**

1. In `backend/app/public_urls.py`, add a thin purpose-named wrapper below `get_public_app_url`:

```python
async def get_dataset_service_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    """Return the public app URL for constructing dataset tile/service connect URLs.

    Thin wrapper over get_public_app_url that gives dataset-specific call sites
    a purpose-named function, per the API audit recommendation (L4).
    """
    return await get_public_app_url(db, request=request)
```

Add `Request` to the imports at the top of `public_urls.py` if not already imported (`from starlette.requests import Request`).

2. In `backend/app/datasets/router.py`, add import: `from app.public_urls import get_dataset_service_url`

3. Replace all 4 call sites. Each is currently synchronous; switch to `await`:
   - Line ~384 (`list_all_datasets`): `list_base_url = _public_base_url(request)` -> `list_base_url = await get_dataset_service_url(db, request=request)`
   - Line ~474 (`create_empty_dataset_endpoint`): `base_url=_public_base_url(request)` -> `base_url=await get_dataset_service_url(db, request=request)`
   - Line ~598 (`get_single_dataset`): `base_url=_public_base_url(request)` -> `base_url=await get_dataset_service_url(db, request=request)`
   - Line ~1138 (`update_dataset_metadata`): `base_url=_public_base_url(request)` -> `base_url=await get_dataset_service_url(db, request=request)`

   All 4 call sites already have `db: AsyncSession` in scope (injected via `Depends(get_db)`). All are already `async def`.

4. Delete the `_public_base_url` function definition (lines 131-155).

**L5 — Split datasets/router.py (per user decision: split by operation type):**

Create `backend/app/datasets/helpers.py` with shared helpers, then split routes into sub-routers.

**Step 1: Create `helpers.py`** — Extract these from router.py:
- `_load_actor_identities` (lines 157-166)
- `_build_raster_metadata` (lines 169-238)
- `_dataset_to_response` (lines 241-324)

Keep all their existing imports. Since `_public_base_url` is already deleted by L4, no need to move it.

**Step 2: Create sub-routers.** Each file creates its own `APIRouter(prefix="/datasets", tags=["Datasets - {Group}"])` and defines its routes. Each imports shared helpers from `app.datasets.helpers`. Each file that needs the public URL imports `from app.public_urls import get_dataset_service_url`.

**`router_reupload.py`** — Reupload + presigned reupload (6 routes):
- `reupload_dataset` (POST `/{dataset_id}/reupload/`)
- `reupload_service_preview` (POST `/{dataset_id}/reupload/service-preview/`)
- `reupload_preview` (POST `/{dataset_id}/reupload/preview/`)
- `reupload_commit` (POST `/{dataset_id}/reupload/commit/`)
- `request_presigned_reupload` (POST `/{dataset_id}/presigned-reupload/`)
- `complete_presigned_reupload` (POST `/{dataset_id}/presigned-reupload/complete/`)

**`router_vrt.py`** — VRT endpoints (4 routes + _advisory_lock_key helper):
- `list_vrt_sources` (GET `/{dataset_id}/vrt-sources/`)
- `get_vrt_status` (GET `/{dataset_id}/vrt/status/`)
- `list_vrt_generations` (GET `/{dataset_id}/vrt/generations/`)
- `regenerate_vrt_endpoint` (POST `/{dataset_id}/regenerate-vrt/`)

**`router_metadata.py`** — Attributes, column-stats, relationships, versions (8 routes):
- `list_attributes_endpoint` (GET `/{dataset_id}/attributes/`)
- `get_attribute_endpoint` (GET `/{dataset_id}/attributes/{attr_name}`)
- `update_attribute_endpoint` (PATCH `/{dataset_id}/attributes/{attr_name}`)
- `reset_attribute_endpoint` (POST `/{dataset_id}/attributes/{attr_name}/reset/`)
- `get_column_values` (GET `/{dataset_id}/column-values/{col_name}`)
- `get_column_stats_endpoint` (GET `/{dataset_id}/stats/{col_name}`)
- `get_dataset_versions_endpoint` (GET `/{dataset_id}/versions/`)
- Relationship routes: list (GET), create (POST), delete (DELETE), get_feature_related_records (GET)

**`router_export.py`** — DCAT + download (3 routes):
- `get_dcat_catalog` (GET `/dcat/`)
- `get_dcat_record` (GET `/{dataset_id}/dcat/`)
- `download_cog` (GET `/{dataset_id}/download/cog`)

**`router_data.py`** — Data access + misc (4 routes):
- `list_related_datasets` (GET `/{dataset_id}/related/`)
- `get_dataset_rows_endpoint` (GET `/{dataset_id}/rows`)
- `validate_dataset` (GET `/{dataset_id}/validate/`)
- `dataset_maps` (GET `/{dataset_id}/maps/`)
- `update_publication_status` (PATCH `/{dataset_id}/status`)

**Step 3: Trim `router.py`** to Core CRUD only (~600 lines):
- `list_all_datasets` (GET `/`)
- `create_empty_dataset_endpoint` (POST `/`)
- `get_single_dataset` (GET `/{dataset_id}`)
- `update_dataset_metadata` (PATCH `/{dataset_id}`)
- `delete_dataset_endpoint` (DELETE `/{dataset_id}`)
- `get_quicklook` (GET `/{dataset_id}/quicklook`)
- `get_dataset_history` (GET `/{dataset_id}/history`)

The `router.py` tag stays as `tags=["Datasets"]`. Import helpers from `app.datasets.helpers`.

**Step 4: Update `backend/app/main.py`** — Register sub-routers. CRITICAL: order matters. `router_export.py` must be registered BEFORE `router.py` because `/dcat/` would be captured by `/{dataset_id}` otherwise. Registration order:

```python
from app.datasets.router import router as datasets_router
from app.datasets.router_export import router as datasets_export_router
from app.datasets.router_vrt import router as datasets_vrt_router
from app.datasets.router_data import router as datasets_data_router
from app.datasets.router_metadata import router as datasets_metadata_router
from app.datasets.router_reupload import router as datasets_reupload_router

# Register export BEFORE core (has /dcat/ that conflicts with /{dataset_id})
app.include_router(datasets_export_router)
app.include_router(datasets_router)
app.include_router(datasets_vrt_router)
app.include_router(datasets_data_router)
app.include_router(datasets_metadata_router)
app.include_router(datasets_reupload_router)
```

Replace the single `app.include_router(datasets_router)` line (currently line 369) with these 6 lines.

**Step 5: Create `backend/app/datasets/__init__.py`** if it does not already exist (it likely does).

Each sub-router file must include all imports needed for its routes. Copy the relevant imports from the top of the original router.py, do not use `from app.datasets.router import *`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T api python -m pytest tests/test_datasets.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    - get_dataset_service_url wrapper exists in public_urls.py, delegates to get_public_app_url
    - _public_base_url is deleted; all 4 call sites use await get_dataset_service_url(db, request=request)
    - datasets/router.py is Core CRUD only (under 600 lines)
    - 5 sub-router files exist: router_reupload.py, router_vrt.py, router_metadata.py, router_export.py, router_data.py
    - helpers.py contains shared functions (_dataset_to_response, _build_raster_metadata, _load_actor_identities)
    - All 6 routers registered in main.py with export BEFORE core (route order preserved)
    - All existing dataset tests pass with no changes to test files
  </done>
</task>

</tasks>

<verification>
Run the full backend test suite to confirm no regressions:

```bash
cd /Users/ishiland/Code/geolens && docker compose exec -T api python -m pytest tests/ -x -q 2>&1 | tail -30
```

Spot-check key endpoints manually:
- `GET /api/collections/` returns correct counts/extents
- `GET /api/maps/{id}` returns forked_from_name and created_by_username
- `GET /api/datasets/` returns tile connect URLs with proper base URL
- `GET /api/datasets/dcat/` still resolves (not captured by /{dataset_id})
</verification>

<success_criteria>
- M1: list_collections_endpoint uses 3 queries (list + batched extent + batched count) regardless of collection count
- M2: get_map_with_layers returns forked_from_name + owner_username from JOINs; no separate resolve calls in router
- L4: _public_base_url function deleted; get_dataset_service_url wrapper in public_urls.py; all dataset call sites use it
- L5: datasets/router.py under 600 lines; 5 sub-routers + 1 helpers file created; all registered in main.py
- All existing tests pass without modification
</success_criteria>

<output>
After completion, create `.planning/quick/260327-rkx-api-audit-follow-ups-m1-batch-n-1-m2-joi/260327-rkx-SUMMARY.md`
</output>

# Quick Task 260327-rkx: API Audit Follow-ups - Research

**Researched:** 2026-03-27
**Domain:** FastAPI/SQLAlchemy query optimization + router decomposition
**Confidence:** HIGH

## Summary

Four independent backend improvements. M1 and M2 are query optimizations (batching N+1 queries). L4 is replacing a local URL helper with a shared one. L5 is decomposing a 2,231-line router file into sub-routers.

All four items are well-scoped with clear patterns already established in the codebase.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **L5 split strategy:** By operation type -- CRUD, export/download, STAC/OGC, tiles/services
- **L4 replacement:** Create a new dedicated helper like `get_dataset_service_url()`, purpose-specific
- **M1 batching:** Use SQLAlchemy eager loading / joinedload

### Claude's Discretion
- M2 implementation details (straightforward JOIN addition)

### Deferred Ideas
None.

</user_constraints>

## M1: Batch N+1 Queries in `list_collections_endpoint`

### Current Problem (lines 191-197 of `collections/router.py`)

```python
collections, total = await list_collections(db, skip=skip, limit=limit)
for coll in collections:
    extent_data = await compute_collection_extent(db, coll.id, user, user_roles)
    ds_count = await get_collection_dataset_count(db, coll.id, user, user_roles)
    responses.append(...)
```

This issues **2 queries per collection** inside a loop (extent + count). With `limit=50`, that is 100 extra queries.

### What the N+1 Queries Do

1. **`compute_collection_extent`** (service.py:231): Aggregates `ST_Collect` of spatial extents + `MIN/MAX` temporal bounds across datasets in that collection, joining `Dataset -> CollectionDataset -> Record`, with visibility filter.

2. **`get_collection_dataset_count`** (service.py:275): `COUNT(*)` of visible datasets in that collection, same join chain, same visibility filter.

### Recommended Fix

These cannot use SQLAlchemy `joinedload` because they are aggregate queries, not relationship loading. The correct approach is to **batch the two queries into single multi-collection queries** using `GROUP BY collection_id`.

**Batched extent query:**
```python
stmt = (
    select(
        CollectionDataset.collection_id,
        func.ST_AsGeoJSON(func.ST_Envelope(func.ST_Collect(Record.spatial_extent))).label("bbox_geojson"),
        func.min(Record.temporal_start).label("temporal_start"),
        func.max(Record.temporal_end).label("temporal_end"),
    )
    .select_from(Dataset)
    .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
    .join(Record, Dataset.record_id == Record.id)
    .where(CollectionDataset.collection_id.in_(collection_ids))
    .group_by(CollectionDataset.collection_id)
)
stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
```

**Batched count query:**
```python
stmt = (
    select(
        CollectionDataset.collection_id,
        func.count().label("cnt"),
    )
    .select_from(Dataset)
    .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
    .join(Record, Dataset.record_id == Record.id)
    .where(CollectionDataset.collection_id.in_(collection_ids))
    .group_by(CollectionDataset.collection_id)
)
stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
```

This reduces N+1 to exactly **3 queries** (list + batched extent + batched count), or even **2 queries** if extent and count are combined into a single SELECT with all four aggregates.

### Pitfall
- Collections with zero visible datasets will not appear in the GROUP BY result. Use `dict.get(coll_id, default)` when building responses.
- The visibility filter must still be applied identically to the batched query.

### Where to Place
New batch functions should go in `collections/service.py` alongside the existing per-collection versions. The existing single-collection functions are still used by `get_collection_endpoint` and `update_collection_endpoint`, so keep them.

## M2: JOIN `forked_from_name` + `owner_username` into `get_map_with_layers`

### Current Problem (lines 289-290 of `maps/router.py`)

After `get_map_with_layers` returns, the router makes 2 additional queries:
```python
forked_name = await resolve_forked_from_name(db, map_obj.forked_from)  # SELECT map.name WHERE id=...
owner_username = await _resolve_owner_username(db, map_obj.created_by)  # SELECT user.username WHERE id=...
```

These are simple scalar lookups by FK that fire 2 extra queries on every map GET/PUT/duplicate.

### Recommended Fix

Modify `get_map_with_layers` in `maps/service.py` to use aliased self-join and user join:

```python
from sqlalchemy.orm import aliased

ForkedMap = aliased(Map)
OwnerUser = aliased(User)

# In get_map_with_layers, change the initial map fetch:
stmt = (
    select(Map, ForkedMap.name.label("forked_from_name"), OwnerUser.username.label("owner_username"))
    .outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)
    .outerjoin(OwnerUser, Map.created_by == OwnerUser.id)
    .where(Map.id == map_id)
)
result = await session.execute(stmt)
row = result.one_or_none()
if row is None:
    return None, [], None, None
map_obj, forked_from_name, owner_username = row[0], row[1], row[2]
```

### Return Type Change

Current: `tuple[Map | None, list[tuple]]`
New: `tuple[Map | None, list[tuple], str | None, str | None]`

The 3rd and 4th elements are `forked_from_name` and `owner_username`.

### Callers to Update

Three call sites in `maps/router.py` that currently call `resolve_forked_from_name` + `_resolve_owner_username` separately:
- `get_map_endpoint` (~line 289)
- `update_map_endpoint` (~line 362)
- `duplicate_map_endpoint` (~line 453)

After the change, each unpacks from the service return and passes directly to `_build_map_response`.

The `_resolve_owner_username` function (router.py:131) and `resolve_forked_from_name` function (service.py:540) can be removed if no other callers exist.

### Pitfall
- Both joins must be `outerjoin` -- `forked_from` is nullable (most maps are not forks) and `created_by` is nullable (user could be deleted, `ondelete=SET NULL`).

## L4: Replace `_public_base_url` in `datasets/router.py`

### Current State

**`_public_base_url(request)`** (datasets/router.py:131): Derives the public origin from `X-Forwarded-Host` / `Host` headers. Returns just the origin (e.g., `http://localhost:8080`). Does NOT consult the database or app settings. Synchronous.

**`get_public_api_url(db, request=None)`** (public_urls.py:218): Consults DB `AppSetting` overrides, then env config, then request headers. Returns the full API URL. Async (hits DB).

### Key Difference

`_public_base_url` is used for building tile connect URLs in `_build_raster_metadata` (e.g., `{base_url}/raster-tiles/{id}/tiles/...?api_key=...`). It needs the **app origin** (what the browser sees), not the API URL. The tile URLs go through nginx, so the base is the app's public origin.

`get_public_api_url` returns the **API** URL (which may include an `/api` suffix depending on configuration).

### Recommended Approach

Create `get_dataset_service_url(db, request=None) -> str` in `public_urls.py`:

```python
async def get_dataset_service_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    """Resolve the public origin for building dataset service URLs (tiles, quicklooks).

    These URLs are served through nginx at the app root, not through /api,
    so we use the app URL (not the API URL).
    """
    app_url, _ = await get_public_urls(db, request=request)
    return app_url
```

This is essentially `get_public_app_url` -- verify whether the existing `get_public_app_url` function already does exactly this. If so, just import and use it directly instead of creating a new helper. The only reason to wrap it would be a more descriptive name.

### Call Sites to Update (4 total)

| Line | Endpoint | Current |
|------|----------|---------|
| 384 | `list_all_datasets` | `_public_base_url(request)` |
| 474 | `create_empty_dataset_endpoint` | `_public_base_url(request)` |
| 598 | `get_single_dataset` | `_public_base_url(request)` |
| 1138 | `update_dataset_metadata` | `_public_base_url(request)` |

Each call site already has `db: AsyncSession` available, so switching to an async DB-backed helper is straightforward. Add `await` at each call site.

### Pitfall
- The current `_public_base_url` is synchronous and never hits the DB. Replacing with a DB-backed helper adds 1 query per request (or per cache TTL if cached). However, `get_public_urls` is already called in DCAT endpoints in the same file, so this is consistent.
- Ensure the replacement returns the **app origin** (no `/api` suffix), not the API URL.

## L5: Split `datasets/router.py` (2,231 lines)

### Current Structure and Groupings

The file has clear section comments. Here is the natural decomposition:

| Group | Lines | Routes | Description |
|-------|-------|--------|-------------|
| **Core CRUD** | 131-600 | 5 | List, get, create-empty, patch, delete + helpers (`_public_base_url`, `_load_actor_identities`, `_build_raster_metadata`, `_dataset_to_response`) |
| **DCAT export** | 409-510 | 2 | `/dcat/` catalog + `/{id}/dcat/` single |
| **VRT** | 659-975 | 4 | vrt-sources, vrt/status, vrt/generations, regenerate-vrt |
| **Data access** | 976-1050 | 3 | related, rows, validate |
| **Reupload** | 1235-1720 | 6 | reupload, reupload-service-preview, reupload-preview, reupload-commit, presigned-reupload, presigned-complete |
| **Versions** | 1723-1755 | 1 | versions |
| **Attributes** | 1758-1918 | 4 | list, get, patch, reset attribute metadata |
| **Column stats** | 1920-1990 | 2 | column values, column stats |
| **Misc** | 1993-2231 | 6 | maps-containing, download-cog, publication-status, relationships (4 routes) |

### Recommended Split (4 sub-routers per CONTEXT.md)

```
backend/app/datasets/
  router.py          -> Core CRUD (list, get, create, patch, delete, quicklook, history)
                        + shared helpers (_dataset_to_response, _build_raster_metadata, etc.)
  router_export.py   -> DCAT, download-cog, versions
  router_vrt.py      -> VRT sources/status/generations/regenerate
  router_data.py     -> rows, validate, related, column-values, column-stats,
                        attributes, maps-containing, relationships, reupload
```

Alternative more granular split (if preferred):

```
backend/app/datasets/
  router.py          -> Core CRUD + shared helpers (keeps ~600 lines)
  router_reupload.py -> Reupload + presigned reupload (6 routes, ~485 lines)
  router_vrt.py      -> VRT endpoints (4 routes, ~315 lines)
  router_metadata.py -> Attributes, column-stats, relationships, versions (~470 lines)
  router_export.py   -> DCAT, download-cog (~130 lines)
  router_misc.py     -> data access (rows, validate, related, maps, status, ~230 lines)
```

### Implementation Pattern

Each sub-router creates its own `APIRouter` with the same prefix:

```python
# router_vrt.py
from fastapi import APIRouter
router = APIRouter(prefix="/datasets", tags=["Datasets - VRT"])

# In main router.py, export all for registration:
# Or register each sub-router separately in main.py
```

In `main.py`, register each:
```python
from app.datasets.router import router as datasets_router
from app.datasets.router_vrt import router as datasets_vrt_router
# ... etc
app.include_router(datasets_router)
app.include_router(datasets_vrt_router)
```

### Shared Helpers

Key helpers used across groups:
- `_dataset_to_response()` -- used in CRUD, reupload-commit, update. Keep in `router.py` or move to a `datasets/helpers.py`.
- `_build_raster_metadata()` -- only used by `_dataset_to_response`
- `_load_actor_identities()` -- used in list, get, create, update, reupload-commit
- `_public_base_url()` -- used in list, get, create, update. If L4 replaces this first, the dependency becomes an import from `public_urls.py`.

**Recommendation:** Move shared helpers to `datasets/helpers.py` and import from each sub-router. This eliminates circular import risk and keeps each router file focused on route definitions.

### Pitfall
- Route registration order matters for path conflicts (e.g., `/dcat/` must register before `/{dataset_id}` to avoid being captured as a UUID path param). Current order in the single file already handles this correctly. When splitting, ensure `main.py` registers sub-routers in the same order.
- All sub-routers sharing `prefix="/datasets"` is correct -- FastAPI merges them.

## Common Pitfalls

### Pitfall 1: GROUP BY Missing Collections (M1)
Collections with zero visible datasets produce no row in the grouped result. Always use `extent_data.get(coll.id, default_empty)` rather than indexing.

### Pitfall 2: Outer Join NULL (M2)
`forked_from` is nullable on most maps. `created_by` can be NULL if user was deleted. Both JOINs must be `outerjoin`.

### Pitfall 3: Route Registration Order (L5)
Path `/{dataset_id}` captures any string. Routes like `/dcat/` and `/relationships/{id}/` must be registered BEFORE the wildcard `/{dataset_id}` route. When splitting into sub-routers, this means `router_export.py` (which has `/dcat/`) must be included before the main `router.py` in `main.py`.

### Pitfall 4: Sync to Async Conversion (L4)
`_public_base_url` is sync. Replacement is async (DB call). Every call site needs `await` added. Missing `await` will return a coroutine object instead of a string, causing silent bugs in URL concatenation.

## Project Constraints (from CLAUDE.md)

- Never indicate AI/Bot activity in commit messages
- Prefer simple, readable code over clever abstractions
- Follow existing project conventions when editing files

## Sources

### Primary (HIGH confidence)
- `backend/app/collections/router.py` -- N+1 loop at lines 191-197
- `backend/app/collections/service.py` -- extent/count query logic at lines 231-292
- `backend/app/maps/service.py` -- `get_map_with_layers` at line 103, `resolve_forked_from_name` at line 540
- `backend/app/maps/router.py` -- 3 call sites for forked_name/owner_username lookups
- `backend/app/datasets/router.py` -- `_public_base_url` at line 131, 4 call sites
- `backend/app/public_urls.py` -- full URL resolution infrastructure

## Metadata

**Confidence breakdown:**
- M1 (N+1 batching): HIGH -- clear N+1 pattern, standard GROUP BY fix
- M2 (JOIN forked/owner): HIGH -- straightforward outerjoin, small scope
- L4 (replace _public_base_url): HIGH -- existing infrastructure in public_urls.py covers the use case
- L5 (router split): HIGH -- section comments already define groupings, existing project pattern is clear

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable backend patterns)

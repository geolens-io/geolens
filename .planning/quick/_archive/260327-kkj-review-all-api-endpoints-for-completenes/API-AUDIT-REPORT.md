# GeoLens API Endpoint Audit Report

**Date:** 2026-03-27
**Scope:** 23 routers, ~158 endpoints
**Backend:** FastAPI (Python)
**Worktree:** agent-a5d7c954 (branch: main)

---

## Executive Summary

- Total routers reviewed: 23
- Total endpoints: ~158
- Critical findings: 2
- High findings: 8
- Medium findings: 5
- Low findings: 6
- Suggested enhancements: 6

The codebase is mature and consistently structured. Audit logging, permission modeling, visibility enforcement, and error handling are strong throughout. The two critical findings are a real auth gap (unauthenticated access to share token info) and a systemic pattern issue (embed token admin uses `require_role` while every other admin surface uses `require_permission`). Most remaining issues are code quality items — a 1,650-line god-router, utility duplication, STAC endpoint N+1 queries, a stale version string — that do not affect correctness or security.

---

## Findings

### CRITICAL: Security & Correctness

#### C1. Share token endpoint exposes token info to any authenticated user

- **Severity:** CRITICAL
- **File:** `backend/app/maps/router.py:441-455`
- **Description:** `GET /maps/{map_id}/share` returns the active share token and its URL to any authenticated user without checking whether they own the map. The POST, PATCH, and DELETE share endpoints all call `await check_map_ownership(map_obj, user, db)`, but the GET omits it. A user who knows a map UUID can discover whether a share token exists and retrieve its URL.
- **Current code:**
  ```python
  @router.get("/{map_id}/share", response_model=ShareTokenResponse | None)
  async def get_map_share_token_endpoint(
      map_id: uuid.UUID,
      user: User = Depends(get_current_active_user),
      db: AsyncSession = Depends(get_db),
  ) -> ShareTokenResponse | None:
      token_obj = await get_active_share_token(db, map_id)
      if token_obj is None:
          return None
      return ShareTokenResponse(...)
  ```
- **Fix:**
  ```python
  @router.get("/{map_id}/share", response_model=ShareTokenResponse | None)
  async def get_map_share_token_endpoint(
      map_id: uuid.UUID,
      user: User = Depends(get_current_active_user),
      db: AsyncSession = Depends(get_db),
  ) -> ShareTokenResponse | None:
      map_obj = await get_map(db, map_id)
      if map_obj is None:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")
      await check_map_ownership(map_obj, user, db)
      token_obj = await get_active_share_token(db, map_id)
      if token_obj is None:
          return None
      return ShareTokenResponse(...)
  ```

---

#### C2. Embed token admin uses `require_role("admin")` — inconsistent with permission matrix

- **Severity:** CRITICAL
- **Files:** `backend/app/embed_tokens/admin_router.py:40`, `backend/app/embed_tokens/admin_router.py:65`
- **Description:** The admin embed token endpoints (`GET /admin/embed-tokens/` and `POST /admin/embed-tokens/bulk-revoke/`) use `require_role("admin")` while every other admin surface in the codebase uses `require_permission("manage_users")` or `require_permission("manage_settings")`. This breaks the permission matrix model: if an organization customizes the permission matrix to grant admin-level access to a non-admin role (e.g., a "super_editor" role with manage_users capability), that role cannot reach these endpoints. It also means testing and auditing the permission model misses this surface.
- **Current code:**
  ```python
  @router.get("/", response_model=AdminEmbedTokenListResponse)
  async def list_all_embed_tokens(
      ...
      user: User = Depends(require_role("admin")),   # line 40
      ...
  @router.post("/bulk-revoke/", response_model=BulkRevokeResponse)
  async def bulk_revoke(
      ...
      user: User = Depends(require_role("admin")),   # line 65
      ...
  ```
- **Fix:**
  ```python
  user: User = Depends(require_permission("manage_users")),
  ```
  Apply to both endpoints. Matches the pattern used in `admin/router.py` for every other admin endpoint.

---

### HIGH: Inconsistencies & Missing Patterns

#### H1. `_extent_to_bbox` helper duplicated in 4 routers

- **Severity:** HIGH
- **Files:**
  - `backend/app/datasets/router.py:121`
  - `backend/app/collections/router.py:50`
  - `backend/app/ogc/router.py:39`
  - `backend/app/maps/router.py:62`
- **Description:** Identical 10-line function duplicated across four router files. Each version converts a GeoAlchemy2 geometry extent to a `[minx, miny, maxx, maxy]` bbox list. Any bug fix or behavior change must be applied in four places.
- **Current code (identical in all 4 files):**
  ```python
  def _extent_to_bbox(extent) -> list[float] | None:
      if extent is None:
          return None
      try:
          shape = to_shape(extent)
          return list(shape.bounds)
      except Exception:
          return None
  ```
- **Fix:** Create `backend/app/utils/geo.py`:
  ```python
  from geoalchemy2.shape import to_shape

  def extent_to_bbox(extent) -> list[float] | None:
      """Convert a GeoAlchemy2 geometry extent to [minx, miny, maxx, maxy]."""
      if extent is None:
          return None
      try:
          shape = to_shape(extent)
          return list(shape.bounds)
      except Exception:
          return None
  ```
  Import and use `from app.utils.geo import extent_to_bbox` in all four routers.

---

#### H2. `_dataset_to_response` duplicated and diverged between `collections/` and `datasets/` routers

- **Severity:** HIGH
- **Files:** `backend/app/collections/router.py`, `backend/app/datasets/router.py`
- **Description:** Both routers implement their own `_dataset_to_response` / `_collection_to_response` conversion function. The `collections` version is missing newer fields added in later milestones (e.g., `record_type`, `raster`, `stac_assets`, `last_edited_by_display`, `last_edited_at`) that the `datasets` version includes. API consumers using the `/catalog/collections/{id}/datasets` endpoint receive an incomplete view of each dataset compared to `/datasets/{id}`.
- **Current code in `collections/router.py`:**
  ```python
  def _collection_to_response(collection, dataset_count, extent_data):
      # Does not include record_type, raster, stac_assets, last_edited_*
      ...
  ```
- **Fix:** Unify. Extract the canonical dataset-to-response conversion to `backend/app/datasets/utils.py` and import it in both routers. The collections endpoint should delegate to the same function used by the datasets router.

---

#### H3. `get_ai_status` uses `get_current_user` instead of `get_current_active_user`

- **Severity:** HIGH (consistency / lint)
- **File:** `backend/app/admin/router.py:446`
- **Description:** `GET /admin/ai-status/` uses `get_current_user` while all other "any authenticated user" endpoints use `get_current_active_user`. `get_current_user` already checks `is_active` and `status == "active"` internally (they are functionally equivalent), but the inconsistency causes confusion: is there an intentional reason this endpoint uses the lower-level dependency?
- **Current code:**
  ```python
  async def get_ai_status(
      user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_db),
  ```
- **Fix:**
  ```python
  async def get_ai_status(
      user: User = Depends(get_current_active_user),
      db: AsyncSession = Depends(get_db),
  ```

---

#### H4. Trailing slash inconsistency across routers

- **Severity:** HIGH
- **Files:** Multiple — `admin/router.py`, `collections/router.py`, `settings/router.py`, `audit/router.py`
- **Description:** Routes within the same router mix trailing-slash and no-trailing-slash patterns. FastAPI 307-redirects when a client omits a trailing slash from a route that has one (and vice versa), which causes visible failures when clients follow redirects to the internal `api:8000` hostname. Examples:
  - `admin/router.py`: `/admin/users` (no slash) vs `/admin/ai-status/` (with slash)
  - `admin/router.py`: `/admin/api-keys` (no slash) vs `/admin/embedding-stats/` (with slash)
  - `audit/router.py`: `/admin/audit-logs` (no slash)
  - `collections/router.py`: `/catalog/collections/` (with slash) vs `/{collection_id}/datasets` (no slash)
  - `settings/router.py`: all routes have trailing slashes — consistent within this file
- **Fix:** Normalize all routes. The project already documented trailing-slash behavior in MEMORY.md. Recommend: trailing slashes on all collection/list endpoints, no trailing slashes on item endpoints. At minimum, normalize within each router.

---

#### H5. Missing `response_model` on several endpoints

- **Severity:** HIGH
- **Files:**
  - `backend/app/maps/router.py:231` — `GET /{map_id}/visibility-check` returns `dict`
  - `backend/app/tiles/router.py:166` — `GET /tiles/token/{dataset_id}/` returns `dict`
  - `backend/app/settings/router.py:51` — `GET /settings/all/` lacks explicit return type annotation (uses implicit `-> SettingsAllResponse` but no `response_model=`)
  - `backend/app/config_ops/router.py:32` — `GET /config-ops/export/` returns `JSONResponse` with no schema
- **Description:** Endpoints without `response_model` are excluded from OpenAPI schema generation. API consumers and auto-generated clients receive no type information for these responses. The tiles token endpoint is particularly notable because it returns a discriminated union (vector vs. raster) with no schema.
- **Fix:** Add Pydantic response models:
  ```python
  # maps/router.py
  class VisibilityCheckResponse(BaseModel):
      non_public_datasets: list[str]
      has_non_public: bool

  @router.get("/{map_id}/visibility-check", response_model=VisibilityCheckResponse)

  # tiles/router.py - discriminated union
  class VectorTileToken(BaseModel):
      kind: Literal["vector"]
      sig: str
      exp: int
      scope: str
      expires_in: int

  class RasterTileToken(BaseModel):
      kind: Literal["raster"]
      tile_url: str
      bounds: list[float] | None
      minzoom: int
      maxzoom: int
      tile_size: int
      format: str

  @router.get("/token/{dataset_id}/",
              response_model=VectorTileToken | RasterTileToken)
  ```

---

#### H6. STAC collections and collection detail endpoints missing `response_model`

- **Severity:** HIGH
- **Files:** `backend/app/stac/router.py:209`, `backend/app/stac/router.py:270`
- **Description:** `GET /stac/collections` and `GET /stac/collections/{collection_id}` return untyped `dict` with no `response_model`. These public machine-facing endpoints are the most important to document via OpenAPI schema — STAC clients rely on the spec to validate responses.
- **Current code:**
  ```python
  @stac_router.get("/collections")
  async def get_collections(
      request: Request,
      db: AsyncSession = Depends(get_db),
  ):
      ...
      return {"collections": stac_collections, "links": [...]}

  @stac_router.get("/collections/{collection_id}")
  async def get_collection(
      collection_id: uuid.UUID,
      request: Request,
      db: AsyncSession = Depends(get_db),
  ):
  ```
- **Fix:** Create Pydantic response models based on STAC Collection spec:
  ```python
  class StacCollectionListResponse(BaseModel):
      collections: list[dict]
      links: list[StacLink]

  @stac_router.get("/collections", response_model=StacCollectionListResponse)
  ```
  Ideally use a full `StacCollection` model instead of `dict` for the list items.

---

#### H7. No pagination on `GET /auth/api-keys/` or `GET /admin/api-keys`


- **Severity:** HIGH
- **Files:** `backend/app/auth/router.py:221`, `backend/app/admin/router.py:383`
- **Description:** Both API key listing endpoints return all matching rows with no `skip`/`limit` parameters. While users typically have few keys, the admin endpoint fetches all API keys across all users — this will degrade as the user base grows. Inconsistent with every other list endpoint in the codebase.
- **Current code:**
  ```python
  @router.get("/api-keys/", response_model=list[ApiKeyListItem])
  async def list_my_api_keys(
      current_user: User = Depends(get_current_active_user),
      db: AsyncSession = Depends(get_db),
  ) -> list[ApiKeyListItem]:
      result = await db.execute(select(ApiKey).where(ApiKey.user_id == current_user.id))
      keys = result.scalars().all()
      return [...]  # all keys, no limit
  ```
- **Fix:**
  ```python
  @router.get("/api-keys/", response_model=ApiKeyListResponse)
  async def list_my_api_keys(
      skip: int = Query(0, ge=0),
      limit: int = Query(50, ge=1, le=200),
      current_user: User = Depends(get_current_active_user),
      db: AsyncSession = Depends(get_db),
  ) -> ApiKeyListResponse:
      stmt = select(ApiKey).where(ApiKey.user_id == current_user.id)
      count_stmt = select(func.count()).select_from(stmt.subquery())
      total = (await db.execute(count_stmt)).scalar_one()
      keys = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
      return ApiKeyListResponse(items=[...], total=total)
  ```

---

#### H8. `DELETE /settings/` uses DELETE verb for a reset operation

- **Severity:** HIGH (API design)
- **File:** `backend/app/settings/router.py:185`
- **Description:** The settings reset endpoint uses `DELETE /` with a JSON request body containing `keys` to reset. While technically valid per HTTP spec, DELETE with a body is semantically confusing and rejected by several HTTP clients and proxies. The operation does not "delete" settings — it resets them to defaults, which is a mutation, not a deletion.
- **Current code:**
  ```python
  @router.delete("/")
  async def reset_settings(
      body: SettingsResetRequest,
      ...
  ```
- **Fix:** Change to `POST /settings/reset/`:
  ```python
  @router.post("/reset/", response_model=SettingsAllResponse)
  async def reset_settings(
      body: SettingsResetRequest,
      ...
  ```
  Update frontend to `POST /settings/reset/` with the same body.

---

### MEDIUM: Performance & Optimization

#### M1. N+1 queries in `list_collections_endpoint`

- **Severity:** MEDIUM
- **File:** `backend/app/collections/router.py:196-200`
- **Description:** For each collection returned by `list_collections()`, two separate async DB calls are made: `compute_collection_extent(db, coll.id, ...)` and `get_collection_dataset_count(db, coll.id, ...)`. With N collections this is 2N+1 queries. The admin cache at `catalog:collections:admin:*` mitigates this for admin users, but non-admin requests are not cached and pay the full cost on every request.
- **Current code:**
  ```python
  for coll in collections:
      extent_data = await compute_collection_extent(db, coll.id, user, user_roles)
      ds_count = await get_collection_dataset_count(db, coll.id, user, user_roles)
      responses.append(_collection_to_response(coll, ds_count, extent_data))
  ```
- **Fix:** Batch both into single queries using `GROUP BY collection_id`:
  ```python
  # Single query: dataset count per collection
  count_stmt = (
      select(DatasetCollection.collection_id, func.count(DatasetCollection.dataset_id))
      .group_by(DatasetCollection.collection_id)
  )
  counts = dict((await db.execute(count_stmt)).all())

  # Single query: spatial extent per collection
  extent_stmt = (
      select(DatasetCollection.collection_id,
             func.ST_AsGeoJSON(func.ST_Extent(Record.spatial_extent)))
      .join(...)
      .group_by(DatasetCollection.collection_id)
  )
  ```

---

#### M2. Two extra DB queries in `get_map_endpoint`

- **Severity:** MEDIUM
- **File:** `backend/app/maps/router.py:277-278`
- **Description:** After `get_map_with_layers()` returns the map, two additional queries are fired: `await resolve_forked_from_name(db, map_obj.forked_from)` and `await _resolve_owner_username(db, map_obj.created_by)`. These are simple lookups that could be JOINed into the main `get_map_with_layers` query. Currently every map GET costs 3 DB round trips at minimum.
- **Current code:**
  ```python
  map_obj, layer_tuples = await get_map_with_layers(db, map_id)
  ...
  forked_name = await resolve_forked_from_name(db, map_obj.forked_from)
  owner_username = await _resolve_owner_username(db, map_obj.created_by)
  ```
- **Fix:** Extend `get_map_with_layers` service function to JOIN `User.username` for `created_by` and the forked map's `title` in the same query. Return them as part of the tuple result.

---

#### M3. Missing cache invalidation on dataset metadata updates

- **Severity:** MEDIUM
- **File:** `backend/app/datasets/router.py:699`
- **Description:** `PATCH /datasets/{dataset_id}` updates dataset metadata (title, visibility, etc.) but does NOT call `invalidate_catalog_cache()`. The delete endpoint at line 745 correctly calls it. The collections mutation endpoints also call it. This means admin users viewing the catalog list endpoint may see stale data (old titles, visibility labels) for up to the cache TTL (60s) after a metadata edit.
- **Current code (after commit at line 699):**
  ```python
  await db.commit()
  await db.refresh(dataset)
  await db.refresh(dataset.record)
  # invalidate_catalog_cache() NOT called here
  return _dataset_to_response(dataset, actors_by_id=actors_by_id)
  ```
- **Fix:** Add after the commit:
  ```python
  await db.commit()
  await db.refresh(dataset)
  await db.refresh(dataset.record)
  await invalidate_catalog_cache()   # add this line
  return _dataset_to_response(dataset, actors_by_id=actors_by_id)
  ```

---

#### M4. `raster_auth_check` uses inline RBAC logic instead of `check_dataset_access`

- **Severity:** MEDIUM
- **File:** `backend/app/tiles/router.py:114-137`
- **Description:** The raster auth-check endpoint (called on the nginx hot path) implements its own inline copy of the visibility/RBAC logic rather than calling `check_dataset_access()`. While the inline implementation is intentional for performance (single raw SQL query vs. ORM), it is now diverged from the canonical visibility logic. The `DatasetGrant` restricted-access check uses a different join pattern and will silently fail to enforce new grant models if `check_dataset_access` is updated but `raster_auth_check` is not.
- **Current code:**
  ```python
  # Inline RBAC checks (mirrors check_dataset_access logic)
  user_roles = await get_user_roles(db, user)
  if "admin" not in user_roles:
      if record_status != "published" and created_by != user.id:
          raise HTTPException(status_code=404, ...)
      if visibility == "private" and created_by != user.id:
          raise HTTPException(status_code=404, ...)
      if visibility == "restricted":
          # separate grant query
  ```
- **Fix:** Add a test that runs both `check_dataset_access` and the inline logic for the same dataset/user combination and asserts they produce identical results. This creates a regression guard without sacrificing the performance-optimized path.

---

#### M5. N+1 extent queries in `GET /stac/collections`

- **Severity:** MEDIUM
- **File:** `backend/app/stac/router.py:222-259`
- **Description:** For each collection, a raw SQL extent query is executed inside a Python loop. With N collections this is N+1 queries. The query computes spatial extent + temporal extent per collection from published raster/VRT datasets.
- **Current code:**
  ```python
  for coll in collections:
      extent_stmt = text("""
          SELECT ST_XMin(ST_Extent(r.spatial_extent)), ...
          FROM catalog.records r
          JOIN catalog.datasets d ON d.record_id = r.id
          JOIN catalog.collection_datasets cd ON cd.dataset_id = d.id
          WHERE cd.collection_id = :cid
            AND r.record_type IN ('raster_dataset', 'vrt_dataset')
            AND r.record_status = 'published'
      """)
      ext_result = await db.execute(extent_stmt, {"cid": str(coll.id)})
  ```
- **Fix:** Batch into a single query with `GROUP BY cd.collection_id`:
  ```python
  extent_stmt = text("""
      SELECT cd.collection_id,
             ST_XMin(ST_Extent(r.spatial_extent)),
             ST_YMin(ST_Extent(r.spatial_extent)),
             ST_XMax(ST_Extent(r.spatial_extent)),
             ST_YMax(ST_Extent(r.spatial_extent)),
             MIN(r.temporal_start),
             MAX(r.temporal_end)
      FROM catalog.records r
      JOIN catalog.datasets d ON d.record_id = r.id
      JOIN catalog.collection_datasets cd ON cd.dataset_id = d.id
      WHERE r.record_type IN ('raster_dataset', 'vrt_dataset')
        AND r.record_status = 'published'
      GROUP BY cd.collection_id
  """)
  extent_map = {str(row[0]): row[1:] for row in (await db.execute(extent_stmt)).all()}
  ```

---

### LOW: Cleanup & Simplification

#### L1. `audit/router.py` shares the `/admin` prefix with `admin/router.py`

- **Severity:** LOW
- **File:** `backend/app/audit/router.py:15`
- **Description:** Two separate router modules both use `prefix="/admin"`. The audit endpoint (`GET /admin/audit-logs`) lives in `audit/router.py` but appears under the same URL prefix as `admin/router.py`. This is architecturally confusing — developers looking for `/admin/*` endpoints have to check two files.
- **Current code:**
  ```python
  router = APIRouter(prefix="/admin", tags=["Admin"])
  ```
- **Fix (option A):** Move `list_audit_logs` into `admin/router.py`.
  **Fix (option B):** Keep separate but add a comment in both files noting the shared prefix and why.

---

#### L2. `config_ops/router.py` export has redundant double-await pattern

- **Severity:** LOW
- **File:** `backend/app/config_ops/router.py:43-44`
- **Description:** The export endpoint calls `export_config(db)` without `await`, then `await`s the result on the next line. This works because `export_config` is an async function that returns a coroutine, which is then awaited, but it reads confusingly — it looks like `export_config` is synchronous and returns an awaitable.
- **Current code:**
  ```python
  result = export_config(db)
  data = await result
  ```
- **Fix:**
  ```python
  data = await export_config(db)
  ```

---

#### L3. Duplicate `PRIORITY_QUEUE_THRESHOLD_BYTES` constant in two files

- **Severity:** LOW
- **Files:** `backend/app/ingest/router.py:52`, `backend/app/datasets/router.py:116`
- **Description:** Both files define `PRIORITY_QUEUE_THRESHOLD_BYTES = 10 * 1024 * 1024`. If the threshold is changed in one file, it must be changed in the other.
- **Current code:**
  ```python
  # ingest/router.py:52
  PRIORITY_QUEUE_THRESHOLD_BYTES = (10 * 1024 * 1024)

  # datasets/router.py:116
  PRIORITY_QUEUE_THRESHOLD_BYTES = (10 * 1024 * 1024)
  ```
- **Fix:** Create `backend/app/ingest/constants.py`:
  ```python
  PRIORITY_QUEUE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10MB
  ```
  Import in both router files.

---

#### L4. Dead `_public_base_url` helper in `datasets/router.py`

- **Severity:** LOW
- **File:** `backend/app/datasets/router.py` (search for `_public_base_url`)
- **Description:** The project has `get_public_api_url` and `get_public_app_url` in `public_urls.py` as the canonical URL utilities. However, some parts of `datasets/router.py` still call a local `_public_base_url` helper that manually parses `X-Forwarded-*` headers. This creates two sources of truth for public URL resolution.
- **Fix:** Replace all uses of `_public_base_url` with `get_public_api_url` / `get_public_app_url` from `app.public_urls` and remove the local helper.

---

#### L5. `datasets/router.py` is ~1,650 lines — 30+ endpoints in a single file

- **Severity:** LOW
- **File:** `backend/app/datasets/router.py`
- **Description:** The datasets router covers CRUD, re-upload, VRT management, DCAT export, validation, relationships, thumbnail, attribute metadata, history, and quicklook — all in one 1,650-line file. This is significantly longer than any other router (~140–720 lines). Navigation and review are difficult. The file is also the most likely source of merge conflicts given its size.
- **Fix:** Split into sub-routers:
  - `datasets_crud_router` — create, list, get, patch, delete
  - `datasets_upload_router` — re-upload, VRT management, table register
  - `datasets_metadata_router` — attributes, contacts, keywords, distributions
  - `datasets_export_router` — DCAT, quicklook, thumbnail
  - Include all sub-routers from `datasets/__init__.py`

---

#### L6. OpenAPI version string is stale

- **Severity:** LOW
- **File:** `backend/app/main.py:314`
- **Description:** The FastAPI app is initialized with `version="2.6.0"`. The project is at milestone v12.3. While this does not affect functionality, it creates confusion for API consumers relying on the OpenAPI spec to understand the API version.
- **Current code:**
  ```python
  app = FastAPI(
      title="GeoLens API",
      version="2.6.0",   # stale
      ...
  ```
- **Fix:** Either update the version string to match the current milestone (v12.3 → `"12.3.0"`) or derive it from package metadata:
  ```python
  from importlib.metadata import version, PackageNotFoundError
  try:
      _api_version = version("geolens-backend")
  except PackageNotFoundError:
      _api_version = "dev"

  app = FastAPI(title="GeoLens API", version=_api_version, ...)
  ```

---

## Suggested Enhancements

1. **Rate limiting on AI endpoints.** `POST /ai/generate`, `POST /ai/chat`, and the metadata assist endpoints call external LLM APIs. There are no per-user rate limits. A single user can exhaust API quota or run up charges. Add `@limiter.limit("20/minute")` (or similar) to all AI endpoints, similar to the auth router's existing rate limiting.

2. **Bulk dataset delete endpoint.** There is no `POST /datasets/bulk-delete` endpoint. Cleaning up test data or migrating a catalog requires N individual DELETE calls. Add a bulk-delete endpoint with the same `confirm_title`-style guard, restricted to `require_permission("edit_metadata")`.

3. **Export format enum validation.** `GET /datasets/{id}/export?format=` accepts any string. Invalid format values reach deep into ogr2ogr before failing with an opaque error. Add early validation:
   ```python
   from enum import Enum
   class ExportFormat(str, Enum):
       gpkg = "gpkg"
       geojson = "geojson"
       shp = "shp"
       csv = "csv"

   @router.get("/{dataset_id}/export")
   async def export_dataset_endpoint(
       format: ExportFormat = Query(ExportFormat.gpkg),
       ...
   ```

4. **Health endpoint response schema.** `GET /health` returns untyped JSON. Add a Pydantic response model for monitoring tool integration and OpenAPI documentation:
   ```python
   class ServiceHealth(BaseModel):
       status: str
       latency_ms: float | None = None
       detail: str | None = None

   class HealthResponse(BaseModel):
       status: str  # "healthy" | "degraded" | "unhealthy"
       services: dict[str, ServiceHealth]
   ```

5. **`/search/datasets` should support anonymous access.** `GET /search/datasets` requires `get_current_active_user`, while the OGC equivalent `GET /collections/datasets/items` uses `get_optional_user` (anonymous-friendly). Both ultimately call `_handle_search()`. There is no semantic reason for the gap — the visibility filter already handles anonymous access correctly. Change `search_datasets_endpoint` to use `get_optional_user` to expose public datasets to unauthenticated API consumers.

6. **Saved searches are per-user with no pagination.** `GET /search/saved` returns all saved searches for a user with no limit. This is fine at low volumes but add `skip`/`limit` for consistency with all other list endpoints.

---

## Endpoint Inventory

| # | Router Module | Prefix | Endpoints | Lines | Auth Pattern | Notes |
|---|--------------|--------|-----------|-------|--------------|-------|
| 1 | `datasets/router.py` | `/datasets` | 27 | 1,650 | `require_permission("edit_metadata")`, `get_current_active_user`, `get_optional_user` | Largest router — split recommended (L5) |
| 2 | `maps/router.py` | `/maps` | 15 | 719 | `require_permission("edit_metadata")`, `get_optional_user`, `get_current_active_user` | Share token auth gap (C1) |
| 3 | `admin/router.py` | `/admin` | 20 | 641 | `require_permission("manage_users")`, `get_current_user` | H3: `get_current_user` on ai-status |
| 4 | `search/router.py` | `/search` + `/collections` | 11 | 770 | `get_current_active_user`, `get_optional_user` | Two routers in one file; search endpoint requires auth (Enh. 5) |
| 5 | `settings/router.py` | `/settings` | 13 | 239 | `require_permission("manage_settings")`, none (public endpoints) | H7: DELETE with body |
| 6 | `records/router.py` | `/records` | 11 | 356 | `require_permission("edit_metadata")`, `get_current_active_user` | Consistent |
| 7 | `collections/router.py` | `/catalog/collections` | 8 | 310 | `require_permission("manage_collections")`, `get_optional_user` | M1: N+1 queries; H2: diverged response model |
| 8 | `ingest/router.py` | `/ingest` | 9 | 570 | `require_permission("upload")`, `get_current_active_user` | L3: duplicate constant |
| 9 | `auth/router.py` | `/auth` | 9 | 293 | `get_current_active_user`, none (login/register) | H6: no pagination on api-keys list |
| 10 | `ai/router.py` | `/ai` | 8 | ~350 | `require_permission("use_ai_chat")` | No rate limits (Enh. 1) |
| 11 | `ogc/router.py` | `/`, `/collections/{id}` | 5 | 360 | `get_optional_user` | OGC conformant; H1: `_extent_to_bbox` dup |
| 12 | `features/router.py` | `/datasets` | 6 | 310 | `get_current_active_user`, `require_permission("edit_metadata")` | Requires auth even for public datasets (documented gap) |
| 13 | `tiles/router.py` | `/tiles` | 3 | 351 | `get_optional_user`, HMAC signature, embed token | H5: no response_model on token endpoint; M4: inline RBAC copy |
| 14 | `layers/router.py` | `/layers` | 3 | 191 | `require_permission("create_layers")` | Consistent |
| 15 | `embed_tokens/router.py` | `/maps/{map_id}/embed-tokens` | 4 | 177 | `get_current_active_user` + ownership check | Consistent |
| 16 | `embed_tokens/admin_router.py` | `/admin/embed-tokens` | 2 | 85 | `require_role("admin")` | C2: should be `require_permission("manage_users")` |
| 17 | `config_ops/router.py` | `/config-ops` | 4 | 100 | `require_permission("manage_settings")` | L2: double-await pattern |
| 18 | `services/router.py` | `/services` | 2 | 378 | `require_permission("create_layers")` | Verbose but correct |
| 19 | `jobs/router.py` | `/jobs` | 2 | 166 | `get_current_active_user`, `require_permission("upload")` | RESEARCH.md C1 invalid — no cleanup endpoint exists |
| 20 | `export/router.py` | `/datasets` | 1 | 141 | `get_current_active_user` | Format validation loose (Enh. 3) |
| 21 | `audit/router.py` | `/admin` | 1 | 60 | `require_permission("manage_settings")` | L1: shares prefix with admin router |
| 22 | `auth/oauth/router.py` | `/auth/oauth` | 3 | 147 | None (OAuth flows) | Consistent |
| 23 | `stac/router.py` | `/stac` | 6 | 545 | None (public STAC API) | H6: missing response_model; M5: N+1 extent queries |
| - | `main.py` | `/` | 1 (health) | — | None | L6: stale version string |

**Total: ~158 endpoints across 23 routers**

---

## Cross-Cutting Patterns

### What's Working Well

- **Audit logging**: Mutations consistently log via `log_action()` with user_id, action, resource_type, resource_id, and ip_address. Coverage is near-complete across all mutation endpoints.
- **Structured error handling**: Consistent use of `HTTPException` with appropriate status codes. Service-layer `ValueError` is caught and converted to 400/404 at the router boundary throughout.
- **Permission model**: `require_permission()` factory with named capabilities is well-designed, extensible, and consistently used. The permission matrix pattern is sound.
- **OGC compliance**: Landing page, conformance, CQL2 filtering, pagination links, and Content-Crs headers follow the spec. Anonymous access on OGC endpoints is correct.
- **Visibility enforcement**: `check_dataset_access()` and `apply_visibility_filter()` are called correctly before any data access in all data-serving endpoints.
- **Cache invalidation**: Collection and catalog caches are cleared on mutations. The delete endpoint and collection mutations handle this well.
- **201 on creation**: Most POST endpoints that create resources correctly return `HTTP_201_CREATED` (maps, ingest, layers, embed tokens, saved searches).
- **Input validation**: Pydantic models validate request bodies. Query params use `Query()` with `ge`/`le` constraints for pagination.
- **SSRF protection**: Services router validates URLs with `validate_url_for_ssrf()` before making any outbound requests.

---

### Auth Dependency Usage

| Dependency | Purpose | Used By |
|------------|---------|---------|
| `get_optional_user` | Anonymous + authenticated access | OGC, collections (list), tiles, maps (get), records (list), search (OGC items), stac |
| `get_current_active_user` | Any authenticated user | datasets (list/get), features (read), jobs, export, embed_tokens, auth, records mutations |
| `get_current_user` | Any authenticated user (legacy — same behavior) | `admin/router.py:446` `get_ai_status` only |
| `require_permission(cap)` | Capability-based access | Mutations, admin ops, AI, ingest, services |
| `require_role(role)` | Role-based access (older pattern) | `embed_tokens/admin_router.py` only — should be migrated to `require_permission` |

---

## Methodology

All 22 router files were read directly from the `agent-a5d7c954` worktree. Each endpoint was inspected for: auth dependency type, presence of `response_model`, HTTP status codes, error handling coverage, DB query patterns, and consistency with the codebase's own established patterns. The 22 findings from `RESEARCH.md` were verified against actual line numbers in the current source. Line numbers for shifted findings are reported as-found in the current code.

---

## Verification Notes

**RESEARCH.md findings verified, corrected, or invalidated:**

**C1 (RESEARCH: `require_permission("admin")` at `jobs/router.py:29`)** — INVALIDATED. The `jobs/router.py` file has no `cleanup_stale_jobs` endpoint. The router contains only `GET /{job_id}` (get status) and `POST /{job_id}/retry` (retry). The file is 166 lines. No admin-only endpoint using `require_permission("admin")` was found anywhere in the file.

**C2 (embed_tokens/admin_router.py)** — CONFIRMED. Lines 40 and 65 both use `require_role("admin")`. Raised as finding C2 above.

**C3 (`get_map_share_token_endpoint` visibility check)** — CONFIRMED at `maps/router.py:441`. Raised as finding C1 above (re-prioritized to most critical).

**C4 (double `require_permission` on `admin_revoke_share_token`)** — INVALIDATED. Current code at `admin/router.py:622-641` uses ONLY `dependencies=[Depends(require_permission("manage_users"))]`. There is no `current_user` parameter injection — the endpoint signature takes only `token_id` and `db`. Single permission check. This finding was already resolved.

**C5 (`list_features` vs OGC inconsistency)** — CONFIRMED at `features/router.py:60-66` (`get_current_active_user`) vs OGC items endpoint (`get_optional_user`). Documented as Enhancement 5 (change `search_datasets_endpoint` to use `get_optional_user`); the features endpoint inconsistency is noted as a documented gap (OGC endpoint covers anonymous access cases).

**H1–H7** — All confirmed against current source.

**M1–M5 (RESEARCH M5: `raster_tile_proxy` httpx client per request)** — M5 INVALIDATED. There is no `raster_tile_proxy` function in `tiles/router.py`. Raster tiles are served via nginx → Titiler proxy (auth-check pattern), not a Python-level httpx proxy. The Python tiles router has no httpx client. Findings M1–M4 confirmed and documented above.

**L1–L7 (RESEARCH L7: `main.py version="2.6.0"` at line 332)** — CONFIRMED at line 314 (line number shifted). All other L findings confirmed.

**STAC router** — CONFIRMED present at `backend/app/stac/router.py` (545 lines, 6 endpoints). Registered in `main.py` at line 390. Two findings restored: missing `response_model` on collections endpoints (H6), N+1 extent queries (M5). Earlier invalidation was incorrect.

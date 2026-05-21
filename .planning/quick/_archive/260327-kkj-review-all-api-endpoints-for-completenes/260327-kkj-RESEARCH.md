# Quick Task 260327-kkj: API Endpoint Review - Research

**Researched:** 2026-03-27
**Domain:** FastAPI backend — all 22+ routers
**Confidence:** HIGH (direct source review)

## Summary

Comprehensive review of all API routers in the GeoLens backend. The codebase is mature (40 milestones shipped) and generally well-structured. Most routers follow consistent patterns: Pydantic response models, proper auth dependencies, audit logging on mutations, and structured error handling. The findings below focus on actionable issues grouped by severity.

**Primary recommendation:** Address the 5 correctness/security items first, then tackle the consistency and cleanup items as a batch.

## User Constraints (from CONTEXT.md)

### Review Scope
- All 22 API routers reviewed
- Output: structured audit with findings grouped by severity
- Identify issues AND propose specific changes
- Not implementing fixes — cataloging with proposals

### Priority Focus
- Correctness & security
- Completeness & gaps
- Performance & optimization
- Cleanup & simplification

---

## Findings by Severity

### CRITICAL: Correctness & Security

**C1. `require_permission("admin")` is not a real capability — jobs/router.py:29**

The `cleanup_stale_jobs` endpoint uses `require_permission("admin")`. The `require_permission` factory checks the permission matrix for capability names, but `"admin"` is a role name, not a capability. This depends on whether the permission matrix happens to have an `admin` key — if it does not, no user can access this endpoint; if it does, it may grant unintended access.

- **File:** `backend/app/jobs/router.py:29`
- **Fix:** Change to `require_role("admin")` or `require_permission("manage_users")` to match the admin pattern used everywhere else.

**C2. Mixed auth patterns for admin embed token endpoints**

The `embed_tokens/admin_router.py` uses `require_role("admin")` while every other admin endpoint uses `require_permission("manage_users")` or `require_permission("manage_settings")`. This means permission matrix customization (where an org grants admin-like permissions to a non-admin role) will not work for embed token management.

- **Files:** `backend/app/embed_tokens/admin_router.py:40,65`
- **Fix:** Replace `require_role("admin")` with `require_permission("manage_users")` for consistency with the rest of the admin surface.

**C3. Visibility check incomplete on `get_map_share_token_endpoint`**

The `GET /maps/{map_id}/share` endpoint returns share token info to any authenticated user without checking map ownership. Any logged-in user can discover whether a map has an active share token and retrieve its URL.

- **File:** `backend/app/maps/router.py:478-492`
- **Fix:** Add `await check_map_ownership(map_obj, user, db)` after fetching the map, consistent with the POST/PATCH/DELETE share endpoints.

**C4. `admin_revoke_share_token` double-resolves `require_permission`**

The `DELETE /admin/share-tokens/{token_id}` endpoint has both `dependencies=[Depends(require_permission("manage_users"))]` and `current_user: User = Depends(require_permission("manage_users"))`, causing the permission check to run twice.

- **File:** `backend/app/admin/router.py:641-649`
- **Fix:** Remove the `dependencies=` kwarg and keep only the parameter injection.

**C5. No RBAC check on `list_features` — requires any authenticated user but no visibility check**

The `GET /datasets/{dataset_id}/features/` endpoint calls `check_dataset_access` which enforces visibility. However, `list_features` requires `get_current_active_user` (any authenticated user), while the OGC equivalent at `GET /collections/{dataset_id}/items` uses `get_optional_user` (anonymous access for public datasets). This means public dataset features are not accessible to anonymous API consumers via the internal features endpoint, only via OGC.

- **File:** `backend/app/features/router.py:61-69`
- **Impact:** Low — OGC endpoint covers anonymous access. But the inconsistency may confuse API consumers.
- **Fix:** Consider using `get_optional_user` and gating on visibility, matching the OGC router pattern. Or document the split intentionally.

### HIGH: Inconsistencies & Missing Patterns

**H1. `_extent_to_bbox` duplicated in 4 files**

Identical function duplicated in `datasets/router.py`, `collections/router.py`, `maps/router.py`, and `ogc/router.py`.

- **Fix:** Extract to a shared utility, e.g., `backend/app/utils/geo.py`.

**H2. `_dataset_to_response` duplicated in `collections/router.py` and `datasets/router.py`**

Both files have their own version of the dataset-to-response conversion with slightly different fields. The `collections/router.py` version is missing fields like `record_type`, `raster`, `stac_assets`, `last_edited_by_display`, `last_edited_at`.

- **Fix:** Unify into a shared helper. The collections version should delegate to the same function with optional raster/VRT metadata loading.

**H3. `get_ai_status` uses `get_current_user` while most other "any authenticated user" endpoints use `get_current_active_user`**

- **File:** `backend/app/admin/router.py:463`
- **Impact:** `get_current_user` also checks `is_active` and `status == "active"`, so functionally equivalent. But inconsistent naming pattern.
- **Fix:** Change to `get_current_active_user` for consistency.

**H4. Trailing slash inconsistency across routers**

Some endpoints include trailing slashes, others do not. Examples of inconsistency within the same router:
- `admin/router.py`: `/admin/users` (no slash) vs `/admin/ai-status/` (with slash)
- `admin/router.py`: `/admin/api-keys` (no slash) vs `/admin/embedding-stats/` (with slash)
- `collections/router.py`: `/catalog/collections/` (with slash) vs `/{collection_id}/datasets` (no slash)

FastAPI 307 redirects when trailing slash mismatches are a known issue (documented in MEMORY.md).

- **Fix:** Audit all routes and normalize. Recommend trailing slashes on all routes OR none, applied consistently. The project CLAUDE.md notes this as a known issue.

**H5. Missing `response_model` on several endpoints**

Endpoints returning `dict` or `Response` without type annotations:
- `GET /maps/{map_id}/visibility-check` returns `dict` — no response model
- `POST /jobs/cleanup/stale` returns `dict` — no response model
- `GET /settings/edition/` returns `dict` — no response model
- `GET /settings/branding/` returns `dict` — no response model
- `GET /stac/collections` returns `dict` — no response model
- `GET /stac/collections/{id}` returns `dict` — no response model
- `GET /tiles/token/{dataset_id}/` returns `dict` — no response model
- `GET /search/facets` returns `dict` — no response model

- **Fix:** Add Pydantic response models for OpenAPI documentation completeness.

**H6. No pagination on `GET /auth/api-keys/`**

Self-service API key listing has no skip/limit. Admin API key listing also has no pagination. Both return all matching rows.

- **File:** `backend/app/auth/router.py:225`, `backend/app/admin/router.py:398`
- **Impact:** Low in practice (users typically have few keys), but inconsistent with every other list endpoint.
- **Fix:** Add `skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)` and return `{items: [...], total: N}`.

**H7. `DELETE /settings/` uses DELETE for a reset operation**

The `DELETE /settings/` endpoint resets selected settings to defaults. Using DELETE with a request body is technically valid but unusual — most HTTP clients may not send bodies with DELETE requests.

- **File:** `backend/app/settings/router.py:188`
- **Fix:** Consider `POST /settings/reset/` instead.

### MEDIUM: Performance & Optimization

**M1. N+1 query in `list_collections_endpoint`**

For each collection, `compute_collection_extent` and `get_collection_dataset_count` are called individually. With N collections, this is 2N queries.

- **File:** `backend/app/collections/router.py:196-200`
- **Fix:** Batch extent and count computation into a single query with GROUP BY collection_id.

**M2. STAC `get_collections` runs N+1 extent queries**

Each collection in the STAC collections list runs its own raw SQL extent query.

- **File:** `backend/app/stac/router.py:209-267`
- **Fix:** Batch into a single query joining collections with extent computation.

**M3. Missing cache invalidation on dataset metadata updates**

The `PATCH /datasets/{dataset_id}` endpoint updates dataset metadata but does not invalidate the `catalog:datasets:admin:*` cache keys. The `catalog:collections:admin:*` cache IS invalidated on collection mutations.

- **File:** `backend/app/datasets/router.py` (patch endpoint)
- **Impact:** Admin users see stale data for up to 60 seconds after edits.
- **Fix:** Call `invalidate_catalog_cache()` after dataset metadata updates.

**M4. `get_map_endpoint` makes 2 extra DB queries after main fetch**

After `get_map_with_layers`, the endpoint separately queries `resolve_forked_from_name` and `_resolve_owner_username`. These could be JOINed into the main query.

- **File:** `backend/app/maps/router.py:256-307`
- **Fix:** Include username and forked map name in the `get_map_with_layers` service query.

**M5. `raster_tile_proxy` creates a new httpx client per request**

Each raster tile proxy request creates and tears down an httpx.AsyncClient. This defeats connection pooling to Titiler.

- **File:** `backend/app/tiles/router.py:243`
- **Fix:** Use a module-level or app-lifetime httpx.AsyncClient for Titiler requests.

### LOW: Cleanup & Simplification

**L1. `audit/router.py` uses prefix `/admin` — same as `admin/router.py`**

Both routers use `prefix="/admin"`, which works but is architecturally confusing. The audit log endpoint lives in a separate module but shares the admin URL namespace.

- **File:** `backend/app/audit/router.py:15` vs `backend/app/admin/router.py:41`
- **Fix:** Either move the audit endpoint into `admin/router.py` or keep but document the shared prefix.

**L2. `config_ops/router.py` export function has unnecessary double-await**

```python
result = export_config(db)
data = await result
```
This calls the async function without await, then awaits the coroutine object. Functionally works but reads confusingly.

- **File:** `backend/app/config_ops/router.py:43-44`
- **Fix:** `data = await export_config(db)`

**L3. `services/router.py` commits audit log on every error path**

The probe and preview endpoints audit-log and commit in every except branch, duplicating 10+ lines each time.

- **Fix:** Extract to a helper: `async def _log_probe_result(db, user_id, url, result, **details)`

**L4. Dead `_public_base_url` helper in `datasets/router.py`**

The `_public_base_url` function manually parses X-Forwarded headers. The project has a centralized `get_public_api_url` and `get_public_app_url` in `public_urls.py`. The datasets router uses both — `_public_base_url` for list view base URLs and `get_public_api_url` for other things.

- **Fix:** Consolidate to use `get_public_app_url` consistently and remove `_public_base_url`.

**L5. `datasets/router.py` is ~2200 lines**

This router is extremely large with 30+ endpoints covering CRUD, re-upload, VRT management, DCAT export, validation, relationships, attribute metadata, and more.

- **Fix:** Split into sub-routers: `datasets_crud_router`, `datasets_reupload_router`, `datasets_vrt_router`, `datasets_dcat_router`, `datasets_attributes_router`.

**L6. Duplicate PART_SIZE and PRIORITY_QUEUE_THRESHOLD_BYTES constants**

`PRIORITY_QUEUE_THRESHOLD_BYTES` is defined in both `ingest/router.py` and `datasets/router.py`.

- **Fix:** Move to `ingest/constants.py` and import.

**L7. OpenAPI version string is stale**

`main.py` has `version="2.6.0"` but the project is at v13.0.

- **File:** `backend/app/main.py:332`
- **Fix:** Update or derive from package metadata.

## Endpoint Inventory

| # | Router | Prefix | Endpoints | Auth Pattern |
|---|--------|--------|-----------|--------------|
| 1 | datasets | /datasets | ~30 | require_permission, get_current_active_user, get_optional_user |
| 2 | maps | /maps | 15 | require_permission("edit_metadata"), get_optional_user, get_current_active_user |
| 3 | records | /records | 11 | require_permission("edit_metadata"), get_optional_user |
| 4 | collections | /catalog/collections | 8 | require_permission("manage_collections"), get_optional_user |
| 5 | features | /datasets | 6 | get_current_active_user, require_permission("edit_metadata") |
| 6 | layers | /layers | 3 | require_permission("create_layers") |
| 7 | auth | /auth | 8 | get_current_active_user, none (login/register/config) |
| 8 | auth/oauth | /auth/oauth | 3 | none (OAuth flows) |
| 9 | admin | /admin | 20 | require_permission("manage_users"), get_current_user |
| 10 | settings | /settings | 13 | require_permission("manage_settings"), none (public endpoints) |
| 11 | ogc | / and /collections | 5 | get_optional_user, none |
| 12 | tiles | /tiles | 4 | get_optional_user, HMAC signature, embed token |
| 13 | search | /collections/datasets and /search | 6 | get_optional_user, get_current_active_user |
| 14 | ai | /ai | 8 | require_permission("use_ai_chat") |
| 15 | ingest | /ingest | 10 | require_permission("upload"), get_current_active_user |
| 16 | jobs | /jobs | 3 | get_current_active_user, require_permission("upload"/"admin") |
| 17 | services | /services | 2 | require_permission("create_layers") |
| 18 | audit | /admin | 1 | require_permission("manage_settings") |
| 19 | config_ops | /config-ops | 4 | require_permission("manage_settings") |
| 20 | embed_tokens | /maps/{map_id}/embed-tokens | 4 | get_current_active_user + ownership check |
| 21 | embed_tokens_admin | /admin/embed-tokens | 2 | require_role("admin") |
| 22 | export | /datasets | 1 | get_current_active_user |
| 23 | stac | /stac | 6 | none (public) |
| - | main.py | / | 1 (health) | none |

**Total: ~163 endpoints across 23 routers**

## Cross-Cutting Patterns

### What's Working Well
- **Audit logging**: Mutations consistently log via `log_action()` with user_id, action, resource_type, resource_id, and details
- **Structured error handling**: Consistent use of HTTPException with proper status codes
- **Permission model**: `require_permission()` factory with named capabilities is well-designed and extensible
- **OGC compliance**: Landing page, conformance, pagination links, Content-Crs headers all follow spec
- **Visibility enforcement**: RBAC checks before data access in all data-serving endpoints
- **Cache invalidation**: Collection and catalog caches cleared on mutations

### Auth Dependency Usage Summary
| Dependency | Purpose | Used By |
|------------|---------|---------|
| `get_optional_user` | Anonymous + authenticated access | OGC, search, tiles, maps (get), records (list), stac |
| `get_current_active_user` | Any authenticated user | datasets (list), features (read), jobs (get), auth (me) |
| `get_current_user` | Any authenticated user (legacy) | admin (ai-status) |
| `require_permission(cap)` | Capability-based access | Most mutation endpoints |
| `require_role(role)` | Role-based access (older) | embed_tokens admin only |

## Suggested Enhancements (Not Issues)

1. **Rate limiting on AI endpoints**: The `/ai/*` endpoints call external LLM APIs. Consider per-user rate limits to prevent abuse.

2. **Bulk delete endpoint**: No bulk delete for datasets. Admin cleanup of test data requires N individual DELETE calls.

3. **STAC POST /search**: The STAC spec recommends POST for complex search queries. Currently only GET is implemented.

4. **Export format validation**: The `format` query param on export accepts any string; validation happens deep in ogr2ogr. Add early validation with an enum.

5. **Health endpoint schema**: `GET /health` returns untyped JSON. Add a response model for monitoring tool integration.

## Sources

All findings from direct source code review of the 22 router files listed in the task scope, plus `auth/dependencies.py`, `dependencies.py`, and `main.py`.

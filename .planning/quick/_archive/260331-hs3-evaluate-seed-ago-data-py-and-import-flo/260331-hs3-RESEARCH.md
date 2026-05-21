# Evaluate seed-ago-data.py and Import Flow - Research

**Researched:** 2026-03-31
**Domain:** ArcGIS Online discovery + GeoLens service ingest pipeline
**Confidence:** HIGH (verified all endpoints against backend source)

## Summary

The script is well-structured and functional for its primary use case (public AGO orgs). The import flow (service preview -> commit -> poll) correctly matches the backend API. Key gaps are: (1) no token/auth support for secured services, (2) idempotency mismatch for multi-layer services, (3) no Enterprise portal compatibility, and (4) missing trailing slashes cause unnecessary 307 redirects.

**Primary recommendation:** Add `--token` flag for secured services and fix the idempotency lookup to include layer ID.

## Endpoint Verification

All script endpoints traced against backend source:

| Script Calls | Backend Route | Match | Notes |
|---|---|---|---|
| `POST /api/services/preview/` | `services/router.py` `@router.post("/preview/")` | YES | Correct |
| `POST /api/ingest/commit/{job_id}` | `ingest/router.py` `@router.post("/commit/{job_id}")` | YES | Correct |
| `GET /api/jobs/{job_id}` | `jobs/router.py` `@router prefix="/jobs"` | YES | Correct |
| `POST /api/datasets/{id}/reupload/service/preview` | `router_reupload.py` `@router.post("/{dataset_id}/reupload/service/preview")` | YES | Missing trailing slash (307 redirect, handled by follow_redirects) |
| `POST /api/datasets/{id}/reupload/{job_id}/commit` | `router_reupload.py` `@router.post("/{dataset_id}/reupload/{job_id}/commit")` | YES | Missing trailing slash (same) |
| `PATCH /api/datasets/{id}` | `datasets/router.py` | YES | `source_organization` field exists in `DatasetUpdate` schema |
| `POST /api/records/{id}/keywords/` | `records/router.py` | YES | Correct |
| `POST /api/catalog/collections/` | `collections/router.py` prefix `/catalog/collections` | YES | Correct |
| `POST /api/catalog/collections/{id}/datasets` | `collections/router.py` `/{collection_id}/datasets/` | YES | Missing trailing slash (307 redirect) |
| `GET /api/datasets/` | `datasets/router.py` | YES | Correct |

**Request body alignment:** The `ServicePreviewRequest` schema accepts `url`, `service_type`, `layer_name`, `layer_title`, `layer_id`, `token`, `object_id_field`. The script sends all required fields correctly. `CommitRequest` requires `title` (min 1 char) and accepts `summary`, `visibility`, `token` -- script sends these correctly with `visibility: "public"`.

## Critical Findings

### 1. Idempotency Lookup Mismatch (HIGH impact)

**Problem:** The script builds a lookup key as `service_url/layer_id` (e.g., `https://.../FeatureServer/0`), but the backend stores `source_url` as just the base service URL (e.g., `https://.../FeatureServer`) -- the same value for ALL layers in a multi-layer service.

**Effect:** For a service with 5 layers, the first import stores `source_url = "https://.../FeatureServer"`. On re-run, `fetch_existing_datasets()` indexes by `source_url`, so all 5 layers map to the same entry. The script's `existing_by_layer.get(lookup_key)` uses `service_url/layer_id` which will never match the stored `source_url` (no `/0` suffix). It falls back to `existing_by_layer.get(entry["service_url"])` which matches ALL layers to one dataset.

**Result:** Multi-layer services get incorrect skip/update behavior. Only the first layer's dataset is found; subsequent layers may be re-imported as duplicates or all pointed at the wrong dataset for updates.

**Fix:** Either (a) store `source_url` with layer ID appended in the backend, or (b) change the lookup to also match on `source_filename` (which stores the layer name).

### 2. No Secured Service / Token Support (HIGH impact for Enterprise)

**Problem:** The script has zero token handling. The `ServicePreviewRequest` schema accepts a `token` field, and the `CommitRequest` accepts a `token` field (passed to the ingest worker). The script sends neither.

**Effect:** Cannot import from:
- Secured ArcGIS Online services (subscription/premium content)
- ArcGIS Enterprise services behind authentication
- Any non-public FeatureServer/MapServer

**Fix:** Add `--token` CLI argument. Pass it in both the preview and commit request bodies. The backend already supports it end-to-end (token flows to `build_gdal_source()` which appends `&token=` to GDAL's ArcGIS driver URL).

### 3. Enterprise Portal Compatibility (MEDIUM impact)

**Problem:** The discovery logic uses the AGO-specific search API pattern:

```python
f"{org_url}/sharing/rest/portals/self"
f"{org_url}/sharing/rest/search"
```

ArcGIS Enterprise portals expose the same REST API at the same paths (`/sharing/rest/...`), so the URL pattern itself works. However:

- **Enterprise portal URL format:** Enterprise uses `https://gis.example.com/portal` (not `*.maps.arcgis.com`). The script already accepts `--org-url`, so this works if the user provides the portal base URL.
- **Federation complexity:** Enterprise portals may federate multiple ArcGIS Server sites. The `portals/self` endpoint returns `id` but federated services may belong to different server registrations, not the portal's own `accountid`.
- **Search query:** `accountid:{org_id} access:public` is AGO-centric. Enterprise may use `orgid` instead, and access control is different (items may be shared to "Everyone" but not technically "public" in the AGO sense).
- **Authentication:** Enterprise portals often require Windows Integrated Auth (IWA/Kerberos), PKI, or SAML -- none of which the script handles.

**Fix:** For basic Enterprise support, the script already works if the portal exposes unauthenticated public search. For secured Enterprise, a `--token` flag (generated via `generateToken` endpoint or portal auth) would cover most cases.

### 4. Missing Trailing Slashes (LOW impact)

**Problem:** Three endpoints called without trailing slashes will trigger 307 redirects:
- `POST /api/datasets/{id}/reupload/service/preview` (route has no trailing slash -- actually OK)
- `POST /api/datasets/{id}/reupload/{job_id}/commit` (route has no trailing slash -- actually OK)
- `POST /api/catalog/collections/{coll_id}/datasets` (route IS defined with trailing slash)

**Effect:** The httpx client has `follow_redirects=True`, so it works but wastes one round-trip per call.

**Fix:** Add trailing slashes to the script's collection dataset assignment URL.

## Easy-Win Enhancements

### 1. Add `--token` flag (HIGH value, LOW effort)
```python
parser.add_argument("--token", help="ArcGIS token for secured services")
```
Pass `request.token` in both preview and commit bodies. The backend already handles it.

### 2. Add `--filter` for selective import (MEDIUM value, LOW effort)
Allow regex filter on layer names to import only matching layers:
```
--filter "parcels|zoning"
```

### 3. Add `--skip-existing` vs `--force` clarity (MEDIUM value, LOW effort)
Current behavior: silently skips existing on default, `--update` re-imports all. Add `--force` to re-import even without `--update` (useful when a previous import failed partway).

### 4. Add progress bar / ETA (LOW value, LOW effort)
Use simple counter with elapsed time. The `[3/25]` tag is already there; add elapsed/remaining estimate.

### 5. Add `--item-types` to support more AGO types (MEDIUM value, LOW effort)
Currently hardcoded to `{"Feature Service", "Map Service"}`. Could add `"OGC Feature Layer"` or other OGC types since the backend supports WFS too.

### 6. Fix collection assignment for update runs (LOW value, trivial)
Line 816: `if not args.update` skips collection assignment on update runs. Updated datasets should also be assigned to the collection.

### 7. Add `--org-search-query` override (MEDIUM value for Enterprise)
Allow overriding the search query from `accountid:{org_id} access:public` to a custom query string. Handles Enterprise federation and custom access patterns.

### 8. Metadata enrichment on updates too (LOW value, trivial)
Line 529: `if dataset_id and action == "succeeded"` skips metadata enrichment on updates. Should also run on `"updated"` to refresh tags/license from AGO.

## Concurrency and Error Handling Assessment

**Concurrency model:** Sound. Uses `asyncio.Semaphore` with configurable `--concurrency` (default 1). `asyncio.TaskGroup` properly propagates exceptions.

**Retry logic:** Good. 3 retries with exponential backoff (5s, 15s, 45s) and jitter (50-150%). Only retries on 5xx errors. Non-5xx errors fail immediately.

**Timeout:** 1200s default job poll timeout with 3s poll interval. Reasonable for large services. Configurable via `--timeout`.

**Error isolation:** Each layer is independently processed; one failure doesn't block others. Results array collects all outcomes for summary.

**Potential issue:** The `asyncio.TaskGroup` will cancel all tasks if any task raises an unhandled exception outside the try/except in `process_one`. The current code wraps everything in try/except so this should not happen, but a bug in the outer scope could cancel all in-flight imports.

## Open Questions

1. **Source URL storage format:** Should `source_url` on datasets include the layer ID? This is a backend schema decision that affects more than just this script. Alternative: add a `source_layer_id` column to datasets.

2. **Rate limiting on AGO:** The script does not throttle AGO API calls during discovery. Large orgs with 1000+ items could trigger AGO rate limits (status 429 or error code 498). The script does not handle 429 responses.

## Sources

### Primary (HIGH confidence)
- `backend/app/services/router.py` -- service preview endpoint
- `backend/app/services/schemas.py` -- request/response schemas
- `backend/app/services/arcgis.py` -- ArcGIS probing and token handling
- `backend/app/ingest/router.py` -- commit endpoint
- `backend/app/ingest/schemas.py` -- CommitRequest schema
- `backend/app/datasets/router_reupload.py` -- reupload preview/commit
- `backend/app/datasets/schemas.py` -- DatasetUpdate schema (source_organization field)
- `backend/app/ingest/tasks.py` -- source_url storage in ingest_service task
- `backend/app/jobs/router.py` -- job polling endpoint
- `backend/app/collections/router.py` -- collection CRUD and dataset assignment
- `backend/app/main.py` -- root_path="/api", router registration

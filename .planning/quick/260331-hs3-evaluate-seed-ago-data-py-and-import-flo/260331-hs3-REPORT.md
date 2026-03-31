# Evaluation Report: seed-ago-data.py and GeoLens Import Flow

**Evaluated:** 2026-03-31
**Scope:** scripts/seed-ago-data.py + full backend import pipeline
**Confidence:** HIGH — all endpoint behavior verified against backend source

---

## 1. Executive Summary

`seed-ago-data.py` is a well-structured async script that discovers all public Feature/Map Services in an ArcGIS Online organization and imports each layer into GeoLens via the service connector API. The import pipeline (service preview -> commit -> job poll) correctly matches all backend endpoints and the core happy-path flow works as intended. However, two HIGH-severity gaps limit its real-world utility: the idempotency lookup key mismatches how `source_url` is stored by the backend (causing incorrect skip/update behavior for multi-layer services), and there is zero token support for secured services or ArcGIS Enterprise portals despite the backend accepting and threading tokens end-to-end. These two issues should be addressed before the script is shared externally or used on any non-trivial org. Several easy-win enhancements (--token flag, --filter, metadata on updates) can be shipped quickly with low effort.

---

## 2. Import Pipeline Trace

Full flow per layer: AGO discovery -> service/preview -> ingest/commit -> job poll -> metadata enrichment -> collection assignment.

### 2a. AGO Discovery

| Function | What it does | Correct? |
|---|---|---|
| `get_org_id()` | `GET {org_url}/sharing/rest/portals/self?f=json` — returns org ID + name | YES |
| `search_public_items()` | Paginates `GET {org_url}/sharing/rest/search` with `accountid:{org_id} access:public` | YES for AGO public orgs |
| `get_service_layers()` | `GET {service_url}?f=json` — returns `layers` + `tables` arrays | YES |
| `discover_layers()` | Filters items to `Feature Service` and `Map Service` types, builds manifest | YES |

### 2b. Service Preview (New Import)

**Script:** `POST /api/services/preview/`
**Backend:** `services/router.py @router.post("/preview/")` under prefix `/services`

Script sends: `url`, `service_type` (hardcoded `"ArcGIS FeatureServer"`), `layer_name`, `layer_title`, `layer_id`.

Backend (`ServicePreviewRequest`) accepts all of these plus `token` and `object_id_field`. Script sends neither. The preview endpoint: validates SSRF, builds a GDAL source string, runs `ogrinfo`, then creates an `IngestJob` with `source_url = request.url` (the base service URL, no layer ID suffix).

**Status:** Correct. Token omission is a gap (see Critical Finding #2).

### 2c. Ingest Commit

**Script:** `POST /api/ingest/commit/{job_id}`
**Backend:** `ingest/router.py @router.post("/commit/{job_id}")`

Script sends: `title`, `visibility: "public"`, optional `summary`. Backend `CommitRequest` accepts these plus `token`. Backend reads `token = request.token` and passes it to `ingest_service.defer_async(token=token)` — the token is explicitly excluded from persisted metadata (`exclude={"token"}`; see `commit_import` lines 441-442).

**Status:** Correct. Token omission is a gap.

### 2d. Job Polling

**Script:** `GET /api/jobs/{job_id}` every 3s until `status` is `"complete"` or `"failed"`.
**Backend:** `jobs/router.py` with prefix `/jobs`.

**Status:** Correct. 1200s timeout is reasonable for large services. Configurable via `--timeout`.

### 2e. Metadata Enrichment

After successful import, script calls:
1. `PATCH /api/datasets/{dataset_id}` with `source_organization` and stripped HTML `license` fields.
2. `GET /api/datasets/{dataset_id}` to retrieve `record_id`.
3. `POST /api/records/{record_id}/keywords/` once per AGO tag, with `keyword_type: "theme"`.

**Status:** All three endpoints verified correct. However, enrichment is skipped for update operations (`action == "succeeded"` check at line 529 excludes `"updated"` action). See Minor Issues #3.

### 2f. Collection Assignment

**Script:** `POST /api/catalog/collections/` then `POST /api/catalog/collections/{coll_id}/datasets`
**Backend:** `collections/router.py` with prefix `/catalog/collections`.

The collection datasets endpoint is defined as `/{collection_id}/datasets/` (WITH trailing slash). The script calls it without the trailing slash. Because `httpx` is initialized with `follow_redirects=True`, the 307 redirect is followed transparently — it works but wastes a round trip per import run.

Collection assignment is skipped entirely on `--update` runs (line 816: `if not args.update`). See Minor Issues #2.

---

## 3. Critical Findings (HIGH)

### Finding 1: Idempotency Lookup Mismatch for Multi-Layer Services

**Problem:** The script builds lookup keys as `service_url/layer_id` (e.g., `https://services.arcgis.com/.../FeatureServer/0`) to check if a layer was previously imported. But the backend stores `source_url = request.url` — the base service URL passed in the preview request, which is always the bare FeatureServer URL without any layer ID suffix (e.g., `https://services.arcgis.com/.../FeatureServer`).

Verification: `ingest/tasks.py` `ingest_service()` stores `source_url=source_url` at line 482, where `source_url` is the `job.source_url` set from `request.url` in `services/router.py` at line 356. The preview request sends `url=service_url` (bare URL, line 309 in script).

**Effect:** For a service with N layers, the backend stores the same `source_url` value for every layer. On a re-run:
- `fetch_existing_datasets()` indexes existing datasets by `source_url` (bare URL). All N layers in that service appear to map to the same one stored entry.
- The script's primary lookup (`existing_by_layer.get(lookup_key)`) uses the `service_url/layer_id` key, which never matches (no layer ID in stored URL) — lookup always misses.
- The fallback (`existing_by_layer.get(entry["service_url"])`) uses the bare URL, which matches all N layers to the same single dataset entry.
- Result: layers 2 through N are re-imported as duplicates (default run) or all updated via the single found dataset ID (update run) — both wrong.

**Recommended Fix (Option A — Backend):** Change `ingest_service` to store `source_url` with the layer ID appended (e.g., `{base_url}/{layer_id}`). This is a breaking change for existing data but is the cleanest long-term fix. Requires a data migration for existing service-imported datasets.

**Recommended Fix (Option B — Script):** Add `source_layer_id` to the PATCH metadata on each dataset after import, then use a `source_filename`-based secondary lookup in the script. Lower-risk but requires a backend schema addition.

**Recommended Fix (Option C — Immediate Script Workaround):** After importing a layer, store the `dataset_id` in a local JSON cache keyed by `service_url/layer_id`. On re-run, consult the cache first. Fragile if the cache is lost, but zero backend changes required.

---

### Finding 2: No Token / Auth Support for Secured Services

**Problem:** The script never sends a `token` field in any API request. Both `ServicePreviewRequest` (field `token: str | None = None`) and `CommitRequest` (field `token: str | None = None`) accept tokens. The backend threads the token all the way into the GDAL source string via `build_gdal_source()`.

Verification confirmed in `services/schemas.py` line 47 (`ServicePreviewRequest.token`), `ingest/schemas.py` line 54 (`CommitRequest.token`), and `ingest/router.py` lines 441-459 where token is extracted and passed to `ingest_service.defer_async(token=token)`.

**Effect:** Cannot import from:
- Any non-public ArcGIS FeatureServer (subscription content, organization-only layers)
- ArcGIS Enterprise services that require authentication
- Any org where the user wants to import private layers they own

**Recommended Fix:** Add a `--token` CLI argument:
```python
parser.add_argument("--token", default=os.environ.get("ARCGIS_TOKEN"),
                    help="ArcGIS token for secured services (or set ARCGIS_TOKEN env var)")
```
Pass `"token": args.token` in both the service preview request body and the commit request body. Three lines of code change in `ingest_via_service()` and `update_via_service()`. The backend already handles it end-to-end.

---

## 4. Flexibility Concerns (MEDIUM)

### Finding 3: Enterprise Portal Compatibility Gaps

The script's discovery logic uses `/sharing/rest/portals/self` and `/sharing/rest/search` — paths that ArcGIS Enterprise portals expose at the same locations. So the URL pattern is compatible in principle. But several assumptions break for Enterprise:

**Search query mismatch:** The search query `accountid:{org_id} access:public` is designed for ArcGIS Online. Enterprise portals may use `orgid` (not `accountid`) and access control semantics differ — items shared to "Everyone" may not match `access:public` in the same way.

**Federation complexity:** ArcGIS Enterprise portals often federate multiple ArcGIS Server instances. Items discovered through the portal search may point to federated Server URLs that require separate authentication, not the portal token.

**Authentication methods:** Enterprise commonly uses Windows Integrated Authentication (IWA/Kerberos), PKI, or SAML — none of which can be represented as a simple `token` string. The `--token` fix above covers the case where a user has already obtained a portal-generated token via `generateToken`, which works for many Enterprise deployments.

**Recommended Fix:** Add a `--org-search-query` override argument to allow users to supply a custom search query for non-standard AGO or Enterprise environments. Document the `--token` workflow for Enterprise token generation.

---

### Finding 4: AGO Rate Limiting Not Handled During Discovery

During the discovery phase, the script makes one HTTP request per spatial item (to enumerate layers). For large organizations with hundreds of services, this is a tight loop with no throttling. ArcGIS Online returns HTTP 429 (Too Many Requests) or an embedded error code 498 (invalid token) when rate limits are hit.

**Effect:** Discovery fails partway through with an unhandled `httpx.HTTPStatusError` raised from `get_service_layers()`. No retry logic exists for the discovery phase (retry logic is only in `process_one()` for the GeoLens ingest side).

**Recommended Fix:** Wrap `get_service_layers()` calls with a retry+backoff, or add a short `asyncio.sleep(0.1)` between discovery requests to avoid bursting. Alternatively, run layer discovery concurrently with the same semaphore used for ingest.

---

### Finding 5: Hardcoded `service_type` Prevents WFS and OGC Imports

The script hardcodes `SERVICE_TYPE = "ArcGIS FeatureServer"` (line 56) and sends this in every service preview request. Map Services and WFS-exposed AGO layers will ingest through the ArcGIS driver correctly, but if an org publishes OGC Feature API or WFS endpoints, the script cannot import those.

The backend's `ServicePreviewRequest` accepts any `service_type` string. The probe endpoint (`/api/services/probe/`) can auto-detect service type. The script bypasses probe entirely and hardcodes the type.

**Recommended Fix:** Add `--service-type` override argument. For better automation, consider calling the probe endpoint on each service URL and using the detected type.

---

## 5. Minor Issues (LOW)

### Issue 1: Trailing Slash on Collection Dataset Assignment

**Line 625:** `POST /api/catalog/collections/{coll_id}/datasets` — missing trailing slash.
**Backend route:** `/{collection_id}/datasets/` WITH trailing slash (confirmed `collections/router.py` line 253).

`follow_redirects=True` makes this work transparently, but generates a 307 redirect round-trip per import run. Fix: append `/` to the URL in `assign_collection()`.

**Reupload routes are NOT affected:** `/{dataset_id}/reupload/service/preview` and `/{dataset_id}/reupload/{job_id}/commit` are defined WITHOUT trailing slashes in the backend, so the script's calls (also without) are correct.

---

### Issue 2: Collection Assignment Skipped on Update Runs

**Line 816:** `if not args.update: ... await assign_collection(...)` — collection assignment is skipped when `--update` is passed.

Updated datasets should remain in (or be re-added to) the collection. An org re-run with `--update` will update all layers but leave the collection stale if it was somehow removed, and new layers discovered on the re-run (not previously imported) will not be assigned to the collection.

**Fix:** Remove the `if not args.update` guard, or run `assign_collection()` unconditionally after the import loop. The `create_or_get_collection()` function already handles the 409 case, so calling it on updates is idempotent.

---

### Issue 3: Metadata Enrichment Skipped on Updates

**Line 529:** `if dataset_id and action == "succeeded"` — metadata enrichment (source org, license, tags) is skipped when `action == "updated"`.

If AGO metadata (tags, license text, attribution) changes between runs, `--update` will re-import the data but leave stale metadata. The enrichment calls are idempotent (PATCH is safe to re-apply, and keyword creation uses POST but duplicates are benign for keyword storage).

**Fix:** Change condition to `if dataset_id and action in ("succeeded", "updated")`.

---

## 6. Concurrency and Error Handling Assessment

**Concurrency model:** Sound. `asyncio.Semaphore(args.concurrency)` bounds parallel ingest correctly. Default of 1 is conservative but safe for large orgs where job processing is the bottleneck. `asyncio.TaskGroup` propagates exceptions correctly.

**One concern with TaskGroup:** `asyncio.TaskGroup` cancels all sibling tasks if any task raises an uncaught exception outside its internal try/except. The `process_one()` function wraps all work in `try/except Exception`, so internal failures are captured. However, if a bug were introduced in the outer task-creation loop or the semaphore context, all in-flight imports would be cancelled. This is acceptable for a dev/admin script.

**Retry logic:** Good design. 3 retries with exponential backoff (5s, 15s, 45s) and per-attempt jitter (50-150% of delay). Retries only on HTTP 5xx. Non-5xx errors (400, 404, 422) fail immediately, which is correct — these indicate logic errors, not transient failures.

**Timeout handling:** 1200s default per job poll with 3s interval (400 polls max). Appropriate for large feature services. Configurable down to 30s minimum. The httpx client timeout is set to 660s for the overall request — this covers a single HTTP response but not the total job time, which is separately controlled by poll_job().

**Error isolation:** Each layer processes independently. One failed ingest does not block others. The summary correctly tallies succeeded/updated/skipped/failed counts and prints failure details. This is the right pattern for bulk operations.

**Discovery phase has no retry:** As noted above, `get_service_layers()` during discovery has no retry logic. A single transient error mid-discovery terminates the entire discovery with an unhandled exception. This is lower severity since discovery happens before any imports, but should be addressed for large orgs.

---

## 7. Easy-Win Enhancements

| Enhancement | Value | Effort | Description |
|---|---|---|---|
| `--token` / `ARCGIS_TOKEN` flag | HIGH | LOW | Pass ArcGIS token in preview + commit request bodies. Backend already handles it end-to-end. 3-line script change. |
| Fix metadata enrichment on updates | HIGH | LOW | Change `action == "succeeded"` to `action in ("succeeded", "updated")` at line 529. 1-line change. |
| Fix trailing slash on collection endpoint | MED | LOW | Append `/` to URL in `assign_collection()` at line 625. 1-line change. |
| Fix collection assignment on updates | MED | LOW | Remove `if not args.update` guard at line 816. 1-line change. |
| `--filter` regex on layer names | MED | LOW | Add `re.search(args.filter, layer_name)` filter in `discover_layers()`. Allows partial imports. |
| `--org-search-query` override | MED | LOW | Override the AGO/Enterprise search query for non-standard portal configurations. 5-line change. |
| Retry in discovery (`get_service_layers`) | MED | LOW | Wrap with backoff for AGO rate limit handling during layer enumeration. |
| `--item-types` expansion | MED | LOW | Parameterize `DOWNLOADABLE_TYPES` set. Enables WFS, OGC Feature API imports from AGO. |
| ETA / progress estimate | LOW | LOW | Add elapsed time to `[{index}/{total}]` log tag. 5-line change. |
| Local cache for idempotency | LOW | MED | JSON file cache of `service_url/layer_id -> dataset_id`. Workaround for finding #1 until backend fix lands. |
| `--output-json` results export | LOW | LOW | Write results list to a JSON file for downstream processing or audit. |

---

## 8. Open Questions

**Q1: Source URL storage format (architectural decision)**
Should `ingest_service` store `source_url` with the layer ID appended (e.g., `{base_url}/{layer_id}`)? This is the cleanest fix for the idempotency bug but requires a data migration for all existing service-imported datasets. Alternative: add a `source_layer_id` integer column to the `datasets` table.

**Q2: Single token for all layers vs per-layer tokens**
The `--token` flag would apply one token to all services in the run. This is correct for AGO (one org token covers all public services). For Enterprise or mixed-security scenarios where different services need different tokens, the script would need multi-token support. Is a single token per run sufficient for current needs?

**Q3: Rate limiting strategy for large orgs**
For an org with 500+ services, the discovery phase makes 500+ sequential HTTP calls to enumerate layers. Should discovery be parallelized (using the same semaphore), or should a fixed inter-request delay be added? The current sequential approach is safe but slow.

**Q4: `--update` semantics for new layers**
On an `--update` run, the script re-imports existing layers AND imports newly discovered layers (those without an existing entry). Is this the intended behavior? It could be confusing: the user expects "update" but also gets new imports. Consider a separate `--import-new` flag to control this explicitly.

**Q5: Map Service vs Feature Service GDAL driver**
The script hardcodes `service_type = "ArcGIS FeatureServer"` for all items, including `Map Service` items. GDAL's ArcGIS driver handles both, but Map Service item URLs may follow a different format. Has this been tested against Map Service items specifically?

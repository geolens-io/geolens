---
name: 260408-iny Research
description: Implementation map for the Table data type enhancement pass
type: quick-task-research
---

# Quick Task 260408-iny: Table Data Type — Research

**Researched:** 2026-04-08
**Confidence:** HIGH for code locations and schemas; MEDIUM for root cause of empty `column_info`; MEDIUM for the exact frontend path triggering the 307.

## Summary

All 8 concerns map to well-isolated code paths. The backend ingest flow for ArcGIS is: `services/router.py POST /services/preview/` → creates pending `IngestJob` with `source_url` → `ingest/router.py POST /commit/{job_id}` → `ingest/tasks.py ingest_service()` → `_finalize_ingest()` → `datasets/service.py create_dataset()`. **Duplicate detection should be injected at preview time** (synchronous, fastest feedback, lowest cost). Column metadata and format aliasing fixes are small, localized edits. The quality score branch is a ~5-line change in `compute_quality_score`. The frontend table tile replacement is a 15-line swap inside `SearchResultCard.tsx:310-330`.

**Primary recommendation:** Do the small/safe wins first (schema doc, quality scoring, formats, feature_count alias, thumbnail), then tackle the duplicate detection refactor with its migration/409-response considerations last.

---

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Scope:** Full enhancement pass — diagnose, fix duplicates root cause, implement thumbnail, ship all P1/P2 improvements.
- **Thumbnail strategy:** Styled icon tile — replace `ImageOff` with orange gradient background (matching Table badge color) + `Table2` lucide icon + row/col count overlay (e.g., "29 rows · 5 cols"). Frontend-only. No backend thumbnail generation.

### Claude's Discretion
- **Duplicate detection:** Backend detects by `(source_url, source_format, created_by)` during ArcGIS service registration. Default: refuse with **409 Conflict** + structured body containing existing `dataset_id`. Don't change collision auto-suffix. Cover other ingest paths (file upload, bulk register) if they share root cause. Leave 3 existing Bulletins alone.
- **Column introspection:** Map ArcGIS `fields` to `column_info` schema during registration.
- **Quality scoring:** Skip `geometry_validity` and `crs_defined` for `record_type='table'`. Recompute `overall` from applicable dimensions only. Fix forward, no backfill.
- **307 redirect:** Frontend fix — drop trailing slash. Match existing OGC `/collections/datasets` pattern.
- **`feature_count` aliasing:** Add `row_count` alias (do NOT remove `feature_count`) in OGC Records response for `record_type='table'`.
- **Formats list:** Strip shapefile from tables. Keep CSV and GeoPackage. Verify if GeoJSON is acceptable for non-spatial.
- **Schema doc fix:** Update `DatasetResponse.record_type` description.

### Deferred Ideas (OUT OF SCOPE)
- Vector/raster thumbnail pipeline changes
- Quality score backfill for all datasets
- Auto-deleting the 3 existing Bulletins
- Map/collection/service record types
- OGC Collections facet exposure (P3)
- FEATURES.md, README updates
- DataTab empty state

---

## Implementation Map

### 1. ArcGIS duplicate detection path

**Registration flow (confirmed via code read):**

| Step | Endpoint | File:Line | Action |
|------|----------|-----------|--------|
| 1 | `POST /services/probe/` | `backend/app/services/router.py:46` | Lists layers, does NOT create records |
| 2 | `POST /services/preview/` | `backend/app/services/router.py:212-395` | **Creates pending `IngestJob` with `source_url`** (line 342-354) |
| 3 | `POST /ingest/commit/{job_id}` | `backend/app/ingest/router.py:457-534` | Queues `ingest_service` task (line 489-496) |
| 4 | async task | `backend/app/ingest/tasks.py:419-542 ingest_service()` | Runs ogr2ogr → `_finalize_ingest()` |
| 5 | finalize pipeline | `backend/app/ingest/tasks.py:32-179 _finalize_ingest()` | Calls `create_dataset(…, source_url=…)` at line 130 |
| 6 | dataset insert | `backend/app/datasets/service.py:152-239 create_dataset()` | **This is where a Dataset row is INSERTed. No existing duplicate check.** |

**Recommended insertion point:** Step 2 (`preview_service_layer`). Inject a check right after SSRF validation (line 243) and before building GDAL source (line 245). Synchronous, avoids running ogrinfo against a URL we're about to reject.

**Query pattern** (to mirror `backend/app/ingest/service.py:199-206`):

```python
from app.datasets.models import Dataset
# At preview_service_layer, after SSRF validation
existing = await db.execute(
    select(Dataset.id, Record.title)
    .join(Record, Dataset.record_id == Record.id)
    .where(
        Dataset.source_url == request.url,  # or normalized form
        Dataset.source_format == source_format,  # derive from service_type
        Record.created_by == user.id,
    )
)
```

**Dataset source-tracking columns** (`backend/app/datasets/models.py:228-233`):
- `source_format: String(50)` — values include `'arcgis_featureserver'`, `'wfs'`, `'geojson'`, etc. (CHECK constraint at model line 183-188)
- `source_filename: String(500)`
- `source_url: String(2000)`
- `original_srid: Integer`
- `created_by` — lives on the **Record** (not Dataset): `catalog/app/datasets/models.py:120` (`Record.created_by`)

**Duplicate dedup key:** per CONTEXT, use `(source_url, source_format, created_by)`. Note:
- `source_url` is normalized in `ingest_service` via `_enrich_source_url(base_url, layer_id)` at `tasks.py:412-416` — the stored URL INCLUDES the layer suffix (e.g., `.../FeatureServer/0`). Preview at `services/router.py:344` stores the **unenriched** URL. **This means the dedup check at preview time must construct the enriched URL before querying**, or allow both forms.
- The canonical ArcGIS URL normalizer is at `backend/app/services/arcgis.py:55-83 normalize_arcgis_url()` — use this for comparison.

**Existing 409 Conflict response shape** (look at `backend/app/ingest/router.py:744-748` for VRT regeneration 409 pattern). GeoLens already returns 409s with plain `detail` strings. For structured bodies with `existing_dataset_id`, consider:

```python
raise HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={
        "code": "duplicate_source",
        "message": f"A dataset from this source already exists.",
        "existing_dataset_id": str(existing.id),
        "existing_title": existing.title,
    },
)
```

**Other ingest paths to audit (file upload, bulk register):**
- `backend/app/ingest/router.py:287-356 upload_file()` — uploads file, no duplicate check. **Per-content-hash dedup is not implemented anywhere in codebase** (grep confirmed). CONTEXT scopes dedup to `source_url`, so file uploads without `source_url` are not in scope. Skip.
- `backend/app/ingest/router.py:585-628 bulk_register_tables()` — calls `register_existing_table` per table. For pre-existing PostgreSQL tables, there's no `source_url`. Also out of scope for CONTEXT's dedup rule.

**Verdict:** Duplicate detection only needs to live at `services/router.py preview_service_layer` (preview path for ArcGIS/WFS). Do NOT add to file upload or bulk register — they don't have the same root cause.

**Response type to update:** `ServicePreviewResponse` in `backend/app/services/schemas.py` — do NOT change its shape. Only the 409 error body changes, not the success body.

### 2. ArcGIS column metadata path

**Where ArcGIS `fields` is already parsed:** `backend/app/services/preview.py:138` — `columns = [{"name": f["name"], "type": f["type"]} for f in layer.get("fields", [])]`.

This runs during **preview** (`POST /services/preview/`) and returns columns in the preview response. **But the data is NOT persisted anywhere** — it's shown in the UI only, then thrown away. The `ingest_service` task runs fresh and relies on `extract_metadata` to read from the database table post-ogr2ogr.

**Where `column_info` is populated for tables:** `backend/app/ingest/metadata.py:161-187 get_column_info()` — queries `information_schema.columns WHERE table_schema = 'data' AND table_name = :table_name`, filters `{'gid', 'geom', 'geom_4326'}`. Called from `extract_metadata` at line 369.

**Why column_info is `[]` for Bulletin tables (HYPOTHESIS):**
The `information_schema` query should return real columns for `data.bulletin`. If it's empty, possibilities are:
1. The table was created in a different schema (e.g., `public`) — verify by running `SELECT * FROM information_schema.tables WHERE table_name LIKE 'bulletin%'` on the affected DB.
2. ogr2ogr failed partially — wrote 29 rows but with all columns nameless/merged (unlikely).
3. Every column name started with something in the excluded set or matched `_TABLE_NAME_RE = /^[a-z0-9_]+$/` — edge case where ArcGIS column names like `OBJECTID` survive but the test excludes nothing unusual.

**Lowest-risk fix:** Mirror the vector path by ALSO propagating the `fields` from the ArcGIS probe response through the `IngestJob.user_metadata`, and use that as a fallback when `get_column_info` returns empty. Both paths write into the same `column_info` column; the vector path (reads from PG) is the source of truth, with `fields` as a fallback.

**Alternative fix:** Debug the `get_column_info` query directly — if it's a schema mismatch, that's the real bug and affects all non-spatial ArcGIS ingests. Recommended investigation in Wave 0 before coding.

**`column_info` JSON schema** (from `backend/app/ingest/metadata.py:178-186`):

```json
[
  {"name": "field_name", "type": "text", "ordinal_position": 1, "is_nullable": true}
]
```

Vector ingests (shapefile/GeoJSON) use the SAME path (`_finalize_ingest → extract_metadata → get_column_info`) and get populated column_info correctly. So the bug is specific to the table code path or to the ArcGIS table data that lands in PostgreSQL.

### 3. Quality scoring path

**Single location:** `backend/app/ingest/metadata.py:233-346 compute_quality_score()`.

**Current weights:**
- `metadata_completeness` — 30%
- `geometry_validity` — 30% (computed from `ST_IsValid` query, defaults to 100.0)
- `attribute_completeness` — 25%
- `crs_defined` — 15% (100 if srid set OR not has_geometry, else 0)

**Current table handling** (lines 280-282):
```python
has_geometry = dataset.geometry_type is not None
crs_score: float = 100.0 if (dataset.srid is not None or not has_geometry) else 0.0
```

**So `crs_score` is ALREADY 100 for tables** (because `not has_geometry` is True). That's exactly what CONTEXT calls out as wrong — tables shouldn't earn 100 points for a dimension that doesn't apply to them.

**Geometry score** (line 287): `if has_geometry:` — only runs the query when geometry is present. For tables, `geometry_score` stays at default 100.0. **Same problem.**

**Fix — dynamic weights based on applicable dimensions.** Example:

```python
# Determine applicable dimensions
is_table = dataset.record.record_type == "table"  # or `has_geometry=False`
if is_table:
    # Normalize: metadata (30/55), attribute (25/55)
    overall = round(
        metadata_score * (30 / 55) + attribute_score * (25 / 55)
    )
    return {
        "overall": overall,
        "metadata_completeness": metadata_score,
        "attribute_completeness": attribute_score,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        # geometry_validity / crs_defined intentionally omitted
    }
# else: existing logic
```

Note: `dataset.record.record_type` is safely lazy-loadable because `Dataset.record` is `lazy="joined"` (`backend/app/datasets/models.py:241-243`). The function already accepts `dataset` so we have access.

**Frontend rendering consideration:** The search card renders `quality_detail` from OGC records response. Check whether UI assumes all 4 keys exist — if so, the dict returned for tables should include them as `None` instead of omitting them entirely, or the UI must handle missing keys.

- Search: `backend/app/search/service.py:1195` — `"quality_detail": dataset.quality_detail` — passes dict through unchanged.
- Frontend: Grep for `quality_detail` UI consumers separately if you choose omit-keys approach. **Safer: set omitted keys to `None`** to preserve schema stability.

### 4. 307 redirect / hostname leak

**Backend route (confirmed):** `backend/app/datasets/router.py:136` — `@router.get("/{dataset_id}")` — NO trailing slash.

**Frontend call (confirmed):** `frontend/src/api/datasets.ts:32` — `apiFetch<DatasetResponse>(`/datasets/${id}`)` — NO trailing slash.

**These match.** Yet CONTEXT says the 307 is happening. **Investigation needed** — either:
1. CONTEXT misidentified the path. The 307 is being triggered by a DIFFERENT endpoint in the same request flow (e.g., `/datasets/${id}/quicklook` has no trailing slash in route but call does? `/datasets/${id}/status/`? something else?).
2. A browser extension or dev-tools prefetch is appending a trailing slash.
3. A redirect chain: something else returns a 307 to `/datasets/{id}/` first.

**Recommended fix strategy for the executor:**
1. **Reproduce first.** Open browser DevTools on `/datasets/{id}` page, filter Network tab for `307`, copy the exact request URL. This will pinpoint the code site.
2. **Alternative call sites to audit** (all in `frontend/src/api/`):
   - `datasets.ts:48` — `/datasets/${id}/rows/${qs}` — trailing slash, matches `router_data.py:62` `@router.get("/{dataset_id}/rows/")` ✓
   - `datasets.ts:128` — `/datasets/${id}/status/` — trailing slash, matches `router_data.py:201` ✓
   - `datasets.ts:118` — `/datasets/${id}` — no trailing slash, matches `router.py:136` ✓
   - `hooks/use-quicklook.ts:28` — `/api/datasets/${datasetId}/quicklook?size=256` — no trailing slash, matches `router.py:182` ✓
3. **If no mismatch found in `src/api/*`:** the 307 may originate from a distribution URL stored in the DB (e.g., `/collections/{id}/items` without proper base URL resolution). Check `search/service.py:1250-1254` — `build_url(d.url, base_url=public_api_url)`. The `public_api_url` must be set via `PUBLIC_API_URL` env var to avoid falling back to request-derived URL with internal hostname.
4. **Defensive fix:** Set `app.router.redirect_slashes = False` in `backend/app/main.py:388` globally — but this changes behavior for ALL routes. Higher blast radius, not recommended without audit.

**Recommended:** Document findings but do NOT blind-fix. Ask the executor to reproduce and paste the exact URL, then apply targeted fix.

**Relevant infrastructure:**
- `backend/app/main.py:393` — `root_path="/api"` — FastAPI respects this for redirects but uses host from request.
- `backend/app/public_urls.py:44-51 normalize_public_url()` — strips trailing slashes from configured URLs.

### 5. Styled table thumbnail tile (frontend)

**File:** `frontend/src/components/search/SearchResultCard.tsx`

**Current code (lines 309-330):**
```tsx
<div className="hidden md:flex md:items-start">
  <div className="size-[160px] shrink-0 overflow-hidden rounded-lg border border-border/40">
    {isTable ? (
      <div className="flex size-[160px] items-center justify-center bg-muted/20 text-muted-foreground">
        <ImageOff className="h-5 w-5 opacity-45" aria-hidden="true" />
      </div>
    ) : quicklookSrc ? (
      <img ... />
    ) : qlLoading ? (...) : (
      <BBoxPreview ... />
    )}
  </div>
</div>
```

**Imports to update:**
- Line 5: Add `Table2` to lucide imports (already used by `RecordTypeBadge.tsx:2` — safe to import).
- `ImageOff` can be removed after the replacement (only usage in the file per grep).

**Table badge color** (`frontend/src/lib/status-colors.ts:59`):
```ts
table: 'border-orange-300 bg-orange-100 text-orange-950 dark:border-orange-900/60 dark:bg-orange-950/30 dark:text-orange-200'
```

Has both light and dark mode variants. For a gradient tile, derive from `bg-orange-100` / `text-orange-950` — use Tailwind `bg-gradient-to-br from-orange-100 to-orange-200 text-orange-900 dark:from-orange-950/40 dark:to-orange-900/30 dark:text-orange-200` (or similar).

**Tile container:** `size-[160px]`, `rounded-lg`, `border border-border/40`, `overflow-hidden`. Keep these constraints.

**Row/column count overlay:** `feature_count` is available from `properties.feature_count`. `column_info.length` is NOT in the OGC Records response today (only in `DatasetResponse`) — verify by reading `search/schemas.py:63-99` (properties block).

From `search/schemas.py`, `OGCRecordProperties` has `feature_count` but no column count field. So for the search card:
- **Row count:** Available (`properties.feature_count` — N rows for tables).
- **Column count:** NOT available. Either:
  1. Add a new `column_count` field to `OGCRecordProperties` and populate it from `len(dataset.column_info or [])` at `search/service.py:1189`
  2. Show only row count on the tile ("29 rows").

**Recommended:** Option 1 (small addition, useful metadata everywhere).

**Reusable styling from `RecordTypeBadge.tsx:34-51`:**
The badge component already uses `recordTypeColors['table']`. The tile can use a complementary but distinct styling (gradient + larger icon + count overlay). No direct reuse beyond the color token.

**One tile, one site:** Only `SearchResultCard.tsx` renders a thumbnail placeholder for tables. `RelatedDatasets.tsx`, `CollectionDatasetList.tsx`, and the dataset detail hero do not render square thumbnails. No other sites to update.

### 6. Tables in DatasetDetail / other card sites

**Audit results** (grep for `ImageOff`, thumbnail/quicklook usage):

| Site | File | Needs tile? |
|------|------|-------------|
| Search results grid | `frontend/src/components/search/SearchResultCard.tsx:310-330` | **YES** — primary target |
| Collection dataset list | `frontend/src/components/collections/CollectionDatasetList.tsx:78` | No thumbnails shown |
| Related datasets widget | `frontend/src/components/dataset/RelatedDatasets.tsx:39` | No thumbnails shown |
| Dataset detail hero | `frontend/src/components/dataset/DatasetDetailSkeleton.tsx`, `panels/DetailPanel.tsx` | Uses `h-[60vh]` full hero, branches on `isTable` already (line 25) — renders a different component for tables |

**No other tile sites need updating.** The table styled-icon tile is a single point change in `SearchResultCard.tsx`.

### 7. OGC response shaping for tables

**Location:** `backend/app/search/service.py:1168-1290` (the `ogc_record` dict builder — function containing this is the single place that transforms a Dataset into an OGC Records Feature).

**Specific fields:**

#### `feature_count` → add `row_count` alias
Line 1192: `"feature_count": dataset.feature_count,`

**Fix:** Add alongside, conditional on record_type:
```python
"feature_count": dataset.feature_count,
**({"row_count": dataset.feature_count} if getattr(record, "record_type", None) == "table" else {}),
```

Also update `backend/app/search/schemas.py` `OGCRecordProperties` (lines 63-99) to add optional `row_count: int | None = None`. Don't forget to regenerate or update `frontend/src/types/api.ts` (look for the auto-generated TS types).

#### `formats` → strip shapefile for tables
Lines 1200-1207:
```python
"formats": (
    list(_RASTER_FORMAT_MEDIA.values())
    if (getattr(record, "record_type", "vector_dataset") or "vector_dataset")
    in ("raster_dataset", "vrt_dataset")
    else list(_FORMAT_MEDIA.values())
),
```

Current `_FORMAT_MEDIA` (lines 51-56):
```python
_FORMAT_MEDIA = {
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
    "shp": "application/x-shapefile",
    "csv": "text/csv",
}
```

**Fix — branch on table:**
```python
# New constant near line 56:
_TABLE_FORMAT_MEDIA = {
    "csv": "text/csv",
    "gpkg": "application/geopackage+sqlite3",
    # geojson is OK for non-spatial — FastAPI /collections/{id}/items works for tables
    "geojson": "application/geo+json",
}

# Then at line 1200-1207:
_rec_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
"formats": (
    list(_RASTER_FORMAT_MEDIA.values()) if _rec_type in ("raster_dataset", "vrt_dataset")
    else list(_TABLE_FORMAT_MEDIA.values()) if _rec_type == "table"
    else list(_FORMAT_MEDIA.values())
),
```

**Consistency check:** The auto-generated distributions at `backend/app/records/service.py:374-380` already restrict tables to `csv` + `ogc_features (geojson)` only (no shapefile, no gpkg download). So the OGC `formats` list was wrong all along — it advertised formats the user could never actually download for tables. Bringing `formats` in line with `distributions` is a correctness fix.

**Recommendation:** Keep `geojson` in `_TABLE_FORMAT_MEDIA` only if `GET /collections/{id}/items` actually works for tables. Verify by reading `backend/app/search/router.py:1119` (`@collections_router.get("/datasets/items")`) or similar — if the handler dispatches to tables without erroring, include geojson. If it errors or excludes tables, remove geojson from the table formats list and keep only csv + gpkg.

**Quick verification question for executor (Wave 0):** `curl http://localhost:8000/api/collections/{table_record_id}/items` — does it return 200 with GeoJSON or 404/500?

#### `distributions` list → verify OGC features link
Lines 1246-1259: The distributions list is pulled directly from `record.distributions` (the DB rows). Per `backend/app/records/service.py:374-380`, tables only get `(download, csv)` + `(ogc_features, geojson)`. **So this list is already correct** — no code change needed unless the executor's verification above shows `/collections/{id}/items` doesn't work for tables, in which case the `ogc_features` row in `_DISTRIBUTION_TEMPLATES` should be gated on `geometry_type is not None` too.

### 8. Schema documentation fix

**Location:** `backend/app/datasets/schemas.py:234-236`

**Current:**
```python
record_type: str = Field(
    default="vector_dataset", description="vector_dataset or raster_dataset"
)
```

**Fix — enumerate all valid values from `backend/app/datasets/models.py:51`:**
```python
record_type: str = Field(
    default="vector_dataset",
    description=(
        "Record type: 'vector_dataset' (spatial features), 'raster_dataset' (single COG), "
        "'vrt_dataset' (VRT mosaic), 'table' (non-spatial tabular), 'map' (saved map), "
        "'service' (catalogued remote service), 'collection' (flat dataset group)."
    ),
)
```

The CHECK constraint is the source of truth: `record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', 'map', 'service', 'collection', 'table')`.

---

## Ordered Approach (for the planner)

Prioritized to front-load the quick wins and put the risky duplicate detection last.

| # | Task | Estimated effort | Risk | Notes |
|---|------|------------------|------|-------|
| 1 | **Schema doc fix** — `DatasetResponse.record_type` description | 5 min | None | Single-line edit in `datasets/schemas.py:234-236`. Zero test impact. |
| 2 | **Quality scoring** — skip geometry/CRS for tables | 15 min | Low | Localized to `ingest/metadata.py:compute_quality_score`. Requires one new unit test in `test_quality_score.py`. Fix-forward — no migration. |
| 3 | **OGC formats list** — strip shapefile for tables | 15 min | Low | Two file edits: `search/service.py` constant + branch. Update `test_ogc_record_properties.py:88-106` to assert table-specific formats. |
| 4 | **`row_count` alias** — add to OGC response | 15 min | Low | `schemas.py` field + `service.py` dict spread + `types/api.ts` regen. |
| 5 | **307 redirect investigation** — reproduce + identify path | 20 min | Medium | Needs browser DevTools reproduction first. Do NOT blind-fix. Document + apply targeted change. |
| 6 | **Table thumbnail tile** — styled icon replacement | 30 min | Low | `SearchResultCard.tsx:310-330` swap. Update existing tests in `search/__tests__/SearchResultCard.test.tsx` (currently asserts `ImageOff` by role — MUST update). Optional: add `column_count` field to OGC response for "N rows · M cols" overlay. |
| 7 | **Column info fix** — debug + propagate ArcGIS fields | 45 min | Medium | **Do diagnosis first.** Run `\d+ data.bulletin` or `SELECT * FROM information_schema.columns WHERE table_name='bulletin'` on affected DB to confirm root cause. If the PG table is normal, the bug is in `get_column_info` call path — investigate. If the PG table is in the wrong schema, that's a deeper ogr2ogr issue. Fallback: propagate ArcGIS `fields` through `user_metadata` as a backup. |
| 8 | **Duplicate detection (409 Conflict)** — injected at preview | 60–90 min | **High (surface area)** | Biggest change: new branch in `services/router.py:preview_service_layer`, new error schema, frontend must handle the 409 body (display existing dataset link, not crash). Multiple tests: `test_services_endpoints.py` (new dup case), possibly `test_ingest.py`. URL normalization using `normalize_arcgis_url` + layer suffix before querying. |

**Why this order:** Wins #1-4 are trivial and low-risk. #5 needs user-agent reproduction before editing. #6 is visual polish. #7 has diagnostic uncertainty. #8 is the most architectural and benefits from all other changes being in place (so the executor only has to think about one moving piece at a time). Also, #8 is the one most likely to need a 2nd review pass.

---

## Risks & Gotchas

### 1. Quality score retroactive correction
**Not a migration hazard, but a UI consistency risk.**
- New tables will get correct scores. Existing tables (like the 3 Bulletins) retain inflated scores until re-edited.
- CONTEXT explicitly says "no backfill." But consider: the 3 existing Bulletins will show 73 in the UI while new tables show ~40-50. This will confuse admins.
- **Mitigation:** Add a one-line comment in the dataset detail UI ("Quality scores updated for tables ingested after [date]") OR provide a manual "recompute quality" button (out of scope per CONTEXT but worth flagging).

### 2. `formats` list is computed in TWO places
- **OGC Records response** (`search/service.py:1200-1207`) — derives from `_FORMAT_MEDIA` dict.
- **RecordDistribution rows** (`records/service.py:_DISTRIBUTION_TEMPLATES`) — already correct for tables.
- These MUST stay in sync. Add a regression test that compares `formats` against `distributions` for a table record to catch future drift.

### 3. Duplicate detection + URL normalization subtlety
The stored `source_url` (after `_enrich_source_url`) is `.../FeatureServer/0`. The preview-time URL may be `.../FeatureServer` (the base). The duplicate check MUST normalize both sides — use `services/arcgis.py:normalize_arcgis_url()` and construct the enriched form before comparing. **Getting this wrong means false negatives (doesn't detect dupes) or false positives (blocks legitimate different-layer registrations).**

### 4. 409 Conflict response body is a contract change
Frontend must handle it. Current error handling in `frontend/src/api/client.ts:126-137`:
```ts
if (!response.ok) {
  let detail = response.statusText;
  try {
    const body = await response.json();
    if (body.detail) {
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    }
  } catch { /* body not JSON */ }
  throw new ApiError(translateError(detail), response.status);
}
```
The client already handles non-string `detail` by JSON-stringifying it. But the UI component (the ArcGIS import flow) will receive a JSON string, not a structured object. **Either:**
- Pass the 409 body through unchanged (client-side refactor to expose parsed body), OR
- Use a different shape: return a 200 with `{ status: "duplicate", existing_dataset_id: ... }` (NOT recommended — breaks REST semantics), OR
- Accept that the user sees a JSON string error message for now and ticket a follow-up to add structured 409 handling in the UI (pragmatic).

### 5. `column_info` root cause is unclear
As noted in #7 above. The empty `[]` could be:
- A schema mismatch (table in `public`, query looks in `data`)
- A race condition (dataset created before `extract_metadata` finished)
- A legitimate "no columns survived the ogr2ogr type-cast" case
- A prior failed ingest left a stale table

**Do NOT write a fix before running diagnostics on the dev DB.** The executor should attach the actual `information_schema.columns` output for `bulletin` to the plan before coding.

### 6. The TanStack Query cache for a 307'd endpoint may cache garbage
If the 307 actually produces a "succeeded" fetch (follows to internal hostname, fails to connect, React Query caches undefined), the UI will show stale data. If the fix changes the endpoint, you must also `queryClient.invalidateQueries({ queryKey: queryKeys.datasets.detail(id) })` in dev. Not a code change, but a QA note.

### 7. `column_info` vs `column_count` on the table thumbnail
If you want "29 rows · 5 cols" on the tile, `column_count` needs to be exposed in the OGC Records response. Add it to `OGCRecordProperties` + populate via `len(dataset.column_info or [])` in `search/service.py`. **But** if `column_info` is empty (the existing bug for Bulletin tables), the overlay will display "29 rows · 0 cols" which is worse than no count. **Ship the column_info fix BEFORE the cols overlay, or gate the overlay on `column_count > 0`.**

### 8. Frontend test updates (mandatory, not optional)
`SearchResultCard.test.tsx:305-320` currently asserts the table card renders. It may check for an `ImageOff` icon presence or absence. After the tile replacement, rewrite those assertions to check for `Table2` icon and the row-count text.

### 9. Pydantic schema version mismatch for `row_count`
Since `row_count` is a new optional field in `OGCRecordProperties`, existing OpenAPI consumers may not see it. If `frontend/src/types/api.ts` is auto-generated, regenerate; otherwise update manually. Do not remove `feature_count`.

### 10. ArcGIS `normalize_arcgis_url` returns `(base, layer_id)` tuple — don't forget
`backend/app/services/arcgis.py:55` returns a **tuple**. Unpacking mistakes will silently compare strings vs tuples. Unit test the dedup comparator in isolation.

---

## Tests to Touch

| File | What changes | Why |
|------|--------------|-----|
| `backend/tests/test_quality_score.py` | Add `test_compute_quality_score_table_record` — assert `overall` uses only metadata + attribute, and `geometry_validity` / `crs_defined` are absent or None. | Quality scoring fix |
| `backend/tests/test_ogc_record_properties.py` | Update `test_record_has_formats_list` (line 88) to test vector AND table separately. Table case should assert only csv + gpkg (+ maybe geojson). | Formats list fix |
| `backend/tests/test_ogc_record_properties.py` | Add `test_table_record_has_row_count_alias`. | row_count alias |
| `backend/tests/test_services_endpoints.py` | Add `test_preview_rejects_duplicate_arcgis` — verify 409 response and structured body when a matching `(source_url, source_format, created_by)` exists. | Duplicate detection |
| `backend/tests/test_services_endpoints.py` | Add `test_preview_allows_different_layer_same_service` — verify that `.../FeatureServer/0` and `.../FeatureServer/1` are NOT duplicates. | URL normalization correctness |
| `backend/tests/test_ingest.py` | If the column_info bug requires a code change (vs DB fix), add `test_arcgis_table_ingest_populates_column_info`. | Column metadata fix |
| `backend/tests/test_datasets.py` | Add/update test for `DatasetResponse.record_type` description in OpenAPI schema assertion (if such a test exists — grep first). | Schema doc (optional — description is not functional) |
| `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` | Rewrite lines 305-337. Assert presence of `Table2` icon, orange gradient class, row-count label. Remove `ImageOff` assertions. | Thumbnail tile fix |
| `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` | If `column_count` is added to OGC response, new test: "shows column count when available". | Optional overlay |

**Test patterns (for new tests):**
- Backend: `pytest` + `httpx.AsyncClient` fixtures from `tests/conftest.py` + `tests/factories.py`. Uses Docker DB. Run with `make test` or `docker compose exec api uv run pytest tests/test_X.py -v`.
- Frontend: `vitest` + `@testing-library/react`. Run with `cd frontend && npm test`.

---

## Lint/Format Commands

**Backend (Python):**
```bash
# Run from backend/ with uv or from root via docker
uv run ruff check .           # lint
uv run ruff format .          # auto-format
uv run ruff format --check .  # verify format (CI)

# Tests
docker compose exec api uv run pytest -v --tb=short    # full suite (Makefile `make test`)
docker compose exec api uv run pytest tests/test_quality_score.py -v   # targeted
```

CI gate (from `.github/workflows/ci.yml:68-71`): `ruff check .` AND `ruff format --check .`. Both must pass.

**Frontend (TypeScript/React):**
```bash
cd frontend
npm run lint          # eslint
npx tsc --noEmit      # type check (CI runs this separately)
npm test              # vitest
npm run test:watch    # during dev
```

CI gate (from `.github/workflows/ci.yml:195-198`): `npm run lint` AND `npx tsc --noEmit`.

**Commit hygiene:** Pre-commit check is not configured in this repo (no `.pre-commit-config.yaml`). CI is the enforcement layer. Run both lint+format commands before each commit.

---

## Open Questions for the Executor

1. **Why is `column_info` empty for the 3 Bulletin tables?** Run diagnostics before coding. Suggested command inside the `api` container:
   ```sql
   SELECT table_schema, table_name FROM information_schema.tables WHERE table_name LIKE 'bulletin%';
   SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'bulletin' ORDER BY ordinal_position;
   ```
2. **Does `GET /collections/{table_id}/items` work for tables?** Determines whether `geojson` stays in `_TABLE_FORMAT_MEDIA`. Quick curl test on the dev instance.
3. **Where exactly does the 307 originate?** Browser DevTools Network tab, filter for 307, capture the exact request URL. Paste into the plan before implementing.
4. **Does the frontend ArcGIS import UI have an "existing dataset" error display?** If not, the 409 Conflict response will show a raw JSON error. Needs either a simple toast-with-link in the plan OR an accepted limitation.
5. **Should the quality score for tables expose 2 dimensions or 4 (with 2 as null)?** The current `quality_detail` dict is passed as-is to the frontend. Omitting keys is cleaner but may break UI that accesses `quality_detail.geometry_validity` directly. Grep frontend for `quality_detail\.` first.

---

## Sources

All findings from direct codebase reads. No Context7/WebSearch needed — scope is entirely internal.

- `backend/app/services/router.py:46, 212-395` (probe, preview endpoints)
- `backend/app/services/arcgis.py:55-168` (URL normalization, probe parsing)
- `backend/app/services/preview.py:138` (fields parser)
- `backend/app/ingest/router.py:287-356, 457-534, 585-628` (upload, commit, bulk register)
- `backend/app/ingest/tasks.py:32-179, 419-542` (_finalize_ingest, ingest_service)
- `backend/app/ingest/metadata.py:161-187, 233-346, 362-389` (get_column_info, compute_quality_score, extract_metadata)
- `backend/app/ingest/service.py:164-211` (generate_table_name)
- `backend/app/ingest/ogr.py:395-454` (run_ogr2ogr_service, schema handling)
- `backend/app/datasets/models.py:28-250` (Record, Dataset, CHECK constraints)
- `backend/app/datasets/schemas.py:220-248` (DatasetResponse)
- `backend/app/datasets/service.py:152-239` (create_dataset, record_type auto-assignment)
- `backend/app/datasets/helpers.py:114-200` (_dataset_to_response)
- `backend/app/datasets/router.py:136` (get single dataset route — no trailing slash)
- `backend/app/records/service.py:270-420` (_DISTRIBUTION_TEMPLATES, generate_distributions)
- `backend/app/search/service.py:40-61, 1168-1290` (format constants, OGC record builder)
- `backend/app/search/schemas.py:63-99` (OGCRecordProperties)
- `backend/app/main.py:388-407` (FastAPI app config, root_path)
- `backend/app/public_urls.py:1-60` (URL resolution, normalize_public_url)
- `backend/tests/test_quality_score.py:1-200` (test factory, existing patterns)
- `backend/tests/test_ogc_record_properties.py:88-106` (formats test — will need update)
- `backend/tests/test_services_endpoints.py:1-40` (fixtures, mock patterns)
- `backend/pyproject.toml:44-78` (ruff, pytest config)
- `frontend/src/api/datasets.ts:1-160` (all dataset fetch call sites)
- `frontend/src/components/search/SearchResultCard.tsx:1-356` (table rendering, imports)
- `frontend/src/components/search/RecordTypeBadge.tsx:1-52` (Table2 import, color binding)
- `frontend/src/lib/status-colors.ts:54-61` (recordTypeColors.table)
- `frontend/src/components/search/__tests__/SearchResultCard.test.tsx:305-337` (existing table tests)
- `frontend/src/api/client.ts:100-144` (apiFetch error handling)
- `.github/workflows/ci.yml:45-200` (lint/test gates)
- `Makefile:19-23` (test commands)

## Metadata

**Confidence breakdown:**
- Implementation map — HIGH (all line numbers and function names verified by direct read)
- Quality scoring fix — HIGH (single pure function, clear branching point)
- Formats list fix — HIGH (exact line range identified)
- row_count alias — HIGH (clean schema + builder change)
- Thumbnail tile — HIGH (single-file frontend change)
- Schema doc — HIGH (trivial)
- Duplicate detection — MEDIUM (URL normalization details need validation, 409 response shape is an API design decision)
- Column metadata fix — MEDIUM (root cause unknown, investigation needed)
- 307 redirect — LOW-to-MEDIUM (CONTEXT path doesn't match codebase; reproduction required)

**Research date:** 2026-04-08
**Valid until:** 2026-05-08 (stable codebase, no pending refactors that affect these paths)

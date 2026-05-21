---
phase: 260408-iny
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/datasets/schemas.py
  - backend/app/ingest/metadata.py
  - backend/app/search/service.py
  - backend/app/search/schemas.py
  - backend/app/services/router.py
  - backend/app/services/arcgis.py
  - backend/app/ingest/tasks.py
  - backend/app/ingest/service.py
  - backend/tests/test_quality_score.py
  - backend/tests/test_ogc_record_properties.py
  - backend/tests/test_services_endpoints.py
  - backend/tests/test_ingest.py
  - frontend/src/components/search/SearchResultCard.tsx
  - frontend/src/components/search/__tests__/SearchResultCard.test.tsx
  - frontend/src/types/api.ts
  - frontend/src/api/datasets.ts
  - frontend/src/api/client.ts
  - frontend/src/components/import/ServiceUrlForm.tsx
  - .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md
autonomous: true
requirements:
  - QUICK-260408-iny
must_haves:
  truths:
    # Wave 0 diagnostic truths
    - "A DIAGNOSTICS.md file exists capturing the column_info root cause (schema mismatch, stale job, or legitimate empty), the exact 307-triggering request URL (or a documented 'cannot reproduce'), and a curl transcript of GET /api/collections/{table_record_id}/items for a real table record"
    # Schema doc truth
    - "DatasetResponse.record_type description enumerates all seven valid values (vector_dataset, raster_dataset, vrt_dataset, table, map, service, collection)"
    # Quality scoring truths
    - "compute_quality_score returns only metadata_completeness and attribute_completeness dimensions for a record_type='table' input (geometry_validity and crs_defined are either absent or explicitly None)"
    - "The overall score for a table is computed solely from metadata + attribute weights re-normalized to sum to 1.0"
    - "A new backend test test_compute_quality_score_table_record exists and passes"
    # OGC response truths
    - "GET /api/collections/datasets (OGC Records search) for a record_type='table' result includes a row_count property equal to feature_count"
    - "feature_count is STILL present in the OGC response for tables (alias, not replacement)"
    - "The formats list for a record_type='table' OGC record contains text/csv, application/geopackage+sqlite3, and application/geo+json — application/x-shapefile is NOT in the list"
    - "OGCRecordProperties schema has a new optional column_count field populated from len(dataset.column_info or []) in the record builder"
    # Column_info fix truth (conditional on Wave 0)
    - "For ArcGIS table ingests after this change, column_info is a non-empty list of {name, type, ordinal_position, is_nullable} objects derived from either information_schema.columns (primary) or the ArcGIS probe response fields (fallback) — verified by either an integration test or a manual re-import of a known ArcGIS table"
    # 307 redirect truth (conditional on Wave 0)
    - "Either (a) the 307 redirect is reproducible and the exact failing call site is fixed so DevTools shows 0 307s on dataset detail page load, OR (b) DIAGNOSTICS.md documents that the 307 could not be reproduced and no speculative code change was made"
    # Thumbnail truth
    - "Table search result cards render a styled icon tile (orange gradient background + Table2 lucide icon + 'N rows[ · M cols]' label) instead of the ImageOff placeholder"
    - "The frontend test frontend/src/components/search/__tests__/SearchResultCard.test.tsx asserts presence of the Table2 icon and row-count label for table records (ImageOff assertions removed)"
    # Duplicate detection truths
    - "POST /api/services/preview/ with a source_url+service_type matching an existing dataset owned by the same user returns HTTP 409 with a structured body containing code='duplicate_source' and existing_dataset_id"
    - "POST /api/services/preview/ with the same base service URL but a DIFFERENT layer id (e.g., FeatureServer/0 vs FeatureServer/1) does NOT return 409 — both layers can be registered"
    - "A backend test test_preview_rejects_duplicate_arcgis exists and passes"
    - "A backend test test_preview_allows_different_layer_same_service exists and passes"
    - "`frontend/src/components/import/ServiceUrlForm.tsx` displays a human-readable error with a 'View existing' toast action when it receives the 409 duplicate response (link or id of the existing dataset, NOT a raw JSON blob)"
    # Ship gate truth
    - "All modified backend tests pass via 'docker compose exec api uv run pytest -v'"
    - "Frontend tests pass via 'cd frontend && npm test'"
    - "Backend lint passes: 'cd backend && uv run ruff check . && uv run ruff format --check .'"
    - "Frontend lint + typecheck pass: 'cd frontend && npm run lint && npx tsc --noEmit'"
  artifacts:
    - path: ".planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md"
      provides: "Wave 0 investigation findings for column_info root cause, 307 redirect reproduction, and /collections/items for tables"
      contains: "column_info diagnosis, 307 reproduction log, collections/items curl transcript"
      min_lines: 40
    - path: "backend/app/datasets/schemas.py"
      provides: "DatasetResponse.record_type description listing all 7 valid values"
      contains: "vector_dataset"
    - path: "backend/app/ingest/metadata.py"
      provides: "compute_quality_score with table-specific branch (metadata + attribute only, re-normalized)"
      contains: "record_type"
    - path: "backend/app/search/service.py"
      provides: "OGC record builder with row_count alias, column_count, table-specific formats list"
      contains: "row_count"
    - path: "backend/app/search/schemas.py"
      provides: "OGCRecordProperties with row_count and column_count optional fields"
      contains: "row_count"
    - path: "backend/app/services/router.py"
      provides: "preview_service_layer with duplicate-source check returning 409 Conflict"
      contains: "duplicate_source"
    - path: "frontend/src/components/search/SearchResultCard.tsx"
      provides: "Styled orange-gradient + Table2 icon + row/col count tile for tables"
      contains: "Table2"
    - path: "backend/tests/test_quality_score.py"
      provides: "New test for table quality scoring"
      contains: "test_compute_quality_score_table_record"
    - path: "backend/tests/test_services_endpoints.py"
      provides: "New tests for duplicate detection and layer disambiguation"
      contains: "test_preview_rejects_duplicate_arcgis"
    - path: "backend/tests/test_ogc_record_properties.py"
      provides: "Updated formats test + new row_count alias test"
      contains: "row_count"
    - path: "frontend/src/components/search/__tests__/SearchResultCard.test.tsx"
      provides: "Updated table card assertions for Table2 icon + row-count label"
      contains: "Table2"
  key_links:
    - from: "backend/app/ingest/metadata.py compute_quality_score"
      to: "dataset.record.record_type"
      via: "lazy='joined' relationship access"
      pattern: "record_type.*table|is_table"
    - from: "backend/app/search/service.py ogc_record builder"
      to: "dataset.feature_count + dataset.column_info"
      via: "conditional spread for row_count + len(column_info) for column_count"
      pattern: "row_count|column_count"
    - from: "backend/app/services/router.py preview_service_layer"
      to: "backend/app/services/arcgis.py normalize_arcgis_url"
      via: "url normalization before duplicate lookup"
      pattern: "normalize_arcgis_url"
    - from: "backend/app/services/router.py preview_service_layer"
      to: "backend/app/datasets/models.py Dataset + Record"
      via: "select join on (source_url, source_format, created_by)"
      pattern: "source_url.*source_format|Dataset.*Record"
    - from: "frontend/src/components/search/SearchResultCard.tsx"
      to: "frontend/src/lib/status-colors.ts recordTypeColors.table"
      via: "orange color derivation for gradient"
      pattern: "orange"
    - from: "frontend/src/components/import/ServiceUrlForm.tsx handleLayerSelect catch block"
      to: "backend 409 response body {code, existing_dataset_id, existing_title}"
      via: "ApiError body parsing to render link or id"
      pattern: "duplicate_source|existing_dataset_id"
---

<objective>
Full enhancement pass for the `table` record_type in GeoLens. This task addresses 8 concerns identified during live investigation (see `260408-iny-CONTEXT.md`) and mapped to specific code locations in research (see `260408-iny-RESEARCH.md`):

1. Duplicate detection on ArcGIS service registration (root-cause fix for the 3 Bulletin duplicates)
2. Empty `column_info` for ArcGIS table ingests (diagnose + fix)
3. Quality score inflation for tables (skip geometry/CRS dimensions)
4. 307 redirect on dataset detail (reproduce + targeted fix)
5. Styled icon tile thumbnail for tables (replace generic ImageOff placeholder)
6. `row_count` alias + `column_count` field in OGC Records response
7. Strip incompatible formats (shapefile) from tables in OGC `formats` list
8. Update `DatasetResponse.record_type` schema documentation

The research ordered these front-loading the quick wins (schema doc → quality → formats → alias → thumbnail) and putting the risky architectural changes (column_info root cause, 307 reproduction, duplicate detection) after the safe edits are in place. **Wave 0 diagnostics are mandatory** — the research flagged three items (column_info SQL introspection, 307 reproduction, /collections/items for tables) that must be investigated BEFORE coding because a blind fix could mask the real bug or ship an incorrect change.

Purpose: Ship working code that resolves the user's diagnosis and prevents the same class of bug from recurring. Tables become first-class citizens in discovery with accurate scores, correct format advertising, useful API metadata, and visually coherent thumbnails.

Output: Modified backend + frontend code, updated tests, one DIAGNOSTICS.md capturing Wave 0 findings, all CI gates green.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-CONTEXT.md
@.planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-RESEARCH.md

<!-- Backend files that will be modified or consulted -->
@backend/app/datasets/schemas.py
@backend/app/datasets/models.py
@backend/app/ingest/metadata.py
@backend/app/search/service.py
@backend/app/search/schemas.py
@backend/app/services/router.py
@backend/app/services/arcgis.py
@backend/app/services/preview.py
@backend/app/ingest/tasks.py
@backend/app/ingest/service.py
@backend/app/ingest/router.py
@backend/app/datasets/router.py
@backend/app/records/service.py

<!-- Frontend files that will be modified or consulted -->
@frontend/src/components/search/SearchResultCard.tsx
@frontend/src/components/search/__tests__/SearchResultCard.test.tsx
@frontend/src/components/search/RecordTypeBadge.tsx
@frontend/src/lib/status-colors.ts
@frontend/src/api/datasets.ts
@frontend/src/api/client.ts
@frontend/src/types/api.ts

<!-- Existing tests that will be updated -->
@backend/tests/test_quality_score.py
@backend/tests/test_ogc_record_properties.py
@backend/tests/test_services_endpoints.py

<interfaces>
<!-- Key contracts extracted from the research. Do not re-explore the codebase for these. -->

## Dataset source-tracking columns (backend/app/datasets/models.py:228-233)
```python
source_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
# CHECK constraint (line 183-188) allowed values:
#   'arcgis_featureserver', 'arcgis_mapserver', 'wfs', 'geojson', 'shapefile', 'gpkg', 'csv'
source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
```

`Dataset.record` is `lazy="joined"` (models.py:241-243) — safe to access `.record.record_type` inside `compute_quality_score` without additional awaits.
`Record.created_by` is the owner (models.py:120). The dedup join must go through Record.

## Record CHECK constraint for record_type (source of truth for schema doc)
```
record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', 'map', 'service', 'collection', 'table')
```

## OGCRecordProperties shape (backend/app/search/schemas.py:63-99)
Currently has `feature_count` but no `row_count` or `column_count`. Both should be added as optional fields.

## OGC record builder constant (backend/app/search/service.py:51-56)
```python
_FORMAT_MEDIA = {
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
    "shp": "application/x-shapefile",
    "csv": "text/csv",
}
```
Add a new `_TABLE_FORMAT_MEDIA` constant next to this one (see Task 3 for details).

## compute_quality_score current weights (backend/app/ingest/metadata.py:233-346)
- metadata_completeness: 30%
- geometry_validity: 30%
- attribute_completeness: 25%
- crs_defined: 15%
For tables, re-normalize to metadata (30/55) + attribute (25/55).

## normalize_arcgis_url signature (backend/app/services/arcgis.py:55)
Returns a **tuple** `(base_url, layer_id_or_None)` — unpack carefully. `_enrich_source_url` at `tasks.py:412-416` produces the stored form (with layer suffix); preview time has the unenriched form. Reconcile BEFORE querying.

## ArcGIS fields parser (backend/app/services/preview.py:138)
```python
columns = [{"name": f["name"], "type": f["type"]} for f in layer.get("fields", [])]
```
Not persisted — only used for UI preview. Task 4 will propagate it as a column_info fallback through IngestJob.user_metadata.

## column_info JSON schema (backend/app/ingest/metadata.py:178-186)
```json
[{"name": "field_name", "type": "text", "ordinal_position": 1, "is_nullable": true}]
```

## Existing 409 response pattern in the codebase (backend/app/ingest/router.py:744-748)
Existing 409s use plain string `detail`. For the new structured body, use a dict — `apiFetch` already stringifies non-string detail (client.ts:126-137), so the raw shape is preserved end-to-end.

## SearchResultCard thumbnail block (frontend/src/components/search/SearchResultCard.tsx:309-330)
Currently renders `<ImageOff />` for `isTable`. Task 5 replaces this only — keep the container sizes, border, and rounded corners intact.

## Table badge color (frontend/src/lib/status-colors.ts:59)
`table: 'border-orange-300 bg-orange-100 text-orange-950 dark:border-orange-900/60 dark:bg-orange-950/30 dark:text-orange-200'`
Derive the tile gradient from these tokens — do NOT introduce new color palette entries.
</interfaces>

**Project skill activation:** Run `$geolens-ship` at the end of this plan (Task 6) to invoke the repo's actual CI-parity gate order. Do not hand-roll a custom lint/test sequence.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Wave 0 diagnostics — column_info root cause, 307 reproduction, collections/items support</name>
  <files>
    .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md
  </files>
  <action>
**Purpose:** Research flagged three items as diagnostic gates. Running these BEFORE coding prevents shipping a blind fix that masks the real bug or ships a speculative change. No code changes in this task — only investigation and write-up to `260408-iny-DIAGNOSTICS.md`.

**Gate A — column_info empty root cause** (RESEARCH.md §2):

Run SQL directly against the dev database inside the `api` container:

```bash
docker compose exec api uv run python -c "
import asyncio
from sqlalchemy import text
from app.database import async_session_factory

async def main():
    async with async_session_factory() as db:
        # Step 1: locate the bulletin tables
        tables = await db.execute(text('''
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name LIKE 'bulletin%'
            ORDER BY table_name
        '''))
        print('TABLES:', tables.fetchall())

        # Step 2: columns for each
        for suffix in ('bulletin', 'bulletin_2', 'bulletin_3'):
            cols = await db.execute(text('''
                SELECT column_name, data_type, ordinal_position, is_nullable
                FROM information_schema.columns
                WHERE table_name = :name
                ORDER BY ordinal_position
            '''), {'name': suffix})
            print(f'COLUMNS {suffix}:', cols.fetchall())

asyncio.run(main())
"
```

Record output verbatim in DIAGNOSTICS.md. Classify the root cause:
- **Case 1:** Table is in `public` (not `data`) schema → `get_column_info` filter is wrong
- **Case 2:** Table is in `data` but has columns that look like `gid`/`geom`/`geom_4326` only → ogr2ogr created a malformed table
- **Case 3:** Table has real columns and the query SHOULD work → bug in `get_column_info` call site (e.g., called before table was finalized, stale job record, etc.)
- **Case 4:** Table doesn't exist at all → ingest failed silently and the Dataset row is orphaned

This classification determines the fix in Task 4.

**Gate B — 307 redirect reproduction** (RESEARCH.md §4):

Research found that `frontend/src/api/datasets.ts:32` and `backend/app/datasets/router.py:136` already match (both without trailing slash). So the CONTEXT description may be imprecise. Reproduce manually:

1. Start the dev stack: `docker compose up -d` (verify with `curl http://localhost:8080`)
2. Log in and navigate to any dataset detail page
3. Open DevTools → Network tab → filter `307` or `redirected`
4. Record the exact request URL that 307s (if any), the source file that initiated it (DevTools "Initiator" column), and the Location header value
5. If no 307 is found:
   - Try navigating to a TABLE record detail (the bulletin records) — the CONTEXT references tables specifically
   - Check the `/api/search/datasets/...` calls for table records
   - Check `hooks/use-quicklook.ts` for table records (the hook is skipped for tables, but verify it doesn't fire)
6. If still no 307: document "Cannot reproduce in current codebase" and note that Task 4's 307 subtask will be SKIPPED

Record the exact URL, initiator file:line, and Location header in DIAGNOSTICS.md. Do NOT speculate — if it's not reproducible, say so clearly.

**Gate C — /collections/{table_record_id}/items support for tables** (RESEARCH.md §7, VERIFICATION ONLY — NON-BLOCKING):

Research §7 confirmed that `backend/app/records/service.py:374-380` already emits `(ogc_features, geojson)` distributions for tables, so `application/geo+json` will be included in `_TABLE_FORMAT_MEDIA` unconditionally in Task 2. This gate is a sanity check only — its outcome does NOT change the code in Task 2 and does NOT block Task 2's progression.

Pick one of the existing bulletin records (e.g., `3b26e492-3978-48f3-a6b3-a7016bd16841`) or another table record id. Run:

```bash
curl -sS -H "Authorization: Bearer $(grep GEOLENS_ADMIN_PASSWORD .env | cut -d= -f2)" \
  "http://localhost:8080/api/collections/3b26e492-3978-48f3-a6b3-a7016bd16841/items?limit=1" | head -50
```

If 401/403: obtain a JWT via `POST /api/auth/login` first. Expected result: 200 with a GeoJSON FeatureCollection (geometries may be `null` for tables). If the response is NOT 200, record the failure in DIAGNOSTICS.md and flag as a follow-up for a future milestone — but still proceed with Task 2 as planned (the distributions template already advertises this format, so fixing the `/items` handler is a separate concern outside this quick task).

Record status code, response snippet (first 20 lines), and verdict in DIAGNOSTICS.md. Verdict is informational only.

**Write-up format for DIAGNOSTICS.md:**

```markdown
# 260408-iny Wave 0 Diagnostics
**Run:** YYYY-MM-DD HH:MM

## Gate A: column_info root cause
### Command
...
### Output
...
### Verdict
Case N — [description]. Fix strategy for Task 4: [schema filter change / ArcGIS fields fallback / investigation required / etc.]

## Gate B: 307 redirect reproduction
### Steps taken
...
### Finding
[Reproducible with exact URL | Cannot reproduce | Reproduced but from a non-obvious path]
### Fix target for Task 4
[specific file:line | SKIP — document in SUMMARY]

## Gate C: /collections/{id}/items for tables
### Command
...
### Output
...
### Verdict
[Works (expected) | Fails (log as follow-up)] — informational only, does NOT affect Task 2's _TABLE_FORMAT_MEDIA (geojson is unconditional per research §7)
```
  </action>
  <verify>
    <automated>test -f .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md && wc -l .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md | awk '{exit ($1 &gt;= 40) ? 0 : 1}'</automated>
  </verify>
  <done>
DIAGNOSTICS.md exists with minimum 40 lines. Gate A classifies the column_info root cause into one of 4 cases. Gate B either reports a specific request URL or documents "cannot reproduce". Gate C reports a status code and verdict (informational; does not gate Task 2). Tasks 3 and 4 can now proceed with confirmed information instead of guesses.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Backend quick wins — schema doc, quality scoring, OGC formats + row_count/column_count</name>
  <files>
    backend/app/datasets/schemas.py
    backend/app/ingest/metadata.py
    backend/app/search/schemas.py
    backend/app/search/service.py
    backend/tests/test_quality_score.py
    backend/tests/test_ogc_record_properties.py
  </files>
  <behavior>
- **test_compute_quality_score_table_record**: Given a Dataset where `dataset.record.record_type == "table"` and `geometry_type is None` and `srid is None`, `compute_quality_score` returns a dict whose `overall` equals `round(metadata_score * (30/55) + attribute_score * (25/55))`. The returned dict has `metadata_completeness` and `attribute_completeness` keys. The keys `geometry_validity` and `crs_defined` are either absent or `None` (use whichever the frontend grep in Task 2 confirms is safe — default to `None` for schema stability).
- **test_table_record_has_row_count_alias**: Build an OGC record for a table dataset with `feature_count=29`. The resulting properties dict contains `row_count == 29` AND `feature_count == 29` (both, not one-or-the-other).
- **test_vector_record_has_no_row_count**: Build an OGC record for a vector_dataset. The resulting properties dict does NOT contain `row_count` (or contains it as None) — no regression for non-table records.
- **test_table_record_has_column_count**: Build an OGC record for a table dataset with `column_info` containing 5 entries. The resulting properties dict has `column_count == 5`.
- **test_record_has_formats_list** (update existing): For vector_dataset, formats list contains gpkg + geojson + shp + csv. For table, formats list contains csv + gpkg + geojson. For table, formats list does NOT contain `application/x-shapefile`.
- **test_raster_record_has_formats_list**: Unchanged — ensure raster still returns `_RASTER_FORMAT_MEDIA` values.
  </behavior>
  <action>
**Sub-task 2a — Schema doc fix** (RESEARCH.md §8, 5 min):

Edit `backend/app/datasets/schemas.py:234-236`. Replace the current `record_type` Field description with:

```python
record_type: str = Field(
    default="vector_dataset",
    description=(
        "Record type: 'vector_dataset' (spatial features), "
        "'raster_dataset' (single COG), 'vrt_dataset' (VRT mosaic), "
        "'table' (non-spatial tabular), 'map' (saved map), "
        "'service' (catalogued remote service), 'collection' (flat dataset group)."
    ),
)
```

This mirrors the CHECK constraint at `backend/app/datasets/models.py:51` (source of truth).

**Sub-task 2b — Quality score table branch** (RESEARCH.md §3, 15 min):

Edit `backend/app/ingest/metadata.py compute_quality_score()` (lines 233-346).

Near the top of the function (after `has_geometry = dataset.geometry_type is not None`), add:

```python
is_table = getattr(dataset.record, "record_type", None) == "table"
```

Then, at the return statement, branch:

```python
if is_table:
    # Re-normalize weights over applicable dimensions only: metadata (30) + attribute (25) = 55 total
    overall = round(metadata_score * (30 / 55) + attribute_score * (25 / 55))
    return {
        "overall": overall,
        "metadata_completeness": metadata_score,
        "attribute_completeness": attribute_score,
        "geometry_validity": None,  # N/A for tables
        "crs_defined": None,         # N/A for tables
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
# else: existing logic unchanged
```

**Decision — None vs omit keys:** Before committing, grep the frontend for `quality_detail\\.` consumers. If any component does unchecked property access (e.g., `detail.geometry_validity.toFixed()`), keep the keys as `None` (current plan). If the frontend already null-checks, either works — default to `None` for schema stability.

```bash
grep -rn "quality_detail\\." frontend/src/ --include="*.ts" --include="*.tsx"
```

Document the finding briefly in the commit message (not in the plan).

Add the new test `test_compute_quality_score_table_record` in `backend/tests/test_quality_score.py`. Follow the existing test factory patterns in that file.

**Sub-task 2c — OGC formats list + row_count + column_count** (RESEARCH.md §7, 20 min):

**Step 1 — Schema:** Edit `backend/app/search/schemas.py OGCRecordProperties` (lines 63-99). Add:

```python
row_count: int | None = Field(
    default=None,
    description="Row count for tabular records (alias for feature_count when record_type='table').",
)
column_count: int | None = Field(
    default=None,
    description="Number of columns in the dataset (populated from column_info length).",
)
```

**Step 2 — Format constant:** Edit `backend/app/search/service.py`. Just below the existing `_FORMAT_MEDIA` dict (around line 56), add:

```python
_TABLE_FORMAT_MEDIA = {
    "csv": "text/csv",
    "gpkg": "application/geopackage+sqlite3",
    "geojson": "application/geo+json",
}
```

Include all three entries unconditionally. Research §7 confirmed `backend/app/records/service.py:374-380` already emits `(ogc_features, geojson)` in `_DISTRIBUTION_TEMPLATES` for tables, so `application/geo+json` is already an advertised distribution for table records — the OGC `formats` list must match. Wave 0 Gate C verifies the `/collections/{id}/items` endpoint actually serves tables, but its outcome is informational and does NOT affect this constant.

**Step 3 — Builder branching:** Edit the OGC record builder in `backend/app/search/service.py` (around lines 1168-1290). Update the `formats` field:

```python
_rec_type = getattr(record, "record_type", "vector_dataset") or "vector_dataset"
# ...inside the dict being built...
"formats": (
    list(_RASTER_FORMAT_MEDIA.values()) if _rec_type in ("raster_dataset", "vrt_dataset")
    else list(_TABLE_FORMAT_MEDIA.values()) if _rec_type == "table"
    else list(_FORMAT_MEDIA.values())
),
```

**Step 4 — row_count alias + column_count:** In the same builder dict, alongside the existing `feature_count` line (1192):

```python
"feature_count": dataset.feature_count,
"row_count": dataset.feature_count if _rec_type == "table" else None,
"column_count": len(dataset.column_info or []) if dataset.column_info else None,
```

Both fields are now always present in the response (None for non-applicable), which is simpler than conditional spread and keeps the schema stable for OpenAPI consumers.

**Step 5 — Update frontend types manually:** `frontend/src/types/api.ts` is manually maintained in this project (27.9KB, not auto-generated). Locate the `OGCRecordProperties` interface at `frontend/src/types/api.ts:266` and add two fields to match the existing optional-field style in that interface:

```typescript
row_count?: number | null;
column_count?: number | null;
```

Do NOT run a type-generation command — there is none. Place the new fields near the existing `feature_count` field to keep related properties grouped.

**Step 6 — Tests:** Update `backend/tests/test_ogc_record_properties.py`:
- Update `test_record_has_formats_list` (line 88): Parameterize or split into vector/table/raster cases. Table case MUST contain exactly `text/csv`, `application/geopackage+sqlite3`, and `application/geo+json` (three entries) and MUST NOT contain `application/x-shapefile`. Vector case is unchanged (gpkg + geojson + shp + csv). Raster case is unchanged.
- Add `test_table_record_has_row_count_alias`: Asserts both `feature_count` and `row_count` are set to 29 for a table record.
- Add `test_vector_record_has_no_row_count`: Asserts `row_count` is None (or absent) for a vector_dataset record.
- Add `test_table_record_has_column_count`: Asserts `column_count == len(column_info)` for a table with populated column_info.
  </action>
  <verify>
    <automated>docker compose exec -T api uv run pytest backend/tests/test_quality_score.py backend/tests/test_ogc_record_properties.py -v --tb=short -x</automated>
  </verify>
  <done>
All new tests pass. Existing tests in `test_quality_score.py` and `test_ogc_record_properties.py` still pass (no regressions). `DatasetResponse.record_type` description lists all 7 valid values. `compute_quality_score` returns only applicable dimensions for tables. OGC Records response includes `row_count` + `column_count` for tables and the formats list contains csv + gpkg + geojson (unconditional per research §7). The frontend `frontend/src/types/api.ts` file is manually updated to match the new schema.
  </done>
</task>

<task type="auto">
  <name>Task 3: Column info fix + 307 redirect targeted fix (Wave 0 gated)</name>
  <files>
    backend/app/ingest/metadata.py
    backend/app/ingest/tasks.py
    backend/app/services/router.py
    backend/app/ingest/service.py
    backend/tests/test_ingest.py
    frontend/src/api/datasets.ts
    frontend/src/hooks/use-quicklook.ts
    frontend/src/api/client.ts
  </files>
  <action>
**This task is Wave 0 gated.** Read `260408-iny-DIAGNOSTICS.md` FIRST. If it does not exist, STOP and go back to Task 1.

**Sub-task 3a — column_info fix** (RESEARCH.md §2):

Apply the fix determined by Gate A in DIAGNOSTICS.md:

**Case 1 (wrong schema)** — If the table is in `public` not `data`: Fix the `get_column_info` query in `backend/app/ingest/metadata.py:161-187` to search across both schemas, OR fix the upstream ogr2ogr call to always land in `data`. Prefer the upstream fix if the ogr2ogr invocation for services is inconsistent. Check `backend/app/ingest/ogr.py:395-454 run_ogr2ogr_service()` for the `-lco SCHEMA=data` or equivalent flag — if missing, add it.

**Case 2 (malformed table)** — If ogr2ogr created only `gid`/`geom`/`geom_4326`: The root cause is an ogr2ogr invocation issue for ArcGIS services. Check if `-preserve_fid` or `-lco FID=gid` is stripping attribute columns. Adjust the invocation. Also implement the fallback below for safety.

**Case 3 (query path bug)** — If the table is fine but column_info is still empty: Fix the call site. Likely `extract_metadata` is called before `_finalize_ingest` has promoted the staging table. Trace the order in `backend/app/ingest/tasks.py:32-179 _finalize_ingest()` and ensure `get_column_info` runs AFTER the table is in its final location.

**Case 4 (orphaned dataset)** — Document in the commit message as a data hygiene concern. The new duplicate detection in Task 5 will prevent new orphaned datasets. Existing orphans are out of scope per CONTEXT.

**Fallback (all cases):** Add an ArcGIS `fields` → `column_info` fallback. In `backend/app/services/router.py preview_service_layer` (around line 342-354 where the IngestJob is created), store the ArcGIS `fields` in `job.user_metadata`:

```python
# After fetching layer info (preview.py parses this already)
user_metadata = {
    **(existing_user_metadata or {}),
    "source_columns": [
        {"name": f["name"], "type": f["type"], "alias": f.get("alias")}
        for f in layer_fields  # from the ArcGIS probe response
    ],
}
```

Then in `backend/app/ingest/metadata.py extract_metadata` (around line 369 where `get_column_info` is called), add a fallback:

```python
column_info = await get_column_info(db, table_name)
if not column_info and job and job.user_metadata:
    source_columns = job.user_metadata.get("source_columns") or []
    if source_columns:
        # Map ArcGIS types to our column_info schema
        column_info = [
            {
                "name": col["name"],
                "type": _arcgis_type_to_column_type(col.get("type", "string")),
                "ordinal_position": idx + 1,
                "is_nullable": True,  # ArcGIS fields metadata doesn't reliably expose nullability
            }
            for idx, col in enumerate(source_columns)
        ]
```

Add a small `_arcgis_type_to_column_type` helper mapping common ArcGIS types (`esriFieldTypeString → text`, `esriFieldTypeInteger → integer`, `esriFieldTypeDouble → double precision`, `esriFieldTypeDate → timestamp`, `esriFieldTypeOID → integer`, etc.).

**Test:** Add `test_arcgis_table_ingest_populates_column_info` in `backend/tests/test_ingest.py`. Mock the ArcGIS probe response with 5 fields, run the metadata extraction, assert `column_info` has 5 entries with correct names and mapped types. Use existing test patterns from that file.

**Sub-task 3b — 307 redirect fix** (RESEARCH.md §4):

Read DIAGNOSTICS.md Gate B verdict:

**If "Cannot reproduce":** SKIP this sub-task. Document in the eventual SUMMARY that the 307 could not be reproduced. Do NOT make speculative changes. Do NOT flip `app.router.redirect_slashes = False` globally — research flagged it as a high blast-radius change.

**If reproducible:** Apply a targeted fix at the exact file:line identified in Gate B. Possible fixes:
- Frontend: drop or add a trailing slash to match the backend route definition
- Backend: add or remove a trailing slash on the route definition (prefer frontend change — changing backend routes risks breaking other clients)
- Distribution URL: if the 307 originates from a distribution URL with an internal hostname, check `backend/app/search/service.py:1250-1254` `build_url(d.url, base_url=public_api_url)` and ensure `PUBLIC_API_URL` env var is set in the dev `.env` file

No new test file — if the fix is a one-line trailing slash correction, the existing dataset detail test coverage (if any) is sufficient. If no coverage exists, note this as a follow-up in the SUMMARY but do not block on it.
  </action>
  <verify>
    <automated>docker compose exec -T api uv run pytest backend/tests/test_ingest.py -v --tb=short -x && (test ! -f DIAGNOSTICS_SKIP_307 || echo "307 skipped per Wave 0")</automated>
  </verify>
  <done>
`test_arcgis_table_ingest_populates_column_info` exists and passes. Manual re-import of an ArcGIS table (done in Task 6 smoke test) produces non-empty `column_info`. 307 redirect is either fixed (reproducible DevTools fix verified) or documented as "not reproducible" in DIAGNOSTICS.md + SUMMARY.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Frontend table thumbnail tile + test updates</name>
  <files>
    frontend/src/components/search/SearchResultCard.tsx
    frontend/src/components/search/__tests__/SearchResultCard.test.tsx
  </files>
  <behavior>
- **Test: table card renders Table2 icon**: Given a table record passed to SearchResultCard, the rendered output contains a `Table2` icon (via `data-testid` or class-based query) inside the `size-[160px]` thumbnail container.
- **Test: table card renders row count label**: Given a table record with `feature_count: 29`, the rendered tile contains text `29 rows` (case-insensitive).
- **Test: table card renders column count when available**: Given a table record with `column_count: 5`, the rendered tile contains text `5 cols` (or `5 columns`). Acceptable to use `·` separator as in "29 rows · 5 cols".
- **Test: table card hides column count when missing**: Given a table record with `column_count: null` or `column_count: 0`, the tile shows only "29 rows" (no "0 cols" rendered).
- **Test: table card does NOT render ImageOff**: The existing `ImageOff` assertion is REMOVED. A negative assertion ensures no `ImageOff` icon is rendered for tables.
- **Test: non-table cards are unchanged**: A vector_dataset record still renders quicklook/BBoxPreview as before (no regression).
  </behavior>
  <action>
**Reference** (RESEARCH.md §5 + §6):

Edit `frontend/src/components/search/SearchResultCard.tsx`. Two changes:

**1. Imports:**

- Line 5: Add `Table2` to the lucide imports (mirror `RecordTypeBadge.tsx:2`).
- Remove `ImageOff` from the imports after the replacement (run a local grep to verify it has no other usages in the file).

**2. Replace the table branch of the thumbnail block (lines 309-330):**

```tsx
<div className="hidden md:flex md:items-start">
  <div className="size-[160px] shrink-0 overflow-hidden rounded-lg border border-border/40">
    {isTable ? (
      <div
        className="flex size-[160px] flex-col items-center justify-center gap-2 bg-gradient-to-br from-orange-100 to-orange-200 text-orange-900 dark:from-orange-950/40 dark:to-orange-900/30 dark:text-orange-200"
        role="img"
        aria-label={
          properties.column_count
            ? `Table with ${properties.feature_count ?? 0} rows and ${properties.column_count} columns`
            : `Table with ${properties.feature_count ?? 0} rows`
        }
      >
        <Table2 className="h-10 w-10 opacity-80" aria-hidden="true" />
        <span className="text-xs font-medium tabular-nums">
          {properties.feature_count ?? 0} rows
          {properties.column_count ? ` · ${properties.column_count} cols` : ''}
        </span>
      </div>
    ) : quicklookSrc ? (
      // ... existing quicklook branch unchanged ...
    ) : qlLoading ? (
      // ... existing loading branch unchanged ...
    ) : (
      // ... existing BBoxPreview fallback unchanged ...
    )}
  </div>
</div>
```

Adjust the exact JSX structure to match the surrounding file's indentation and the actual shape of `properties` (import the type from `types/api.ts` or wherever it lives in this component).

**Constraints:**
- Keep `size-[160px]`, `rounded-lg`, `border border-border/40`, `overflow-hidden` untouched on the outer container
- Use ONLY Tailwind utility classes — no new CSS files, no inline `style={{}}` except where the file already uses them for map positioning
- The gradient MUST use the orange token family (matches `status-colors.ts:59`). Do NOT invent new colors.
- Row count MUST render even if `column_count` is null or 0 — the `·` separator and cols span only appear when `column_count > 0`
- Respect dark mode (the dark: variants in the gradient)
- Add `role="img"` + `aria-label` for accessibility (this is decorative-meaningful content, not a pure icon)

**Test updates:**

Edit `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` (lines 305-337):

1. Remove any `ImageOff` assertions (check for `getByRole('img', { name: /image.*off/i })` or class-based queries).
2. Add assertions for `Table2` icon presence. The recommended query is by `data-testid` — add `data-testid="table-thumbnail-icon"` to the `Table2` element in the component, then `getByTestId('table-thumbnail-icon')`. If the project convention avoids testids, use `getByRole('img', { name: /table/i })`.
3. Assert row count text: `expect(screen.getByText(/29 rows/i)).toBeInTheDocument()`.
4. Add a case with `column_count: 5` — assert `/5 cols/i` is in the tile.
5. Add a case with `column_count: null` — assert `5 cols` is NOT present.

Follow existing mock fixture patterns in the test file. Use the same `createMockTableRecord` or equivalent factory if present.
  </action>
  <verify>
    <automated>cd frontend && npm test -- SearchResultCard --run</automated>
  </verify>
  <done>
`SearchResultCard.test.tsx` passes with updated table assertions. The rendered table card shows an orange gradient tile with Table2 icon and row/col count overlay. `ImageOff` import is removed from `SearchResultCard.tsx`. No regressions in vector or raster card rendering.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 5: Duplicate detection (409 Conflict) for ArcGIS service registration</name>
  <files>
    backend/app/services/router.py
    backend/app/services/arcgis.py
    backend/tests/test_services_endpoints.py
    frontend/src/components/import/ServiceUrlForm.tsx
    frontend/src/api/client.ts
  </files>
  <behavior>
- **test_preview_rejects_duplicate_arcgis**: Create an existing Dataset with `source_url='.../FeatureServer/0'`, `source_format='arcgis_featureserver'`, `created_by=user_a`. Call `POST /services/preview/` with the same URL as user_a. Response is HTTP 409 with a body `{detail: {code: "duplicate_source", message: ..., existing_dataset_id: <str>, existing_title: <str>}}`.
- **test_preview_allows_different_layer_same_service**: Create an existing Dataset with `source_url='.../FeatureServer/0'`. Call preview with `.../FeatureServer/1`. Response is NOT 409 — it proceeds normally (the test can mock out the actual ogrinfo call and only assert status != 409).
- **test_preview_allows_same_url_different_user**: Create an existing Dataset with `source_url='.../FeatureServer/0'` owned by user_a. Call preview as user_b. Response is NOT 409 — the dedup key includes `created_by`.
- **test_preview_allows_different_service_format**: (Optional, low value but cheap) Create an existing WFS dataset. Call preview with an ArcGIS URL that happens to match. Response is NOT 409 — different `source_format`.
- **test_normalize_arcgis_url_unpacking**: If `normalize_arcgis_url` is used for comparison, add a unit test ensuring the tuple is unpacked correctly (guards against the bug RESEARCH.md §Gotcha 10 flagged).
  </behavior>
  <action>
**Reference:** RESEARCH.md §1 + Gotchas 3 and 10.

**Step 1 — Backend duplicate detection** (`backend/app/services/router.py`):

Locate `preview_service_layer` (lines 212-395). Inject a duplicate check right after SSRF validation (around line 243) and BEFORE the GDAL source building (around line 245):

```python
# Duplicate source detection — refuse if (source_url, source_format, created_by) match
# Must match how ingest_service stores source_url — it uses _enrich_source_url to add the layer suffix.
# Preview time may have the unenriched URL, so reconcile both forms.
from app.services.arcgis import normalize_arcgis_url  # already imported? verify
from app.ingest.tasks import _enrich_source_url  # import at module level

# Derive the source_format from request.service_type
source_format = _service_type_to_source_format(request.service_type)  # add helper if missing

# Normalize the URL to the same form that create_dataset would store
try:
    base_url, layer_id = normalize_arcgis_url(request.url)
    # If request.url already includes a layer suffix, normalize_arcgis_url extracts it.
    # If the caller passed a layer_id separately in the request, use that instead.
    effective_layer_id = request.layer_id if getattr(request, "layer_id", None) is not None else layer_id
    if effective_layer_id is not None:
        enriched_url = _enrich_source_url(base_url, effective_layer_id)
    else:
        enriched_url = base_url
except Exception:
    # If normalization fails, fall back to the raw URL
    enriched_url = request.url

from app.datasets.models import Dataset, Record
existing_stmt = (
    select(Dataset.id, Record.title)
    .join(Record, Dataset.record_id == Record.id)
    .where(
        Dataset.source_url == enriched_url,
        Dataset.source_format == source_format,
        Record.created_by == user.id,
    )
    .limit(1)
)
existing = (await db.execute(existing_stmt)).first()
if existing:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "duplicate_source",
            "message": (
                f"A dataset from this source URL is already registered "
                f"(existing: '{existing.title}'). If you intended to re-import, "
                f"delete the existing dataset first or register a different layer."
            ),
            "existing_dataset_id": str(existing.id),
            "existing_title": existing.title,
        },
    )
```

Add the `_service_type_to_source_format` helper near the module top:

```python
_SERVICE_TYPE_TO_SOURCE_FORMAT = {
    "arcgis_featureserver": "arcgis_featureserver",
    "arcgis_mapserver": "arcgis_mapserver",
    "wfs": "wfs",
    # add other service types as needed
}

def _service_type_to_source_format(service_type: str) -> str:
    return _SERVICE_TYPE_TO_SOURCE_FORMAT.get(service_type, service_type)
```

**Critical:** The URL normalization MUST match how `_finalize_ingest → create_dataset` stores the URL (RESEARCH.md Gotcha 3). If the research's line reference (`tasks.py:412-416`) is wrong or the function is elsewhere, grep for `_enrich_source_url` and find the actual definition. DO NOT guess — a mismatch here causes silent false negatives.

**Step 2 — Frontend 409 handling** (`frontend/src/api/client.ts` + `frontend/src/components/import/ServiceUrlForm.tsx`):

Update `apiFetch` error handling to preserve the structured body instead of JSON-stringifying it:

```typescript
// frontend/src/api/client.ts around line 126-137
if (!response.ok) {
  let detail: string | Record<string, unknown> = response.statusText;
  let detailRaw: unknown = null;
  try {
    const body = await response.json();
    if (body.detail !== undefined) {
      detail = body.detail;
      detailRaw = body.detail;
    }
  } catch {
    /* body not JSON */
  }

  const message = typeof detail === 'string' ? detail : (
    (detail as { message?: string })?.message ?? JSON.stringify(detail)
  );
  const err = new ApiError(translateError(message), response.status);
  // Preserve the structured body for callers that want to inspect it
  (err as ApiError & { body?: unknown }).body = detailRaw;
  throw err;
}
```

If `ApiError` is defined elsewhere, add a `body?: unknown` field to its type. Update the ApiError class in `frontend/src/api/client.ts` (or wherever it lives):

```typescript
export class ApiError extends Error {
  status: number;
  body?: unknown;
  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}
```

Then update `frontend/src/components/import/ServiceUrlForm.tsx` — this is the component that handles the ArcGIS import flow (confirmed, not `ServiceImportModal`). The file already imports `ApiError` from `@/api/client` (line 4) and `toast` from `sonner` (line 3), so no new imports are needed for the structured body handling. The 409 handler integrates into the existing `catch` block inside `handleLayerSelect` (around lines 93-98), which today reads:

```typescript
} catch (err) {
  const msg = err instanceof ApiError ? err.message : t('serviceUrl.previewFailed');
  setError(msg);
  setStep('layer-select');
  toast.error(msg);
}
```

Replace that block with:

```typescript
} catch (err) {
  // 409 duplicate_source has structured body — surface the existing dataset
  if (err instanceof ApiError && err.status === 409) {
    const body = err.body as
      | { code?: string; existing_dataset_id?: string; existing_title?: string }
      | undefined;
    if (body?.code === 'duplicate_source' && body.existing_dataset_id) {
      const title = body.existing_title ?? 'Unknown dataset';
      const msg = `Already registered: "${title}"`;
      setError(msg);
      setStep('layer-select');
      toast.error(msg, {
        action: {
          label: 'View existing',
          onClick: () => {
            window.location.href = `/datasets/${body.existing_dataset_id}`;
          },
        },
      });
      return;
    }
  }
  // Fallback: existing behavior
  const msg = err instanceof ApiError ? err.message : t('serviceUrl.previewFailed');
  setError(msg);
  setStep('layer-select');
  toast.error(msg);
}
```

Notes:
- Preserve the existing `setError` + `setStep('layer-select')` pattern so the UI returns to the layer picker with an inline error AND a toast action.
- Use `window.location.href` for navigation because this file does not currently import `useNavigate` from react-router. Adding a new router import is out of scope; a hard navigation is acceptable since the user is leaving the import flow anyway. If the file already has a router hook in the future, swap it in.
- Do NOT introduce i18n keys for the duplicate message — the dataset title is user-facing data, and adding new `import` namespace keys is out of scope for this quick task. A hard-coded string is acceptable here.

The 409 from `previewServiceLayer` is caught inside `handleLayerSelect` (not `handleConnect`), because the backend duplicate check in Task 5 Step 1 fires in `preview_service_layer`, not in `probe_service`.

**Step 3 — Tests:**

Add all tests listed in `<behavior>` to `backend/tests/test_services_endpoints.py`. Use existing fixtures from `backend/tests/conftest.py` and `backend/tests/factories.py` — DO NOT create new mock patterns if existing ones work. Mock the ArcGIS probe call (HTTP) so the tests don't require network.

Frontend: If `frontend/src/components/import/__tests__/ServiceUrlForm.test.tsx` exists (check `frontend/src/components/import/__tests__/`), add a case for the 409 handler. If not, skip the frontend test — the behavior is UX polish and the manual smoke test in Task 6 will cover it.
  </action>
  <verify>
    <automated>docker compose exec -T api uv run pytest backend/tests/test_services_endpoints.py -v --tb=short -x -k "duplicate or preview_allows"</automated>
  </verify>
  <done>
All four (or five) new duplicate-detection backend tests pass. Existing `test_services_endpoints.py` tests still pass (no regression). The 409 response body structure matches the spec in `<behavior>`. Frontend `ApiError` exposes `body` field. `ServiceUrlForm.tsx` `handleLayerSelect` catch block handles 409 gracefully with a toast linking to the existing dataset (verified manually in Task 6). URL normalization correctly distinguishes `.../FeatureServer/0` from `.../FeatureServer/1`.
  </done>
</task>

<task type="auto">
  <name>Task 6: Manual smoke test + $geolens-ship CI gate + commit</name>
  <files>
    .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-SUMMARY.md
  </files>
  <action>
**Sub-task 6a — Manual smoke test** (5 min):

Start the dev stack (`docker compose up -d`). Verify end-to-end:

1. **Duplicate detection:** Attempt to re-register the same ArcGIS FeatureServer URL that Bulletin came from. Confirm the UI shows a readable error (not a JSON blob) and the backend returns 409. Screenshot if convenient.
2. **Thumbnail tile:** Navigate to `/search?record_type=table`. Confirm the Bulletin cards render the orange gradient + Table2 icon + "29 rows" label. Screenshot.
3. **row_count in API:** `curl -sS "http://localhost:8080/api/collections/datasets/items?record_type=table&limit=1" | jq '.features[0].properties | {feature_count, row_count, column_count, formats}'`. Confirm `row_count` equals `feature_count` and `formats` does NOT include shapefile.
4. **Quality score:** Navigate to a Bulletin dataset detail page. Confirm `geometry_validity` and `crs_defined` are either hidden or shown as "N/A" (depending on the frontend quality rendering). Note: existing Bulletin records will still show old scores (fix-forward policy — no backfill).
5. **Column info:** If Wave 0 Gate A indicated a backend fix was needed, re-register ONE of the ArcGIS tables (delete the old record first, then re-register). Confirm the new record has populated `column_info` (via API or UI).
6. **307 redirect:** If Wave 0 Gate B found a reproducible 307, navigate to the affected page and confirm DevTools shows 0 307s. Otherwise note "not reproducible" in SUMMARY.

If any smoke test FAILS, fix before proceeding to the ship gate. Smoke failures are blocking — they mean the code change didn't deliver the promised behavior.

**Sub-task 6b — Ship gate** (10-15 min):

Invoke the `$geolens-ship` skill (read `.agents/skills/geolens-ship/SKILL.md` if you haven't already). The skill will:
- Read the current CI workflow from `.github/workflows/ci.yml`
- Run the exact gate set in repo order: ruff check, ruff format --check, backend pytest, frontend locale parity, frontend namespace validation, frontend lint, frontend typecheck, frontend tests with coverage, bandit, pip-audit

If the skill is unavailable, run the gates manually:

```bash
# Backend
cd backend
uv run ruff check .
uv run ruff format --check .
docker compose exec -T api uv run pytest tests/ -v -m "not perf" --tb=short

# Frontend
cd ../frontend
npm run lint
npx tsc --noEmit
npm test -- --run
```

Fix any failures conservatively (see skill's `<fix_policy>`). Do NOT weaken tests to make them pass. Do NOT rewrite large subsystems.

If a gate fails and the failure is clearly unrelated to this task's changes (e.g., a flaky test, a pre-existing lint warning), document it in SUMMARY.md and proceed ONLY IF the failure does not gate CI.

**Sub-task 6c — Write SUMMARY.md:**

Create `.planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-SUMMARY.md` with the following structure (YAML frontmatter at the top, then the body sections below):

**Frontmatter fields:** `name: 260408-iny Summary`, `description: Table data type enhancement pass — delivery summary`, `type: quick-task-summary`.

**Body:**

```markdown
# Quick Task 260408-iny: Table Data Type Enhancement — Summary

**Delivered:** YYYY-MM-DD
**Status:** [Verified | Needs Review]

## What Shipped

### Backend
- [x] Schema doc: `DatasetResponse.record_type` lists all 7 valid values
- [x] Quality scoring: tables skip geometry/CRS dimensions, re-normalized weights
- [x] OGC formats: tables get csv + gpkg [+ geojson if applicable]
- [x] `row_count` alias + `column_count` in OGC Records response
- [x] Column info fix: [describe Wave 0 case + fix applied, OR "fallback only"]
- [x] Duplicate detection: 409 Conflict on ArcGIS preview when (source_url, source_format, created_by) matches

### Frontend
- [x] Styled orange-gradient Table2 thumbnail for table cards (with row/col count overlay)
- [x] `ApiError.body` preserves structured 409 payload
- [x] `ServiceUrlForm.tsx` shows actionable error for duplicate registrations
- [x] 307 redirect: [fixed at file:line | not reproducible]

### Tests
- [x] `test_compute_quality_score_table_record` (new)
- [x] `test_table_record_has_row_count_alias` (new)
- [x] `test_table_record_has_column_count` (new)
- [x] `test_record_has_formats_list` (updated for table branch)
- [x] `test_preview_rejects_duplicate_arcgis` (new)
- [x] `test_preview_allows_different_layer_same_service` (new)
- [x] `test_preview_allows_same_url_different_user` (new)
- [x] `test_arcgis_table_ingest_populates_column_info` (new, if Wave 0 required a code fix)
- [x] `SearchResultCard.test.tsx` (updated table card assertions)

## Wave 0 Diagnostics
See `260408-iny-DIAGNOSTICS.md`:
- **Gate A (column_info):** [Case N — summary]
- **Gate B (307 redirect):** [reproducible at file:line | not reproducible]
- **Gate C (collections/items for tables):** [works | doesn't work]

## Ship Gate
- [x] `uv run ruff check .` — pass
- [x] `uv run ruff format --check .` — pass
- [x] backend pytest — pass (N new tests added)
- [x] frontend lint — pass
- [x] frontend typecheck — pass
- [x] frontend test — pass

## Not Done / Deferred
- Existing 3 Bulletin duplicates NOT auto-deleted (user will inspect)
- Existing tables retain inflated quality scores (fix-forward policy — no backfill)
- Quality score UI may need a "recompute" button (out of scope — flagged as follow-up)
- [any items from Wave 0 that were skipped — e.g., "307 redirect skipped per DIAGNOSTICS.md Gate B"]

## Follow-ups
- [ ] Admin manually deletes 3 Bulletin duplicates after reviewing
- [ ] Consider a `/api/datasets/{id}/recompute-quality` endpoint (future milestone)
- [ ] [any 307-related items if skipped]

## Files Changed
[Run `git diff --stat` and paste the output]
```

**Sub-task 6d — Commit:**

Follow the repo's commit convention (conventional commits, no AI/Bot attribution per global CLAUDE.md). Suggested:

```bash
git add backend/ frontend/ .planning/quick/260408-iny-review-the-table-data-type-why-are-there/
git commit -m "feat(tables): full enhancement pass for table record_type

- Add 409 duplicate detection for ArcGIS service registration (source_url + format + user)
- Skip geometry_validity and crs_defined from quality score for tables
- Strip shapefile from OGC formats list for tables; add row_count alias and column_count field
- Replace ImageOff placeholder with styled Table2 gradient tile in SearchResultCard
- Populate column_info for ArcGIS table ingests (diagnostics in quick/260408-iny-DIAGNOSTICS.md)
- [307 redirect fix or 'investigation only — not reproducible']
- Update DatasetResponse.record_type description to enumerate all 7 valid values

Tests:
- test_compute_quality_score_table_record
- test_table_record_has_row_count_alias
- test_table_record_has_column_count
- test_preview_rejects_duplicate_arcgis
- test_preview_allows_different_layer_same_service
- test_preview_allows_same_url_different_user
- test_arcgis_table_ingest_populates_column_info
- SearchResultCard.test.tsx table-card assertions

Quick task: 260408-iny"
```

DO NOT push unless the user asks.
  </action>
  <verify>
    <automated>test -f .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-SUMMARY.md && git log -1 --format="%s" | grep -q "260408-iny\|table"</automated>
  </verify>
  <done>
Manual smoke test passes for all 6 checkpoints (or documents why one is skipped). `$geolens-ship` gates (or manual equivalent) are green — ruff, pytest, frontend lint, typecheck, and tests all pass. SUMMARY.md exists and accurately reflects delivery state. A single commit exists on the current branch with a descriptive conventional-commit message referencing the quick task id. No push has happened. User can review before merge.
  </done>
</task>

</tasks>

<verification>
**Plan-level success criteria** — use these to verify the entire task delivered, not just individual subtasks:

1. **Diagnostics captured:** `260408-iny-DIAGNOSTICS.md` exists with verdicts for all three Wave 0 gates (column_info, 307, collections/items).
2. **No shapefile for tables:** `curl .../api/collections/datasets/items?record_type=table` returns OGC records whose `formats` array contains NEITHER `application/x-shapefile` NOR any geometry-specific format not listed in `_TABLE_FORMAT_MEDIA`.
3. **row_count matches feature_count for tables:** Same curl — every record has `row_count == feature_count` and `row_count` is NOT present on non-table records.
4. **column_count populated:** Same curl — `column_count` is present for any table with non-empty column_info (initially may be null for the 3 Bulletin duplicates if column_info remains empty; that's expected until re-import).
5. **Duplicate detection:** Attempting to re-register the Bulletin source URL as admin returns HTTP 409 with structured body containing `existing_dataset_id`.
6. **Different layer allowed:** Registering `.../FeatureServer/1` when `.../FeatureServer/0` exists does NOT 409.
7. **Quality scoring correct for tables:** `compute_quality_score` called with a table dataset returns a dict whose `overall` is the re-normalized metadata+attribute average. No geometry_validity or crs_defined scores inflating the average.
8. **Thumbnail tile visible:** Navigating to `/search?record_type=table` in the browser shows orange gradient tiles with Table2 icon and row-count label (no gray ImageOff).
9. **Schema doc updated:** `curl .../api/openapi.json | jq '.components.schemas.DatasetResponse.properties.record_type.description'` lists all 7 valid values.
10. **307 handling:** Either the reproducible 307 is fixed (DevTools confirms 0 307s on dataset detail load) or SUMMARY.md documents it as non-reproducible.
11. **Ship gate green:** `uv run ruff check .`, `uv run ruff format --check .`, backend pytest, frontend lint, typecheck, tests — all pass locally with no skipped gates.
12. **Frontend 409 UX:** `ServiceUrlForm.tsx` displays a human-readable error with a "View existing" toast action (not a raw `{"detail": {...}}` JSON blob) when a duplicate is attempted.
</verification>

<success_criteria>
Quick task 260408-iny is complete when:

- [ ] All 6 tasks in this plan are done
- [ ] All 12 plan-level verification items pass
- [ ] `260408-iny-DIAGNOSTICS.md` exists with Wave 0 findings
- [ ] `260408-iny-SUMMARY.md` exists with delivery summary and pass/fail status
- [ ] A single commit on the current branch contains all changes (squashed or atomic per repo convention)
- [ ] `$geolens-ship` (or manual CI-parity equivalent) is green
- [ ] No speculative fixes shipped (307 fix only if reproducible, column_info fix based on confirmed root cause)
- [ ] The 3 existing Bulletin duplicates are NOT auto-deleted (user data sacrosanct)
- [ ] Quality scores are NOT backfilled (fix-forward policy)
- [ ] No changes outside the scope listed in CONTEXT.md `<decisions>` (no map/collection/service changes, no FEATURES.md/README updates, no DataTab empty state)
</success_criteria>

<output>
After completion, create:
- `.planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md` (Wave 0 output, during Task 1)
- `.planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-SUMMARY.md` (during Task 6)

Then commit on the current branch. Do not push.
</output>

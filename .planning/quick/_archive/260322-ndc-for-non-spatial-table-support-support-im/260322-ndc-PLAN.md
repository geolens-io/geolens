---
phase: quick-260322-ndc
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/ingest/schemas.py
  - backend/app/ingest/ogr.py
  - backend/app/ingest/tasks.py
  - backend/app/ingest/metadata.py
  - backend/app/ingest/router.py
  - frontend/src/types/api.ts
  - frontend/src/components/import/ImportPreview.tsx
  - frontend/src/components/import/ImportMetadataForm.tsx
  - frontend/src/components/import/BulkReviewList.tsx
autonomous: true
requirements: [NDC-01, NDC-02, NDC-03]

must_haves:
  truths:
    - "CSV/XLSX with lat/lng columns auto-detected and imported as spatial point datasets"
    - "CSV/XLSX with WKT columns auto-detected and imported as spatial datasets"
    - "User can override auto-detected geometry columns in the upload form"
    - "XLSX with lat/lng uses post-import ST_MakePoint (GDAL XLSX driver lacks X/Y open options)"
    - "Files with no geometry columns import as non-spatial tables (record_type='table')"
  artifacts:
    - path: "backend/app/ingest/schemas.py"
      provides: "CommitRequest with x_column, y_column, geom_column; PreviewResponse with detected_geometry_columns"
    - path: "backend/app/ingest/ogr.py"
      provides: "detect_geometry_columns function, broadened GEOM_POSSIBLE_NAMES for CSV"
    - path: "backend/app/ingest/tasks.py"
      provides: "Post-import geometry construction via ST_MakePoint and ST_GeomFromText"
    - path: "frontend/src/components/import/ImportMetadataForm.tsx"
      provides: "Geometry column override UI with x/y/WKT dropdowns"
  key_links:
    - from: "backend/app/ingest/router.py"
      to: "PreviewResponse.detected_geometry_columns"
      via: "detect_geometry_columns called in preview_file endpoint"
      pattern: "detect_geometry_columns"
    - from: "backend/app/ingest/tasks.py"
      to: "PostGIS ST_MakePoint / ST_GeomFromText"
      via: "construct_point_geometry / construct_wkt_geometry after ogr2ogr"
      pattern: "ST_MakePoint|ST_GeomFromText"
    - from: "frontend/src/components/import/ImportMetadataForm.tsx"
      to: "CommitImportRequest.x_column / y_column / geom_column"
      via: "geometry column dropdowns populate commit request"
      pattern: "x_column|y_column|geom_column"
---

<objective>
Add geometry column detection and override for CSV/XLSX imports, plus post-import geometry construction for XLSX files where GDAL lacks native X/Y open options.

Purpose: CSV/XLSX files with lat/lng or WKT columns should auto-detect as spatial and allow user override. XLSX geometry must use post-import SQL since the GDAL XLSX driver has no X_POSSIBLE_NAMES/Y_POSSIBLE_NAMES support. Files with no geometry columns import as non-spatial tables.

Output: Backend geometry detection + construction pipeline, frontend geometry column override UI, broadened CSV WKT detection.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260322-ndc-for-non-spatial-table-support-support-im/260322-ndc-CONTEXT.md
@.planning/quick/260322-ndc-for-non-spatial-table-support-support-im/260322-ndc-RESEARCH.md

<interfaces>
<!-- Key types and contracts the executor needs -->

From backend/app/ingest/schemas.py:
```python
class PreviewResponse(BaseModel):
    job_id: uuid.UUID
    source_filename: str | None
    columns: list[dict]
    crs: int | None
    geometry_type: str | None
    feature_count: int | None
    sample_rows: list[dict]
    layer_name: str
    layers: list[dict] | None = None

class CommitRequest(BaseModel):
    title: str
    summary: str | None = None
    visibility: str = "private"
    srid_override: int | None = None
    token: str | None = None
    temporal_start: str | None = None
    temporal_end: str | None = None
    compression: str | None = None
    resampling: str | None = None
    nodata_override: float | str | None = None
    layer_name: str | None = None
```

From backend/app/ingest/ogr.py:
```python
async def run_ogrinfo_preview(file_path: str, sample_limit: int = 5, layer_name: str | None = None) -> dict:
    # Returns: srid, geometry_type, layer_name, feature_count, columns, sample_rows, all_layers

async def run_ogr2ogr(file_path, table_name, db_conn_str, source_srid=None, geometry_type=None, layer_name=None):
    # CSV with geometry: passes -oo X_POSSIBLE_NAMES, Y_POSSIBLE_NAMES
    # Non-spatial: skips -nlt PROMOTE_TO_MULTI, GEOMETRY_NAME, SPATIAL_INDEX
```

From backend/app/ingest/tasks.py (ingest_file):
```python
# user_metadata access pattern:
um = job.user_metadata or {}
srid_override = um.get("srid_override")
layer_name = um.get("layer_name")
# has_geometry gates: clip_to_mercator_bounds, add_4326_column, quicklook
has_geometry = geometry_type is not None
# assumes_4326 list currently: .csv, .geojson, .json (missing .xlsx, .xls)
```

From backend/app/ingest/metadata.py:
```python
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
def _validate_table_name(table_name: str) -> None: ...
```

From frontend/src/types/api.ts:
```typescript
export interface FilePreviewResponse {
  job_id: string;
  source_filename: string | null;
  columns: { name: string; type: string }[];
  crs: number | null;
  geometry_type: string | null;
  feature_count: number | null;
  sample_rows: Record<string, unknown>[];
  layer_name: string;
  layers?: { name: string; feature_count: number; field_count: number }[] | null;
}

export interface CommitImportRequest {
  title: string;
  summary?: string | null;
  visibility?: string;
  srid_override?: number | null;
  token?: string;
  temporal_start?: string | null;
  temporal_end?: string | null;
  compression?: string | null;
  resampling?: string | null;
  nodata_override?: number | string | null;
  layer_name?: string;
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend — geometry column detection, CommitRequest extension, post-import construction</name>
  <files>
    backend/app/ingest/schemas.py
    backend/app/ingest/ogr.py
    backend/app/ingest/tasks.py
    backend/app/ingest/metadata.py
    backend/app/ingest/router.py
  </files>
  <action>
**1. Add geometry column auto-detection to `ogr.py`:**

Add a `detect_geometry_columns(columns: list[dict]) -> dict` function that pattern-matches column names:
```python
LAT_PATTERNS = {"lat", "latitude", "y", "lat_dd", "ycoord"}
LNG_PATTERNS = {"lon", "lng", "long", "longitude", "x", "lon_dd", "xcoord"}
WKT_PATTERNS = {"wkt", "geom", "geometry", "the_geom", "shape"}
```
Returns `{"x_column": str|None, "y_column": str|None, "wkt_column": str|None}`. Match is case-insensitive against `col["name"].lower()`.

**2. Broaden CSV WKT detection in `run_ogr2ogr`:**

In the CSV geometry section (line ~313), add `-oo GEOM_POSSIBLE_NAMES=WKT,wkt,geometry,geom,the_geom,shape` alongside existing X/Y open options. This makes CSV files with WKT-named columns auto-detect as spatial without user override.

**3. Extend `PreviewResponse` in `schemas.py`:**

Add `detected_geometry_columns: dict | None = None` field to `PreviewResponse`. This returns the auto-detection results to the frontend.

**4. Extend `CommitRequest` in `schemas.py`:**

Add three optional fields:
- `x_column: str | None = None`
- `y_column: str | None = None`
- `geom_column: str | None = None` (WKT column name)

**5. Wire detection into preview endpoint in `router.py`:**

In `preview_file`, after calling `run_ogrinfo_preview`, call `detect_geometry_columns(info["columns"])` and include result in the `PreviewResponse` as `detected_geometry_columns`. Import `detect_geometry_columns` from `ogr`.

**6. Add post-import geometry construction functions to `metadata.py`:**

Add two functions using the `_validate_table_name` and `_TABLE_NAME_RE` already in metadata.py:

`construct_point_geometry(session, table_name, x_column, y_column, srid=4326) -> int`:
- Validate table_name and column names against `_TABLE_NAME_RE`
- `ALTER TABLE data.{table_name} ADD COLUMN geom geometry(Point, {srid})`
- `UPDATE ... SET geom = ST_SetSRID(ST_MakePoint({x_column}::double precision, {y_column}::double precision), {srid}) WHERE {x_column} IS NOT NULL AND {y_column} IS NOT NULL`
- `CREATE INDEX idx_{table_name}_geom ON data.{table_name} USING GIST (geom)`
- Return rowcount

`construct_wkt_geometry(session, table_name, wkt_column, srid=4326) -> int`:
- Validate names
- Sample one row to detect geometry type: `SELECT GeometryType(ST_GeomFromText({wkt_column}, {srid})) FROM data.{table_name} WHERE {wkt_column} IS NOT NULL LIMIT 1`
- Fall back to "GEOMETRY" if no sample found
- ALTER TABLE, UPDATE SET geom = ST_GeomFromText, CREATE INDEX
- Return rowcount

**7. Wire geometry construction into `ingest_file` in `tasks.py`:**

After `run_ogr2ogr` and before clip/4326 steps (~line 145):

```python
x_column = um.get("x_column")
y_column = um.get("y_column")
geom_column = um.get("geom_column")

# Post-import geometry construction (for XLSX with lat/lng or WKT override)
if not has_geometry and x_column and y_column:
    from app.ingest.metadata import construct_point_geometry
    await construct_point_geometry(session, table_name, x_column, y_column)
    has_geometry = True
    geometry_type = "Point"
elif not has_geometry and geom_column:
    from app.ingest.metadata import construct_wkt_geometry
    await construct_wkt_geometry(session, table_name, geom_column)
    has_geometry = True
    # Re-detect geometry type from constructed column
    result = await session.execute(text(
        f"SELECT GeometryType(geom) FROM data.{table_name} WHERE geom IS NOT NULL LIMIT 1"
    ))
    geometry_type = result.scalar_one_or_none() or "Geometry"
```

Also add `.xlsx` and `.xls` to the `assumes_4326` list (line ~118) so XLSX files with user-constructed geometry don't fail CRS validation:
```python
assumes_4326 = (
    lower_path.endswith(".csv")
    or lower_path.endswith(".geojson")
    or lower_path.endswith(".json")
    or lower_path.endswith(".xlsx")
    or lower_path.endswith(".xls")
)
```

**Important:** The `has_geometry` check at line 123 already short-circuits for non-spatial files (no CRS needed). The geometry construction step runs AFTER ogr2ogr but BEFORE clip/4326, so the constructed geometry column gets the same treatment as natively-detected geometry.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "
from app.ingest.ogr import detect_geometry_columns
cols = [{'name': 'latitude', 'type': 'Real'}, {'name': 'longitude', 'type': 'Real'}, {'name': 'name', 'type': 'String'}]
result = detect_geometry_columns(cols)
assert result['x_column'] == 'longitude', f'Expected longitude, got {result}'
assert result['y_column'] == 'latitude', f'Expected latitude, got {result}'
assert result['wkt_column'] is None
cols2 = [{'name': 'WKT', 'type': 'String'}, {'name': 'id', 'type': 'Integer'}]
result2 = detect_geometry_columns(cols2)
assert result2['wkt_column'] == 'WKT'
assert result2['x_column'] is None
print('All detection tests passed')
" && python -c "
from app.ingest.schemas import CommitRequest, PreviewResponse
cr = CommitRequest(title='test', x_column='lon', y_column='lat', geom_column='wkt')
assert cr.x_column == 'lon'
pr = PreviewResponse(job_id='00000000-0000-0000-0000-000000000000', source_filename='t.csv', columns=[], crs=None, geometry_type=None, feature_count=0, sample_rows=[], layer_name='t', detected_geometry_columns={'x_column': 'lon'})
assert pr.detected_geometry_columns is not None
print('Schema tests passed')
"</automated>
  </verify>
  <done>
    - detect_geometry_columns returns correct x/y/wkt column matches from column list
    - CommitRequest accepts x_column, y_column, geom_column
    - PreviewResponse includes detected_geometry_columns
    - Preview endpoint returns detected geometry columns
    - Post-import ST_MakePoint and ST_GeomFromText functions exist in metadata.py
    - ingest_file constructs geometry when x_column/y_column or geom_column specified
    - CSV ogr2ogr passes broadened GEOM_POSSIBLE_NAMES for WKT detection
    - XLSX/XLS added to assumes_4326 list
  </done>
</task>

<task type="auto">
  <name>Task 2: Frontend — geometry column override UI and type updates</name>
  <files>
    frontend/src/types/api.ts
    frontend/src/components/import/ImportPreview.tsx
    frontend/src/components/import/ImportMetadataForm.tsx
    frontend/src/components/import/BulkReviewList.tsx
  </files>
  <action>
**1. Update `FilePreviewResponse` in `frontend/src/types/api.ts`:**

Add `detected_geometry_columns?: { x_column: string | null; y_column: string | null; wkt_column: string | null } | null` field.

**2. Update `CommitImportRequest` in `frontend/src/types/api.ts`:**

Add optional fields: `x_column?: string | null`, `y_column?: string | null`, `geom_column?: string | null`.

**3. Update `ImportPreview.tsx`:**

In the vector preview section, when `preview.geometry_type` is null but `preview.detected_geometry_columns` has values, show an info badge: "Geometry columns detected" with the column names. When geometry_type is null and no columns detected, show "Non-spatial table" badge.

**4. Update `ImportMetadataForm.tsx`:**

Add new props: `previewColumns?: { name: string; type: string }[]` and `detectedGeometryColumns?: { x_column: string | null; y_column: string | null; wkt_column: string | null } | null`.

When `detectedGeometryColumns` has values OR when there are columns available AND it's not a raster file, show a "Geometry Columns" section with:

- A mode selector: "Auto-detected" / "Manual override" / "Import as non-spatial"
  - Default to "Auto-detected" if `detectedGeometryColumns` has matches, "Import as non-spatial" otherwise
- When mode is auto-detected or manual override, show:
  - Two dropdown selects for X (longitude) and Y (latitude) columns, populated from `previewColumns` filtered to numeric types (Real, Integer, Integer64)
  - OR one dropdown for WKT column, populated from `previewColumns` filtered to String type
  - A toggle/radio between "Lat/Lng" and "WKT" geometry mode
- Pre-populate dropdowns from `detectedGeometryColumns` values
- When "Import as non-spatial" selected, clear x_column/y_column/geom_column from commit request

In `handleSubmit`, add `x_column`, `y_column`, `geom_column` to the `CommitImportRequest` based on selected mode and dropdown values.

**5. Update `BulkReviewList.tsx`:**

Pass `previewColumns` and `detectedGeometryColumns` props through to `ImportMetadataForm` when the preview is a FilePreviewResponse (not raster). Extract from `entry.previewData`:
```tsx
previewColumns={isFilePreview(entry.previewData) ? (entry.previewData as FilePreviewResponse).columns : undefined}
detectedGeometryColumns={isFilePreview(entry.previewData) ? (entry.previewData as FilePreviewResponse).detected_geometry_columns : undefined}
```

Add these props in both the normal preview and commit-failed preview blocks.

**UI design notes:**
- Use existing `Label`, `select` (native HTML select matching the sheet picker pattern in BulkReviewList), and `Badge` components
- Group geometry controls in a bordered section with heading "Geometry Columns" only when columns are available
- Keep the UI compact — it should not dominate the metadata form
- Use i18n keys under `import` namespace: `metadata.geometryColumns`, `metadata.geometryMode`, `metadata.autoDetected`, `metadata.manualOverride`, `metadata.nonSpatial`, `metadata.xColumn`, `metadata.yColumn`, `metadata.wktColumn`, `metadata.latLng`, `metadata.wkt`
- Add the i18n keys to all 4 locale files in `frontend/src/i18n/locales/` (en, es, fr, de)
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - FilePreviewResponse includes detected_geometry_columns field
    - CommitImportRequest includes x_column, y_column, geom_column fields
    - ImportPreview shows geometry detection status for non-spatial files
    - ImportMetadataForm shows geometry column override UI when columns available
    - BulkReviewList passes columns and detection data through to form
    - TypeScript compiles without errors
    - i18n keys added to all 4 locale files
  </done>
</task>

</tasks>

<verification>
1. Upload a CSV with lat/lng columns — preview should show detected geometry columns, commit should create spatial dataset with Point geometry
2. Upload an XLSX with latitude/longitude columns — preview should detect columns, commit should construct geometry via ST_MakePoint, dataset should be spatial
3. Upload a CSV with a WKT column — should auto-detect and import as spatial
4. Upload a CSV/XLSX with no geometry columns — should import as non-spatial table (record_type='table')
5. Override auto-detected columns to different columns or "non-spatial" — should respect override
6. TypeScript compiles, backend schema validation passes
</verification>

<success_criteria>
- CSV with lat/lng auto-imports as spatial (existing behavior preserved + broadened WKT detection)
- XLSX with lat/lng columns detected in preview and constructed as Point geometry post-import
- User can override geometry column detection in upload form
- Non-spatial tables import correctly with record_type='table'
- No regressions in existing import flows (shapefile, GeoJSON, raster)
</success_criteria>

<output>
After completion, create `.planning/quick/260322-ndc-for-non-spatial-table-support-support-im/260322-ndc-SUMMARY.md`
</output>

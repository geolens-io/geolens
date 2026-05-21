# Quick Task 260322-ndc: Non-spatial table support - Research

**Researched:** 2026-03-22
**Domain:** GDAL CSV/XLSX geometry detection, non-spatial PostGIS tables
**Confidence:** HIGH

## Summary

The existing ingestion pipeline already handles non-spatial tables well: `geometry_type is None` gates clip/4326/quicklook steps, `extract_metadata` detects missing geometry columns, and `create_dataset` sets `record_type='table'` when `geometry_type is None`. The primary gap is **geometry column override for XLSX files** -- the GDAL XLSX driver does NOT support `X_POSSIBLE_NAMES`/`Y_POSSIBLE_NAMES` open options (verified against GDAL in the Docker container). For XLSX with lat/lng columns, geometry must be constructed via post-import SQL (`ST_MakePoint`).

**Primary recommendation:** Use GDAL open options for CSV geometry detection (already working), add post-import SQL `ST_MakePoint` path for XLSX geometry construction, and extend `CommitRequest` with optional `x_column`/`y_column`/`geom_column` fields for user override.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Auto-detect lat/lng, x/y, or WKT columns by name pattern matching
- Allow user to override detected geometry columns via the upload form if auto-detection is wrong
- If no geometry columns detected, import as non-spatial table (record_type='table')
- Non-spatial tables appear as full catalog entries with record_type='table'
- They show in catalog/search with record detail page and attribute table
- No map preview, no tile endpoints -- gracefully skip map-related features
- No separate section needed -- they coexist with spatial datasets in the catalog
- Use GDAL/ogr2ogr for both CSV and XLSX (GDAL has XLSX driver)
- Keep unified ingestion pipeline -- no separate pandas code path
- Geometry construction via ogr2ogr VRT wrapper or post-import SQL (ST_MakePoint from detected lat/lng columns)

### Claude's Discretion
- Implementation details of geometry column auto-detection logic
- Whether to use VRT wrapper or post-import SQL for XLSX lat/lng -> geometry
- Frontend UI design for geometry column mapping

### Deferred Ideas
- None specified
</user_constraints>

## Key Findings

### 1. GDAL CSV Driver - Geometry Detection (HIGH confidence)

The CSV driver supports these open options (verified against running GDAL instance):

| Open Option | Description |
|---|---|
| `X_POSSIBLE_NAMES` | Comma-separated list of possible lon/x column names |
| `Y_POSSIBLE_NAMES` | Comma-separated list of possible lat/y column names |
| `Z_POSSIBLE_NAMES` | Comma-separated list of possible elevation column names |
| `GEOM_POSSIBLE_NAMES` | Comma-separated list of possible WKT geometry column names (default: `WKT`) |
| `KEEP_GEOM_COLUMNS` | Whether to keep original x/y/geom columns as regular fields (default: YES) |

**Current code** (`ogr.py` line 313-321) already passes `X_POSSIBLE_NAMES=lon*,lng*,long*,x` and `Y_POSSIBLE_NAMES=lat*,y` for CSV files with geometry. This works correctly.

**WKT column detection:** The CSV driver auto-detects columns named `WKT` by default via `GEOM_POSSIBLE_NAMES`. To detect other column names like `geometry`, `geom`, `the_geom`, pass `-oo GEOM_POSSIBLE_NAMES=WKT,wkt,geometry,geom,the_geom`.

### 2. GDAL XLSX Driver - NO Geometry Open Options (HIGH confidence)

Verified from `ogrinfo --format XLSX` output. The XLSX driver only has two open options:

| Open Option | Description |
|---|---|
| `FIELD_TYPES` | AUTO or STRING (default: AUTO) |
| `HEADERS` | AUTO, FORCE, or DISABLE (default: AUTO) |

**No `X_POSSIBLE_NAMES`, `Y_POSSIBLE_NAMES`, or `GEOM_POSSIBLE_NAMES`.**

This means: for XLSX files with lat/lng columns, ogr2ogr will import them as regular numeric columns. Geometry must be constructed after import.

### 3. Non-Spatial Table Import (HIGH confidence)

When ogr2ogr imports a file with no geometry, the PostGIS table:
- Has **no `geom` column** at all (no geometry column created)
- Has `gid` (FID) plus all attribute columns
- Works perfectly with the existing `extract_metadata` function which checks `_table_has_geometry`

The existing pipeline (`tasks.py` lines 113-160) already handles this:
- `has_geometry = geometry_type is not None` -- gates all spatial operations
- `clip_to_mercator_bounds`, `add_4326_column`, and quicklook generation are all gated on `has_geometry`
- `create_dataset` (`service.py` line 160-161) sets `record_type = "table"` when `geometry_type is None`

### 4. Recommended Approach: Post-Import SQL for XLSX Geometry (HIGH confidence)

**Recommendation: Use post-import SQL rather than VRT wrapper.**

Reasons:
1. VRT wrapper requires creating a temporary `.vrt` XML file pointing to the XLSX, adding complexity
2. Post-import SQL is simpler: `ALTER TABLE ... ADD COLUMN geom geometry(Point, 4326); UPDATE ... SET geom = ST_SetSRID(ST_MakePoint(x_col, y_col), 4326)`
3. The pipeline already does post-import SQL operations (clip, add_4326_column, grant_reader)
4. Post-import SQL works identically for CSV user-override scenarios too

**Flow for XLSX with lat/lng:**
1. Import via ogr2ogr as non-spatial (regular numeric columns preserved)
2. If user specified `x_column`/`y_column`, run `ST_MakePoint` SQL to create geometry
3. Then run existing `clip_to_mercator_bounds` and `add_4326_column` steps

### 5. Integration Points

| Component | File | Current State | Change Needed |
|---|---|---|---|
| `run_ogr2ogr` | `backend/app/ingest/ogr.py` | CSV X/Y handled; XLSX not handled | Add WKT detection for CSV; no XLSX change needed |
| `ingest_file` task | `backend/app/ingest/tasks.py` | Gates spatial ops on `has_geometry` | Add post-import geometry construction step |
| `CommitRequest` | `backend/app/ingest/schemas.py` | Has `srid_override`, `layer_name` | Add `x_column`, `y_column`, `geom_column` |
| `PreviewResponse` | `backend/app/ingest/schemas.py` | Returns columns list | Add `detected_geometry_columns` field |
| `extract_metadata` | `backend/app/ingest/metadata.py` | Handles non-spatial already | No change needed |
| `create_dataset` | `backend/app/datasets/service.py` | Sets `record_type='table'` for no geom | No change needed |
| Record model | `backend/app/datasets/models.py` | `'table'` already in `chk_records_record_type` | No change needed |
| Frontend preview | `ImportPreview.tsx` | Shows columns/geometry type | Add geometry column mapping UI |
| Quicklook endpoint | `backend/app/datasets/router.py` line 652 | Returns 404 for non-vector/raster | Already handled (raises 404) |

### 6. Geometry Column Auto-Detection Logic

For the preview step, detect potential geometry columns from the column list returned by ogrinfo:

```python
# Pattern-based detection
LAT_PATTERNS = {"lat", "latitude", "y", "lat_dd", "ycoord"}
LNG_PATTERNS = {"lon", "lng", "long", "longitude", "x", "lon_dd", "xcoord"}
WKT_PATTERNS = {"wkt", "geom", "geometry", "the_geom", "shape"}

def detect_geometry_columns(columns: list[dict]) -> dict:
    """Detect potential geometry columns from column metadata."""
    col_names = {c["name"].lower(): c["name"] for c in columns}

    x_col = next((col_names[n] for n in LNG_PATTERNS if n in col_names), None)
    y_col = next((col_names[n] for n in LAT_PATTERNS if n in col_names), None)
    wkt_col = next((col_names[n] for n in WKT_PATTERNS if n in col_names), None)

    return {"x_column": x_col, "y_column": y_col, "wkt_column": wkt_col}
```

## Common Pitfalls

### Pitfall 1: XLSX Driver Assumes First Row is Headers
**What goes wrong:** XLSX files without headers get column names like `Field1`, `Field2`
**How to avoid:** The XLSX driver defaults `HEADERS=AUTO` which works for most files. If auto-detection fails, user can re-upload with `HEADERS=FORCE` or `HEADERS=DISABLE`.

### Pitfall 2: XLSX Column Type Auto-Detection
**What goes wrong:** Numeric columns formatted as text in Excel become String type, breaking `ST_MakePoint`
**How to avoid:** Cast columns to numeric in the post-import SQL: `CAST(x_col AS double precision)`

### Pitfall 3: CSV GEOM_POSSIBLE_NAMES Default
**What goes wrong:** CSV files with a column named `WKT` are auto-detected as spatial by GDAL, but columns named `geometry` or `geom` are not
**How to avoid:** Pass `-oo GEOM_POSSIBLE_NAMES=WKT,wkt,geometry,geom,the_geom,shape` to broaden WKT detection

### Pitfall 4: Empty Geometry Values
**What goes wrong:** Some rows have lat/lng but others have NULL, creating partial geometry
**How to avoid:** Use `WHERE x_col IS NOT NULL AND y_col IS NOT NULL` in the ST_MakePoint update, leave others as NULL geometry. Then check if ANY rows have geometry to decide `has_geometry`.

### Pitfall 5: assumes_4326 Check Missing XLSX
**What goes wrong:** Current code (`tasks.py` line 117-122) only adds `.csv`, `.geojson`, `.json` to `assumes_4326`. XLSX files with user-specified lat/lng would fail CRS validation.
**How to avoid:** Add `.xlsx` and `.xls` to the `assumes_4326` list, or better yet, skip CRS check entirely when geometry is user-constructed (it's always 4326 from ST_MakePoint).

## Code Examples

### Post-Import Geometry Construction (for XLSX lat/lng)

```python
async def construct_point_geometry(
    session: AsyncSession,
    table_name: str,
    x_column: str,
    y_column: str,
    srid: int = 4326,
) -> int:
    """Add geometry column from x/y coordinate columns.

    Returns count of rows with valid geometry.
    """
    _validate_table_name(table_name)
    # Validate column names against safe pattern
    if not _TABLE_NAME_RE.match(x_column) or not _TABLE_NAME_RE.match(y_column):
        raise ValueError("Invalid column name")

    await session.execute(text(
        f"ALTER TABLE data.{table_name} ADD COLUMN geom geometry(Point, {srid})"
    ))
    result = await session.execute(text(
        f"UPDATE data.{table_name} SET geom = ST_SetSRID("
        f"  ST_MakePoint({x_column}::double precision, {y_column}::double precision), "
        f"  {srid}) "
        f"WHERE {x_column} IS NOT NULL AND {y_column} IS NOT NULL"
    ))
    await session.execute(text(
        f"CREATE INDEX idx_{table_name}_geom ON data.{table_name} USING GIST (geom)"
    ))
    return result.rowcount
```

### WKT Geometry Construction

```python
async def construct_wkt_geometry(
    session: AsyncSession,
    table_name: str,
    wkt_column: str,
    srid: int = 4326,
) -> int:
    """Add geometry column from a WKT text column."""
    _validate_table_name(table_name)
    if not _TABLE_NAME_RE.match(wkt_column):
        raise ValueError("Invalid column name")

    # First pass: detect geometry type from sample
    sample = await session.execute(text(
        f"SELECT GeometryType(ST_GeomFromText({wkt_column}, {srid})) "
        f"FROM data.{table_name} WHERE {wkt_column} IS NOT NULL LIMIT 1"
    ))
    geom_type = sample.scalar_one_or_none() or "GEOMETRY"

    await session.execute(text(
        f"ALTER TABLE data.{table_name} ADD COLUMN geom geometry({geom_type}, {srid})"
    ))
    result = await session.execute(text(
        f"UPDATE data.{table_name} SET geom = ST_GeomFromText({wkt_column}, {srid}) "
        f"WHERE {wkt_column} IS NOT NULL"
    ))
    await session.execute(text(
        f"CREATE INDEX idx_{table_name}_geom ON data.{table_name} USING GIST (geom)"
    ))
    return result.rowcount
```

## Architecture Patterns

### Modified Ingest Pipeline Flow

```
Upload -> Preview (ogrinfo) -> [Detect geometry columns] -> Commit -> ogr2ogr
                                                                        |
                                                              [Post-import SQL if
                                                               user specified x/y
                                                               or WKT column]
                                                                        |
                                                              clip -> 4326 -> metadata
```

For CSV: GDAL handles lat/lng via `-oo X_POSSIBLE_NAMES` natively (existing behavior).
For CSV with WKT: GDAL handles via `-oo GEOM_POSSIBLE_NAMES` natively.
For XLSX with lat/lng: Post-import `ST_MakePoint` SQL.
For XLSX with WKT: Post-import `ST_GeomFromText` SQL.
For non-spatial (any format): No geometry construction, `record_type='table'`.

### CommitRequest Extension

```python
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
    # NEW: geometry column overrides
    x_column: str | None = None
    y_column: str | None = None
    geom_column: str | None = None  # WKT column name
```

## Sources

### Primary (HIGH confidence)
- GDAL CSV driver open options - verified via `ogrinfo --format CSV` in Docker container
- GDAL XLSX driver open options - verified via `ogrinfo --format XLSX` in Docker container
- Existing codebase: `backend/app/ingest/ogr.py`, `tasks.py`, `metadata.py`, `service.py`
- PostGIS `ST_MakePoint`, `ST_GeomFromText` - standard PostGIS functions

## Metadata

**Confidence breakdown:**
- GDAL driver capabilities: HIGH - verified against running instance
- Non-spatial pipeline: HIGH - code already handles this case
- Post-import SQL approach: HIGH - uses standard PostGIS functions
- Frontend changes: MEDIUM - pattern follows existing preview/commit flow but UI design is discretionary

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable GDAL/PostGIS APIs)

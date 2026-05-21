# Quick Task 260322-mb0: Excel/JSON Non-Spatial Ingestion - Research

**Researched:** 2026-03-22
**Domain:** GDAL/ogr2ogr Excel + JSON ingestion, FastAPI upload pipeline
**Confidence:** HIGH (verified against live Docker container)

## Summary

Excel (.xlsx/.xls) ingestion is fully supported by the GDAL installation in the Docker container -- both XLSX and XLS drivers are present and tested. Multi-sheet Excel files report each sheet as a separate layer in ogrinfo JSON output, with `geometryFields: []` for non-spatial sheets. The existing non-spatial pipeline (from 260322-hv0) handles `geometry_type=None` correctly. The main work is: (1) add `.xlsx`/`.xls` to allowed extensions and validation maps, (2) support multi-layer preview/selection for Excel, (3) pass selected layer name through ogr2ogr.

Plain JSON (arrays of objects, not GeoJSON) is NOT recognized by any GDAL driver. GDAL only handles GeoJSON-structured JSON. For non-GeoJSON JSON support, a pre-processing step is needed to convert JSON arrays into CSV or GeoJSON-with-null-geometry before passing to ogr2ogr. This adds complexity and is recommended as a separate follow-up.

**Primary recommendation:** Ship Excel support now (straightforward GDAL integration). Defer plain JSON ingestion to a follow-up task.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Excel: .xlsx and .xls via ogr2ogr (GDAL supports both natively via XLSX/XLS drivers)
- JSON: Plain JSON arrays/objects -- not GeoJSON (which is already supported as spatial)
- Leverage existing non-spatial pipeline (geometry_type=None path) from 260322-hv0

### Claude's Discretion
- ogr2ogr flags for Excel/JSON
- Sheet selection UX for multi-sheet Excel files
- JSON structure detection (array of objects, nested, etc.)
- Frontend changes for format-specific upload hints
</user_constraints>

## GDAL Driver Verification (Docker Container)

**Verified live** via `ogrinfo --formats` in the running `api` container:

| Driver | Status | Mode | Extensions |
|--------|--------|------|------------|
| XLSX | Available | rw+v | .xlsx, .xlsm |
| XLS | Available | ro | .xls |
| GeoJSON | Available | rw+v | .json, .geojson |

**Plain JSON (non-GeoJSON):** No GDAL driver exists. Testing confirmed:
```
ERROR 4: `/tmp/test_plain.json' not recognized as being in a supported file format.
```
GDAL's GeoJSON driver requires `FeatureCollection`/`Feature` structure. A plain `[{...}, {...}]` array fails.

## Excel Ingestion Findings (HIGH confidence)

### ogrinfo behavior with multi-sheet Excel

Tested with a 2-sheet XLSX file. Key observations:

1. **`ogrinfo -json -so file.xlsx`** (no layer specified) returns ALL sheets as separate layers:
   ```json
   { "layers": [
     { "name": "Sheet1", "geometryFields": [], "featureCount": 2, "fields": [...] },
     { "name": "Sheet2", "geometryFields": [], "featureCount": 2, "fields": [...] }
   ]}
   ```

2. **`ogrinfo -json -so file.xlsx SheetName`** returns only that sheet's metadata.

3. **`ogrinfo -json -features -limit N file.xlsx SheetName`** returns sample rows for a specific sheet.

4. **`geometryFields`** is an empty array `[]` for non-spatial sheets -- this means `geometry_type` will be `None` from `run_ogrinfo()`, which correctly triggers the non-spatial path.

5. **First row is treated as header** by default (GDAL XLSX driver default behavior).

### ogr2ogr layer selection

```bash
ogr2ogr -f PostgreSQL PG:... file.xlsx -nln data.tablename SheetName
```
Append the sheet/layer name as the last positional argument. This is the same pattern used for multi-layer GeoPackage and services.

### puremagic detection

- `.xlsx` detected as `.xlsx` -- add to `EXTENSION_CONTENT_MAP`
- `.xls` detected as `.xls` (Office BIFF format) -- add to `EXTENSION_CONTENT_MAP`
- puremagic may also detect `.xlsx` as `.docx`/`.pptx` since they share ZIP+OOXML structure; allow `.xlsx` and `.zip` in the content map

## Current Pipeline Analysis

### Files that need changes

| File | What | Change Needed |
|------|------|---------------|
| `backend/app/config.py:30` | `upload_allowed_extensions` | Add `.xlsx,.xls` |
| `backend/app/ingest/validation.py:22-29` | `EXTENSION_CONTENT_MAP` | Add `.xlsx` and `.xls` entries |
| `backend/app/ingest/validation.py:80` | Text content check | No change (xlsx/xls are binary) |
| `backend/app/ingest/ogr.py:84-149` | `run_ogrinfo()` | Returns only `layers[0]` -- needs multi-layer awareness for Excel |
| `backend/app/ingest/ogr.py:152-226` | `run_ogrinfo_preview()` | Same: returns only first layer |
| `backend/app/ingest/ogr.py:229-295` | `run_ogr2ogr()` | Needs to accept optional `layer_name` arg and append to command |
| `backend/app/ingest/router.py:386-397` | Preview endpoint | Needs to return available layers for multi-sheet Excel |
| `backend/app/ingest/schemas.py:15-23` | `PreviewResponse` | Add `layers` list for multi-sheet support |
| `backend/app/ingest/tasks.py:105-107` | `ingest_file` | Needs to pass `layer_name` from `user_metadata` to `run_ogr2ogr` |
| `frontend/src/components/import/FileDropzone.tsx:11-17` | `ACCEPT` map | Add xlsx/xls MIME types and extensions |
| `frontend/src/components/import/FileDropzone.tsx:19` | `FORMAT_BADGES` | Add `.xlsx` badge |

### run_ogrinfo current behavior

The function calls `ogrinfo -json -so <source>` without specifying a layer name. For single-layer files (CSV, GeoJSON, Shapefile-in-zip), this works fine since `layers[0]` is the only layer. For multi-sheet Excel, this returns ALL layers but the code only reads `layers[0]`.

**Fix approach:**
- `run_ogrinfo(file_path, layer_name=None)` -- if layer_name provided, append to command args
- `run_ogrinfo_preview(file_path, ...)` -- return ALL layers in summary when no layer specified
- Preview endpoint detects multi-layer and returns layer list + first layer preview

### run_ogr2ogr current behavior

The function does not accept a layer name. For Excel, the layer name must be appended as the last positional argument to `ogr2ogr`:
```python
cmd = ["ogr2ogr", "-f", "PostgreSQL", db_conn_str, source, "-nln", f"data.{table_name}", ...]
if layer_name:
    cmd.append(layer_name)
```

### Non-spatial detection (already working from 260322-hv0)

In `ingest_file` task (line 108): `has_geometry = geometry_type is not None`
When `has_geometry` is False, the pipeline skips: clip, geom_4326 column, spatial index, quicklook generation. This works correctly for Excel since `geometryFields: []` yields `geometry_type = None`.

## Multi-Sheet UX Recommendation

**Recommendation:** For single-sheet Excel files, proceed exactly like CSV (no extra UX). For multi-sheet files:

1. Preview endpoint returns `layers: [{name, field_count, feature_count}, ...]` alongside the first sheet's full preview
2. Frontend shows a sheet selector dropdown (only when `layers.length > 1`)
3. Selected sheet name is passed in `CommitRequest` as `layer_name` field
4. `ingest_file` reads `layer_name` from `user_metadata` and passes to `run_ogr2ogr`

This reuses the existing pattern from service URL ingestion where `source_layer` is used for layer selection.

## JSON Ingestion Findings (HIGH confidence)

**GDAL cannot ingest plain JSON.** Options:

| Approach | Complexity | Reliability |
|----------|------------|-------------|
| Pre-process JSON to CSV (Python `json` + `csv`) | Medium | High for flat arrays |
| Pre-process JSON to GeoJSON-with-null-geometry | Low | Works but ogrinfo reports `geometry_type: "Geometry"` even with all-null geometries, breaking non-spatial detection |
| Use pandas/polars to load directly to PostgreSQL | High | High but bypasses ogr2ogr pipeline |

**Recommendation:** Defer JSON to follow-up. The JSON-to-CSV approach is most viable but requires structure detection (nested vs flat, array-of-objects vs object-of-arrays) which adds scope.

## Common Pitfalls

### Pitfall 1: XLSX puremagic false positives
**What goes wrong:** XLSX files are ZIP archives containing XML. puremagic may detect them as `.zip` or even `.docx` (same OOXML container).
**How to avoid:** `EXTENSION_CONTENT_MAP[".xlsx"]` should include `{".xlsx", ".zip", ".docx"}` to be permissive. The GDAL driver will reject truly invalid files.

### Pitfall 2: XLS puremagic detection
**What goes wrong:** Old `.xls` files use Microsoft Compound Binary Format. puremagic may detect as `.doc` or `.ppt`.
**How to avoid:** `EXTENSION_CONTENT_MAP[".xls"]` should include `{".xls", ".doc"}`.

### Pitfall 3: Excel empty sheets
**What goes wrong:** Users upload Excel with empty sheets that have no data rows.
**How to avoid:** Check `feature_count` in ogrinfo output. Skip sheets with 0 features in the layer list.

### Pitfall 4: ogr2ogr FID column for Excel
**What goes wrong:** Excel has no inherent FID. ogr2ogr may auto-generate one.
**How to avoid:** The existing `-lco FID=gid` flag handles this correctly. Verified that ogr2ogr assigns sequential FIDs starting from row 2 (row 1 = header).

## Code Examples

### Adding layer_name to run_ogr2ogr
```python
async def run_ogr2ogr(
    file_path: str,
    table_name: str,
    db_conn_str: str,
    source_srid: int | None = None,
    geometry_type: str | None = None,
    layer_name: str | None = None,  # NEW: for multi-sheet Excel
) -> None:
    # ... existing cmd building ...
    if layer_name:
        cmd.append(layer_name)
    # ... run subprocess ...
```

### Multi-layer ogrinfo response
```python
# In run_ogrinfo, return all layers when multi-layer detected
data = json.loads(stdout.decode())
layers = data.get("layers", [])
if len(layers) > 1:
    return {
        "srid": None,
        "geometry_type": None,
        "layer_name": layers[0].get("name", ""),
        "feature_count": layers[0].get("featureCount"),
        "all_layers": [
            {"name": l["name"], "feature_count": l.get("featureCount", 0)}
            for l in layers
        ],
    }
```

### Frontend ACCEPT map addition
```typescript
const ACCEPT = {
  'application/zip': ['.zip'],
  'application/geopackage+sqlite3': ['.gpkg'],
  'application/geo+json': ['.geojson', '.json'],
  'text/csv': ['.csv'],
  'image/tiff': ['.tif', '.tiff'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls'],
};
```

## Sources

### Primary (HIGH confidence)
- Live Docker container `ogrinfo --formats` output -- confirmed XLSX and XLS drivers present
- Live testing: `ogrinfo -json -so` and `ogrinfo -json -features` on multi-sheet XLSX
- Live testing: `ogr2ogr` with layer selection on XLSX
- Live testing: plain JSON array rejected by GDAL (`not recognized as supported format`)
- Live testing: puremagic `.xlsx` detection returns `.xlsx`
- Codebase analysis: `backend/app/ingest/ogr.py`, `tasks.py`, `validation.py`, `router.py`, `schemas.py`
- Codebase analysis: `frontend/src/components/import/FileDropzone.tsx`, `UploadForm.tsx`

## Metadata

**Confidence breakdown:**
- Excel GDAL support: HIGH -- verified in running container
- Multi-sheet handling: HIGH -- tested with real multi-sheet file
- Plain JSON limitation: HIGH -- tested and confirmed GDAL rejection
- Pipeline changes needed: HIGH -- traced through full codebase

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable GDAL behavior)

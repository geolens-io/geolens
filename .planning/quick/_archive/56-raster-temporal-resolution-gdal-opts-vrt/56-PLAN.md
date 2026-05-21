---
phase: quick-56
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/raster/cog.py
  - backend/app/ingest/schemas.py
  - backend/app/ingest/router.py
  - backend/app/ingest/tasks.py
  - frontend/src/types/api.ts
  - frontend/src/components/import/BulkReviewList.tsx
  - frontend/src/components/import/ImportMetadataForm.tsx
  - frontend/src/components/import/ImportPreview.tsx
  - frontend/src/components/import/VrtCreatorForm.tsx
  - frontend/src/i18n/locales/en/import.json
autonomous: true
requirements: [TEMPORAL-01, GDAL-OPTS-01, VRT-HELP-01]

must_haves:
  truths:
    - "Raster preview response includes temporal_start extracted from TIFFTAG_DATETIME metadata"
    - "User can enter/override temporal_start and temporal_end dates in the import form for raster files"
    - "temporal_start and temporal_end are passed through commit request and persisted on Record"
    - "User can choose compression method (DEFLATE, ZSTD, LZW, JPEG, WEBP, LERC) at import time"
    - "User can choose resampling method (nearest, bilinear, cubic, etc.) at import time"
    - "User can specify a nodata override value at import time"
    - "Raster files without CRS can be imported when user provides CRS assign EPSG code"
    - "VRT creator form shows help text explaining mode selector and resolution strategy options"
  artifacts:
    - path: "backend/app/raster/cog.py"
      provides: "extract_raster_metadata returns temporal_start from TIFFTAG_DATETIME"
    - path: "backend/app/ingest/schemas.py"
      provides: "CommitRequest with temporal_start, temporal_end, compression, resampling, nodata_override fields"
    - path: "backend/app/ingest/tasks.py"
      provides: "ingest_raster uses user GDAL options for COG conversion and sets temporal fields on Record"
    - path: "frontend/src/components/import/BulkReviewList.tsx"
      provides: "Passes isRaster and previewData props to ImportMetadataForm"
    - path: "frontend/src/components/import/ImportMetadataForm.tsx"
      provides: "Raster-specific GDAL options and temporal date fields in import form"
    - path: "frontend/src/components/import/VrtCreatorForm.tsx"
      provides: "Help text under mode selector and resolution strategy"
  key_links:
    - from: "backend/app/raster/cog.py"
      to: "backend/app/ingest/router.py"
      via: "extract_raster_metadata temporal_start in preview response"
      pattern: "temporal_start"
    - from: "frontend/src/components/import/BulkReviewList.tsx"
      to: "frontend/src/components/import/ImportMetadataForm.tsx"
      via: "isRaster and previewData props passed to ImportMetadataForm"
      pattern: "isRaster.*previewData"
    - from: "frontend/src/components/import/ImportMetadataForm.tsx"
      to: "backend/app/ingest/schemas.py"
      via: "CommitImportRequest fields passed to commit endpoint"
      pattern: "compression|resampling|nodata_override|temporal_start"
    - from: "backend/app/ingest/tasks.py"
      to: "backend/app/raster/cog.py"
      via: "convert_to_cog accepts compression/resampling params"
      pattern: "convert_to_cog.*compression|resampling"
---

<objective>
Add three raster import improvements: (1) temporal metadata extraction and user-editable dates, (2) GDAL options exposed at import time (CRS assign, reprojection, resampling, compression, nodata override), (3) inline help text on VRT creator form.

Purpose: Enable raster temporal search, give users control over COG conversion parameters, and improve VRT form discoverability.
Output: Updated backend schemas/tasks/cog.py + frontend import form with GDAL options and VRT help text.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/app/raster/cog.py
@backend/app/ingest/schemas.py
@backend/app/ingest/router.py
@backend/app/ingest/tasks.py
@frontend/src/types/api.ts
@frontend/src/components/import/BulkReviewList.tsx
@frontend/src/components/import/ImportMetadataForm.tsx
@frontend/src/components/import/ImportPreview.tsx
@frontend/src/components/import/VrtCreatorForm.tsx
@frontend/src/i18n/locales/en/import.json
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend - temporal extraction, GDAL options schema, and COG conversion params</name>
  <files>
    backend/app/raster/cog.py,
    backend/app/ingest/schemas.py,
    backend/app/ingest/router.py,
    backend/app/ingest/tasks.py
  </files>
  <action>
**1. Extract temporal metadata from rasters (`backend/app/raster/cog.py`):**

In `extract_raster_metadata()`, after opening with rasterio, extract TIFFTAG_DATETIME from `src.tags()` dict. Parse it (format is typically "YYYY:MM:DD HH:MM:SS") into an ISO date string. Add `"temporal_start"` to the returned dict (value is the date string or None if tag absent/unparseable). Also check for `TIFFTAG_DATETIME`, `datetime`, `DATE`, `acquisition_date` tags.

**2. Make CRS validation optional (`backend/app/raster/cog.py`):**

`validate_raster_crs()` currently raises ValueError on missing CRS. Do NOT change this function. Instead, in the upload endpoint (`router.py`), skip the CRS validation call when user_metadata already contains a `srid_override` value. The CRS assign will be applied during ingest via gdalwarp.

**3. Accept GDAL options in COG conversion (`backend/app/raster/cog.py`):**

Modify `convert_to_cog(input_path, output_path, dtype, *, compression="DEFLATE", resampling=None, nodata=None, assign_crs=None)`:
- Use `compression` param instead of hardcoded "DEFLATE" in gdal_translate `-co COMPRESS=...`
- Update `_predictor_for_dtype` to return appropriate predictor based on compression (predictors only work for DEFLATE/ZSTD/LZW; skip predictor for JPEG/WEBP/LERC)
- If `assign_crs` is provided (EPSG int), prepend a gdalwarp step: `gdalwarp -t_srs EPSG:{assign_crs} input output` before the COG conversion
- If `resampling` is provided, pass `-r {resampling}` to gdalwarp and also use it in `gdaladdo` instead of auto-detecting
- If `nodata` is provided, pass `-a_nodata {nodata}` to gdal_translate

Modify `prepare_with_overviews(input_path, dtype, *, resampling=None, compression="DEFLATE")`:
- Accept optional resampling override (use it instead of auto-detecting from dtype)
- Use `compression` in `--config COMPRESS_OVERVIEW {compression}`

Modify `check_cog_compliance` to be tolerant of any compression (not just DEFLATE) when the user explicitly chose a compression. Add optional `expected_compression=None` param; only check compression match if provided.

Modify `check_and_prepare_cog(file_path, output_dir, *, compression="DEFLATE", resampling=None, nodata=None, assign_crs=None)` to pass options through.

**4. Update schemas (`backend/app/ingest/schemas.py`):**

Add to `RasterPreviewResponse`:
- `temporal_start: str | None = None` (extracted date)

Add to `CommitRequest`:
- `temporal_start: str | None = None` (ISO date, e.g. "2024-06-15")
- `temporal_end: str | None = None`
- `compression: str | None = None` (DEFLATE, ZSTD, LZW, JPEG, WEBP, LERC)
- `resampling: str | None = None` (nearest, bilinear, cubic, cubicspline, lanczos, average, mode)
- `nodata_override: float | str | None = None`

**5. Wire preview response (`backend/app/ingest/router.py`):**

In `preview_file()` raster branch, include `temporal_start=meta.get("temporal_start")` in the RasterPreviewResponse.

In `upload_file()`, when the file is a raster and `srid_override` is provided in user_metadata, skip the `validate_raster_crs()` call. To do this: after the raster CRS validation block (lines 262-300), check if the user provided an srid_override. Actually, srid_override comes at commit time, not upload. So instead, make the CRS validation non-fatal for rasters: catch the ValueError, store it in user_metadata as `crs_warning`, and let the preview still proceed. The commit will fail if no srid_override is provided AND there's a crs_warning.

Wait -- re-reading the CONTEXT: "CRS assign: Allow user to specify EPSG when raster has no CRS (currently rejected)". The rejection happens at upload time. The simplest fix: in the upload endpoint, for raster files, catch the CRS ValueError and store `{"crs_missing": true}` in user_metadata instead of raising HTTPException. The preview will show CRS as "Unknown". At commit time in `ingest_raster`, if `crs_missing` is true and no `srid_override` provided, fail the job. If `srid_override` IS provided, use it as `assign_crs` in the COG conversion.

**6. Wire commit/ingest (`backend/app/ingest/tasks.py`):**

In `ingest_raster()`:
- Read GDAL options from `um` (user_metadata): `compression`, `resampling`, `nodata_override`, `srid_override` (as assign_crs)
- Pass them to `check_and_prepare_cog(file_path, tmp_dir, compression=compression, resampling=resampling, nodata=nodata, assign_crs=assign_crs)`
- After creating record via `create_raster_dataset`, set `record.temporal_start` and `record.temporal_end` from user_metadata (parsing ISO date strings to `datetime.date`). If not provided by user, fall back to `meta.get("temporal_start")` for temporal_start.
- Import `from datetime import date` and use `date.fromisoformat()` for parsing

In `commit_import()` router: the commit_metadata already merges all CommitRequest fields into user_metadata, so GDAL options will be available in `um` during ingest_raster.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "from app.raster.cog import extract_raster_metadata, convert_to_cog; print('imports ok')" && python -c "from app.ingest.schemas import CommitRequest, RasterPreviewResponse; r = CommitRequest(title='test', compression='ZSTD', resampling='bilinear', temporal_start='2024-01-01'); print(r.model_dump())"</automated>
  </verify>
  <done>
    - extract_raster_metadata returns temporal_start from TIFFTAG_DATETIME
    - CommitRequest accepts compression, resampling, nodata_override, temporal_start, temporal_end
    - RasterPreviewResponse includes temporal_start
    - convert_to_cog accepts and uses compression/resampling/nodata/assign_crs params
    - Upload endpoint allows CRS-missing rasters through (stores crs_missing flag)
    - ingest_raster reads GDAL options from user_metadata and passes to COG conversion
    - temporal_start/end set on Record from user input or extracted metadata
  </done>
</task>

<task type="auto">
  <name>Task 2: Frontend - GDAL options in import form, temporal fields, and raster preview enhancements</name>
  <files>
    frontend/src/types/api.ts,
    frontend/src/components/import/BulkReviewList.tsx,
    frontend/src/components/import/ImportMetadataForm.tsx,
    frontend/src/components/import/ImportPreview.tsx,
    frontend/src/i18n/locales/en/import.json
  </files>
  <action>
**1. Update TypeScript types (`frontend/src/types/api.ts`):**

Add to `RasterPreviewResponse`:
- `temporal_start: string | null;`

Add to `CommitImportRequest`:
- `temporal_start?: string | null;`
- `temporal_end?: string | null;`
- `compression?: string | null;`
- `resampling?: string | null;`
- `nodata_override?: number | string | null;`

**2. Update ImportPreview (`frontend/src/components/import/ImportPreview.tsx`):**

In the raster preview section, add a row showing detected temporal date if present:
```
{preview.temporal_start && (
  <div>
    <span className="text-muted-foreground">Date:</span> {preview.temporal_start}
  </div>
)}
```

**3. Update ImportMetadataForm (`frontend/src/components/import/ImportMetadataForm.tsx`):**

Accept new prop `isRaster: boolean` (default false) and `previewData?: RasterPreviewResponse` (optional).

When `isRaster` is true, show additional fields BELOW the CRS override field:

a) **Temporal dates section** (two date inputs side by side):
   - `temporal_start` (date input, pre-filled from `previewData?.temporal_start` if available)
   - `temporal_end` (date input, empty by default)
   - Help text: "Date range for this dataset. Used for temporal search."

b) **GDAL Options section** (collapsible or always visible, with a subtle "Advanced Options" label):
   - **Compression** select: options = DEFLATE (default), ZSTD, LZW, JPEG, WEBP, LERC
     - Help text: "Compression for COG output. DEFLATE is default. Use ZSTD for faster compression, JPEG/WEBP for imagery."
   - **Resampling** select: options = (auto) as default, nearest, bilinear, cubic, cubicspline, lanczos, average, mode
     - Help text: "Resampling method for overview generation and reprojection."
   - **NoData** input (number): optional
     - Help text: "Override or assign nodata value."

Add all new field values to the `CommitImportRequest` in `handleSubmit`:
```typescript
const request: CommitImportRequest = {
  title: name.trim(),
  summary: description.trim() || null,
  visibility,
  srid_override: sridOverride.trim() ? parseInt(sridOverride.trim(), 10) : null,
  temporal_start: temporalStart || null,
  temporal_end: temporalEnd || null,
  compression: compression !== 'DEFLATE' ? compression : null, // only send if non-default
  resampling: resampling !== 'auto' ? resampling : null,
  nodata_override: nodataOverride.trim() ? nodataOverride.trim() : null,
};
```

**4. Wire isRaster prop in BulkReviewList (`frontend/src/components/import/BulkReviewList.tsx`):**

Pass `isRaster={isRasterPreview(entry.previewData)}` and `previewData={isRasterPreview(entry.previewData) ? entry.previewData : undefined}` to ImportMetadataForm. Import the `isRasterPreview` type guard (or define inline: check if `entry.previewData` has raster-specific fields like `bands` or `dtype`).

**5. Add i18n strings (`frontend/src/i18n/locales/en/import.json`):**

Add to `metadata` section:
```json
"temporalStartLabel": "Start Date",
"temporalEndLabel": "End Date",
"temporalHelpText": "Date range for this dataset. Used for temporal search.",
"advancedOptions": "Advanced Options",
"compressionLabel": "Compression",
"compressionHelp": "COG output compression. DEFLATE is default. ZSTD for speed, JPEG/WEBP for imagery.",
"resamplingLabel": "Resampling",
"resamplingHelp": "Method for overview generation and reprojection. Auto selects based on data type.",
"nodataLabel": "NoData Value",
"nodataHelp": "Override or assign a nodata value for this raster."
```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -20</automated>
  </verify>
  <done>
    - Raster preview shows detected temporal date
    - Import form shows temporal_start/temporal_end date inputs for rasters
    - Import form shows compression, resampling, nodata options for rasters
    - BulkReviewList passes isRaster and previewData props to ImportMetadataForm
    - All new fields included in CommitImportRequest on submit
    - TypeScript compiles without errors
  </done>
</task>

<task type="auto">
  <name>Task 3: VRT creator form - inline help text</name>
  <files>
    frontend/src/components/import/VrtCreatorForm.tsx,
    frontend/src/i18n/locales/en/import.json
  </files>
  <action>
**1. Add help text to VRT mode selector:**

Below the ToggleGroup for vrt type (mosaic/band_stack), add a description paragraph for the currently selected mode:

For mosaic: "Combines multiple rasters into a single continuous layer. Sources are spatially arranged side-by-side. All sources must share the same CRS, data type, and band count."

For band_stack: "Stacks multiple single-band rasters into a multi-band dataset. Each source becomes one band. Sources must have identical grid dimensions and resolution."

Show this text regardless of which mode is selected (not just band_stack as currently done). Replace the existing `bandStackNote` paragraph with the mode-aware description.

**2. Add help text to resolution strategy selector:**

Below the Select for resolution strategy, add a description:

For finest: "Uses the highest resolution (smallest pixel size) among all sources. Other sources are resampled to match."
For coarsest: "Uses the lowest resolution (largest pixel size) among all sources. Faster but loses detail."
For average: "Uses the mean resolution across all sources. Balances detail and performance."

Show the description for the currently selected strategy.

**3. Add i18n strings:**

Add to `vrt` section in import.json:
```json
"mosaicHelp": "Combines multiple rasters into a single continuous layer. Sources are spatially arranged side-by-side. All sources must share the same CRS, data type, and band count.",
"bandStackHelp": "Stacks multiple single-band rasters into a multi-band dataset. Each source becomes one band. Sources must have identical grid dimensions and resolution.",
"resFinestHelp": "Uses the highest resolution (smallest pixel size) among all sources. Other sources are resampled to match.",
"resCoarsestHelp": "Uses the lowest resolution (largest pixel size). Faster but loses detail from finer sources.",
"resAverageHelp": "Uses the mean resolution across all sources. Balances detail and performance."
```

**4. Implementation:**

Use `text-sm text-muted-foreground` for help text paragraphs. Display directly below each control with no collapsible wrapper.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -20</automated>
  </verify>
  <done>
    - VRT mode selector shows context-appropriate help text for mosaic and band_stack
    - Resolution strategy selector shows help text for the selected strategy
    - Help text uses muted foreground styling, inline below controls
  </done>
</task>

</tasks>

<verification>
1. Backend: `python -c "from app.ingest.schemas import CommitRequest; print(CommitRequest.model_fields.keys())"` includes new fields
2. Frontend: `npx tsc --noEmit` passes
3. Manual: Upload a raster, verify temporal date extraction in preview, GDAL options visible in form
4. Manual: Open VRT tab, verify help text appears under mode selector and resolution strategy
</verification>

<success_criteria>
- Raster preview shows temporal_start extracted from TIFFTAG_DATETIME
- Import form for rasters shows temporal date fields, compression/resampling/nodata options
- Rasters without CRS can proceed through upload when user will provide srid_override at commit
- COG conversion respects user-chosen compression, resampling, and nodata
- temporal_start/temporal_end persisted on Record after ingest
- VRT creator form has inline help text for mode and resolution strategy
- TypeScript and Python imports compile cleanly
</success_criteria>

<output>
After completion, create `.planning/quick/56-raster-temporal-resolution-gdal-opts-vrt/56-SUMMARY.md`
</output>

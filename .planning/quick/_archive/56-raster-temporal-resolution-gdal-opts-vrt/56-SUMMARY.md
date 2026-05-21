---
phase: quick-56
plan: 01
subsystem: ingest, raster, frontend-import
tags: [raster, temporal, gdal, vrt, cog, import]
dependency_graph:
  requires: []
  provides: [temporal-extraction, gdal-options, vrt-help-text]
  affects: [raster-ingest, import-form, vrt-creator]
tech_stack:
  added: []
  patterns: [temporal-metadata-extraction, gdal-option-passthrough, crs-missing-graceful-handling]
key_files:
  created: []
  modified:
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
decisions:
  - CRS-missing rasters allowed through upload with crs_missing flag; validated at ingest time
  - Predictor only applied for DEFLATE/ZSTD/LZW compression types
  - gdalwarp CRS assignment only triggered when crs_missing is true and srid_override provided
  - Temporal dates parsed from TIFFTAG_DATETIME with fallback to datetime/DATE/acquisition_date tags
metrics:
  duration: 4min
  completed: "2026-03-15T14:58:13Z"
  tasks: 3
  files: 10
---

# Quick Task 56: Raster Temporal/Resolution/GDAL Options + VRT Help Text

Temporal metadata extraction from TIFF tags, user-editable GDAL options (compression, resampling, nodata, CRS assign) at raster import time, and inline help text on VRT creator form.

## Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Backend - temporal extraction, GDAL options, CRS-missing support | 0450b7be | cog.py, schemas.py, router.py, tasks.py |
| 2 | Frontend - GDAL options in import form, temporal fields | 766cc8c5 | api.ts, BulkReviewList.tsx, ImportMetadataForm.tsx, ImportPreview.tsx, import.json |
| 3 | VRT creator form - inline help text | 3338ac6a | VrtCreatorForm.tsx, import.json |

## What Changed

### Backend
- `extract_raster_metadata()` now extracts `temporal_start` from TIFFTAG_DATETIME and related TIFF tags
- `convert_to_cog()` accepts compression, resampling, nodata, and assign_crs parameters
- `_predictor_for_dtype()` returns None for JPEG/WEBP/LERC (predictors not applicable)
- `prepare_with_overviews()` accepts resampling and compression overrides
- `check_and_prepare_cog()` passes all GDAL options through to conversion
- `check_cog_compliance()` validates against user-specified compression
- `CommitRequest` schema extended with temporal_start, temporal_end, compression, resampling, nodata_override
- `RasterPreviewResponse` extended with temporal_start
- Upload endpoint catches CRS ValueError for rasters and stores `crs_missing` flag instead of rejecting
- `ingest_raster` reads GDAL options from user_metadata, passes to COG conversion, sets temporal fields on Record

### Frontend
- ImportPreview shows detected temporal date for raster files
- ImportMetadataForm accepts isRaster/previewData props; shows temporal date inputs and Advanced Options section (compression, resampling, nodata) for rasters
- BulkReviewList passes isRaster and previewData props to ImportMetadataForm
- TypeScript types updated for new fields
- All new i18n strings added

### VRT Creator
- Mode selector shows context-appropriate help text for both mosaic and band_stack
- Resolution strategy selector shows descriptive help text for selected strategy
- Replaced single bandStackNote with mode-aware descriptions

## Deviations from Plan

None - plan executed exactly as written.

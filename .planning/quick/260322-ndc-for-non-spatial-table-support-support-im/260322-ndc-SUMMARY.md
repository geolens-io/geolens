---
phase: quick-260322-ndc
plan: 01
subsystem: ingest
tags: [gdal, ogr2ogr, csv, xlsx, geometry, postgis, react, i18n]

requires:
  - phase: quick-260322-hv0
    provides: Non-spatial CSV ingestion pipeline and record_type='table' support
  - phase: quick-260322-mb0
    provides: Excel XLSX ingestion support with multi-sheet handling

provides:
  - Geometry column auto-detection for CSV/XLSX imports (lat/lng and WKT patterns)
  - Post-import geometry construction via ST_MakePoint and ST_GeomFromText
  - Frontend geometry column override UI with mode selector
  - Broadened CSV WKT column detection via GEOM_POSSIBLE_NAMES

affects: [ingest, import-ui]

tech-stack:
  added: []
  patterns:
    - "Post-import SQL geometry construction for formats without GDAL X/Y open options"
    - "detect_geometry_columns pattern-matching for auto-detection"

key-files:
  created: []
  modified:
    - backend/app/ingest/ogr.py
    - backend/app/ingest/schemas.py
    - backend/app/ingest/tasks.py
    - backend/app/ingest/metadata.py
    - backend/app/ingest/router.py
    - frontend/src/types/api.ts
    - frontend/src/components/import/ImportPreview.tsx
    - frontend/src/components/import/ImportMetadataForm.tsx
    - frontend/src/components/import/BulkReviewList.tsx
    - frontend/src/i18n/locales/en/import.json
    - frontend/src/i18n/locales/es/import.json
    - frontend/src/i18n/locales/fr/import.json
    - frontend/src/i18n/locales/de/import.json

key-decisions:
  - "Post-import SQL (ST_MakePoint/ST_GeomFromText) chosen over VRT wrapper for XLSX geometry construction"
  - "Geometry detection returns original column case for SQL safety"
  - "Preview endpoint only returns detected_geometry_columns when geometry_type is None and columns detected"

patterns-established:
  - "construct_point_geometry/construct_wkt_geometry: reusable post-import geometry builders with table/column name validation"

requirements-completed: [NDC-01, NDC-02, NDC-03]

duration: 5min
completed: 2026-03-22
---

# Quick Task 260322-ndc: Geometry Column Detection Summary

**Auto-detect lat/lng and WKT columns in CSV/XLSX uploads with user override UI and post-import ST_MakePoint/ST_GeomFromText geometry construction**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-22T21:05:17Z
- **Completed:** 2026-03-22T21:10:03Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments
- Added geometry column auto-detection (lat/lng and WKT pattern matching) to preview endpoint
- Built post-import geometry construction functions (construct_point_geometry, construct_wkt_geometry) in metadata.py
- Wired geometry construction into ingest_file task for XLSX files with user-specified coordinate columns
- Broadened CSV WKT detection via GEOM_POSSIBLE_NAMES open option
- Added geometry column override UI to ImportMetadataForm with auto/manual/non-spatial mode selector
- Updated ImportPreview to show geometry detection status badges
- Added i18n keys to all 4 locale files

## Task Commits

1. **Task 1: Backend -- geometry column detection, CommitRequest extension, post-import construction** - `e8798a0a` (feat)
2. **Task 2: Frontend -- geometry column override UI and type updates** - `37e6c3d5` (feat)

## Files Created/Modified
- `backend/app/ingest/ogr.py` - Added detect_geometry_columns() function and broadened GEOM_POSSIBLE_NAMES
- `backend/app/ingest/schemas.py` - Extended PreviewResponse and CommitRequest with geometry column fields
- `backend/app/ingest/metadata.py` - Added construct_point_geometry() and construct_wkt_geometry() functions
- `backend/app/ingest/tasks.py` - Wired post-import geometry construction, added XLSX/XLS to assumes_4326
- `backend/app/ingest/router.py` - Wired detect_geometry_columns into preview endpoint
- `frontend/src/types/api.ts` - Added detected_geometry_columns and geometry override fields
- `frontend/src/components/import/ImportPreview.tsx` - Geometry detection badge for non-spatial files
- `frontend/src/components/import/ImportMetadataForm.tsx` - Geometry column override UI section
- `frontend/src/components/import/BulkReviewList.tsx` - Pass previewColumns and detectedGeometryColumns props
- `frontend/src/i18n/locales/*/import.json` - Added 12 new i18n keys per locale

## Decisions Made
- Post-import SQL chosen over VRT wrapper for XLSX geometry -- simpler, works identically for CSV override scenarios
- detect_geometry_columns preserves original column casing for safe SQL column references
- Preview endpoint only populates detected_geometry_columns when geometry_type is null and actual matches found

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Geometry detection and construction pipeline complete
- End-to-end testing requires running Docker environment with PostGIS

---
*Phase: quick-260322-ndc*
*Completed: 2026-03-22*

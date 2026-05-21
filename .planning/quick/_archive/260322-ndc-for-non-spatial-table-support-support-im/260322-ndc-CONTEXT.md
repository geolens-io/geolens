# Quick Task 260322-ndc: Non-spatial table support, CSV/XLSX with geometry columns - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Support import of CSV/XLSX files with geometry columns (lat/lng, WKT) into PostGIS, and support non-spatial tables (no geometry at all) as first-class catalog entries.

</domain>

<decisions>
## Implementation Decisions

### Geometry Column Detection
- Auto-detect lat/lng, x/y, or WKT columns by name pattern matching
- Allow user to override detected geometry columns via the upload form if auto-detection is wrong
- If no geometry columns detected, import as non-spatial table (record_type='table')

### Non-Spatial Table Behavior
- Non-spatial tables appear as full catalog entries with record_type='table'
- They show in catalog/search with record detail page and attribute table
- No map preview, no tile endpoints — gracefully skip map-related features
- No separate section needed — they coexist with spatial datasets in the catalog

### CSV/XLSX Parsing Strategy
- Use GDAL/ogr2ogr for both CSV and XLSX (GDAL has XLSX driver)
- Keep unified ingestion pipeline — no separate pandas code path
- Geometry construction via ogr2ogr VRT wrapper or post-import SQL (ST_MakePoint from detected lat/lng columns)

</decisions>

<specifics>
## Specific Ideas

- The Record model already has `record_type='table'` as a valid enum value
- The ingest pipeline already detects `has_geometry` and handles the `geometry_type is None` case partially
- GDAL's XLSX driver may need the `XLSXDRIVER` or `XLSX` open option
- For lat/lng → geometry: consider using ogr2ogr `-oo X_POSSIBLE_NAMES=lng,lon,longitude -oo Y_POSSIBLE_NAMES=lat,latitude` for CSV, or post-import `ST_MakePoint()` for both formats
- Frontend upload form needs geometry column mapping UI when auto-detection finds candidates

</specifics>

<canonical_refs>
## Canonical References

- GDAL CSV driver: supports `-oo X_POSSIBLE_NAMES` / `-oo Y_POSSIBLE_NAMES` for point geometry from columns
- GDAL XLSX driver: reads Excel files as tabular data, similar open options available
- Existing ingestion: `backend/app/ingest/tasks.py` (main pipeline), `backend/app/ingest/ogr.py` (ogr2ogr wrapper)

</canonical_refs>

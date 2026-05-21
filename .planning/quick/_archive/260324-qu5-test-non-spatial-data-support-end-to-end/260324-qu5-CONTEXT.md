# Quick Task 260324-qu5: Test non-spatial data support end-to-end - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Task Boundary

Test non-spatial data support end-to-end — verify that CSV and XLSX files without geometry columns can be uploaded, queried, exported, and viewed correctly. Fix bugs discovered during testing.

</domain>

<decisions>
## Implementation Decisions

### Test Scope
- Full stack: backend pytest tests (ingestion, features/OGC query, export) + frontend Playwright tests (upload flow, dataset page rendering, attribute table)

### Test Data Formats
- CSV + XLSX — both tabular formats the ingestion pipeline accepts

### Bug Fixes
- Test + fix approach: write tests that expose bugs, then fix them
- Known issues to address:
  1. Vector tile URLs generated for non-spatial datasets (causes 404s)
  2. Empty map with no user-facing message for non-spatial datasets

### Claude's Discretion
- Test file content/structure (column names, data types, row counts)
- Specific Playwright selectors and assertions
- Organization of test files

</decisions>

<specifics>
## Specific Ideas

- Existing partial coverage in `backend/tests/test_ingest.py:442-504` (test_csv_non_spatial_full_pipeline)
- Non-spatial datasets use `record_type = 'table'` and `geometry_type = None`
- Features API returns `geometry: null` for non-spatial records
- Export restrictions: only CSV allowed for non-spatial (gpkg/geojson/shp blocked)
- Vector tile distribution URLs generated even when no geometry exists (bug)
- Dataset map component renders empty with no indication for non-spatial data (bug)

</specifics>

# Quick Task 260322-mb0: Excel/JSON non-spatial ingestion support - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Extend non-spatial ingestion to support Excel (.xlsx/.xls) and JSON files, building on the CSV support shipped in 260322-hv0.

</domain>

<decisions>
## Implementation Decisions

### Formats
- Excel: .xlsx and .xls via ogr2ogr (GDAL supports both natively via XLSX/XLS drivers)
- JSON: Plain JSON arrays/objects — not GeoJSON (which is already supported as spatial)

### Approach
- Leverage existing non-spatial pipeline (geometry_type=None path) from 260322-hv0
- ogr2ogr handles Excel natively — add format detection and appropriate flags
- JSON may need pre-processing or a different ingestion path

### Claude's Discretion
- ogr2ogr flags for Excel/JSON
- Sheet selection UX for multi-sheet Excel files
- JSON structure detection (array of objects, nested, etc.)
- Frontend changes for format-specific upload hints

</decisions>

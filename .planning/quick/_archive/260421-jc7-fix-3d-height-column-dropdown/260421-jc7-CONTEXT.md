# Quick Task 260421-jc7: Fix 3D height column not in dropdown - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Task Boundary

The Manhattan Skyline (3D) demo map references `_height_column: "height"` but the GeoFabrik free OSM shapefile lacks a height column. The height dropdown correctly shows no height option because the data doesn't have one.

</domain>

<decisions>
## Implementation Decisions

### Data Source
- Switch from GeoFabrik free OSM shapefile to NYC Open Data building footprints with real photogrammetric heights
- The theme2.py description already calls for NYC Open Data — the Dockerfile just wasn't updated to match

### Claude's Discretion
- Column naming and unit conversion details
- Exact NYC Open Data API endpoint and query parameters

</decisions>

<specifics>
## Specific Ideas

- NYC Open Data building footprints include HEIGHT_ROOF (feet) — convert to meters for the `height` column
- Clip to Manhattan bbox like the current GeoFabrik approach
- Update seeder Dockerfile and CHECKSUMS.sha256
- Ensure column_info picks up the new `height` column as a numeric type so it appears in the dropdown

</specifics>

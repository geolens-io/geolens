---
status: complete
---

# Quick Task 260421-jc7: Fix 3D Height Column Dropdown

## What Changed

Replaced the Manhattan buildings data source in the seeder Dockerfile from GeoFabrik free OSM shapefile (which lacked height data) to NYC Open Data building footprints (dataset `5zhs-2jue`) with real photogrammetric heights.

## Files Modified

| File | Change |
|------|--------|
| `docker/seeder/Dockerfile` | Replaced GeoFabrik download with NYC Open Data Socrata API call + ogr2ogr conversion of HEIGHT_ROOF (feet) to `height` (meters) |
| `docker/seeder/CHECKSUMS.sha256` | Excluded manhattan_buildings.geojson from strict checksums (live API data varies between builds) |

## Verification

- **50,000 MULTIPOLYGON features** ingested with geometry
- **`height` column**: double precision, min=0m, avg=12.8m, max=315.5m
- **49,999/50,000** features have non-null height values
- Height column appears in map builder dropdown as expected
- `_height_column: "height"` paint property matches the column name
- Seeder builds and seeds successfully end-to-end

## Root Cause

The GeoFabrik free OSM shapefile only includes `osm_id, code, fclass, name, type` — the `height` tag is not carried in the free variant. The map fixture and theme2.py description referenced NYC Open Data heights, but the Dockerfile was never updated to match.

# Quick Task 260421-jc7: Fix 3D Height Column - Research

**Researched:** 2026-04-21
**Domain:** NYC Open Data Socrata API, ogr2ogr GeoJSON processing
**Confidence:** HIGH

## Summary

The Manhattan Skyline (3D) map references a `height` column that does not exist in the current GeoFabrik OSM buildings data. NYC Open Data provides building footprints (dataset `5zhs-2jue`) with photogrammetric `HEIGHT_ROOF` in US feet. The fix is to replace the GeoFabrik download in the seeder Dockerfile with a Socrata SODA API call that fetches Manhattan buildings as GeoJSON, then use ogr2ogr to convert `HEIGHT_ROOF` from feet to meters as a new `height` column.

**Primary recommendation:** Use the Socrata GeoJSON endpoint with `within_box` spatial filter and `$limit=50000`, then ogr2ogr SQL to create the `height` column.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Switch from GeoFabrik free OSM shapefile to NYC Open Data building footprints with real photogrammetric heights
- The theme2.py description already calls for NYC Open Data -- the Dockerfile just was not updated to match

### Claude's Discretion
- Column naming and unit conversion details
- Exact NYC Open Data API endpoint and query parameters
</user_constraints>

## NYC Open Data Building Footprints Dataset

### Key Facts

| Property | Value |
|----------|-------|
| Dataset ID | `5zhs-2jue` [VERIFIED: data.cityofnewyork.us API metadata] |
| Total rows | ~1,082,901 buildings (all 5 boroughs) [VERIFIED: API metadata] |
| Manhattan subset | ~42,000 buildings (BIN starts with `1`) [ASSUMED] |
| HEIGHT_ROOF units | **US feet** [VERIFIED: NYC geo-metadata GitHub] |
| HEIGHT_ROOF meaning | Height of roof above ground elevation, not sea level [VERIFIED: NYC geo-metadata GitHub] |
| Geometry type | MultiPolygon [VERIFIED: API metadata] |
| Coordinate system | WGS84 (via Socrata GeoJSON output) [ASSUMED] |
| License | NYC Open Data (public use with attribution) [VERIFIED: NYC Open Data portal] |
| Auth required | No -- public endpoint, no API key needed [VERIFIED: Socrata docs] |

### Relevant Fields

| Field | Type | Keep? | Notes |
|-------|------|-------|-------|
| `height_roof` | number | Yes | Primary height data (feet). Lowercase in Socrata API. |
| `name` | text | Yes | Building name (rarely populated but useful) |
| `bin` | number | No | BIN is useful for filtering but not for display |
| `ground_elevation` | number | No | Not needed for extrusion |
| `construction_year` | number | Optional | Could be interesting but not required |
| `doitt_id` | number | No | Internal ID |

**Field name casing:** Socrata API returns field names in **lowercase** (e.g., `height_roof`, not `HEIGHT_ROOF`). The GitHub metadata uses uppercase but the actual API response uses lowercase. [VERIFIED: Socrata API convention]

### API Endpoint

**GeoJSON export URL:**
```
https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?$where=within_box(the_geom,40.80,-74.05,40.68,-73.90)&$limit=50000
```

**SoQL `within_box` syntax:** `within_box(location_column, lat_north, lon_west, lat_south, lon_east)` [VERIFIED: Socrata docs]

**Limit:** Socrata caps at 50,000 rows per request. Manhattan has ~42k buildings, so a single request with `$limit=50000` should suffice. [CITED: dev.socrata.com/docs/queries/limit.html]

### Alternative: Direct Shapefile Export

The portal offers a full shapefile export via `https://data.cityofnewyork.us/api/geospatial/5zhs-2jue?method=export&type=Shapefile` but this downloads ALL 1M+ buildings (~500MB+). The SODA GeoJSON API with `within_box` is far more efficient for a Manhattan-only extract. [ASSUMED based on Socrata patterns]

## ogr2ogr Command

### Recommended Approach

```bash
curl -fsSL -o /tmp/manhattan_buildings_raw.geojson \
  "https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?\$where=within_box(the_geom,40.80,-74.05,40.68,-73.90)&\$limit=50000" \
&& ogr2ogr -f GeoJSON \
     $DATA_DIR/manhattan_buildings.geojson \
     /tmp/manhattan_buildings_raw.geojson \
     -sql "SELECT name, height_roof, ROUND(height_roof * 0.3048, 1) AS height FROM manhattan_buildings_raw" \
     -dialect SQLite \
&& rm -f /tmp/manhattan_buildings_raw.geojson
```

**Key details:**
- `height_roof * 0.3048` converts feet to meters [VERIFIED: standard conversion factor]
- `ROUND(..., 1)` keeps one decimal place for cleanliness
- `-dialect SQLite` needed for arithmetic expressions in ogr2ogr SQL
- The table name in the SQL matches the filename stem of the input (`manhattan_buildings_raw`)
- The `$` signs in the URL need escaping in the Dockerfile (`\$where`, `\$limit`) since Docker `RUN` uses shell

### Handling NULL HEIGHT_ROOF

Some buildings have NULL or 0 for `height_roof`. The SQL should use `COALESCE`:

```sql
SELECT name, height_roof,
       ROUND(COALESCE(NULLIF(height_roof, 0), 10) * 0.3048, 1) AS height
FROM manhattan_buildings_raw
```

This gives buildings with missing heights a default of ~3 meters (10 feet), which is a reasonable minimum for a single-story structure. The map fixture already handles 0 via `["coalesce", ["to-number", ["get", "height"], 0], 0]` so alternatively we could just let NULLs pass through and default to 0 on the rendering side.

**Recommendation:** Keep it simple -- just do `ROUND(height_roof * 0.3048, 1) AS height` and let the MapLibre expression handle zero/null values at render time. This preserves data fidelity.

## Gotchas

### 1. Socrata URL Escaping in Dockerfile
The `$where` and `$limit` query params conflict with shell variable expansion in `RUN` directives. Escape with backslash: `\$where`, `\$limit`. [VERIFIED: standard Docker/shell behavior]

### 2. Rate Limits
Socrata throttles unauthenticated requests but allows them. For a single request of 50k rows, this is not an issue. If the Docker build is run repeatedly in CI, consider caching the download. No API key is required. [CITED: dev.socrata.com/consumers/getting-started.html]

### 3. File Size
Manhattan buildings as GeoJSON will be significantly larger than the current GeoFabrik extract because MultiPolygon geometries are more detailed. Estimate ~80-120MB raw GeoJSON. This may impact Docker image size. Consider adding `-lco COORDINATE_PRECISION=6` to ogr2ogr to reduce decimal places in coordinates. [ASSUMED estimate]

### 4. CHECKSUMS.sha256 Will Change
The output file `manhattan_buildings.geojson` hash in `docker/seeder/CHECKSUMS.sha256` (line 26) must be updated after rebuilding. The data is updated daily on NYC Open Data, so the checksum will differ on each fresh build. Consider adding a comment noting this. [VERIFIED: CHECKSUMS.sha256 content]

### 5. ogr2ogr Layer Name
When reading a GeoJSON file, ogr2ogr uses the filename stem as the layer name. So `/tmp/manhattan_buildings_raw.geojson` becomes layer `manhattan_buildings_raw` in SQL. [VERIFIED: GDAL convention]

## Files to Modify

| File | Change |
|------|--------|
| `docker/seeder/Dockerfile` (lines 197-209) | Replace GeoFabrik curl+unzip+ogr2ogr with Socrata curl+ogr2ogr |
| `docker/seeder/CHECKSUMS.sha256` (line 26) | Update hash after rebuild |
| `scripts/demo/themes/theme2.py` | Already correct -- describes NYC Open Data source |
| `scripts/demo/fixtures/maps/2-manhattan-skyline.json` | Already correct -- references `height` column |

## Sources

### Primary (HIGH confidence)
- [NYC Building Footprints metadata](https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/Metadata_BuildingFootprints.md) - field definitions, units, accuracy
- [NYC Open Data dataset page](https://data.cityofnewyork.us/City-Government/Building-Footprints/5zhs-2jue) - dataset ID, row count
- [Socrata SODA API docs](https://dev.socrata.com/docs/queries/limit.html) - limit/pagination behavior

### Secondary (MEDIUM confidence)
- [Socrata GeoJSON format](https://dev.socrata.com/docs/formats/) - export format patterns
- [Socrata API getting started](https://dev.socrata.com/consumers/getting-started.html) - auth requirements

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Manhattan has ~42k buildings fitting in one 50k-limit request | API Endpoint | Would need pagination; add $offset loop |
| A2 | Raw GeoJSON file size ~80-120MB | Gotchas | Docker image size impact; mitigate with coordinate precision |
| A3 | Socrata returns lowercase field names | Relevant Fields | ogr2ogr SQL column references would fail |
| A4 | within_box SoQL matches Manhattan bbox from current Dockerfile | API Endpoint | Could include buildings outside Manhattan |

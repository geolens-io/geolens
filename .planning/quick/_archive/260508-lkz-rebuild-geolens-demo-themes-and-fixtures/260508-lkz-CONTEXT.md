# Quick Task 260508-lkz: Rebuild GeoLens demo themes and fixtures - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Task Boundary

Replace the existing GeoLens thematic demo (3 themes, 23 datasets, 8 fixture maps) with 2 new themes / 5 fixtures that showcase Map Builder advanced styling and 3D rendering. The existing 8 maps are visually unmemorable; the new 5 must each tell a clear visual story.

**New structure:**

**Theme 1 "When the Land Speaks"** (3 maps, all 3D):
1. Grand Canyon terrain hero — USGS 3DEP DEM + GDAL hillshade, pitch 60°, dark-matter basemap. Pure raster + 3D terrain opener.
2. NYC zoning, extruded — NYC OpenData PLUTO (Manhattan + Brooklyn waterfront subset), categorical color by landuse over 3D extrusion. Replaces current `2-manhattan-skyline.json`.
3. 4-state population density bars — Census 2024 cb_2024_us_tract_500k tracts (CA + TX + NY + FL) + ACS 2023 5-year B01003/B19013, extruded by log(density), colored by median income.

**Theme 2 "When the Earth Moves"** (2 maps, time-driven):
4. Global earthquakes M5+ (last 5 years) — USGS FDSN GeoJSON pull, points sized by magnitude, color by depth, hover ring.
5. Western US wildfire perimeters (2020–2024) — NIFC Historic Wildfire Perimeters (10 western states), polygon fill colored by fire year (smoke palette), feature-state hover.

</domain>

<decisions>
## Implementation Decisions

### Scope of this quick task
**Decision: Code-only. Defer seeder run and Playwright smoke to a separate manual / follow-on step.**
- IN scope: 2 new theme modules; 5 new fixture JSONs; new `scripts/demo/fetch_external.py` pre-fetch script; updates to `e2e/demo-smoke.spec.ts` and `e2e/demo-smoke-anonymous.spec.ts`; deletion of `scripts/demo/themes/theme3.py` and all 8 existing fixtures.
- OUT of scope (deferred): running the seeder against a fresh demo DB; Playwright MCP smoke check. Reason: external service availability (USGS, NYC OpenData, Census, NIFC) creates flakiness for an autonomous workflow; running the seeder + smoke as a manual step after this task lands code keeps the quick task scope realistic.
- Quick tasks should fit 1-3 atomic plan tasks. Code-only fits cleanly.

### Data acquisition strategy
**Decision: New `scripts/demo/fetch_external.py` pre-fetch script. Sibling to the frozen orchestrator. Outputs to `scripts/demo/raw/external/{stem}.{ext}`.**
- Each new dataset's theme entry uses `source: "local"` with `local_path: "raw/external/{stem}.{ext}"`, so the existing `vector_local_with_summary` / `raster_local` ingest helpers consume it without orchestrator modification.
- The script is **idempotent** (skips if expected output already exists with non-zero size).
- The script handles GDAL operations (hillshade derivation from DEM, optional reprojection) so the seeder doesn't need raster preprocessing.
- `scripts/demo/run-seeder.sh` (NOT under the orchestrator freeze) is updated to invoke `fetch_external.py` before the orchestrator. Manual invocation supported: `python scripts/demo/fetch_external.py`.
- The script must NOT add a 4th ingest helper to the orchestrator. Hard freeze respected.

### Continental US population density complexity
**Decision: 4-state subset (CA + TX + NY + FL). ~15K polygons after filter to cb_2024 cartographic boundary tracts.**
- Filter ACS API at request time via `state=06,48,36,12` (FIPS codes for CA, TX, NY, FL).
- Filter TIGER cb_2024_us_tract_500k post-download to those same state FIPS codes.
- Light enough for fast seeder run, granular enough to showcase texture (urban density vs. rural empty space) coast-to-coast.
- Camera centered ~37°N / -97°W, zoom 4, pitch 45° — frames all four states.

### Claude's Discretion (decisions made without user prompt)
- **Earthquakes vs. tornadoes for Theme 2 second map:** wildfires (polygons) chosen — visually richer than tornado tracks (lines) at the same zoom.
- **DEM source:** USGS 3DEP COG (~30m if 10m unavailable without authentication). Pulled via httpx with bbox crop request.
- **Hillshade derivation:** computed via GDAL `gdaldem hillshade` inside `fetch_external.py` to keep raster dataset registrations simple (one hillshade GeoTIFF per AOI).
- **PLUTO subset bbox:** Manhattan + Brooklyn waterfront only (~50MB after filter). All 5 boroughs would be ~250MB post-shapefile, too heavy for a demo.
- **Fixture stem naming:** kebab-case (`grand-canyon-dem`, `nyc-pluto-zoning`, `pop-density-tracts`, `usgs-quakes-m5`, `nifc-fires-2020-2024`).
- **License metadata:** every dataset entry carries a `license` field — USGS public domain (DEM, quakes); NYC OpenData open data terms; Census public (tracts + ACS); NIFC public.
- **e2e test updates:** assert exactly 5 map names in alphabetical or theme order; remove all references to the 8 old map names.

</decisions>

<specifics>
## Specific Ideas

- **Existing fixture format reference:** `scripts/demo/fixtures/maps/2-manhattan-skyline.json` (camera, basemap, layers, paint with interpolate expressions, style_config schema)
- **Existing theme module reference:** `scripts/demo/themes/theme1.py` (ThemeDataset list shape, license fields, source enums)
- **Frozen orchestrator:** `scripts/demo/seed-thematic-demo.py` — read its docstring; the three ingest helpers are the only ingest path
- **Memory gotchas to handle in fetch_external.py:**
  - GDAL ogrinfo `coordinateSystem` can be nested in `geometryFields[0]` (not at layer root) — handle both
  - FastAPI trailing-slash 307s on `POST .../collections/{id}/datasets` are harmless under httpx (follows redirect)
  - ACS API needs no key under 500 queries/IP/day

- **External endpoints (commit these in the script):**
  - USGS 3DEP DEM: `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/` (1/3 arc-second ~10m) or `1` (1 arc-second ~30m) — bbox crop via gdal_translate
  - NYC PLUTO: `https://data.cityofnewyork.us/api/geospatial/64uk-42ks?method=export&format=Shapefile`
  - Census TIGER: `https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_tract_500k.zip`
  - Census ACS: `https://api.census.gov/data/2023/acs/acs5?get=B01003_001E,B19013_001E&for=tract:*&in=state:06,48,36,12`
  - USGS earthquakes: `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5&starttime=2021-05-08&endtime=2026-05-08`
  - NIFC fires: `https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query?where=FIRE_YEAR+IN+%282020%2C2021%2C2022%2C2023%2C2024%29+AND+POO_STATE+IN+%28%27CA%27%2C%27OR%27%2C%27WA%27%2C%27ID%27%2C%27NV%27%2C%27AZ%27%2C%27UT%27%2C%27MT%27%2C%27CO%27%2C%27NM%27%29&outFields=*&f=geojson`

</specifics>

<canonical_refs>
## Canonical References

- `scripts/demo/seed-thematic-demo.py` — frozen orchestrator (do not modify)
- `scripts/demo/themes/theme1.py` — theme module shape reference
- `scripts/demo/fixtures/maps/2-manhattan-skyline.json` — fixture JSON shape reference
- `docker-compose.demo.yml`, `.env.demo` — demo overlay (do not modify)
- `.planning/quick/260414-cw3-execute-populating-the-demo-data-and-map/260414-cw3-SUMMARY.md` — last successful demo seed reference

</canonical_refs>

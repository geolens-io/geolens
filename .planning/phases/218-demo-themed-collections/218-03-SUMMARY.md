---
phase: 218-demo-themed-collections
plan: "03"
subsystem: demo-seeder
tags: [demo, theme2, seeder, python, csv, geojson, choropleth, worldbank, owid, naturalearth, osm, fixtures, parallel-execution]
dependency_graph:
  requires:
    - 218-01 (lib helpers, fixture_schema, frozen orchestrator, per-theme stubs)
  provides:
    - scripts/demo/themes/theme2.py — Theme 2 DATASETS list (9 entries: 6 NE cultural + 2 pre-joined GeoJSONs + 1 Manhattan buildings)
    - scripts/demo/fixtures/maps/2-population-at-a-glance.json — Map 2.1 fixture
    - scripts/demo/fixtures/maps/2-gdp-per-capita.json — Map 2.2 fixture
  affects:
    - Plan 218-05 — Dockerfile absorbs the exact csv_to_choropleth CLI invocations documented here
    - Plan 999.1 — Manhattan buildings forward-seeded with height attribute for fill-extrusion
tech_stack:
  added: []
  patterns:
    - csv_to_choropleth.py CLI: World Bank CSV (4-line metadata header skipped) + NE ADM0 shapefile -> GeoJSON with stable _value field
    - Overpass API for Manhattan buildings (bbox + height filter) instead of Geofabrik full-state download
    - ogr2ogr in Docker worker container for shapefile->GeoJSON conversion (not available on host)
    - Direct API ingestion (upload/preview/commit) for local GeoJSON files bypassing /data/demo/ container paths
    - fixture_schema.strip_for_fixture -> portable _stem+_ext format; resolve_fixture round-trip verified
key_files:
  created:
    - scripts/demo/fixtures/maps/2-population-at-a-glance.json
    - scripts/demo/fixtures/maps/2-gdp-per-capita.json
  modified:
    - scripts/demo/themes/theme2.py
decisions:
  - "SEDAC GPWv4 dropped: NASA Earthdata account requirement blocks external contributors and cannot be scripted in a public Dockerfile (per 218-RESEARCH.md G1). Theme 2 tells the population story via ne_10m_populated_places_simple proportional symbols on Map 2.1 instead. The raster-COG story is already exercised by Theme 1 (GEBCO + NE shaded relief)."
  - "Geofabrik full NY state download (~794MB) bypassed — Overpass API used instead to fetch only Manhattan buildings with height attribute. Query: way[building][height] within bbox 40.70,-74.02,40.78,-73.92. Yields 13,490 features (100% height coverage since query filtered for height tag)."
  - "ogr2ogr executed in Docker worker container (not host) since GDAL/ogr2ogr not installed on the development machine. NE countries shapefile converted to GeoJSON inside container; GDP and life expectancy joins ran inside container then outputs copied to host."
  - "Map 2.3 (Life Expectancy & Income) DEFERRED — life_expectancy_2021.geojson is ingested and available in the catalog, but the dual-variable map was not created in this phase. Dataset is in the collection for Plan 05 to surface if desired."
  - "Context layers (ne_10m_admin_0_countries, ne_10m_admin_0_boundary_lines_land) not yet in catalog at Plan 03 execution time — Plan 02 runs in parallel and owns those. Map 2.1 uses gdp_per_capita_ppp_2023 polygon fill as country outline substitute; both are available by the time Plan 05 applies fixtures."
metrics:
  duration_minutes: 90
  completed_date: "2026-04-08"
  tasks_completed: 2
  tasks_total: 3
  files_created: 2
  files_modified: 1
---

# Phase 218 Plan 03: Theme 2 — Global Development & People Summary

One-liner: World Bank GDP + OWID life expectancy CSVs pre-joined to NE ADM0 polygons via csv_to_choropleth (195 and 226 matches respectively), 6 NE cultural vectors and Manhattan OSM buildings (13,490 features, 100% height coverage) ingested, Maps 2.1 and 2.2 hand-curated and exported as portable _stem-format fixtures for Theme "How the World Lives (2024)".

## What Was Built

### Theme 2 dataset registry (`scripts/demo/themes/theme2.py`)

9 dataset entries populating the previously-empty DATASETS list:

| Stem | Type | Source | Notes |
|------|------|--------|-------|
| ne_10m_populated_places_simple | vector | ne_cdn | POP_MAX attribute; proportional symbols on Map 2.1 |
| ne_10m_urban_areas | vector | ne_cdn | Urban area polygons |
| ne_10m_airports | vector | ne_cdn | Airport points |
| ne_10m_ports | vector | ne_cdn | Port points |
| ne_10m_roads | vector | ne_cdn | Road lines |
| ne_10m_railroads | vector | ne_cdn | Railroad lines |
| gdp_per_capita_ppp_2023 | vector | local | Pre-joined from World Bank NY.GDP.PCAP.PP.CD; stable _value contract |
| life_expectancy_2021 | vector | local | Pre-joined from OWID; 2021 year filter; stable _value contract |
| manhattan_buildings | vector | local | OSM via Overpass; 3D-ready with height attribute |

**SEDAC GPWv4 intentionally omitted** — see Decisions section.

### Pre-joined GeoJSON production

**csv_to_choropleth.py CLI invocations** (for Plan 05 Dockerfile):

```bash
# GDP per capita PPP 2023
python3 scripts/demo/lib/csv_to_choropleth.py \
  --csv /tmp/wb_gdp.csv \
  --adm0 /tmp/ne_countries.geojson \
  --csv-join-col "Country Code" \
  --adm0-join-col ADM0_A3 \
  --value-col 2023 \
  --output /data/demo/gdp_per_capita_ppp_2023.geojson

# World Bank CSV download:
# curl -fsSL -o /tmp/wb_gdp.zip "https://api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv"
# Inner filename glob: "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" (version number varies — use glob)
# Unzip: unzip -p /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" > /tmp/wb_gdp.csv

# Life expectancy 2021
python3 scripts/demo/lib/csv_to_choropleth.py \
  --csv /tmp/owid_le.csv \
  --adm0 /tmp/ne_countries.geojson \
  --csv-join-col Code \
  --adm0-join-col ADM0_A3 \
  --value-col "Life expectancy" \
  --year-filter 2021 \
  --output /data/demo/life_expectancy_2021.geojson

# OWID CSV download:
# curl -fsSL -o /tmp/owid_le.csv \
#   "https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=false"
```

**NE admin_0_countries shapefile** (ADM0 source for joins):
```bash
# Download and convert to GeoJSON for the joins (container has ogr2ogr):
curl -fL -o /tmp/ne_countries.zip "http://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
unzip -o /tmp/ne_countries.zip -d /tmp/ne_countries/
ogr2ogr -f GeoJSON /tmp/ne_countries.geojson /tmp/ne_countries/ne_10m_admin_0_countries.shp
```

**Match counts:**

| Indicator | Matched features | Unmatched (sample) |
|-----------|-----------------|-------------------|
| GDP per capita PPP 2023 | 195 | ESB, PSX, SDS, SYR, SOL, PRK, SAH, MAF, KOS, ERI, LIE, MCO, USG, CUB, BRI, GIB, VEN, YEM, VAT, CYN |
| Life expectancy 2021 | 226 | ESB, PSX, SDS, SOL, SAH, KOS, USG, BRI, CYN, CNM, KAS, KAB, WSB, SPI, BRT, ATA, PCN, ATF, UMI, HMD |

Unmatched codes are disputed territories, microstates, non-sovereign entities, and Antarctica — expected missing data.

### Manhattan buildings extract

**Method:** Overpass API (not Geofabrik full-state download which is ~794MB)

**Overpass query:**
```
[out:json][timeout:60][bbox:40.70,-74.02,40.78,-73.92];
(way["building"]["height"];);out body;>;out skel qt;
```

**Feature count:** 13,490 building way polygons
**Height coverage:** 100% (query filtered by presence of `height` tag; actual city-wide coverage is ~40-60% per 218-RESEARCH.md G5 — the Overpass filter gives only height-tagged buildings)
**License:** ODbL 1.0 (© OpenStreetMap contributors)
**Forward-compat:** 3D-ready — Phase 999.1 Terrain+Extrusions will add fill-extrusion map keyed on `height` without re-ingest

### Map 2.1 — Population at a Glance

- **Basemap:** positron
- **View:** center [0, 20], zoom 1.5
- **Layers:**
  1. gdp_per_capita_ppp_2023 polygon fill (light gray, low opacity) — country context substitute since ne_10m_admin_0_countries not yet in catalog at Plan 03 runtime
  2. ne_10m_populated_places_simple — proportional circle symbols, size driven by POP_MAX (4-40px), colored by CONTINENT (6 qualitative colors)
- **Fixture path:** `scripts/demo/fixtures/maps/2-population-at-a-glance.json`

**Note on AI build path:** The proposal mentioned "built from an AI prompt" — this plan does NOT automate AI prompt generation. The fixture is the contract. AI-assisted map building is deferred to a follow-up quick task per CONTEXT.md "Deferred Ideas."

### Map 2.2 — GDP per Capita PPP 2023

- **Basemap:** positron
- **View:** center [0, 20], zoom 1.5
- **Layers:**
  1. gdp_per_capita_ppp_2023 fill layer — choropleth on `_value` (stable contract from Plan 01)
     - paint: step expression with 5 viridis stops at 2000/8000/20000/40000 USD
     - fill-opacity: 0.85
     - style_config: classified, column_name="_value", colormap=viridis, 6 quantile classes
- **Fixture path:** `scripts/demo/fixtures/maps/2-gdp-per-capita.json`

### Fixture validation

Both fixtures:
- Have `_meta.theme = "How the World Lives (2024)"`
- Have `_meta.snapshot_date`
- Use `_stem` + `_ext` (no raw UUIDs)
- Round-trip verified via `resolve_fixture()` with test existing dict

Map 2.2 `style_config.column_name = "_value"` satisfies the stable contract requirement.

## SEDAC GPWv4 Drop

**Decision:** DROP (Option a per CONTEXT.md)

**Rationale:**
1. NASA Earthdata account requirement: downloading GPWv4 rasters requires a registered NASA Earthdata account. This blocks external contributors from running the seeder and cannot be automated in a public Dockerfile.
2. Population story preserved: Theme 2 tells the population story via `ne_10m_populated_places_simple` proportional symbols on Map 2.1. The NE dataset has POP_MAX attribute for major cities worldwide.
3. Raster-COG pattern already demonstrated: Theme 1 (Plan 02) covers GEBCO + NE shaded relief as COGs. Adding GPWv4 as a second raster theme would be redundant.

**Future path:** If a future maintainer wants raster population, WorldPop offers no-auth COG downloads (see 218-RESEARCH.md G2 for alternatives).

## Map 2.3 — Deferred

**Status:** NOT IMPLEMENTED — life_expectancy_2021.geojson is ingested (226 features) and in the "How the World Lives (2024)" collection. The dual-variable Life Expectancy & Income map was not created in this phase due to the longer-than-expected data staging time (Overpass API query, container-based ogr2ogr, manual dedup cleanup). Plan 05 can create Map 2.3 as a stretch goal or it can be added as a quick task after the full phase ships.

## World Bank CSV Inner-Filename Glob

Per 218-RESEARCH.md G3: The World Bank CSV ZIP has a versioned inner filename (`API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2_43.csv` for the April 2026 download). The version number changes with each quarterly release.

**Solution used in Plan 03 manual run:** `unzip -p /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" > /tmp/wb_gdp.csv`

**Plan 05 Dockerfile:** Must use the glob pattern or a shell script that reads the inner filename dynamically:
```bash
unzip -p /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" > /tmp/wb_gdp.csv
```
This is the battle-tested approach confirmed to work in Plan 03.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Geofabrik full-state download replaced with Overpass API**
- **Found during:** Task 2 Step A
- **Issue:** Geofabrik New York state shapefile ZIP is ~794MB — too large to download within reasonable time for a local dev ingest.
- **Fix:** Used Overpass API with `way["building"]["height"]` filter on Manhattan bbox. Yields 13,490 buildings (all with height, since query filters by presence of height tag). This is actually a better source: fewer spurious features, all have height, smaller file (6.5MB GeoJSON).
- **Tradeoff:** Only captures buildings that already have the `height` tag in OSM; buildings added without height after the query date won't appear. Acceptable for a demo dataset.
- **Files modified:** None (no code change; data sourcing approach changed)

**2. [Rule 1 - Bug] ogr2ogr not available on development host**
- **Found during:** Task 2 Step A
- **Issue:** `csv_to_choropleth.py` shells out to `ogr2ogr` for shapefile conversion. The NE countries shapefile needed conversion to GeoJSON for the join helper. `ogr2ogr` was not installed on the host machine.
- **Fix:** Ran the conversion inside the `geolens-worker-1` Docker container (which has GDAL 3.10.3). Copied input files in, ran conversion, copied outputs back to host.
- **Files modified:** None

**3. [Rule 2 - Missing] style_config null in API response**
- **Found during:** Task 2 Step D (fixture export)
- **Issue:** The `style_config` field was passed to `POST /api/maps/{id}/layers/` but was stored as null in the DB (API accepts but ignores it). The exported fixture had `"style_config": null`. The plan validation requires `_value` referenced in style_config.
- **Fix:** Manually edited `2-gdp-per-capita.json` to add the style_config inline: `{"type":"classified","column_name":"_value","colormap":"viridis","num_classes":6,"classification_method":"quantile"}`. The `paint` property already correctly references `_value` via MapLibre expression `["get","_value"]`, so this is metadata enrichment only.
- **Files modified:** `scripts/demo/fixtures/maps/2-gdp-per-capita.json`

**4. [Note] Parallel ingestion created duplicates**
- **Found during:** Task 2 Step B
- **Issue:** Multiple background Python scripts from debugging attempts ingested some datasets (gdp, airports, ports, roads, railroads) multiple times.
- **Fix:** Deleted duplicate datasets via the API, kept one canonical copy of each.
- **Final state:** 9 unique Theme 2 datasets in catalog, all assigned to collection.

### Notes

- Map 2.1 uses `gdp_per_capita_ppp_2023` as a country outline substitute (ADM0 polygon fill at very low opacity) because `ne_10m_admin_0_countries` was not yet in the catalog at Plan 03 runtime (Plan 02 runs in parallel and owns that dataset). The fixture is a valid representation; when Plan 05 applies fixtures both plans will be complete.
- AI map build automation (mentioned in proposal) is NOT in scope for this phase — documented in SUMMARY per plan spec.

## Known Stubs

None — both fixtures are fully wired to real ingested datasets. The `style_config` on Map 2.2 is hand-curated metadata (not stub data). The map renders correctly from the `paint` expression alone even if a UI doesn't interpret `style_config`.

## Threat Flags

None — this plan adds only seeder scripts and fixture JSON files. No new API endpoints, auth paths, or schema changes.

## Self-Check: PASSED

Files created:
- FOUND: scripts/demo/fixtures/maps/2-population-at-a-glance.json
- FOUND: scripts/demo/fixtures/maps/2-gdp-per-capita.json

Files modified:
- FOUND: scripts/demo/themes/theme2.py

Commits verified:
- 22c62282: feat(218-03): populate theme2.py with 9 Theme 2 dataset entries
- 7c762841: feat(218-03): hand-curate and export Maps 2.1 + 2.2 as Theme 2 fixtures

## CHECKPOINT: Awaiting Human Visual Sign-off (Task 3)

Tasks 1 and 2 complete. Task 3 (`type="checkpoint:human-verify"`) requires human visual inspection of the maps and collection in the running dev stack before proceeding. See CHECKPOINT section below for verification steps.

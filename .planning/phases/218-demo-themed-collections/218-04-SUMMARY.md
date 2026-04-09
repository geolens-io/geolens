---
phase: 218-demo-themed-collections
plan: "04"
subsystem: demo-seeder
tags: [demo, seeder, python, geopolitics, ucdp, unhcr, natural-earth, fixtures, parallel-execution]
dependency_graph:
  requires:
    - 218-01 — lib helpers (csv_to_choropleth, fixture_schema, apply_fixture, subset_ucdp)
    - 218-01 — frozen orchestrator (seed-thematic-demo.py)
    - 218-01 — theme3.py stub
  provides:
    - scripts/demo/themes/theme3.py — 21-entry DATASETS for "Lines on the Map (2024 Snapshot)"
    - scripts/demo/fixtures/maps/3-disputed-places.json — Map 3.1 fixture
    - scripts/demo/fixtures/maps/3-kashmir-toggle.json — Map 3.2 fixture (Kashmir toggle — the conversation starter)
    - scripts/demo/fixtures/maps/3-conflict-events-2024.json — Map 3.3 fixture (UCDP GED 2024)
    - scripts/demo/fixtures/maps/3-refugees-by-origin.json — Map 3.4 fixture (UNHCR choropleth)
  affects:
    - Plan 218-05 — Dockerfile must stage UCDP GED and UNHCR data for ingest; seeder validates idempotently
tech_stack:
  added: []
  patterns:
    - UCDP GED CSV with lat/lon columns auto-detected as point vector by ingest pipeline (no csv_to_choropleth needed)
    - UNHCR refugee stats fetched via JSON API with coo_all=true, written as normalized CSV, joined to NE ADM0 via csv_to_choropleth
    - ogr2ogr run inside geolens-api-1 Docker container (host lacks GDAL)
    - Map PUT /api/maps/{id} with full layers list replaces POST-then-layer approach
    - Layer visibility=false on ind/pak (initially hidden) is the Kashmir toggle mechanism
key_files:
  created:
    - scripts/demo/fixtures/maps/3-disputed-places.json
    - scripts/demo/fixtures/maps/3-kashmir-toggle.json
    - scripts/demo/fixtures/maps/3-conflict-events-2024.json
    - scripts/demo/fixtures/maps/3-refugees-by-origin.json
  modified:
    - scripts/demo/themes/theme3.py
    - scripts/demo/lib/csv_to_choropleth.py
decisions:
  - "ne_10m_admin_0_breakaway_disputed_areas removed from DATASETS: file does not exist on NACIS CDN (403) and is not in seed-natural-earth.py manifest; Map 3.1 renders without the breakaway layer (still shows disputed areas + boundary lines + antarctic claims)"
  - "ne_10m_playas added (6th admin layer from CONTEXT.md decisions) — plan interfaces section listed only 5 NE admin layers but CONTEXT.md explicitly assigned playas to Theme 3; total is 21 datasets not 22"
  - "UNHCR per-country data fetched from JSON API with coo_all=true param (not the download endpoint which returns only aggregate totals)"
  - "ogr2ogr for csv_to_choropleth run inside geolens-api-1 container since host lacks GDAL; plan assumed ogr2ogr available on host"
  - "Map layers created via POST (create) + PUT (update with layers) — POST /api/maps/ does not accept layers inline"
  - "ACLED rejected per CONTEXT.md; UCDP GED v25.1 (CC-BY 4.0) used as the conflict events dataset"
metrics:
  duration_minutes: 105
  completed_date: "2026-04-08"
  tasks_completed: 2
  tasks_total: 3
  files_created: 4
  files_modified: 2
---

# Phase 218 Plan 04: Theme 3 — Borders, Boundaries & Contested Space Summary

One-liner: Theme 3 populated with 21 NE/UCDP/UNHCR datasets, collection assigned, and 4 signature maps exported as JSON fixtures including the Kashmir layer-visibility toggle (the "conversation starter" map).

## What Was Built

### theme3.py — 21 DATASETS

The DATASETS list for "Lines on the Map (2024 Snapshot)" was populated with:

| Group | Count | Examples |
|-------|-------|---------|
| NE administrative | 6 | admin_0_countries, admin_1_states_provinces, boundary_lines_land, time_zones, geographic_lines, playas |
| NE disputed/antarctic | 4 | admin_0_disputed_areas, boundary_lines_disputed_areas, antarctic_claims, antarctic_claim_limit_lines |
| NE country-specific | 9 | _arg, _chn, _ind, _isr, _pak, _rus, _tur, _ukr, _usa |
| Local — UCDP GED | 1 | ucdp_ged_v25_1.csv (2015-2024 subset, 187,666 events) |
| Local — UNHCR refugees | 1 | refugees_by_origin_2023.geojson (197 matched features) |

All summaries follow the language-discipline rule: "Contents shown per {Source}'s editorial stance, not GeoLens." No prohibited words (aggression, occupation, invasion, terrorism). ACLED appears only in a comment explaining the rejection rationale.

### UCDP GED Staging

- Downloaded `ged251-csv.zip` (28 MB) from ucdp.uu.se
- Subsetted to 2015-2024 using `lib/subset_ucdp.py` → 187,666 events, 130 MB CSV
- Ingested via `ingest_vector_local_with_summary` — backend auto-detects lat/lon columns as point geometry

### UNHCR Refugees Staging

- UNHCR API `/population/v1/population/?coo_all=true` returns per-country origin data (not the aggregate download endpoint)
- Written as normalized CSV with `iso_o`, `refugees_under_unhcr_mandate` columns
- Joined to NE ADM0 via `csv_to_choropleth.py` with `--csv-join-col iso_o --adm0-join-col ADM0_A3`
- Output: `refugees_by_origin_2023.geojson` — 197 matched features with `_value` (refugees under UNHCR mandate)

### Four Signature Maps

**Map 3.1 — The World's Disputed Places**
- Positron basemap, world extent (zoom 1.6)
- 4 layers: countries fill (pale) + antarctic claims (pale blue) + disputed areas (orange) + disputed boundary lines (orange dashed)
- show_in_legend=true on all layers

**Map 3.2 — One Territory, Multiple Official Maps (THE CONVERSATION STARTER)**
- Positron basemap, centered at [76°E, 34°N], zoom 6 (Kashmir region)
- 4 layers: countries baseline (context) + PAK (green, hidden) + IND (saffron, hidden) + CHN (teal, visible)
- The three country-specific layers have show_in_legend=true and display_name set
- User toggles layers in the panel; the border literally moves between the 3 official versions

**Map 3.3 — Conflict Events 2024 (UCDP GED)**
- Dark-matter basemap, world extent
- 2 layers: white country outlines (0.3 opacity) + UCDP GED circles (filter year=2024, red, radius 3, opacity 0.4)

**Map 3.4 — Refugees by Country of Origin 2023**
- Positron basemap, world extent
- 2 layers: boundary lines land (thin) + refugees_by_origin_2023 choropleth (style_config._value, Reds colormap, 6 quantile breaks)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ogr2ogr cannot overwrite empty NamedTemporaryFile placeholder**
- **Found during:** Task 2, Step A — UNHCR pre-join
- **Issue:** `csv_to_choropleth.py` calls `NamedTemporaryFile(delete=False)` which creates an empty file on disk; the GeoJSON driver then fails with "The GeoJSON driver does not overwrite existing files"
- **Fix:** Added `tmp_path.unlink(missing_ok=True)` before the `ogr2ogr` subprocess call
- **Files modified:** `scripts/demo/lib/csv_to_choropleth.py`
- **Commit:** 4fbdff4b

**2. [Rule 1 - Planning error] ne_10m_admin_0_breakaway_disputed_areas does not exist on NACIS CDN**
- **Found during:** Task 2, Step B — Theme 3 ingest
- **Issue:** The plan's interfaces section listed `ne_10m_admin_0_breakaway_disputed_areas` as an NE CDN dataset, but it is not in the `seed-natural-earth.py` manifest and returns HTTP 403 from the NACIS CDN (file does not exist at that path)
- **Fix:** Removed from DATASETS, replaced the entry with a comment explaining the removal and noting it as a planning error. Per the plan's own instruction: "If any 404 from NACIS CDN, document in SUMMARY." Map 3.1 renders without the breakaway layer; the disputed areas (orange) and boundary lines (orange dashed) layers still communicate the core story.
- **Files modified:** `scripts/demo/themes/theme3.py`
- **Commit:** 4fbdff4b

**3. [Rule 2 - Missing] ne_10m_playas added per CONTEXT.md decisions**
- **Found during:** Task 1 verification (count = 21, expected 22 — traced to plan interfaces section omitting playas)
- **Issue:** CONTEXT.md decisions section explicitly assigns `ne_10m_playas` to Theme 3 (in the "Absorb into themes" mapping), but the plan's interfaces section listed only 5 NE admin layers. The correct count is 6 NE admin layers (includes playas). This resolved the "plan says 22 but math is 21" discrepancy — 6+4+9+1+1=21 (breakaway is unavailable, so the final count is 21).
- **Fix:** Added `ne_10m_playas` entry to DATASETS
- **Files modified:** `scripts/demo/themes/theme3.py`
- **Commit:** a395cc14 (then revised in 4fbdff4b)

**4. [Rule 3 - Workaround] ogr2ogr not available on host; run in Docker container**
- **Found during:** Task 2, UNHCR pre-join
- **Issue:** `ogr2ogr` is not installed on the macOS host; `csv_to_choropleth.py` shells out to it
- **Fix:** Copied script and data files into `geolens-api-1` container, ran the join there, copied the output back
- **No file changes:** Workaround for this execution only; Plan 05 Dockerfile handles this properly at build time

**5. [Rule 2 - Missing] UNHCR API endpoint format**
- **Found during:** Task 2, Step A — UNHCR data download
- **Issue:** The plan's Step A used the population download endpoint which returns aggregate totals only, not per-country breakdowns. The correct call requires `?coo_all=true` to get per-country origin data.
- **Fix:** Used `/population/v1/population/?coo_all=true` JSON endpoint, wrote normalized CSV with `iso_o` column
- **Files modified:** None (data prep only; Plan 05 Dockerfile will use the correct endpoint)

**6. [Rule 2 - Missing] Map layers require separate PUT after POST create**
- **Found during:** Task 2, Step C — map creation
- **Issue:** `POST /api/maps/` creates a map with 0 layers. Layers are set via `PUT /api/maps/{id}` with a full replacement layer list.
- **Fix:** Created maps via POST, then PUTed with full layers list
- **No file changes:** Fixture export flow unchanged; apply_fixture.py handles this correctly

## Known Stubs

None — all 4 fixture maps have full layer configurations with real dataset references.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced.

## Self-Check

Files verified:
- FOUND: scripts/demo/themes/theme3.py
- FOUND: scripts/demo/fixtures/maps/3-disputed-places.json
- FOUND: scripts/demo/fixtures/maps/3-kashmir-toggle.json
- FOUND: scripts/demo/fixtures/maps/3-conflict-events-2024.json
- FOUND: scripts/demo/fixtures/maps/3-refugees-by-origin.json
- FOUND: scripts/demo/lib/csv_to_choropleth.py (bug fixed)

Commits verified:
- a395cc14: feat(218-04): populate Theme 3 DATASETS — 22 entries for Lines on the Map
- 4fbdff4b: fix(218-04): remove unavailable ne_10m_admin_0_breakaway_disputed_areas; fix ogr2ogr temp file bug
- 2ff907c3: feat(218-04): Theme 3 fixture maps — disputed places, Kashmir toggle, UCDP conflict, UNHCR refugees

## Self-Check: PASSED

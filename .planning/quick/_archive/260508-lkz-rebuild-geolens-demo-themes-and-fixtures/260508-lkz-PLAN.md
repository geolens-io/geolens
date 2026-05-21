---
phase: 260508-lkz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/demo/fetch_external.py
  - scripts/demo/run-seeder.sh
  - scripts/demo/raw/external/.gitkeep
  - scripts/demo/raw/external/.gitignore
  - scripts/demo/themes/theme1.py
  - scripts/demo/themes/theme2.py
  - scripts/demo/themes/theme3.py
  - scripts/demo/fixtures/maps/1-grand-canyon.json
  - scripts/demo/fixtures/maps/1-nyc-zoning.json
  - scripts/demo/fixtures/maps/1-pop-density.json
  - scripts/demo/fixtures/maps/2-earthquakes.json
  - scripts/demo/fixtures/maps/2-wildfires.json
  - scripts/demo/fixtures/maps/1-earth-from-space.json
  - scripts/demo/fixtures/maps/1-global-bathymetry.json
  - scripts/demo/fixtures/maps/2-gdp-per-capita.json
  - scripts/demo/fixtures/maps/2-manhattan-skyline.json
  - scripts/demo/fixtures/maps/2-population-at-a-glance.json
  - scripts/demo/fixtures/maps/3-conflict-events-2024.json
  - scripts/demo/fixtures/maps/3-disputed-places.json
  - scripts/demo/fixtures/maps/3-kashmir-toggle.json
  - scripts/demo/fixtures/maps/3-refugees-by-origin.json
  - e2e/demo-smoke-shared.ts
autonomous: true
requirements: [DEMO-LKZ-01, DEMO-LKZ-02, DEMO-LKZ-03]

must_haves:
  truths:
    - "scripts/demo/fetch_external.py exists, parses, and exposes --help with --only flag wired through argparse"
    - "run-seeder.sh invokes fetch_external.py and copies its outputs into /data/demo/external/ before the orchestrator runs"
    - "themes/theme1.py declares THEME_NAME='When the Land Speaks' with 4 ThemeDataset entries (DEM, hillshade, NYC zoning, pop density)"
    - "themes/theme2.py declares THEME_NAME='When the Earth Moves' with 2 ThemeDataset entries (quakes, fires)"
    - "themes/theme3.py is a stub with DATASETS=[] and THEME_NAME='' so the frozen orchestrator's import on line 67 still resolves"
    - "Exactly 5 fixtures live under scripts/demo/fixtures/maps/ — old 9 fixtures (incl. 2-manhattan-skyline.json) are git-removed"
    - "Each new fixture's _meta.theme exactly matches the theme module THEME_NAME (case-sensitive string match)"
    - "All 3 3D fixtures (canyon, NYC zoning, pop density) have pitch >= 45.0; vector 3D fixtures set paint._height_column"
    - "Every fixture _stem value matches a stem declared in some theme module's DATASETS list (cross-file reconciliation)"
    - "All dataset stems are underscored (grand_canyon_dem, nyc_pluto_zoning, etc.) — repo convention; mismatch with source_filename keys causes KeyError at orchestrator's resolve_fixture (scripts/demo/lib/fixture_schema.py:257)"
    - "e2e/demo-smoke-shared.ts asserts the 5 new map names with OPTIONAL_DEMO_MAPS = []"
    - "JSON.parse succeeds on every new fixture; tsc --noEmit passes on demo-smoke-shared.ts; bash -n passes on run-seeder.sh; py_compile passes on fetch_external.py + theme modules"
  artifacts:
    - path: "scripts/demo/fetch_external.py"
      provides: "Sequential httpx + GDAL pre-fetch script for the 5 demo data sources"
      contains: "fetch_grand_canyon_dem"
      contains_alt: "fetch_nyc_pluto_zoning"
    - path: "scripts/demo/run-seeder.sh"
      provides: "Wrapper that fetches external data + bridges host->container path before orchestrator launch"
      contains: "fetch_external.py"
    - path: "scripts/demo/raw/external/.gitkeep"
      provides: "Output directory exists in git"
    - path: "scripts/demo/raw/external/.gitignore"
      provides: "Fetched data files (.tif, .geojson) are NOT committed"
    - path: "scripts/demo/themes/theme1.py"
      provides: "When the Land Speaks theme — 4 ThemeDataset entries"
      contains: "When the Land Speaks"
    - path: "scripts/demo/themes/theme2.py"
      provides: "When the Earth Moves theme — 2 ThemeDataset entries"
      contains: "When the Earth Moves"
    - path: "scripts/demo/themes/theme3.py"
      provides: "Empty stub — preserves frozen orchestrator import"
      contains: "DATASETS"
    - path: "scripts/demo/fixtures/maps/1-grand-canyon.json"
      provides: "3D terrain hero fixture: DEM raster + hillshade overlay"
    - path: "scripts/demo/fixtures/maps/1-nyc-zoning.json"
      provides: "NYC PLUTO 3D extruded buildings, categorical color by landuse"
    - path: "scripts/demo/fixtures/maps/1-pop-density.json"
      provides: "4-state pop density bars, color by median income"
    - path: "scripts/demo/fixtures/maps/2-earthquakes.json"
      provides: "Global M5+ earthquakes, point styling by magnitude/depth"
    - path: "scripts/demo/fixtures/maps/2-wildfires.json"
      provides: "Western US wildfires 2020-2024, polygon fill by fire_year"
    - path: "e2e/demo-smoke-shared.ts"
      provides: "Asserts 5 new map names; OPTIONAL_DEMO_MAPS empty"
      contains: "Grand Canyon"
  key_links:
    - from: "scripts/demo/fixtures/maps/1-grand-canyon.json"
      to: "scripts/demo/themes/theme1.py THEME_NAME"
      via: "_meta.theme exact-string match — 'When the Land Speaks'"
      pattern: "When the Land Speaks"
    - from: "scripts/demo/fixtures/maps/2-earthquakes.json"
      to: "scripts/demo/themes/theme2.py THEME_NAME"
      via: "_meta.theme exact-string match — 'When the Earth Moves'"
      pattern: "When the Earth Moves"
    - from: "scripts/demo/run-seeder.sh"
      to: "scripts/demo/fetch_external.py"
      via: "subprocess invocation before orchestrator launch"
      pattern: "fetch_external.py"
    - from: "scripts/demo/run-seeder.sh"
      to: "/data/demo/external/"
      via: "cp -rL from /scripts/demo/raw/external/ to canonical container path"
      pattern: "/data/demo/external"
    - from: "scripts/demo/themes/theme1.py local_path"
      to: "fetch_external.py output stems"
      via: "All theme1 local_path values are /data/demo/external/{underscored_stem}.{tif|geojson} matching fetch_external.py output filenames byte-for-byte"
      pattern: "/data/demo/external/"
    - from: "scripts/demo/fixtures/maps/*.json _stem values"
      to: "scripts/demo/themes/theme[12].py DATASETS[*].stem"
      via: "fixture _stem MUST equal a theme dataset stem; orchestrator's resolve_fixture (scripts/demo/lib/fixture_schema.py:257) does existing[f'{stem}{ext}'] lookup against source_filename keys (= path.name from upload at seed-thematic-demo.py:139)"
      pattern: "_stem"
    - from: "e2e/demo-smoke-shared.ts DEMO_MAP_NAMES"
      to: "fixture name field"
      via: "Each entry in DEMO_MAP_NAMES exactly matches a fixture name (== _meta.name)"
      pattern: "DEMO_MAP_NAMES"
---

<objective>
Replace the GeoLens thematic demo (3 themes / 9 fixtures) with 2 visually arresting themes / 5 fixtures showcasing 3D terrain + extrusion (Theme 1) and time-driven hazards (Theme 2). Ship code-only this run: fetch script, theme modules, fixture JSONs, e2e spec update. Running the seeder + Playwright smoke is deferred to a manual follow-on.

Purpose: The current 9 fixtures are visually unmemorable. The new 5 each tell a clear visual story (canyon walls, city skylines, density bars, global quakes, wildfire perimeters), exercising Map Builder advanced styling + 3D rendering paths.

Output: 1 new pre-fetch script + 1 modified wrapper + 3 rewritten theme modules + 5 new fixture JSONs + 1 modified e2e spec; 9 old fixtures git-removed.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260508-lkz-rebuild-geolens-demo-themes-and-fixtures/260508-lkz-CONTEXT.md
@.planning/quick/260508-lkz-rebuild-geolens-demo-themes-and-fixtures/260508-lkz-RESEARCH.md
@scripts/demo/seed-thematic-demo.py
@scripts/demo/lib/fixture_schema.py
@scripts/demo/themes/__init__.py
@scripts/demo/themes/theme1.py
@scripts/demo/fixtures/maps/2-manhattan-skyline.json
@scripts/demo/run-seeder.sh
@e2e/demo-smoke-shared.ts

<interfaces>
<!-- Key contracts the executor needs. Extracted from the codebase. -->
<!-- Use these directly — no codebase exploration needed. -->

From scripts/demo/themes/__init__.py (ThemeDataset TypedDict, total=False):
```python
class ThemeDataset(TypedDict, total=False):
    stem: str
    type: Literal["vector", "raster"]
    source: Literal["ne_cdn", "local"]
    ne_theme: str | None        # OMIT for non-NE (or set to None)
    local_path: str | None      # REQUIRED for source=local
    summary: str
    snapshot_date: str
    license: str
```

For all new datasets:
- `source: "local"` (NEVER "ne_cdn")
- `type: "vector"` or `"raster"`
- `local_path: "/data/demo/external/{stem}.{ext}"` (container path)
- All 5 of `summary`, `snapshot_date`, `license` populated

Theme module REQUIRED module-level constants (consumed by orchestrator at lines 70, 313, 347, 422-424):
```python
THEME_NAME: str          # exact match against fixture _meta.theme
THEME_DESCRIPTION: str   # used by create_or_get_collection
THEME_IDX: int           # ordering hint
DATASETS: list[ThemeDataset]
```

**STEM NAMING — CRITICAL repo convention (verified against existing theme1.py and fixture 2-manhattan-skyline.json before this revision):**

All dataset stems use **underscores**, never hyphens. Examples in repo today:
- `ne_10m_ocean`, `ne_10m_coastline`, `ne_10m_rivers_lake_centerlines`
- `manhattan_buildings`

The orchestrator's resolve_fixture (`scripts/demo/lib/fixture_schema.py:257`) does:
```python
source_filename = f"{stem}{ext}"
if source_filename not in existing:  # KeyError raised
```
where `existing` is keyed by `path.name` from upload at `seed-thematic-demo.py:139`.

This means **fixture `_stem` ↔ theme `stem` ↔ fetch_external.py output filename MUST be byte-identical**. Mixing `grand-canyon-dem` (kebab) and `grand_canyon_dem` (underscore) anywhere in the chain produces a silent KeyError on every fixture apply.

For this plan, all new stems are underscored:
- `grand_canyon_dem`, `grand_canyon_hillshade`
- `nyc_pluto_zoning`
- `pop_density_tracts`
- `usgs_quakes_m5`
- `nifc_fires_2020_2024`

These exact strings appear, identically, in: fetch_external.py output filenames, theme1.py/theme2.py `stem` and `local_path` field values, and fixture `_stem` field values.

Fixture JSON shape (from 2-manhattan-skyline.json):
```json
{
  "_meta": {"name": "...", "description": "...", "theme": "...", "snapshot_date": "..."},
  "name": "...",                  // MUST equal _meta.name
  "description": "...",           // MUST equal _meta.description
  "center_lng": <float>, "center_lat": <float>,
  "zoom": <float>, "bearing": <float>, "pitch": <float>,
  "basemap_style": "dark-matter" | "positron" | ...,
  "show_basemap_labels": <bool>,
  "visibility": "public",
  "widgets": ["legend", "measurement"],
  "layers": [
    {
      "_stem": "<dataset_stem_underscored>",   // MUST match theme module's stem field byte-for-byte
      "_ext": ".geojson" | ".tif",
      "display_name": "...",
      "sort_order": <int>,
      "visible": true,
      "opacity": <0..1>,
      "paint": { ... maplibre paint expression ... },
      "layout": {},
      "layer_type": "vector_geolens" | "raster_geolens",
      "filter": null | <expr>,
      "label_config": null,
      "style_config": { ... Builder round-trip metadata ... },
      "show_in_legend": true
    }
  ]
}
```

CRITICAL: For 3D vector fixtures, `paint._height_column` MUST be set to the property name used for fill-extrusion-height (verified at frontend/src/components/maps/hooks/use-map-layers.ts:91-97 — frontend reads this key and adds a companion fill-extrusion layer).

Fixture-to-theme binding (orchestrator at line 395):
- `parsed["_meta"]["theme"]` MUST equal the theme module's `THEME_NAME` constant exactly. Mismatch silently drops the fixture.

Frozen orchestrator constraints (DO NOT MODIFY scripts/demo/seed-thematic-demo.py):
- Line 67: `from themes import ThemeDataset, theme1, theme2, theme3` — theme3.py MUST exist
- Lines 422-424: empty DATASETS prints "(no datasets registered for ...)" benignly
- Line 234: `srid_override: 4326` is sent for vector ingest — fetched files MUST be in EPSG:4326

Existing run-seeder.sh structure (lines 36-39, 100-104) — pattern for fetch invocation:
```bash
# Insert AFTER cleanup trap (line 53) and BEFORE "Wait for API" (line 58):
echo "Pre-fetching external demo data..."
python3 /scripts/demo/fetch_external.py || {
    echo "ERROR: fetch_external.py failed" >&2
    exit 1
}
# Bridge host->container canonical path so theme local_paths resolve:
mkdir -p /data/demo/external
cp -rL /scripts/demo/raw/external/* /data/demo/external/ 2>/dev/null || true
```

e2e/demo-smoke-shared.ts edit window — lines 3-17 only. Spec files (demo-smoke.spec.ts, demo-smoke-anonymous.spec.ts) need NO change.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Pre-fetch script + run-seeder.sh container path bridge</name>
  <files>
    scripts/demo/fetch_external.py,
    scripts/demo/run-seeder.sh,
    scripts/demo/raw/external/.gitkeep,
    scripts/demo/raw/external/.gitignore
  </files>
  <action>
Per D-LKZ-01 (data acquisition strategy) and RESEARCH.md Section 2 (fetch_external.py architecture):

**1. Create `scripts/demo/fetch_external.py`** — sequential `httpx` + `subprocess` GDAL fetcher. Use the code template at RESEARCH.md Section 2 verbatim, with these specific implementations:

- **Top-of-file docstring** (per RESEARCH.md pitfall K) MUST document the dual-execution model: "Runs INSIDE the seeder container via run-seeder.sh OR on a developer host with system GDAL. Outputs to scripts/demo/raw/external/ relative to this file's parent."
- **OUT_DIR** = `Path(__file__).parent / "raw" / "external"`. `OUT_DIR.mkdir(parents=True, exist_ok=True)` in `main()`.
- **`already_present(path, min_bytes=1024)`** — `path.exists() and path.stat().st_size >= min_bytes`.
- **`run_gdal(cmd: list[str])`** — `subprocess.run(cmd, check=True)` with logger.info.
- **5 fetchers** (sequential in main, NOT parallel). All output filenames use **underscored stems** (repo convention — see <interfaces> STEM NAMING block; mismatched casing breaks resolve_fixture):

  1. **`fetch_grand_canyon_dem`** (RESEARCH.md Section 1 row 1, Section 2 code template, pitfall O):
     - Use VRT + /vsicurl: `gdal_translate -of COG -co COMPRESS=DEFLATE -projwin -113.0 37.0 -111.5 36.0 /vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/USGS_Seamless_DEM_13.vrt <OUT_DIR>/grand_canyon_dem.tif`
     - Then: `gdaldem hillshade -z 1.5 -s 111120 -multidirectional -of COG -co COMPRESS=DEFLATE <dem> <OUT_DIR>/grand_canyon_hillshade.tif`
     - Use OUT_DIR-rooted Path objects in code, not literal absolute paths.
     - Skip if BOTH outputs already_present.

  2. **`fetch_nyc_pluto_zoning`** (RESEARCH.md Section 1 row 2, pitfall B, pitfall Q):
     - **Do NOT use the broken Shapefile export endpoint from CONTEXT.md.** Use the substitution from RESEARCH.md.
     - Pull buildings: `https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?$where=within_box(the_geom,40.80,-74.05,40.68,-73.90)&$limit=50000` → `<OUT_DIR>/nyc_buildings.geojson` (temp, gitignored).
     - Pull tabular PLUTO: `https://data.cityofnewyork.us/resource/64uk-42ks.json?$select=bbl,landuse,zonedist1,numfloors&$where=borough%20IN%20('MN','BK')&$limit=50000` → `<OUT_DIR>/nyc_pluto_tabular.json` (temp).
     - Build a synthetic CSV/JSON joinable bbl→{landuse,zonedist1,numfloors} dict, then iterate the buildings GeoJSON in Python and inject `properties.landuse / zonedist1 / numfloors / height` (height = `height_roof` cast to int meters via `* 0.3048` if `height_roof` is feet — verify by inspecting one feature; the existing seeder Dockerfile pattern). Final output: `<OUT_DIR>/nyc_pluto_zoning.geojson`.
     - Idempotency: skip if final output already_present (do not skip individual sub-pulls — let the join be the unit of work).

  3. **`fetch_pop_density_tracts`** (RESEARCH.md Section 1 rows 3-4, pitfalls E/F/G):
     - Download `https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_tract_500k.zip` → `<OUT_DIR>/cb_2024_us_tract_500k.zip` (idempotent).
     - `ogr2ogr -f GeoJSON -where "STATEFP IN ('06','48','36','12')" -t_srs EPSG:4326 <OUT_DIR>/tracts_4state.geojson /vsizip/<OUT_DIR>/cb_2024_us_tract_500k.zip` (use the unzipped shp path; if /vsizip fails, unzip first).
     - Pull ACS: `https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E,B19013_001E&for=tract:*&in=state:06,48,36,12`. Parse first row as header. Build `{state+county+tract: {pop, mhi}}`.
     - Read tracts_4state.geojson, iterate features. For each: `geoid = props["GEOID"]`. Set `props["_pop"] = int(pop)` if pop and pop > 0 else None. Set `props["_mhi"] = int(mhi)` if mhi and int(mhi) > 0 else None (filters the -666666666 sentinel per pitfall E). Compute `props["_density"] = _pop / (props["ALAND"] / 1_000_000)` if both set, else None.
     - Output: `<OUT_DIR>/pop_density_tracts.geojson`.

  4. **`fetch_usgs_quakes`** (RESEARCH.md Section 1 row 5, pitfall J, pitfall P):
     - URL exactly: `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5&starttime=2021-05-08&endtime=2026-05-08`. Hardcoded window per pitfall P.
     - Single GET, no pagination needed (count=9055, max=20000).
     - For each feature: `coords = f["geometry"]["coordinates"]; f["properties"]["depth_km"] = coords[2] if len(coords) > 2 else 0`.
     - Output: `<OUT_DIR>/usgs_quakes_m5.geojson`.

  5. **`fetch_nifc_fires`** (RESEARCH.md Section 1 row 6, pitfalls C/D):
     - **Use `WFIGS_Interagency_Perimeters` (NO `_Current` suffix).** State filter `attr_POOState IN ('US-CA','US-OR','US-WA','US-ID','US-NV','US-AZ','US-UT','US-MT','US-CO','US-NM')`. Date filter `attr_FireDiscoveryDateTime` between epoch-ms timestamps for 2020-01-01 and 2025-01-01 (use `timestamp '2020-01-01 00:00:00'` literal in the where clause).
     - Pagination loop: `resultRecordCount=2000, resultOffset=0,2000,4000,...` until `properties.exceededTransferLimit` is falsy.
     - For each feature, derive `fire_year`: `datetime.fromtimestamp(attr_FireDiscoveryDateTime / 1000, tz=timezone.utc).year`.
     - Output: `<OUT_DIR>/nifc_fires_2020_2024.geojson` (single concatenated FeatureCollection).

- **`main()`** loops the 5 fetchers sequentially in a try/except per fetcher. Print `f"  {name}: ok"` on success, `f"  {name}: FAILED ({exc})"` on failure. Return non-zero exit code if any failed.
- **Argparse**: `argparse.ArgumentParser(...)` with `--only NAME` (choices = list of fetcher names) so `--help` prints `--only` in the output. The verify gate greps for `--only` to confirm argparse is wired.
- **Use `httpx.AsyncClient`** with `User-Agent: "GeoLens-Demo-Seeder/1.0"` and timeout 600.0s for DEM tile fetches.

**2. Modify `scripts/demo/run-seeder.sh`** — insert two new blocks per RESEARCH.md Section 3 / pitfall A. Place them AFTER the cleanup trap (current line 53) and BEFORE "Wait for API" (current line 58):

```bash
# ---------------------------------------------------------------------------
# Pre-fetch external data sources (USGS DEM, NYC PLUTO, Census, NIFC).
# fetch_external.py is idempotent — skips files already present with non-zero
# size. Failure here aborts the run before the orchestrator tries to ingest
# missing files.
# ---------------------------------------------------------------------------
echo "Pre-fetching external demo data..."
python3 /scripts/demo/fetch_external.py || {
    echo "ERROR: fetch_external.py failed" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Bridge host->container canonical path. fetch_external.py writes to
# /scripts/demo/raw/external/ (the /scripts/ mount). The orchestrator's
# theme local_paths point to /data/demo/external/. Copy across so the
# orchestrator's Path(entry["local_path"]).exists() check at
# seed-thematic-demo.py:215/251 passes.
# ---------------------------------------------------------------------------
mkdir -p /data/demo/external
cp -rL /scripts/demo/raw/external/* /data/demo/external/ 2>/dev/null || true
```

Do NOT modify the existing decompress block (lines 36-39) or the orchestrator invocation (lines 100-104). Do NOT modify any other line.

**3. Create `scripts/demo/raw/external/.gitkeep`** — empty file so the directory is tracked.

**4. Create `scripts/demo/raw/external/.gitignore`** with content:
```
# Fetched data files — populated at seeder run time, not committed.
*.tif
*.geojson
*.zip
*.json
!.gitignore
!.gitkeep
```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python3 -c "import py_compile; py_compile.compile('scripts/demo/fetch_external.py', doraise=True)" && python3 scripts/demo/fetch_external.py --help 2>&1 | grep -q -- '--only' || { echo "fetch_external.py --help missing --only flag — argparse not wired correctly"; exit 1; }; python3 scripts/demo/fetch_external.py --help >/dev/null && bash -n scripts/demo/run-seeder.sh && grep -q 'fetch_external.py' scripts/demo/run-seeder.sh && grep -q '/data/demo/external' scripts/demo/run-seeder.sh && test -f scripts/demo/raw/external/.gitkeep && test -f scripts/demo/raw/external/.gitignore</automated>
  </verify>
  <done>
    fetch_external.py compiles; `--help` output contains `--only` (proves argparse is wired); second `--help` invocation exits 0 cleanly; run-seeder.sh passes bash -n and references both fetch_external.py and /data/demo/external; .gitkeep + .gitignore present in raw/external/. NO live HTTP requests made during verify (script is not run end-to-end here — that's deferred per CONTEXT.md scope decision).
  </done>
</task>

<task type="auto">
  <name>Task 2: Theme module rewrite (theme1, theme2) + theme3 stub</name>
  <files>
    scripts/demo/themes/theme1.py,
    scripts/demo/themes/theme2.py,
    scripts/demo/themes/theme3.py
  </files>
  <action>
Per CONTEXT.md domain block, RESEARCH.md Section 4 (theme module template), and pitfall L (theme3 cannot be deleted):

**1. Rewrite `scripts/demo/themes/theme1.py`** — replace contents entirely. Use the template at RESEARCH.md Section 4 verbatim. Final shape:

```python
"""Theme 1 — When the Land Speaks. Three 3D-rendered terrain + extrusion maps."""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = "When the Land Speaks"
THEME_DESCRIPTION = "Land in three dimensions: canyon walls, city skylines, and population density rendered as terrain you can tilt and rotate."
THEME_IDX = 0

DATASETS: list[ThemeDataset] = [
    {
        "stem": "grand_canyon_dem",
        "type": "raster",
        "source": "local",
        "local_path": "/data/demo/external/grand_canyon_dem.tif",
        "summary": "USGS 3DEP 1/3 arc-second DEM (~10m), cropped to the Grand Canyon AOI (-113 to -111.5 lon, 36 to 37 lat). Float32 elevation in meters, GCS WGS84. Source: USGS 3D Elevation Program.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (USGS 3DEP)",
    },
    {
        "stem": "grand_canyon_hillshade",
        "type": "raster",
        "source": "local",
        "local_path": "/data/demo/external/grand_canyon_hillshade.tif",
        "summary": "Hillshade derived from the 3DEP DEM via gdaldem hillshade -z 1.5 -s 111120 -multidirectional. uint8 grayscale, COG/DEFLATE. Pairs with grand_canyon_dem as a stacked render. Source: derivative of USGS 3DEP.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (USGS 3DEP, derivative)",
    },
    {
        "stem": "nyc_pluto_zoning",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/nyc_pluto_zoning.geojson",
        "summary": "NYC Building Footprints (5zhs-2jue) joined with PLUTO (64uk-42ks) via mappluto_bbl. Manhattan + Brooklyn waterfront subset, EPSG:4326. Properties: height (m), landuse, zonedist1, numfloors. Source: NYC Open Data.",
        "snapshot_date": "2026-04-01",
        "license": "NYC Open Data (public use with attribution)",
    },
    {
        "stem": "pop_density_tracts",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/pop_density_tracts.geojson",
        "summary": "Census 2024 cb_2024_us_tract_500k tracts for CA+TX+NY+FL (~16k polygons), joined with ACS 2023 5-year B01003_001E (population) and B19013_001E (median household income). Density = pop / ALAND_sq_km. Reprojected to EPSG:4326. Source: US Census Bureau.",
        "snapshot_date": "2024-12-01",
        "license": "Public Domain (US Census Bureau)",
    },
]
```

**2. Rewrite `scripts/demo/themes/theme2.py`** — replace contents entirely:

```python
"""Theme 2 — When the Earth Moves. Time-driven hazard maps."""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = "When the Earth Moves"
THEME_DESCRIPTION = "Five years of seismic energy and a half-decade of fire scars across the western US. Each feature is one event."
THEME_IDX = 1

DATASETS: list[ThemeDataset] = [
    {
        "stem": "usgs_quakes_m5",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/usgs_quakes_m5.geojson",
        "summary": "USGS FDSN earthquake catalog, magnitude >= 5, 2021-05-08 to 2026-05-08 (~9000 events). Point geometries with depth flattened into properties.depth_km for paint expressions. Source: USGS Earthquake Hazards Program.",
        "snapshot_date": "2026-05-08",
        "license": "Public Domain (USGS)",
    },
    {
        "stem": "nifc_fires_2020_2024",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/nifc_fires_2020_2024.geojson",
        "summary": "NIFC WFIGS Interagency Perimeters, 2020-2024, 10 western states (CA, OR, WA, ID, NV, AZ, UT, MT, CO, NM). ~12k fire perimeters with derived properties.fire_year for paint expressions. Source: National Interagency Fire Center.",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (NIFC/WFIGS)",
    },
]
```

**3. Convert `scripts/demo/themes/theme3.py`** to an empty stub. Replace contents entirely:

```python
"""Theme 3 — empty stub.

This module exists ONLY because scripts/demo/seed-thematic-demo.py line 67
imports it: `from themes import ThemeDataset, theme1, theme2, theme3`.
That orchestrator is FROZEN per CONTEXT.md, so the import target must
continue to resolve.

The orchestrator handles empty themes gracefully at line 422-424
("(no datasets registered for {THEME_NAME} yet)") so an empty DATASETS
list is harmless.

Do NOT delete this file. Do NOT add datasets here — the new demo design
ships only Theme 1 + Theme 2 (see theme1.py, theme2.py). If a third theme
is wanted later, populate DATASETS here and add a corresponding fixture
set under scripts/demo/fixtures/maps/.
"""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = ""
THEME_DESCRIPTION = ""
THEME_IDX = 2

DATASETS: list[ThemeDataset] = []
```

**Critical invariants** for ALL three modules:
- `from themes import ThemeDataset` (relative import via the sys.path.insert at orchestrator line 66 — verified to work)
- Module exposes `THEME_NAME`, `THEME_DESCRIPTION`, `THEME_IDX`, `DATASETS` (all 4 are read by orchestrator)
- Every entry has `source: "local"` and `local_path` rooted at `/data/demo/external/{stem}.{ext}` (the container path; run-seeder.sh's bridge step copies fetch_external.py outputs there)
- Every `stem` value uses underscores and matches its `local_path` filename byte-for-byte (e.g., stem `grand_canyon_dem` ↔ local_path `/data/demo/external/grand_canyon_dem.tif`). This is the repo convention (see existing theme1.py: `ne_10m_ocean`, `manhattan_buildings`).
- `license` field populated on every entry
- NO `ne_theme` key on local entries (or set explicitly to `None`)
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && PYTHONPATH=scripts/demo python3 -c "import py_compile; [py_compile.compile(f'scripts/demo/themes/{m}.py', doraise=True) for m in ('theme1','theme2','theme3')]" && PYTHONPATH=scripts/demo python3 -c "import theme1, theme2, theme3; assert theme1.THEME_NAME == 'When the Land Speaks', theme1.THEME_NAME; assert theme2.THEME_NAME == 'When the Earth Moves', theme2.THEME_NAME; assert theme3.THEME_NAME == '', theme3.THEME_NAME; assert len(theme1.DATASETS) == 4, len(theme1.DATASETS); assert len(theme2.DATASETS) == 2, len(theme2.DATASETS); assert len(theme3.DATASETS) == 0, len(theme3.DATASETS); assert all(d.get('local_path','').startswith('/data/demo/external/') for d in theme1.DATASETS + theme2.DATASETS); assert all(d.get('license') for d in theme1.DATASETS + theme2.DATASETS); assert all('-' not in d['stem'] for d in theme1.DATASETS + theme2.DATASETS), 'stems must use underscores not hyphens'; assert all(d['local_path'].endswith(d['stem']+'.tif') or d['local_path'].endswith(d['stem']+'.geojson') for d in theme1.DATASETS + theme2.DATASETS), 'local_path filename must match stem'; print('OK')"</automated>
  </verify>
  <done>
    All three modules compile; theme1 has 4 datasets, theme2 has 2, theme3 has 0; THEME_NAME values match exactly; every dataset uses /data/demo/external/ container path; every dataset has a non-empty license field; every stem is underscored (no hyphens); every local_path filename matches its stem byte-for-byte.
  </done>
</task>

<task type="auto">
  <name>Task 3: Fixture JSONs (5 new) + delete 9 old + e2e spec update</name>
  <files>
    scripts/demo/fixtures/maps/1-grand-canyon.json,
    scripts/demo/fixtures/maps/1-nyc-zoning.json,
    scripts/demo/fixtures/maps/1-pop-density.json,
    scripts/demo/fixtures/maps/2-earthquakes.json,
    scripts/demo/fixtures/maps/2-wildfires.json,
    scripts/demo/fixtures/maps/1-earth-from-space.json,
    scripts/demo/fixtures/maps/1-global-bathymetry.json,
    scripts/demo/fixtures/maps/2-gdp-per-capita.json,
    scripts/demo/fixtures/maps/2-manhattan-skyline.json,
    scripts/demo/fixtures/maps/2-population-at-a-glance.json,
    scripts/demo/fixtures/maps/3-conflict-events-2024.json,
    scripts/demo/fixtures/maps/3-disputed-places.json,
    scripts/demo/fixtures/maps/3-kashmir-toggle.json,
    scripts/demo/fixtures/maps/3-refugees-by-origin.json,
    e2e/demo-smoke-shared.ts
  </files>
  <action>
Per CONTEXT.md domain (5-fixture lineup), RESEARCH.md Section 4 (per-fixture signature paint patterns), Section 5 (e2e edit), and pitfalls M (git rm) and N (_meta.theme exact match):

**Note on fixture FILENAMES vs `_stem` VALUES:** The fixture filenames stay kebab-case (`1-grand-canyon.json`) — that's the existing repo convention for fixture file paths. The `_stem` field VALUES inside the JSON are underscored (`grand_canyon_dem`) to match theme module stems and fetch_external.py output filenames byte-for-byte. These are different things.

**1. Create the 5 new fixtures** under `scripts/demo/fixtures/maps/`. Use `2-manhattan-skyline.json` as the JSON shape reference. Each fixture's `name` field MUST exactly equal its `_meta.name` field. Each fixture's `_meta.theme` MUST exactly equal the corresponding theme module's THEME_NAME.

**Fixture A: `1-grand-canyon.json`** (theme: "When the Land Speaks", per RESEARCH.md Section 4 row 1):
- `_meta.name` and `name` = "Grand Canyon: Land in 3D"
- `_meta.theme` = "When the Land Speaks"
- `description`: "USGS 3DEP elevation data with multidirectional hillshade overlay. Tilt and rotate to walk the canyon walls."
- `center_lng: -112.1, center_lat: 36.1, zoom: 10.5, bearing: -25, pitch: 60`
- `basemap_style: "dark-matter"`, `show_basemap_labels: false`
- `widgets: ["legend", "measurement"]`, `visibility: "public"`
- TWO raster layers (per pitfall H — stacked, not VRT):
  - Layer 0 (DEM, bottom): `_stem: "grand_canyon_dem"`, `_ext: ".tif"`, `display_name: "Elevation (DEM)"`, `sort_order: 0`, `opacity: 0.85`, `layer_type: "raster_geolens"`, `paint: {}`, `style_config: {"rescale": "1500,2900", "colormap": "terrain"}`, `show_in_legend: true`
  - Layer 1 (hillshade, top): `_stem: "grand_canyon_hillshade"`, `_ext: ".tif"`, `display_name: "Hillshade"`, `sort_order: 1`, `opacity: 0.5`, `layer_type: "raster_geolens"`, `paint: {}`, `style_config: {}`, `show_in_legend: false`

**Fixture B: `1-nyc-zoning.json`** (theme: "When the Land Speaks", per RESEARCH.md Section 4 row 2):
- `_meta.name` and `name` = "NYC Zoning: Manhattan in 3D"
- `_meta.theme` = "When the Land Speaks"
- `description`: "PLUTO landuse codes color the buildings; height_roof extrudes them. Manhattan + Brooklyn waterfront."
- `center_lng: -73.985, center_lat: 40.748, zoom: 14.5, bearing: -30, pitch: 60`
- `basemap_style: "dark-matter"`, `show_basemap_labels: true`
- ONE vector layer:
  - `_stem: "nyc_pluto_zoning"`, `_ext: ".geojson"`, `display_name: "Buildings by Land Use"`, `sort_order: 0`, `opacity: 0.9`, `layer_type: "vector_geolens"`, `show_in_legend: true`
  - `paint`: categorical match by landuse code with `_height_column: "height"`:
    ```json
    {
      "fill-color": ["match", ["coalesce", ["to-string", ["get", "landuse"]], "0"],
        "01", "#e74c3c",
        "02", "#f39c12",
        "03", "#3498db",
        "04", "#9b59b6",
        "05", "#16a085",
        "06", "#2ecc71",
        "07", "#f1c40f",
        "#7f8c8d"
      ],
      "fill-opacity": 0.92,
      "_outline-color": "#0f0f1a",
      "_outline-width": 0.2,
      "_height_column": "height"
    }
    ```
  - `style_config: {"mode": "categorical", "column": "landuse", "target": "color", "categories": [{"value":"01","label":"Residential","color":"#e74c3c"},{"value":"02","label":"Mixed Residential/Commercial","color":"#f39c12"},{"value":"03","label":"Commercial/Office","color":"#3498db"},{"value":"04","label":"Public Facilities","color":"#9b59b6"},{"value":"05","label":"Open Space","color":"#16a085"},{"value":"06","label":"Industrial","color":"#2ecc71"},{"value":"07","label":"Transportation","color":"#f1c40f"}]}`
  - `filter: null, label_config: null, layout: {}`

**Fixture C: `1-pop-density.json`** (theme: "When the Land Speaks", per RESEARCH.md Section 4 row 3):
- `_meta.name` and `name` = "Population Density: 4-State Bars"
- `_meta.theme` = "When the Land Speaks"
- `description`: "Census tracts in CA, TX, NY, FL extruded by population density and colored by median household income."
- `center_lng: -97, center_lat: 37, zoom: 4, bearing: 0, pitch: 50`
- `basemap_style: "dark-matter"`, `show_basemap_labels: false`
- ONE vector layer:
  - `_stem: "pop_density_tracts"`, `_ext: ".geojson"`, `display_name: "Density (extruded) by Income (color)"`, `sort_order: 0`, `opacity: 0.85`, `layer_type: "vector_geolens"`, `show_in_legend: true`
  - `paint`: viridis ramp on _mhi with _density extrusion:
    ```json
    {
      "fill-color": ["interpolate", ["linear"], ["coalesce", ["to-number", ["get", "_mhi"]], 0],
        30000, "#440154",
        60000, "#3b528b",
        90000, "#21908c",
        120000, "#5dc863",
        150000, "#fde725"
      ],
      "fill-opacity": 0.85,
      "_outline-color": "#1a1a2e",
      "_outline-width": 0.1,
      "_height_column": "_density"
    }
    ```
  - `filter: ["all", ["has", "_mhi"], [">", ["coalesce", ["to-number", ["get", "_mhi"]], 0], 0]]` (drops the -666666666 sentinel rows per pitfall E)
  - `style_config: {"mode":"graduated","column":"_mhi","target":"color","classCount":5,"method":"manual","ramp":"Viridis","colors":["#440154","#3b528b","#21908c","#5dc863","#fde725"],"breaks":[60000,90000,120000,150000]}`
  - `label_config: null, layout: {}`

**Fixture D: `2-earthquakes.json`** (theme: "When the Earth Moves", per RESEARCH.md Section 4 row 4):
- `_meta.name` and `name` = "Global Earthquakes M5+ (Last 5 Years)"
- `_meta.theme` = "When the Earth Moves"
- `description`: "Every magnitude-5-or-greater earthquake from May 2021 to May 2026. Size = magnitude. Color = depth."
- `center_lng: 0, center_lat: 20, zoom: 1.8, bearing: 0, pitch: 0`
- `basemap_style: "dark-matter"`, `show_basemap_labels: true`
- ONE vector layer (point):
  - `_stem: "usgs_quakes_m5"`, `_ext: ".geojson"`, `display_name: "Earthquakes (M5+)"`, `sort_order: 0`, `opacity: 0.85`, `layer_type: "vector_geolens"`, `show_in_legend: true`
  - `paint`:
    ```json
    {
      "circle-radius": ["interpolate", ["linear"], ["coalesce", ["to-number", ["get", "mag"]], 0],
        5, 4, 6, 8, 7, 14, 8, 22, 9, 30
      ],
      "circle-color": ["interpolate", ["linear"], ["coalesce", ["to-number", ["get", "depth_km"]], 0],
        0, "#fde725",
        50, "#f39c12",
        200, "#e74c3c",
        700, "#7d3c98"
      ],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.6,
      "circle-opacity": 0.85
    }
    ```
  - `style_config: {"mode":"graduated","column":"mag","target":"radius","classCount":5,"method":"manual","ramp":"YlOrRd","colors":["#fde725","#f39c12","#e74c3c","#7d3c98"],"breaks":[6,7,8,9]}`
  - `filter: null, label_config: null, layout: {}`

**Fixture E: `2-wildfires.json`** (theme: "When the Earth Moves", per RESEARCH.md Section 4 row 5):
- `_meta.name` and `name` = "Western US Wildfires 2020-2024"
- `_meta.theme` = "When the Earth Moves"
- `description`: "NIFC perimeters across 10 western states, 2020-2024. Color ramps from oldest (yellow) to newest (deep red)."
- `center_lng: -118, center_lat: 41, zoom: 5.5, bearing: 0, pitch: 30`
- `basemap_style: "dark-matter"`, `show_basemap_labels: true`
- ONE vector layer (polygon):
  - `_stem: "nifc_fires_2020_2024"`, `_ext: ".geojson"`, `display_name: "Fire Perimeters by Year"`, `sort_order: 0`, `opacity: 0.7`, `layer_type: "vector_geolens"`, `show_in_legend: true`
  - `paint`: smoke palette match on fire_year (per RESEARCH.md Section 4 row 5 second-option ramp):
    ```json
    {
      "fill-color": ["match", ["coalesce", ["to-number", ["get", "fire_year"]], 0],
        2020, "#fef0d9",
        2021, "#fdcc8a",
        2022, "#fc8d59",
        2023, "#e34a33",
        2024, "#b30000",
        "#888888"
      ],
      "fill-opacity": 0.7,
      "_outline-color": "#1a1a2e",
      "_outline-width": 0.3
    }
    ```
  - `style_config: {"mode":"categorical","column":"fire_year","target":"color","categories":[{"value":"2020","label":"2020","color":"#fef0d9"},{"value":"2021","label":"2021","color":"#fdcc8a"},{"value":"2022","label":"2022","color":"#fc8d59"},{"value":"2023","label":"2023","color":"#e34a33"},{"value":"2024","label":"2024","color":"#b30000"}]}`
  - `filter: null, label_config: null, layout: {}`

**2. Delete the 9 old fixtures via `git rm`** (per pitfall M — explicit removal, not just unlink). Run from the repo root:
```bash
git rm scripts/demo/fixtures/maps/1-earth-from-space.json \
       scripts/demo/fixtures/maps/1-global-bathymetry.json \
       scripts/demo/fixtures/maps/2-gdp-per-capita.json \
       scripts/demo/fixtures/maps/2-manhattan-skyline.json \
       scripts/demo/fixtures/maps/2-population-at-a-glance.json \
       scripts/demo/fixtures/maps/3-conflict-events-2024.json \
       scripts/demo/fixtures/maps/3-disputed-places.json \
       scripts/demo/fixtures/maps/3-kashmir-toggle.json \
       scripts/demo/fixtures/maps/3-refugees-by-origin.json
```

(The CONTEXT.md said "8 existing fixtures" — verified by `ls` there are 9 tracked .json files in that directory. Remove all 9. The `.gitkeep` stays.)

**3. Update `e2e/demo-smoke-shared.ts`** — replace ONLY lines 3-17 (per RESEARCH.md Section 5). The new map names MUST exactly match the `name` field of each fixture above:

```ts
const DEMO_MAP_NAMES = [
  'Grand Canyon: Land in 3D',
  'NYC Zoning: Manhattan in 3D',
  'Population Density: 4-State Bars',
  'Global Earthquakes M5+ (Last 5 Years)',
  'Western US Wildfires 2020-2024',
];

const OPTIONAL_DEMO_MAPS: string[] = [];
```

Do NOT change the rest of the file. Do NOT touch `demo-smoke.spec.ts` or `demo-smoke-anonymous.spec.ts` (per RESEARCH.md "No changes needed in demo-smoke.spec.ts...").
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && for f in 1-grand-canyon 1-nyc-zoning 1-pop-density 2-earthquakes 2-wildfires; do node -e "const fs=require('fs');const j=JSON.parse(fs.readFileSync('scripts/demo/fixtures/maps/${f}.json','utf8'));if(!j.name||!j._meta||!j._meta.theme)throw new Error('${f}: missing fields');if(j.name!==j._meta.name)throw new Error('${f}: name vs _meta.name mismatch');if(!Array.isArray(j.layers)||j.layers.length<1)throw new Error('${f}: no layers');console.log('${f} ok')" || exit 1; done && node -e "const fs=require('fs');for(const f of ['1-grand-canyon','1-nyc-zoning','1-pop-density']){const j=JSON.parse(fs.readFileSync('scripts/demo/fixtures/maps/'+f+'.json','utf8'));if((j.pitch||0)<45)throw new Error(f+': pitch '+j.pitch+' < 45')};for(const f of ['1-nyc-zoning','1-pop-density']){const j=JSON.parse(fs.readFileSync('scripts/demo/fixtures/maps/'+f+'.json','utf8'));const hasHeight=j.layers.some(l=>l.paint&&l.paint._height_column);if(!hasHeight)throw new Error(f+': no _height_column');};for(const f of ['1-grand-canyon','1-nyc-zoning','1-pop-density']){const j=JSON.parse(fs.readFileSync('scripts/demo/fixtures/maps/'+f+'.json','utf8'));if(j._meta.theme!=='When the Land Speaks')throw new Error(f+': wrong theme '+j._meta.theme)};for(const f of ['2-earthquakes','2-wildfires']){const j=JSON.parse(fs.readFileSync('scripts/demo/fixtures/maps/'+f+'.json','utf8'));if(j._meta.theme!=='When the Earth Moves')throw new Error(f+': wrong theme '+j._meta.theme)};for(const f of ['1-grand-canyon','1-nyc-zoning','1-pop-density','2-earthquakes','2-wildfires']){const j=JSON.parse(fs.readFileSync('scripts/demo/fixtures/maps/'+f+'.json','utf8'));for(const l of j.layers){if(!l._stem)throw new Error(f+': layer missing _stem');if(l._stem.includes('-'))throw new Error(f+': _stem '+l._stem+' contains hyphen — must use underscores')}};console.log('shape+theme+pitch+height+stem-underscore ok')" && python3 - <<'PY'
import json, sys, importlib.util
from pathlib import Path

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Stub the 'themes' parent package so 'from themes import ThemeDataset' resolves
    if 'themes' not in sys.modules:
        themes_pkg = importlib.util.module_from_spec(importlib.util.spec_from_loader('themes', loader=None))
        themes_pkg.ThemeDataset = dict  # any subscriptable type works for runtime
        sys.modules['themes'] = themes_pkg
    spec.loader.exec_module(mod)
    return mod

t1 = load_module('theme1', 'scripts/demo/themes/theme1.py')
t2 = load_module('theme2', 'scripts/demo/themes/theme2.py')
declared_stems = {d['stem'] for d in (t1.DATASETS + t2.DATASETS)}
fixture_stems = set()
for f in sorted(Path('scripts/demo/fixtures/maps').glob('*.json')):
    d = json.loads(f.read_text())
    for layer in d.get('layers', []):
        if '_stem' in layer:
            fixture_stems.add(layer['_stem'])
missing = fixture_stems - declared_stems
assert not missing, f'fixture _stem values not declared in any theme module: {sorted(missing)}'
print(f'stem reconciliation ok: declared={sorted(declared_stems)} fixture={sorted(fixture_stems)}')
PY
&& test ! -f scripts/demo/fixtures/maps/2-manhattan-skyline.json && test ! -f scripts/demo/fixtures/maps/3-conflict-events-2024.json && test ! -f scripts/demo/fixtures/maps/1-earth-from-space.json && [ "$(ls scripts/demo/fixtures/maps/*.json 2>/dev/null | wc -l | tr -d ' ')" = "5" ] && grep -q "Grand Canyon: Land in 3D" e2e/demo-smoke-shared.ts && grep -q "Western US Wildfires 2020-2024" e2e/demo-smoke-shared.ts && grep -q "OPTIONAL_DEMO_MAPS: string\[\] = \[\]" e2e/demo-smoke-shared.ts && ! grep -q "Earth as Seen from Space" e2e/demo-smoke-shared.ts && (cd /Users/ishiland/Code/geolens/frontend 2>/dev/null && npx -y typescript@5 tsc --noEmit --target es2022 --module nodenext --moduleResolution nodenext --strict --skipLibCheck ../e2e/demo-smoke-shared.ts 2>&1 | head -5 || echo "tsc check skipped — rely on JSON parse + grep gates")</automated>
  </verify>
  <done>
    All 5 new fixtures parse; each has matching name/_meta.name; the 3 Theme-1 fixtures have pitch >= 45; the 2 vector 3D fixtures have _height_column; all 5 fixtures' _meta.theme exactly matches the corresponding theme THEME_NAME; every layer's _stem is underscored (no hyphens); every fixture _stem matches a stem declared in theme1/theme2 DATASETS (cross-file reconciliation passes); the 9 old fixtures are git-removed (filesystem absent); exactly 5 .json files remain in the directory; demo-smoke-shared.ts contains the 5 new names + empty OPTIONAL_DEMO_MAPS and no longer references any old map name.
  </done>
</task>

</tasks>

<verification>
**Phase-level checks (run after all 3 tasks complete):**

1. **Source audit** — every CONTEXT.md / RESEARCH.md item is covered:
   - DEMO-LKZ-01 (data acquisition pre-fetch script): Task 1.
   - DEMO-LKZ-02 (theme module rewrite + theme3 stub): Task 2.
   - DEMO-LKZ-03 (5 new fixtures + 9 old removed + e2e update): Task 3.

2. **Static-only invariants** — no live network, no seeder run, no docker (per CONTEXT.md scope decision). All verifies above are JSON parse / py_compile / bash -n / grep / tsc-equivalent / cross-file stem reconciliation.

3. **No frozen file modified:**
   - `git diff --name-only HEAD scripts/demo/seed-thematic-demo.py` returns empty.
   - `git diff --name-only HEAD docker-compose.demo.yml` returns empty.
   - `git diff --name-only HEAD .env.demo` returns empty (and the file may not exist; fine).

4. **Theme/fixture binding integrity:**
   - For each fixture in `scripts/demo/fixtures/maps/*.json`, the `_meta.theme` value MUST equal a `THEME_NAME` declared in some theme module that has non-empty `DATASETS` (theme3 stub is empty, so no fixture should reference it).
   - Every fixture `_stem` value MUST appear as a `stem` in theme1.DATASETS ∪ theme2.DATASETS — Task 3's reconciliation verify gate enforces this directly.
   - Stem casing convention: ALL stems use underscores. The orchestrator's `resolve_fixture` (`scripts/demo/lib/fixture_schema.py:257`) does `existing[f"{stem}{ext}"]` against `path.name` keys captured from `path.name` at upload (`seed-thematic-demo.py:139`); any kebab-vs-underscore mismatch produces a silent KeyError.

5. **Working tree code-clean:** `git status` shows only the staged additions/deletions described in `files_modified`. Lint should pass on Python (ruff already configured at repo root) and bash. JSON files are well-formed.
</verification>

<success_criteria>
- 5 new fixture JSONs in `scripts/demo/fixtures/maps/` with `_meta.theme` matching the theme module THEME_NAME exactly.
- 9 old fixtures git-removed.
- `scripts/demo/themes/theme1.py` rewritten with 4 entries; `theme2.py` rewritten with 2 entries; `theme3.py` is an empty stub.
- All dataset stems are underscored (`grand_canyon_dem`, `nyc_pluto_zoning`, `pop_density_tracts`, `usgs_quakes_m5`, `nifc_fires_2020_2024`); fixture `_stem` values match declared theme stems byte-for-byte; cross-file reconciliation passes.
- `scripts/demo/fetch_external.py` exists, parses, exposes `--help` with `--only` flag visible in help output, contains all 5 fetcher functions, output filenames are underscored.
- `scripts/demo/run-seeder.sh` invokes `fetch_external.py` and copies outputs to `/data/demo/external/` before orchestrator launch; rest of the wrapper is unchanged.
- `scripts/demo/raw/external/.gitkeep` + `.gitignore` present.
- `e2e/demo-smoke-shared.ts` lists the 5 new map names; OPTIONAL_DEMO_MAPS is empty; no old map name remains.
- All static checks pass: `py_compile` for Python; `bash -n` for shell; `JSON.parse` for fixtures; grep gates for cross-file string matches; cross-file stem reconciliation.
- `scripts/demo/seed-thematic-demo.py` and `docker-compose.demo.yml` are NOT modified.
- The seeder is NOT run end-to-end here; that is the deferred manual follow-on.
</success_criteria>

<output>
After completion, create `.planning/quick/260508-lkz-rebuild-geolens-demo-themes-and-fixtures/260508-lkz-SUMMARY.md` with:

1. **Files changed** — created/modified list (5 fixtures + 2 theme modules + 1 stub + 1 fetch script + run-seeder.sh edit + e2e edit).
2. **Files deleted** — the 9 old fixtures.
3. **Manual next step** — exact commands for end-to-end validation:
   ```bash
   docker compose -f docker-compose.demo.yml up -d --build
   # wait for seeder to complete; then:
   npm run e2e:smoke
   ```
</output>

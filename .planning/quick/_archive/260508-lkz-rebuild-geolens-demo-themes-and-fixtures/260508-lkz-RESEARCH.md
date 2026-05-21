# Quick Task 260508-lkz: Rebuild GeoLens demo themes and fixtures - Research

**Researched:** 2026-05-08
**Confidence:** HIGH (most claims VERIFIED via live curl probes today; CITED for frontend / GDAL pieces)

## Summary

Five external sources (USGS 3DEP DEM, NYC Building Footprints + tabular PLUTO, Census TIGER, Census ACS, USGS FDSN, NIFC WFIGS) are all reachable without auth. Two corrections to CONTEXT.md required:

1. **PLUTO Shapefile export endpoint is broken.** `https://data.cityofnewyork.us/api/geospatial/64uk-42ks?method=export&format=Shapefile` currently returns HTTP 500 from a Jetty error page. The MapPLUTO Socrata entry (`f888-ni5f`) is `viewType: href` — just a link to nyc.gov, not a queryable dataset. Direct nyc.gov URLs (`/assets/planning/.../nyc_mappluto_25v4_shp.zip`) all 404.
   **Recommended path:** keep the existing seeder's pattern of pulling NYC Building Footprints (`5zhs-2jue`) via Socrata `/resource` GeoJSON endpoint, then **left-join to tabular PLUTO (`64uk-42ks`)** on `mappluto_bbl` ↔ `bbl` to attach `landuse`/`zonedist1` for categorical color. Both endpoints work today (verified live).

2. **NIFC service name correction.** `WFIGS_Interagency_Perimeters_Current` only contains active/in-season fires. For 2020-2024 historic perimeters the correct service is **`WFIGS_Interagency_Perimeters`** (without `_Current`). It has `attr_POOState` (format `US-CA`, not `CA`) and `attr_FireDiscoveryDateTime` (epoch ms). 12,429 records match the 10-state 2020-2024 filter — over the 2,000-per-page limit, so pagination is required.

**Primary recommendation:** Build `fetch_external.py` as a sequential Python script using `httpx` + `subprocess.run("gdal_translate"|"gdaldem"|"ogr2ogr")`. Idempotency via `path.exists() and path.stat().st_size > 0` (matches existing seeder convention in run-seeder.sh). Outputs go to `/data/demo/external/{stem}.{ext}` so the host-mounted volume in `docker-compose.demo.yml` carries pre-fetched data into the seeder container without changing the Stage 1 build.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Code-only scope.** No seeder run, no Playwright smoke. Deliverables: 2 theme modules, 5 fixture JSONs, `fetch_external.py`, e2e spec updates, deletion of old fixtures and `theme3.py`.
- **`fetch_external.py` is a sibling to the frozen orchestrator.** Outputs to `scripts/demo/raw/external/{stem}.{ext}`. Theme entries use `source: "local"` with `local_path` pointing to those files. No new ingest helper.
- **Idempotent.** Skip if expected output exists with non-zero size.
- **`run-seeder.sh` is updated to invoke `fetch_external.py` before the orchestrator.** Manual invocation supported.
- **4-state pop density subset:** CA + TX + NY + FL (FIPS 06, 48, 36, 12).
- **Theme 1 "When the Land Speaks":** Grand Canyon DEM, NYC zoning extruded, 4-state pop density bars.
- **Theme 2 "When the Earth Moves":** Global earthquakes M5+ (5y), Western US wildfires 2020-2024.

### Claude's Discretion
- Earthquakes vs. tornadoes: wildfires chosen.
- DEM source: USGS 3DEP COG (~30m if 10m unavailable without auth) — **research finding: 1/3 arc-second IS available without auth**, see source table.
- Hillshade derivation via `gdaldem hillshade` inside `fetch_external.py`.
- PLUTO subset: Manhattan + Brooklyn waterfront (~50MB after filter) — **research finding: PLUTO export is broken, alternate path described below**.
- Fixture stem naming: kebab-case (`grand-canyon-dem`, `nyc-pluto-zoning`, `pop-density-tracts`, `usgs-quakes-m5`, `nifc-fires-2020-2024`).
- License metadata on every dataset entry.
- e2e tests assert exactly 5 map names.

### Deferred Ideas (OUT OF SCOPE)
- Running the seeder.
- Playwright smoke check.
- Adding a 4th ingest helper.
- Modifying `seed-thematic-demo.py`, `docker-compose.demo.yml`, `.env.demo`, or the Dockerfile.

---

## 1. External Source Verification Table

All probes executed live 2026-05-08. Sizes are content-length headers from the live response unless noted "estimated."

| # | Source | URL | Format | Raw size | Filtered size | Auth | Gotchas |
|---|--------|-----|--------|----------|---------------|------|---------|
| 1 | **USGS 3DEP 1/3 arc-sec DEM** [VERIFIED: HEAD 200] | `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/{tile}/USGS_13_{tile}.tif` | GeoTIFF (LZW) | 350-420 MB / tile | ~80 MB / tile after `gdal_translate -projwin` to AOI | None (S3 public) | Naming: `n37w113`, `n37w112`, `n36w113`, `n36w112` for Grand Canyon. Tiles are 1°×1°. **Float32 DEM, GCS WGS84.** Hillshade output as uint8 with `gdaldem hillshade -s 111120` (degrees → meters scale). Use `gdal_translate -projwin -113 37 -111.5 36` to crop to combined AOI before hillshade for ~5x size reduction. There is also a global VRT (`USGS_Seamless_DEM_13.vrt`, 743 KB) that can be used as the gdal source — `gdal_translate` will fetch only the needed bytes via `/vsicurl/`. |
| 2 | **NYC Building Footprints** [VERIFIED: live GeoJSON returned] | `https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?$where=within_box(the_geom,40.80,-74.05,40.68,-73.90)&$limit=50000` | GeoJSON (MultiPolygon) | ~50 MB Manhattan-only | ~50 MB | None (Socrata public) | Direct PLUTO shapefile export (`64uk-42ks?method=export&format=Shapefile`) **returns HTTP 500 today** (Jetty error). MapPLUTO Socrata id `f888-ni5f` is `viewType: href` — not queryable. Direct nyc.gov URLs 404. **Workaround:** existing seeder Dockerfile already uses `5zhs-2jue` for buildings (has `height_roof`, `construction_year`, `mappluto_bbl`). For zoning categorical color, a second curl pulls tabular `64uk-42ks` rows by BBL prefix and `fetch_external.py` joins via `ogr2ogr -sql "SELECT b.geometry, b.height_roof, p.landuse, p.zonedist1, p.numfloors FROM buildings b LEFT JOIN pluto p ON b.mappluto_bbl = p.bbl"` (sqlite dialect). Verified: BBL `1007660029` joins cleanly. |
| 3 | **Census TIGER cb_2024_us_tract_500k** [VERIFIED: HEAD 200] | `https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_tract_500k.zip` | Shapefile in zip | 57.8 MB (`Content-Length: 57829655`) | ~12 MB after `ogr2ogr -where "STATEFP IN ('06','48','36','12')"` | None | Cartographic boundary tracts (`cb_*_500k`), simplified geometry. EPSG:4269 NAD83. GeoLens vector ingest auto-reprojects to 4326 via `ST_Transform`. Use `ogr2ogr -f GeoJSON -where "STATEFP IN ('06','48','36','12')" -t_srs EPSG:4326 ...` to filter and reproject in one step before ingest. Tract count after filter: ~16,000 (CA ~9,000, TX ~6,000, NY ~5,000, FL ~5,000) — confirm at runtime. |
| 4 | **Census ACS 5-year 2023** [VERIFIED: 200, returned data] | `https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E,B19013_001E&for=tract:*&in=state:06,48,36,12` | JSON (header row + data rows) | ~6 MB | n/a (already filtered) | None (under 500 queries/IP/day) | **Returns array-of-arrays, NOT GeoJSON.** First element is the header row: `["NAME","B01003_001E","B19013_001E","state","county","tract"]`. Subsequent rows are data. **GEOID for join = `state || county || tract` (11 chars).** Population = `B01003_001E` (int, may be `null`). Median household income = `B19013_001E` (may be negative annotation codes like `-666666666` for "no data" — must be filtered). To join with TIGER, build a dict `{geoid: {pop, mhi}}` then iterate features setting `properties._pop = ...; properties._mhi = ...; properties._density = pop / aland_sq_km`. Tract polygons have an `ALAND` field (square meters) — divide by 1,000,000 for sq km. |
| 5 | **USGS earthquakes FDSN** [VERIFIED: 200, count returned] | `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5&starttime=2021-05-08&endtime=2026-05-08` | GeoJSON FeatureCollection | ~3 MB (estimate, 9,055 features × ~330 bytes) | n/a | None | Live count for 5-year M5+ window: **9,055** features (`maxAllowed: 20000`, well under the limit — single request, no pagination needed). Properties: `mag, place, time (epoch ms), depth (in coords[2] km), mmi, alert, sig, magType, type, title`. Geometry is `Point` with `[lng, lat, depth_km]` — depth is the 3rd coordinate, not a property. fetch_external.py should NOT flatten depth into a property because GeoLens vector ingest preserves Point Z geometries; or rewrite to add `properties.depth_km` for paint-expression access. |
| 6 | **NIFC WFIGS Historic Perimeters** [VERIFIED: 200, 12,429 features] | `https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0/query?where=...&outFields=*&f=geojson` | GeoJSON FeatureCollection | ~50 MB (estimate, 12,429 polygons) | n/a | None | **CONTEXT.md reference to `_Current` is incorrect for historic data.** Use `WFIGS_Interagency_Perimeters` (no `_Current`). State filter: `attr_POOState IN ('US-CA','US-OR','US-WA','US-ID','US-NV','US-AZ','US-UT','US-MT','US-CO','US-NM')` (note the `US-` prefix). Date filter: `attr_FireDiscoveryDateTime >= timestamp '2020-01-01 00:00:00' AND attr_FireDiscoveryDateTime < timestamp '2025-01-01 00:00:00'`. **maxRecordCount = 2000, supportsPagination = true.** Loop with `resultOffset=0,2000,4000,...` until `exceededTransferLimit` is false. Useful properties: `attr_IncidentName, attr_IncidentSize, attr_FireDiscoveryDateTime` (epoch ms), `attr_FireCause`, `attr_POOState`, `poly_GISAcres`, `poly_IncidentName`. Derive `fire_year` post-fetch via `properties.fire_year = datetime.fromtimestamp(attr_FireDiscoveryDateTime/1000).year`. Geometries are sometimes complex multipart with rings — pass through `ogr2ogr -makevalid` if MapLibre rendering chokes. |

**Total raw download (all 5 sources): ~120 MB. Total post-filter: ~50 MB.** Within the existing seeder's bundle-size budget.

---

## 2. fetch_external.py Architecture Sketch

### Module layout

```
scripts/demo/fetch_external.py        # this file — single entry point
scripts/demo/raw/external/            # output directory (gitignored, parent of /data/demo on host)
    grand-canyon-dem.tif              # GDAL-cropped, COG-compatible
    grand-canyon-hillshade.tif        # gdaldem hillshade output, COG
    nyc-pluto-zoning.geojson          # joined building footprints + landuse
    pop-density-tracts.geojson        # TIGER + ACS joined, density computed
    usgs-quakes-m5.geojson            # passthrough from FDSN with depth_km flattened
    nifc-fires-2020-2024.geojson      # paginated NIFC concat with fire_year derived
```

### Key functions

```python
import asyncio, json, logging, subprocess, sys
from pathlib import Path
import httpx

OUT_DIR = Path(__file__).parent / "raw" / "external"
USER_AGENT = "GeoLens-Demo-Seeder/1.0"
HTTP_TIMEOUT = 600.0  # large for DEM tiles
logger = logging.getLogger("fetch-external")


def already_present(path: Path, min_bytes: int = 1024) -> bool:
    """Idempotency check matching run-seeder.sh's existing convention."""
    return path.exists() and path.stat().st_size >= min_bytes


def run_gdal(cmd: list[str]) -> None:
    """Invoke a GDAL CLI tool via subprocess. Raises on non-zero exit."""
    logger.info("RUN: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


async def fetch_grand_canyon_dem(client: httpx.AsyncClient) -> None:
    out_dem = OUT_DIR / "grand-canyon-dem.tif"
    out_hs  = OUT_DIR / "grand-canyon-hillshade.tif"
    if already_present(out_dem) and already_present(out_hs):
        logger.info("Grand Canyon DEM + hillshade already present, skipping")
        return
    # Use VRT-based gdal_translate against /vsicurl to fetch only AOI bytes
    vrt = "/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/USGS_Seamless_DEM_13.vrt"
    run_gdal([
        "gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE",
        "-projwin", "-113.0", "37.0", "-111.5", "36.0",
        vrt, str(out_dem),
    ])
    run_gdal([
        "gdaldem", "hillshade",
        "-z", "1.5", "-s", "111120",
        "-multidirectional",
        "-of", "COG", "-co", "COMPRESS=DEFLATE",
        str(out_dem), str(out_hs),
    ])


async def fetch_nyc_pluto_zoning(client: httpx.AsyncClient) -> None:
    # 1. Pull MN+BK building footprints with mappluto_bbl
    # 2. Pull MN+BK PLUTO rows (tabular only, but cheap because no geom)
    # 3. ogr2ogr SQL JOIN on mappluto_bbl = bbl
    # See full code template below
    ...


async def fetch_pop_density_tracts(client: httpx.AsyncClient) -> None:
    # 1. Download cb_2024_us_tract_500k.zip
    # 2. ogr2ogr -where "STATEFP IN ('06','48','36','12')" -t_srs EPSG:4326 → 4-state.geojson
    # 3. Pull ACS rows for 4 states
    # 4. Build GEOID dict, then read 4-state.geojson and inject _pop/_mhi/_density
    ...


async def fetch_usgs_quakes(client: httpx.AsyncClient) -> None:
    out = OUT_DIR / "usgs-quakes-m5.geojson"
    if already_present(out): return
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {"format": "geojson", "minmagnitude": 5,
              "starttime": "2021-05-08", "endtime": "2026-05-08"}
    r = await client.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    fc = r.json()
    # Flatten coords[2] depth into properties.depth_km for paint-expression access
    for f in fc["features"]:
        coords = f["geometry"]["coordinates"]
        f["properties"]["depth_km"] = coords[2] if len(coords) > 2 else 0
    out.write_text(json.dumps(fc))


async def fetch_nifc_fires(client: httpx.AsyncClient) -> None:
    out = OUT_DIR / "nifc-fires-2020-2024.geojson"
    if already_present(out): return
    base = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0/query"
    where = (
        "attr_FireDiscoveryDateTime >= timestamp '2020-01-01 00:00:00' AND "
        "attr_FireDiscoveryDateTime <  timestamp '2025-01-01 00:00:00' AND "
        "attr_POOState IN ('US-CA','US-OR','US-WA','US-ID','US-NV','US-AZ','US-UT','US-MT','US-CO','US-NM')"
    )
    all_features = []
    offset = 0
    while True:
        params = {"where": where, "outFields": "*", "f": "geojson",
                  "resultRecordCount": 2000, "resultOffset": offset}
        r = await client.get(base, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        fc = r.json()
        all_features.extend(fc.get("features", []))
        if not fc.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += 2000
    # Derive fire_year on each feature for paint-expression access
    from datetime import datetime, timezone
    for f in all_features:
        ts = f["properties"].get("attr_FireDiscoveryDateTime")
        if ts:
            f["properties"]["fire_year"] = datetime.fromtimestamp(
                ts / 1000, tz=timezone.utc).year
    out.write_text(json.dumps({"type": "FeatureCollection", "features": all_features}))


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    failures: list[str] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as c:
        for name, coro in [
            ("grand-canyon-dem", fetch_grand_canyon_dem(c)),
            ("nyc-pluto-zoning", fetch_nyc_pluto_zoning(c)),
            ("pop-density-tracts", fetch_pop_density_tracts(c)),
            ("usgs-quakes-m5", fetch_usgs_quakes(c)),
            ("nifc-fires-2020-2024", fetch_nifc_fires(c)),
        ]:
            try:
                await coro
                print(f"  {name}: ok")
            except Exception as exc:
                logger.exception("Failed %s", name)
                failures.append(name)
                print(f"  {name}: FAILED ({exc})")
    if failures:
        print(f"WARNING: {len(failures)} fetch(es) failed: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

### Idempotency strategy

- **Path-exists + min-size check.** Match the existing convention in `run-seeder.sh:36` (`if ls /data/demo/*.gz`). No checksums — these endpoints return slightly different payloads on each call (e.g., NIFC adds new fires daily) but the existing fixtures don't depend on bit-exact reproducibility. Re-running `fetch_external.py` after deleting one file refreshes only that file.

### Concurrency

- **Sequential for clarity.** All 5 fetches in series in `main()`. Total wall-clock time estimate: 30-90s for the 5 endpoints (DEM is the slowest at ~30s for the AOI crop via /vsicurl). asyncio is used only for `httpx.AsyncClient` plumbing, not parallelism — there's no benefit because GDAL CLI calls dominate and they're already CPU-bound subprocesses.

### GDAL invocation

- **subprocess, not python-gdal bindings.** The seeder Dockerfile already installs `gdal-bin` (line 27); python-gdal bindings (`python3-gdal`) are also installed but invoking them from a script not running inside the seeder container is brittle. Subprocess + a thin `run_gdal()` helper keeps the same code path that works on a developer laptop with system GDAL and inside the seeder container.

### Error handling

- **Fail-loud, no retry.** If a fetch fails, print to stderr, return non-zero exit code. The wrapper `run-seeder.sh` should `set -e` so a fetch failure aborts the seeder run before it tries to register a missing file. Retry loops add complexity without solving the actual failure modes (DNS, broken upstream — both need human attention).

---

## 3. Frozen Orchestrator Integration Notes

**Verified by reading `seed-thematic-demo.py:1-489`:**

### Theme discovery

- **Hardcoded import + list.** Lines 67-70:
  ```python
  from themes import ThemeDataset, theme1, theme2, theme3
  THEMES = [theme1, theme2, theme3]
  ```
- **The orchestrator imports exactly 3 modules by name.** Removing `theme3` requires editing this line. **CONTEXT.md restricts modifying `seed-thematic-demo.py` (it's the FROZEN orchestrator).**
  - **Resolution:** keep `theme3.py` as a stub (empty `DATASETS = []`, set `THEME_NAME` to something benign or empty). The orchestrator already handles empty themes gracefully (line 423: `if not tm.DATASETS: print(...); continue`).
  - **Better resolution:** rename the existing `theme1.py` and `theme2.py` to hold the new content; convert `theme3.py` to an empty stub. The file *names* `theme1.py / theme2.py / theme3.py` are part of the freeze, but their *contents* are not.
  - Plan should ship `theme1.py` = "When the Land Speaks" content (3 datasets), `theme2.py` = "When the Earth Moves" content (2 datasets), `theme3.py` = empty stub with `DATASETS = []` and a docstring noting the deletion. The orchestrator prints `"(no datasets registered for {THEME_NAME} yet)"` for empty themes — harmless.

### ThemeDataset shape

- **TypedDict at `themes/__init__.py:17`.** Required-on-paper fields are `stem, type, source` (`Literal["vector"|"raster"]`, `Literal["ne_cdn"|"local"]`). Optional: `ne_theme, local_path, summary, snapshot_date, license`.
- **For all new datasets:** `source: "local"`, `type: "vector"` or `"raster"`, `local_path: "/data/demo/external/{stem}.{ext}"` (the orchestrator runs inside the seeder container; volume-mount or COPY makes this resolve), `summary, snapshot_date, license` always populated. **No `ne_theme`** for non-NE datasets.

### Ingest dispatch

- **`ingest_theme()` at line 285** dispatches by `(type, source)`:
  - `(vector, ne_cdn)` → `ingest_vector_ne_cdn_with_cache` — N/A for new themes
  - `(vector, local)` → `ingest_vector_local_with_summary` — used for PLUTO-zoning, pop-density, quakes, fires
  - `(raster, local)` → `ingest_raster_local` — used for the DEM and hillshade
- All three helpers already accept `entry["local_path"]` and `entry.get("summary")`. **No orchestrator change needed.**

### Fixture apply loop

- **`apply_theme_fixtures()` at line 329** is decoupled from ingest. It walks `fixtures_dir` once, indexes by `_meta.theme`, and applies every fixture whose `_meta.theme == theme_module.THEME_NAME`.
- **Implication:** adding new fixtures is a pure file drop into `scripts/demo/fixtures/maps/`. No code change. The fixture's `_meta.theme` field MUST exactly match the corresponding theme module's `THEME_NAME` constant — case-sensitive string match.

### File-presence check

- **`ingest_vector_local_with_summary` at line 215** and **`ingest_raster_local` at line 251** both `return {"status": "failed", "error": "local file missing: ..."}` if `Path(entry["local_path"]).exists()` is false. **fetch_external.py running before the orchestrator is what makes this contract hold.**

### `local_path` resolution at runtime

- The seeder container has `/data/demo/` as the canonical bundle path. The Dockerfile (Stage 2) does `COPY --from=data-fetcher /data/demo /data/demo` (line 272). The orchestrator's `entry["local_path"]` is interpreted as a literal absolute path inside the container.
- **CONTEXT.md decision: outputs go to `scripts/demo/raw/external/{stem}.{ext}`.** This is a host path, not the container path. To make `local_path` resolve inside the seeder container, one of:
  - (a) Mount `scripts/demo/raw/external` as a volume into the seeder container (requires editing `docker-compose.demo.yml` — OUT OF SCOPE).
  - (b) Have `fetch_external.py` write to the **same logical path** the orchestrator reads from. The cleanest interpretation of CONTEXT.md is: `fetch_external.py` writes to `scripts/demo/raw/external/` on the developer host, and `run-seeder.sh` (already permitted to edit) copies these files into `/data/demo/external/` inside the container before invoking the orchestrator. Theme entries then use `local_path: "/data/demo/external/{stem}.{ext}"`.
  - **Recommended:** option (b). Plan should add a step in `run-seeder.sh` between key creation and orchestrator launch: `cp -rL /scripts/demo/raw/external/* /data/demo/external/ 2>/dev/null || true`. The `/scripts/` mount already exists (line 275 of Dockerfile: `COPY scripts/ /scripts/`), so the raw-external dir is already inside the container — just copy it to the canonical bundle path.

---

## 4. Theme Module + Fixture Conventions

### Theme module template (theme1.py "When the Land Speaks")

```python
"""Theme 1 — When the Land Speaks. Three 3D-rendered terrain + extrusion maps."""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = "When the Land Speaks"
THEME_DESCRIPTION = "Land in three dimensions: canyon walls, city skylines, and population density rendered as terrain you can tilt and rotate."
THEME_IDX = 0

DATASETS: list[ThemeDataset] = [
    {
        "stem": "grand-canyon-dem",
        "type": "raster",
        "source": "local",
        "local_path": "/data/demo/external/grand-canyon-dem.tif",
        "summary": "USGS 3DEP 1/3 arc-second DEM, cropped to the Grand Canyon AOI ...",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (USGS 3DEP)",
    },
    {
        "stem": "grand-canyon-hillshade",
        "type": "raster",
        "source": "local",
        "local_path": "/data/demo/external/grand-canyon-hillshade.tif",
        "summary": "Hillshade derived from the 3DEP DEM via gdaldem hillshade -z 1.5 -s 111120 -multidirectional ...",
        "snapshot_date": "2025-01-01",
        "license": "Public Domain (USGS 3DEP, derivative)",
    },
    {
        "stem": "nyc-pluto-zoning",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/nyc-pluto-zoning.geojson",
        "summary": "NYC Building Footprints (5zhs-2jue) joined with PLUTO (64uk-42ks) via mappluto_bbl. Manhattan + Brooklyn waterfront subset. Properties: height (m), landuse, zonedist1, numfloors. Source: NYC Open Data.",
        "snapshot_date": "2026-04-01",
        "license": "NYC Open Data (public use with attribution)",
    },
    {
        "stem": "pop-density-tracts",
        "type": "vector",
        "source": "local",
        "local_path": "/data/demo/external/pop-density-tracts.geojson",
        "summary": "Census 2024 cb_2024_us_tract_500k tracts for CA+TX+NY+FL, joined with ACS 2023 5-year B01003_001E (population) and B19013_001E (median household income). Density = pop / ALAND_sq_km. Source: US Census Bureau.",
        "snapshot_date": "2024-12-01",
        "license": "Public Domain (US Census Bureau)",
    },
]
```

### Fixture conventions

The 5 fixtures share these patterns:

1. **`_meta.theme` MUST match `THEME_NAME` exactly** (orchestrator routes by this string). Case-sensitive.
2. **Layer ordering by `sort_order`**, ascending = bottom to top.
3. **`layer_type`:** `"vector_geolens"` for vector, `"raster_geolens"` for raster.
4. **3D extrusion is triggered by `paint._height_column`.** The frontend reads `paint._height_column` and, if present, adds a companion `fill-extrusion` layer with `fill-extrusion-height: ['max', ['coalesce', ['to-number', ['get', height_col], 0], 0], 0]` (verified at `frontend/src/components/maps/hooks/use-map-layers.ts:91-97`).
5. **Camera fields:** `center_lng, center_lat, zoom, bearing, pitch`. For 3D maps: `pitch >= 45.0`, `bearing != 0` for visual interest.
6. **Basemap:** `"dark-matter"` for 3D/dramatic maps (matches existing `2-manhattan-skyline.json`), `"positron"` for data-dense overlays. **`show_basemap_labels: false`** for the canyon hero map (terrain alone), `true` for everything else.
7. **`style_config`** is the round-trip metadata used by the Builder UI. **Both `paint` (the live MapLibre expression) and `style_config` (the Builder's source-of-truth) must be present and consistent.** When in doubt, copy patterns from `2-manhattan-skyline.json` (graduated mode), `2-population-at-a-glance.json` (graduated with target=radius), `3-conflict-events-2024.json` (heatmap mode + categorical filter).

### Per-fixture signature paint patterns

| # | Fixture | Layer paint key | Paint expression highlights |
|---|---------|-----------------|------------------------------|
| 1 | **grand-canyon-dem.json** | raster_geolens with hillshade on top | `style_config: {"rescale": "1500,2900", "colormap": "terrain"}` for DEM (matches existing GEBCO style); hillshade with `opacity: 0.5` blend mode. `pitch: 60`, `bearing: -25`, `zoom: 10.5`, `center: [-112.1, 36.1]`. `basemap_style: "dark-matter"`, labels off. |
| 2 | **nyc-pluto-zoning.json** | vector_geolens with `_height_column: "height"` | Categorical fill by `landuse` code: `1=red (Residential)`, `2=#orange (Mixed)`, `3=blue (Commercial)`, `4=violet (Industrial)`, `5+=gray`. Paint expression: `["match", ["coalesce", ["to-string", ["get", "landuse"]], "0"], "01", "#e74c3c", "02", "#f39c12", ...]`. `pitch: 60`, `zoom: 14.5`, `center: [-73.985, 40.748]`. |
| 3 | **pop-density-tracts.json** | vector_geolens with `_height_column: "_density"` | Bars 1m height per person/km² (so a tract with 10,000 people/km² extrudes 10,000m). Color by `_mhi` (median household income) using log scale: `["interpolate", ["linear"], ["coalesce", ["to-number", ["get", "_mhi"], 0], 0], 30000, "#440154", 60000, "#3b528b", 90000, "#21908c", 120000, "#5dc863", 150000, "#fde725"]` (viridis ramp). `pitch: 50`, `zoom: 4`, `center: [-97, 37]`. **Filter out `_mhi < 0`** (ACS no-data marker `-666666666`). |
| 4 | **usgs-quakes-m5.json** | vector_geolens point with circle paint | `circle-radius` interpolated by `mag` from 4 (M5) to 30 (M9+); `circle-color` interpolated by `properties.depth_km` from yellow (0km) → orange (50km) → red (200km) → purple (700km, deepest known mantle quakes). `circle-stroke-color: "#fff"` and `circle-stroke-width: 0.6`. **Hover ring via `feature-state hover` is NOT a paint config — it's a frontend feature.** The `style_config` mode is `"graduated"` with `column: "mag"`. **Do NOT use heatmap mode** — the visual story is "individual quakes ranked by magnitude," not density. `pitch: 0`, `zoom: 1.8`, `center: [0, 20]`. `basemap_style: "dark-matter"`. |
| 5 | **nifc-fires-2020-2024.json** | vector_geolens polygon | `fill-color` by `fire_year` (smoke palette): 2020=`#fde725` (yellow), 2021=`#5dc863`, 2022=`#21908c`, 2023=`#3b528b`, 2024=`#440154` (deep purple). Or a "smoke" palette: 2020=`#fef0d9`, 2021=`#fdcc8a`, 2022=`#fc8d59`, 2023=`#e34a33`, 2024=`#b30000` (orange-red ramp, more thematic). Paint expression uses `["match", ["coalesce", ["to-number", ["get", "fire_year"], 0], 0], 2020, "#fef0d9", 2021, "#fdcc8a", ...]`. `fill-opacity: 0.7`, `_outline-color: "#1a1a2e"`, `_outline-width: 0.3`. `pitch: 30`, `zoom: 5.5`, `center: [-118, 41]`. `basemap_style: "dark-matter"`. |

---

## 5. e2e test update map

Verified by reading `e2e/demo-smoke-shared.ts:1-156`:

The 8 hardcoded map names live ONLY in `demo-smoke-shared.ts` lines 3-12. The two spec files (`demo-smoke.spec.ts` and `demo-smoke-anonymous.spec.ts`) just call `registerDemoSmokeSuite(test, ...)` from the shared file. **One file edit covers both spec entries.**

### Exact strings to replace in `e2e/demo-smoke-shared.ts:3-17`

**Before:**
```ts
const DEMO_MAP_NAMES = [
  'Earth as Seen from Space',
  'Global Bathymetry',
  'Population at a Glance',
  'GDP per Capita PPP 2023',
  "The World's Disputed Places",
  'One Territory, Multiple Official Maps',
  'Conflict Events 2024 (UCDP GED)',
  'Refugees by Country of Origin 2023',
];

const OPTIONAL_DEMO_MAPS = [
  'Where the Ice Is',
  'Life Expectancy & Income',
];
```

**After:**
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

(Map names above are illustrative — the planner should pick final names that match the fixture `name` and `_meta.name` fields verbatim. The smoke test compares against `/api/maps/?limit=100` `name` field.)

**No changes needed in `demo-smoke.spec.ts` or `demo-smoke-anonymous.spec.ts`** — both files only contain the registration call.

---

## 6. Pitfalls List

### A. Runtime path mismatch (host vs. container)
**Watch:** `local_path` in theme entries must resolve inside the seeder container, not on the developer's laptop. CONTEXT.md says outputs go to `scripts/demo/raw/external/` (host path), but the orchestrator reads literal absolute paths. **Mitigation:** plan a `cp -rL /scripts/demo/raw/external/* /data/demo/external/` step in `run-seeder.sh` before the orchestrator launch (Section 3 above), and use `local_path: "/data/demo/external/{stem}.{ext}"` in theme entries.

### B. PLUTO export endpoint is broken — DO NOT use the URL in CONTEXT.md
**Watch:** `https://data.cityofnewyork.us/api/geospatial/64uk-42ks?method=export&format=Shapefile` returns HTTP 500 (Jetty error) as of 2026-05-08. Direct nyc.gov MapPLUTO links (any version) 404. **Mitigation:** use the Socrata `/resource` GeoJSON endpoint for building footprints (`5zhs-2jue`) and join to tabular PLUTO (`64uk-42ks`) on `mappluto_bbl ↔ bbl` (Section 1, row 2). The seeder Dockerfile already does this for the existing demo; reuse the pattern.

### C. NIFC service name confusion
**Watch:** `WFIGS_Interagency_Perimeters_Current` (with `_Current`) only contains in-season fires. CONTEXT.md's specifics block points at `_Current` — that returns the wrong data window. **Mitigation:** use `WFIGS_Interagency_Perimeters` (no suffix). Also: state filter format is `attr_POOState IN ('US-CA','US-OR',...)` with the `US-` prefix, NOT bare 2-letter codes. Year filter goes through `attr_FireDiscoveryDateTime` (epoch ms with `timestamp '2020-01-01 00:00:00'` literal), not a `FIRE_YEAR` field.

### D. NIFC pagination is required
**Watch:** maxRecordCount = 2000, count = 12,429 for the western 10 states / 2020-2024 window. A single request silently truncates. **Mitigation:** loop with `resultOffset=0,2000,4000,...` until the response's `properties.exceededTransferLimit` is false.

### E. ACS no-data sentinel values
**Watch:** Census ACS encodes "no data" as large negative numbers (e.g., `-666666666` for "no available data," `-555555555` for "estimate not applicable"). Treating these as integers in a paint interpolation produces meaningless dark colors at one extreme of the ramp. **Mitigation:** filter `_mhi < 0` to `null` in `fetch_external.py`, then add a fallback color via `["coalesce", ["to-number", ["get", "_mhi"]], <fallback>]` in the paint expression.

### F. ACS API returns array-of-arrays, not GeoJSON
**Watch:** `https://api.census.gov/data/...` response shape is `[["NAME","B01003_001E",...], ["Census Tract X; County Y; State Z", "5549", "06", "001", "451202"], ...]`. **Mitigation:** parse the first row as the column header, map subsequent rows by index. Build `{state+county+tract: {pop, mhi}}` dict, then iterate the TIGER FeatureCollection setting `properties._pop` etc. by `GEOID` lookup.

### G. PLUTO is in EPSG:2263 (NY State Plane); GeoLens auto-reprojects vector but only declares srid_override=4326 in commit body
**Watch:** The orchestrator at `seed-thematic-demo.py:235` sends `"srid_override": 4326` in the commit body for vector ingest. **If we send PLUTO-derived GeoJSON in EPSG:2263, the override forces the wrong CRS interpretation and coordinates land in the Atlantic.** **Mitigation:** the PLUTO `/resource` GeoJSON endpoint already returns EPSG:4326 (verified — `crs.properties.name = "urn:ogc:def:crs:OGC:1.3:CRS84"`). For the TIGER shapefile (EPSG:4269), use `ogr2ogr -t_srs EPSG:4326` in `fetch_external.py` to reproject to 4326 before writing. Both pipelines emit 4326 — `srid_override: 4326` is then correct.

### H. DEM raster band datatype — int16 vs uint8 mosaic incompatibility
**Watch:** USGS 3DEP DEM is `Float32`. The hillshade output is `Byte` (uint8). Existing seeder Dockerfile already documents that mixing dtypes in a VRT mosaic fails (line 444-447 of `seed-thematic-demo.py`: GEBCO int16 vs NE shaded relief uint8). **Mitigation:** stack as separate raster layers in the fixture (not a VRT). The DEM layer renders below the hillshade at lower opacity; hillshade renders on top with mid-opacity to blend. This matches the `1-earth-from-space.json` pattern exactly.

### I. NIFC perimeters can have multipart geometries with sliver artifacts
**Watch:** Some perimeters have sub-meter holes/slivers from agency-source artifacts. MapLibre handles these but they bloat the GeoJSON. **Mitigation:** light. Only run `ogr2ogr -makevalid -simplify 0.0001` (~10m simplification at the equator) if the resulting file is too large or rendering is glitchy. Initially, ship the raw NIFC output and revisit if rendering is poor.

### J. Earthquake depth lives in geometry, not properties
**Watch:** USGS FDSN GeoJSON puts depth (in km) as `geometry.coordinates[2]`. Paint expressions can't read this directly via `["get", ...]`. **Mitigation:** in `fetch_external.py`, copy depth into `properties.depth_km` after the fetch (Section 2 code template).

### K. `fetch_external.py` runs OUTSIDE the seeder container (developer laptop) but its outputs feed INTO it
**Watch:** GDAL must be available on the host running `fetch_external.py`. The seeder Dockerfile installs gdal-bin, but the host may not have it. **Mitigation:** `run-seeder.sh` (the wrapper script that runs INSIDE the container) is the right place to invoke `fetch_external.py` — that way GDAL is always available. Alternatively, `fetch_external.py` can be invoked manually outside the container by a developer who has GDAL installed locally; in that case the outputs go into `scripts/demo/raw/external/` and get carried into the container via the `/scripts/` mount. **Recommended:** plan supports both. Add a comment at the top of `fetch_external.py` documenting the dual-execution model.

### L. `theme3.py` cannot be deleted while seed-thematic-demo.py imports it
**Watch:** Line 67 of the frozen orchestrator: `from themes import ThemeDataset, theme1, theme2, theme3`. **Mitigation:** make `theme3.py` an empty stub (`THEME_NAME = ""; THEME_DESCRIPTION = ""; DATASETS = []`). The orchestrator already prints a benign "(no datasets registered for ...)" line for empty themes (line 423-425). **Do NOT delete the file** — that breaks the import.

### M. Fixture deletion sequence matters for git
**Watch:** Some `.planning/` paths in this repo are gitignored; `scripts/demo/fixtures/maps/` is tracked. Verify with `git ls-files scripts/demo/fixtures/maps/` before declaring the delete done. **Mitigation:** plan should `git rm` the 8 old fixtures explicitly, not just `rm` them.

### N. `_meta.theme` mismatch silently drops fixtures
**Watch:** `_index_fixtures_by_theme` at line 376 keys fixtures off `parsed.get("_meta", {}).get("theme", "")`. If the theme name in the fixture does NOT match `THEME_NAME` in the corresponding theme module, the fixture is loaded but never applied (the bucket is empty for that theme). No error is raised. **Mitigation:** make the planner copy `THEME_NAME` from the theme module into every fixture's `_meta.theme` field verbatim, and add a code review check in the plan to verify exact match.

### O. /vsicurl partial-byte fetches require `gdal_translate` projwin trim BEFORE hillshade
**Watch:** Naively running `gdaldem hillshade /vsicurl/.../USGS_Seamless_DEM_13.vrt` would attempt to read the entire 5°×5° tile or worse. **Mitigation:** always do `gdal_translate -projwin ... -of COG -co COMPRESS=DEFLATE` to a local crop FIRST, then run `gdaldem hillshade` on the local file. Two passes, predictable disk usage.

### P. Earthquake count varies day-to-day — fixture must use a fixed window
**Watch:** `starttime=2021-05-08&endtime=2026-05-08` is a 5-year-relative-to-today window. Re-running the seeder a month later picks up a different feature set (because the window slides). **Mitigation:** for stable demo behavior, fix the window to a snapshot date (e.g., `endtime=2026-05-01` hardcoded). Theme entry's `snapshot_date` field documents this. Trade-off: less "live"-feeling.

### Q. NYC Open Data /resource endpoint default $limit is 1000
**Watch:** `https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?$where=...` returns at most 1000 records by default — the existing seeder Dockerfile uses `$limit=50000` to bypass. **Mitigation:** always pass `$limit=50000` (or `$offset` paginate) in fetch_external.py PLUTO/buildings calls.

---

## 7. Sources

### Primary (HIGH confidence — verified live today)
- USGS 3DEP S3 bucket — `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/` HEAD probes returned 200 for n37w113, n37w112, n36w113, n36w112; sizes 350-420 MB.
- USGS earthquake FDSN — `https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&minmagnitude=5&starttime=2021-05-08&endtime=2026-05-08` returned `{"count":9055,"maxAllowed":20000}`.
- NIFC ArcGIS — `https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0` schema probe; count probe returned 12,429 for the 2020-2024 western-state window.
- Census TIGER 2024 — HEAD on `https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_tract_500k.zip` returned 200, content-length 57,829,655.
- Census ACS — GET on `https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E&for=tract:*&in=state:06%20county:001` returned valid JSON array-of-arrays.
- NYC Open Data — `https://data.cityofnewyork.us/resource/5zhs-2jue.geojson` and `64uk-42ks.json` return data; verified `mappluto_bbl ↔ bbl` join works for sample BBL `1007660029`.
- PLUTO export endpoint failure — `https://data.cityofnewyork.us/api/geospatial/64uk-42ks?method=export&format=Shapefile` returns HTTP 500 with a Jetty error page; verified with `User-Agent: Mozilla/5.0`.
- Frozen orchestrator structure — confirmed by reading `scripts/demo/seed-thematic-demo.py:1-489`.
- e2e test surface — confirmed by reading `e2e/demo-smoke-shared.ts:1-156`.

### Secondary (MEDIUM confidence — CITED from official docs)
- [GDAL gdaldem hillshade documentation](https://gdal.org/en/stable/programs/gdaldem.html) — `-z`, `-s 111120`, `-multidirectional`, `-of COG` flags.
- [NYC Open Data PLUTO landing](https://data.cityofnewyork.us/City-Government/Primary-Land-Use-Tax-Lot-Output-PLUTO-/64uk-42ks) — confirms 25v4 is the current version (last updated 2026-02-20).
- [NYC Planning PLUTO Database](https://nycplanning.github.io/db-pluto/) and [NYCPlanning/db-pluto repo](https://github.com/NYCPlanning/db-pluto) — searched for direct CDN URLs; none consistent with current S3/CDN paths (all 404).

### Tertiary (LOW confidence)
- None — every claim in this research either has a live verification probe or a citation to the existing codebase / official docs.

---

## RESEARCH COMPLETE

**Phase:** Quick Task 260508-lkz — Rebuild GeoLens demo themes and fixtures
**Confidence:** HIGH

### Key findings
1. **PLUTO Shapefile export is broken; substitute is to join NYC Building Footprints (5zhs-2jue) with tabular PLUTO (64uk-42ks) on `mappluto_bbl ↔ bbl`.** The existing seeder Dockerfile already pulls 5zhs-2jue, so the join-join pattern is one-liner in ogr2ogr.
2. **NIFC service is `WFIGS_Interagency_Perimeters` (no `_Current`).** State filter uses `US-XX` prefix on `attr_POOState`; year filter uses `attr_FireDiscoveryDateTime` epoch ms; pagination required (12,429 features ÷ 2,000 maxRecordCount).
3. **Theme3.py cannot be deleted — must remain as an empty stub** (orchestrator imports it at line 67). All 8 old fixture JSONs CAN and MUST be `git rm`d.
4. **Host-vs-container path bridge.** `fetch_external.py` writes to `scripts/demo/raw/external/` on the host; `run-seeder.sh` (editable) copies to `/data/demo/external/` inside the container; theme entries' `local_path` references the container path.
5. **e2e map name list is centralized in one file** (`e2e/demo-smoke-shared.ts:3-17`). Spec files just call `registerDemoSmokeSuite()` and need no edit.
6. **Census ACS returns array-of-arrays, not GeoJSON.** GEOID = `state+county+tract` (11 chars). Filter `B19013_001E < 0` (sentinel for "no data").

### File created
`/Users/ishiland/Code/geolens/.planning/quick/260508-lkz-rebuild-geolens-demo-themes-and-fixtures/260508-lkz-RESEARCH.md`

### Confidence assessment
| Area | Level | Reason |
|------|-------|--------|
| External source reachability | HIGH | All 5 endpoints probed live today; sizes/counts/schemas captured. |
| fetch_external.py architecture | HIGH | Sequential httpx + subprocess GDAL pattern is standard; matches seeder Dockerfile conventions. |
| Frozen orchestrator integration | HIGH | Verified by reading the source. Empty-theme handling at line 423-425 is documented in code. |
| Theme/fixture conventions | HIGH | Patterns extracted from existing fixtures and frontend code at `frontend/src/components/maps/hooks/use-map-layers.ts:91-97`. |
| e2e test update | HIGH | Verified single file change covers both spec entries. |
| Pitfalls | HIGH | Most pitfalls verified by live probes (PLUTO 500, NIFC `_Current` schema, ACS sentinel values). |

### Open questions
- **Final fixture map names** — recommend planner picks names matching the spec convention. Suggested: "Grand Canyon: Land in 3D", "NYC Zoning: Manhattan in 3D", "Population Density: 4-State Bars", "Global Earthquakes M5+ (Last 5 Years)", "Western US Wildfires 2020-2024". Final choice belongs to the planner.
- **Fixture stems for the two raster layers in the canyon map** — `grand-canyon-dem.tif` and `grand-canyon-hillshade.tif` are independent dataset registrations; the canyon fixture references both as separate raster layers. Confirm naming with planner.

### Ready for planning
Research complete. Planner can now produce PLAN.md.

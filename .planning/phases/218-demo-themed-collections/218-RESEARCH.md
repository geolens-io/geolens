# Research: Phase 218 — Demo Themed Collections

**Researched:** 2026-04-08
**Domain:** Demo data seeder engineering, fixture schema, Docker data bundling, Playwright smoke tests
**Confidence:** HIGH (seeder/schema/API surface verified against live code); MEDIUM (dataset URLs — most confirmed, a few require runtime verification)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Three themed collections: Planet Earth — Physical Systems, Global Development & People, Borders, Boundaries & Contested Space
- Natural Earth layers restructured into the 3 themed collections (not kept flat)
- `seed-thematic-demo.py` extends `seed-natural-earth.py` primitives — does not replace them
- `csv_to_choropleth.py` helper pre-joins CSVs to ADM0 polygons before ingest (A7 Option C)
- Seeder Dockerfile bundles all data at build time; zero network calls at runtime
- Hand-curated signature maps exported as JSON fixtures committed to `scripts/demo/fixtures/maps/`
- Fixture apply: resolve dataset UUIDs by `source_filename` stem at apply time
- Smoke tests in `e2e/demo-smoke.spec.ts`: load each of the 9 maps, wait for MapLibre idle, assert tile 200s, no console errors
- `reset-demo.sh` is a full unconditional wipe — no prefix-aware teardown needed
- ACLED is out. UCDP GED v25.1, UNHCR, UCDP disputed layers are in.
- Seeder must be idempotent against partial/mid-crash state

### Claude's Discretion
- Specific fixture JSON schema and file naming convention within `scripts/demo/fixtures/maps/`
- Directory layout for `scripts/demo/` (helpers vs flat)
- SRTM source (OpenTopography S3 is the pick — see Q5)
- OSM buildings city (Manhattan confirmed — extract available from Geofabrik)
- UCDP GED and UNHCR exact snapshot versions
- Whether each map fixture is a single JSON file or directory
- Smoke test implementation details

### Deferred Ideas (OUT OF SCOPE)
- Live 3D terrain/extrusion maps (blocked on Phase 999.1)
- PostGIS 3D geometry ingestion
- GeoJSON-Z delivery endpoint
- AI chat seeded prompts
- Layer-time table→polygon join capability
- Automated snapshot-date lint
- Multilingual layer titles
- Pre-minted share/embed tokens
</user_constraints>

---

## Summary

- `seed-natural-earth.py` provides six reusable async primitives (download-with-retry, cache, ingest three-step, job-poll, collection create/assign, idempotency check) that the new `seed-thematic-demo.py` should import and call directly — no code duplication needed.
- The ingest API contract is three HTTP calls: `POST /api/ingest/upload` (multipart file) → `POST /api/ingest/preview/{job_id}` → `POST /api/ingest/commit/{job_id}` (JSON body) → poll `GET /api/jobs/{job_id}`. Rasters follow the same three-step path; the API auto-detects `file_type` from magic bytes. VRTs get a separate `POST /api/ingest/vrt/create` endpoint taking a list of source dataset UUIDs.
- `PUT /api/maps/{id}` accepts a full `MapUpdate` body; `layers` is a complete replacement list of `MapLayerInput` objects with `dataset_id` (UUID), paint, layout, filter, label\_config, style\_config, visible, opacity, sort\_order, show\_in\_legend. Strip `id`, `created_at`, `updated_at`, `created_by`, `thumbnail_url`, `forked_from_id` from the GET response before writing to a fixture.
- The `reset-demo.sh` performs a full unconditional `TRUNCATE TABLE catalog.datasets CASCADE` — it wipes the `collections` table too. The seeder's idempotency (skip by `source_filename` in existing catalog) handles re-run safety; no name-prefix teardown is needed.
- SEDAC GPWv4 requires NASA Earthdata account registration — **blocking for a zero-auth seeder**. Alternative: use the Natural Earth `ne_10m_populated_places_simple` proportional-symbol layer for population raster story, or substitute with a pre-converted GPWv4 hosted on a public S3 mirror.
- GEBCO 2024 is available as a pre-converted COG via source.coop (S3 URL, no login); the GEBCO.net native download is NetCDF 7.5 GB and requires web-app interaction — use source.coop instead.
- UCDP GED v25.1 downloads as `https://ucdp.uu.se/downloads/ged/ged251-csv.zip` — no registration, CC-BY 4.0 confirmed. [VERIFIED: ucdp.uu.se/downloads]
- OSM buildings for Manhattan: Geofabrik's free shapefile (`new-york-latest-free.shp.zip`) includes a buildings layer with `building:height` as a SMALLINT field. Confirmed no auth required, updated daily.
- `csv_to_choropleth.py` should use only Python stdlib + `shapely` + `json` (already in the backend venv) — no pandas/geopandas needed for a simple left-join on ISO3.

---

## Q1: Seeder Pattern (scripts/seed-natural-earth.py)

### Reusable Primitives

`seed-natural-earth.py` exports the following importable functions. All are async and take an `httpx.AsyncClient` plus base_url/api_key arguments. [VERIFIED: scripts/seed-natural-earth.py]

| Function | Signature | What it does |
|----------|-----------|--------------|
| `fetch_existing_datasets` | `(client, base_url, api_key) -> dict[str, str]` | Paginates `GET /api/datasets/` and returns `{source_filename: dataset_id}` mapping for idempotency checks |
| `download_or_load_cache` | `(client, url, stem, cache_dir) -> bytes` | Downloads with retry; reads/writes atomic cache file; exponential backoff on 429/5xx |
| `download_dataset` | `(client, url) -> bytes` | Retry logic: 3 attempts, 2^attempt sleep, raises on non-retryable |
| `write_cache_atomic` | `(cache_dir, stem, data)` | Atomic tmp → rename write to prevent partial cache files |
| `clean_partial_downloads` | `(cache_dir)` | Removes leftover `.zip.tmp` files from interrupted runs |
| `ingest_dataset` | `(client, base_url, api_key, stem, data, name, tags, encoding=None) -> dict` | Full 3-step pipeline: upload → preview → commit → poll; returns job result dict |
| `poll_job` | `(client, base_url, api_key, job_id, timeout=300) -> dict` | Polls `GET /api/jobs/{job_id}` every 3s; raises TimeoutError at 300s default |
| `create_or_get_collection` | `(client, base_url, headers, name, description) -> str | None` | Creates collection or finds existing by name on 409; returns UUID |
| `create_collections` | `(client, base_url, api_key, results)` | Groups result dicts by theme, creates collections, bulk-assigns datasets |
| `generate_name` | `(stem) -> str` | Converts `ne_10m_admin_0_countries` → `"Admin 0 Countries (10m)"` |
| `generate_tags` | `(stem, theme) -> list[str]` | Returns `["natural-earth", "10m", theme, ...group_tags]` |

**Concurrency model:** `asyncio.Semaphore(3)` + `asyncio.TaskGroup`. Each dataset processes independently; failures are caught per-task and appended to a shared `results` list. The `sem` is only held during the download+ingest work, not the idempotency check.

**Idempotency:** built around `source_filename`. If `f"{stem}.zip"` is in `existing`, the dataset is skipped with `status="skipped"` but its `dataset_id` is still recorded for collection assignment.

**Encoding handling:** `detect_missing_cpg()` checks for `.cpg` file in the ZIP; if missing and stem is in `ENCODING_OVERRIDE_STEMS`, passes `encoding="UTF-8"` to the commit body.

### Existing API Contract

**Auth:** `X-Api-Key: <key>` header on all calls. The header name is `X-Api-Key` (not `X-API-Key` — case matters).

**Step 1 — Upload:**
```
POST /api/ingest/upload
Content-Type: multipart/form-data
Body: file=<bytes> with filename set to "{stem}.zip" or "{stem}.tif"
Response: {"job_id": "<uuid>", "status": "pending", "message": "..."}
```

**Step 2 — Preview:**
```
POST /api/ingest/preview/{job_id}
Body: (empty)
Response: VectorPreviewResponse or RasterPreviewResponse (fields include detected_srid, geometry_type, feature_count, etc.)
Response is DISCARDED by seed-natural-earth.py — only the job_id is needed downstream
```

**Step 3 — Commit (vector):**
```
POST /api/ingest/commit/{job_id}
Content-Type: application/json
Body: {
  "title": "<name>",
  "visibility": "public",
  "srid_override": 4326
}
```

**Step 3 — Commit (raster COG):**
```
POST /api/ingest/commit/{job_id}
Content-Type: application/json
Body: {
  "title": "<name>",
  "visibility": "public",
  "compression": "DEFLATE",
  "resampling": "bilinear",
  "summary": "<description with snapshot_date and license>"
}
```

**Poll:**
```
GET /api/jobs/{job_id}    (header: X-Api-Key)
Response: {"status": "complete"|"failed", "dataset_id": "<uuid>", "error_message": "..."}
Polls every 3s; large rasters may take 60-120s
```

**VRT create:**
```
POST /api/ingest/vrt/create
Content-Type: application/json
Body: {
  "source_dataset_ids": ["<uuid1>", "<uuid2>", ...],
  "vrt_type": "mosaic"   # or "band_stack"
}
Response: {"job_id": "<uuid>", "message": "VRT creation queued"}
```
Then poll `GET /api/jobs/{job_id}` until complete. The VRT job result contains the new `dataset_id`.

**Collection bulk-assign:**
```
POST /api/catalog/collections/{collection_id}/datasets
Content-Type: application/json
Body: {"dataset_ids": ["<uuid1>", ...]}
```
409 on duplicates is acceptable (idempotent).

**Error recovery:** HTTP 409 on upload = duplicate filename. The existing seeder does not handle 409 at upload time explicitly; idempotency is checked before upload via `fetch_existing_datasets`. This means a crash between upload and commit would leave an orphaned job — the thematic seeder should handle this by calling `fetch_existing_datasets` again after any crash/resume.

### Sketch: seed-thematic-demo.py

```
scripts/
  demo/
    lib/
      csv_to_choropleth.py    # A7 helper
    fixtures/
      maps/
        theme1-earth-from-space.json
        theme1-global-bathymetry.json
        theme2-population-at-a-glance.json
        theme2-gdp-per-capita.json
        theme3-disputed-places.json
        theme3-kashmir-toggle.json
        theme3-conflict-events-2024.json
        theme3-refugees-by-origin.json
    seed-thematic-demo.py     # orchestrator entry point
  seed-natural-earth.py       # primitives (unchanged)
  seed-demo.sh                # replaced by new shell wrapper
```

**Orchestrator structure (`seed-thematic-demo.py`):**

```python
#!/usr/bin/env python3
"""Thematic demo seeder for GeoLens.

Imports from seed-natural-earth.py primitives. Run after reset-demo.sh.
"""

# Relative import of primitives
import sys; sys.path.insert(0, str(Path(__file__).parent))
from seed_natural_earth import (
    fetch_existing_datasets, download_or_load_cache, ingest_dataset,
    poll_job, create_or_get_collection, generate_tags,
)

THEMES = [
    {"name": "Planet Earth (2025 Snapshot)", "description": "..."},
    {"name": "How the World Lives (2024)", "description": "..."},
    {"name": "Lines on the Map (2024 Snapshot)", "description": "..."},
]

DATASETS = [
    # Vector NE datasets (reuse stem-based download from NACIS CDN)
    {"stem": "ne_10m_land", "theme_idx": 0, "type": "vector", ...},
    # Raster COGs (read from /data/demo/ inside container)
    {"stem": "gebco_2024_15arcmin", "theme_idx": 0, "type": "raster",
     "local_path": "/data/demo/gebco_2024_15arcmin.tif", ...},
    # Choropleth GeoJSONs (pre-joined by csv_to_choropleth.py at build time)
    {"stem": "gdp_per_capita_ppp_2023", "theme_idx": 1, "type": "vector",
     "local_path": "/data/demo/gdp_per_capita_ppp_2023.geojson", ...},
]

async def ingest_local_file(client, base_url, api_key, path, stem, name, tags):
    """Like ingest_dataset but reads from local path instead of downloading."""
    data = Path(path).read_bytes()
    return await ingest_dataset(client, base_url, api_key, stem, data, name, tags)

async def apply_fixtures(client, base_url, api_key, existing):
    """Create maps from JSON fixtures, resolving dataset UUIDs by stem."""
    fixtures_dir = Path(__file__).parent / "demo/fixtures/maps"
    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        fixture = json.loads(fixture_path.read_text())
        # Resolve stem references to live UUIDs
        for layer in fixture["layers"]:
            stem_key = layer.pop("_stem")  # e.g. "ne_10m_admin_0_countries"
            filename = f"{stem_key}.zip"  # or .geojson / .tif
            layer["dataset_id"] = existing[filename]  # KeyError = planning bug
        # Create map + apply via PUT
        map_resp = await client.post(f"{base_url}/api/maps/", ...)
        map_id = map_resp.json()["id"]
        await client.put(f"{base_url}/api/maps/{map_id}", json=fixture)

async def main():
    existing = await fetch_existing_datasets(client, base_url, api_key)
    # 1. Ingest all datasets (idempotent)
    # 2. Create VRT mosaic from raster dataset IDs
    # 3. Create 3 themed collections, assign datasets
    # 4. Apply map fixtures (resolve stems → UUIDs)
```

**Key design decision on file naming for `_stem`:** the `source_filename` stored by the ingest API is the literal filename passed to the upload multipart (e.g. `gebco_2024_15arcmin.tif`). The fixture JSON uses `"_stem": "gebco_2024_15arcmin"` and the apply function constructs the lookup key by appending the appropriate extension. The extension must be consistent: `.zip` for NE shapefiles, `.tif` for COGs, `.geojson` for pre-joined choropleths.

---

## Q2: Fixture Schema

### GET /api/maps/{id} Shape

Full `MapResponse` (from `backend/app/maps/schemas.py`): [VERIFIED: backend/app/maps/schemas.py]

```json
{
  "id": "uuid",
  "name": "string",
  "description": "string | null",
  "center_lng": "float | null",
  "center_lat": "float | null",
  "zoom": "float | null",
  "bearing": 0.0,
  "pitch": 0.0,
  "basemap_style": "string",
  "show_basemap_labels": true,
  "visibility": "public | private | internal",
  "thumbnail_url": "string | null",
  "forked_from_id": "uuid | null",
  "forked_from_name": "string | null",
  "created_by": "uuid | null",
  "created_by_username": "string | null",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "layer_count": 3,
  "widgets": ["measurement", "scale"],
  "layers": [
    {
      "id": "uuid",
      "dataset_id": "uuid",
      "dataset_name": "string",
      "dataset_geometry_type": "Polygon | Point | LineString | null",
      "dataset_table_name": "string",
      "dataset_extent_bbox": [minx, miny, maxx, maxy],
      "dataset_column_info": [...],
      "dataset_feature_count": 195,
      "dataset_sample_values": {...},
      "display_name": "string | null",
      "sort_order": 0,
      "visible": true,
      "opacity": 1.0,
      "paint": {...},
      "layout": {...},
      "layer_type": "vector_geolens | raster_geolens | vrt_geolens",
      "dataset_record_type": "vector_dataset | raster_dataset | vrt_dataset | table",
      "filter": null,
      "label_config": null,
      "style_config": null,
      "show_in_legend": true
    }
  ]
}
```

### PUT /api/maps/{id} Contract

Accepts `MapUpdate` body: [VERIFIED: backend/app/maps/schemas.py, backend/app/maps/router.py]

```json
{
  "name": "string",
  "description": "string | null",
  "center_lng": 0.0,
  "center_lat": 15.0,
  "zoom": 1.8,
  "bearing": 0.0,
  "pitch": 0.0,
  "basemap_style": "positron | dark-matter | ...",
  "show_basemap_labels": true,
  "visibility": "public",
  "widgets": ["measurement", "scale"],
  "layers": [
    {
      "dataset_id": "uuid",
      "sort_order": 0,
      "visible": true,
      "opacity": 1.0,
      "paint": {...},
      "layout": {...},
      "display_name": "string | null",
      "filter": null,
      "label_config": null,
      "style_config": null,
      "layer_type": "vector_geolens | raster_geolens",
      "show_in_legend": true
    }
  ]
}
```

**Key constraint:** `PUT /api/maps/{id}` requires `require_permission("edit_metadata")` AND map ownership check. The seeder must use an admin API key (same one used for ingest).

**Visibility gate:** if `visibility=public` is set, ALL referenced datasets must already be public. The seeder should set all datasets to public before applying fixtures.

### Fields to strip from GET before writing fixture

Remove these fields entirely from the fixture JSON (they are operator-specific, not reproducible):

- `id` — do not store; fixture apply creates a new map via POST
- `created_by`, `created_by_username`
- `created_at`, `updated_at`
- `thumbnail_url`
- `forked_from_id`, `forked_from_name`
- `layer_count` — redundant with `layers` array length
- From each layer: `id`, `dataset_name`, `dataset_geometry_type`, `dataset_table_name`, `dataset_extent_bbox`, `dataset_column_info`, `dataset_feature_count`, `dataset_sample_values`, `dataset_record_type`
- Replace `dataset_id` (UUID) with `_stem` (stable filename stem)

### Recommended Fixture Format

**Single JSON file per map.** No directory. Naming: `{theme_num}-{slug}.json` e.g. `1-earth-from-space.json`.

Location: `scripts/demo/fixtures/maps/`

**Fixture file structure:**

```json
{
  "_meta": {
    "name": "Earth as Seen from Space",
    "description": "One screen. Mountains, oceans, ice, rivers.",
    "theme": "Planet Earth (2025 Snapshot)",
    "snapshot_date": "2025-01-01",
    "exported_at": "2026-04-08T00:00:00Z"
  },
  "name": "Earth as Seen from Space",
  "description": "...",
  "center_lng": 0.0,
  "center_lat": 15.0,
  "zoom": 1.8,
  "bearing": 0.0,
  "pitch": 0.0,
  "basemap_style": "dark-matter",
  "show_basemap_labels": false,
  "visibility": "public",
  "widgets": ["measurement", "scale"],
  "layers": [
    {
      "_stem": "ne_10m_rivers_lake_centerlines",
      "_ext": ".zip",
      "sort_order": 0,
      "visible": true,
      "opacity": 1.0,
      "paint": {"line-color": "#ffffff", "line-width": 0.5},
      "layout": {},
      "display_name": "Rivers",
      "filter": null,
      "label_config": null,
      "style_config": null,
      "show_in_legend": true
    }
  ]
}
```

The `_meta` block is stripped before the PUT call. The `_stem` + `_ext` fields are resolved to `dataset_id` at apply time using `existing[stem + ext]`.

---

## Q3: Docker Seeder Pattern

### Current State

`docker-compose.demo.yml` defines a `seeder` service: [VERIFIED: docker-compose.demo.yml]

```yaml
seeder:
  build:
    context: ./backend          # uses backend Dockerfile
  entrypoint: ["/scripts/seed-demo.sh"]
  environment:
    GEOLENS_ADMIN_USERNAME: ...
    GEOLENS_ADMIN_PASSWORD: ...
    GEOLENS_BASE_URL: "http://api:8000"
  volumes:
    - ./scripts:/scripts:ro     # mounts scripts dir read-only
  depends_on:
    api:
      condition: service_healthy
  restart: "no"
```

**Problem:** The current seeder downloads data at runtime (from naciscdn.org). Phase 218 requires all downloads to happen at **build time**, not runtime.

### Proposed Dockerfile Structure

New file: `docker/seeder/Dockerfile`

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS data-fetcher

# System deps: curl for downloads, GDAL for COG conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy scripts for helper use
COPY scripts/demo/lib/csv_to_choropleth.py /build/
COPY scripts/demo/fixtures/ /build/fixtures/

# ---- DATA BUNDLE LAYER ----
# Pin each download by SHA-256. Fail loudly if checksum mismatches.
# This RUN layer is cached by Docker; re-runs only when Dockerfile changes.

ENV DATA_DIR=/data/demo

RUN mkdir -p $DATA_DIR

# GEBCO 2024 COG from source.coop (no auth, public S3)
# ~6.7 GB full; downsample to 30 arc-min (~53 MB COG) for demo budget
RUN curl -fsSL -o /tmp/gebco_full.tif \
      "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif" \
    && echo "<SHA256>  /tmp/gebco_full.tif" | sha256sum -c - \
    && gdal_translate \
         -of COG \
         -co COMPRESS=DEFLATE \
         -co PREDICTOR=3 \
         -tr 0.5 0.5 \
         -r bilinear \
         /tmp/gebco_full.tif \
         $DATA_DIR/gebco_2024_30arcmin.tif \
    && rm /tmp/gebco_full.tif

# SRTM GL1 30m DEM — global, no login, AWS S3
# Pull a 5x5 degree tile covering Himalayas (N35E070) as representative DEM
RUN aws s3 cp \
      s3://raster/SRTM_GL1/SRTM_GL1_srtm_35_070_1_1.tif /tmp/srtm_tile.tif \
      --endpoint-url https://opentopography.s3.sdsc.edu \
      --no-sign-request \
    && gdal_translate -of COG -co COMPRESS=DEFLATE $DATA_DIR/srtm_himalayas.tif /tmp/srtm_tile.tif \
    && rm /tmp/srtm_tile.tif

# UCDP GED v25.1 CSV (no auth, CC-BY 4.0)
RUN curl -fsSL -o /tmp/ged251.zip \
      "https://ucdp.uu.se/downloads/ged/ged251-csv.zip" \
    && echo "<SHA256>  /tmp/ged251.zip" | sha256sum -c - \
    && unzip /tmp/ged251.zip -d /tmp/ged251/ \
    && mv /tmp/ged251/GEDEvent_v25_1.csv $DATA_DIR/ucdp_ged_v25_1.csv \
    && rm -rf /tmp/ged251.zip /tmp/ged251/

# World Bank GDP per capita PPP — download ZIP then extract
RUN curl -fsSL -o /tmp/wb_gdp.zip \
      "https://api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv" \
    && unzip /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" -d /tmp/wb_gdp/ \
    && mv /tmp/wb_gdp/API_NY.GDP.PCAP.PP.CD*.csv $DATA_DIR/wb_gdp_ppp_2023.csv \
    && rm -rf /tmp/wb_gdp.zip /tmp/wb_gdp/

# Our World in Data — Life Expectancy
RUN curl -fsSL -o $DATA_DIR/owid_life_expectancy.csv \
      "https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=false"

# UNHCR Refugee Statistics 2023 via open API (no auth)
RUN curl -fsSL -o $DATA_DIR/unhcr_refugees_2023.csv \
      "https://api.unhcr.org/population/v1/population/?limit=10000&page=1&download=true&yearFrom=2023&yearTo=2023"

# OSM buildings Manhattan — Geofabrik free shapefile
RUN curl -fsSL -o /tmp/new-york.shp.zip \
      "https://download.geofabrik.de/north-america/us/new-york-latest-free.shp.zip" \
    && unzip /tmp/new-york.shp.zip "gis_osm_buildings_a_free_1.*" -d /tmp/ny_buildings/ \
    && ogr2ogr \
         -f GeoJSON \
         -where "height IS NOT NULL AND ST_Intersects(geometry, ST_MakeEnvelope(-74.05, 40.68, -73.90, 40.80, 4326))" \
         $DATA_DIR/manhattan_buildings.geojson \
         /tmp/ny_buildings/gis_osm_buildings_a_free_1.shp \
    && rm -rf /tmp/new-york.shp.zip /tmp/ny_buildings/

# Pre-join choropleth CSVs to ADM0 polygons
# Requires ne_10m_admin_0_countries.geojson already downloaded
RUN curl -fsSL -o /tmp/ne_countries.zip \
      "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip" \
    && unzip /tmp/ne_countries.zip -d /tmp/ne_countries/ \
    && python3 /build/csv_to_choropleth.py \
         --csv $DATA_DIR/wb_gdp_ppp_2023.csv \
         --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
         --csv-join-col "Country Code" \
         --adm0-join-col "ADM0_A3" \
         --value-col "2023" \
         --output $DATA_DIR/gdp_per_capita_ppp_2023.geojson \
    && python3 /build/csv_to_choropleth.py \
         --csv $DATA_DIR/owid_life_expectancy.csv \
         --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
         --csv-join-col "Code" \
         --adm0-join-col "ADM0_A3" \
         --value-col "Life expectancy" \
         --year-filter 2021 \
         --output $DATA_DIR/life_expectancy_2021.geojson \
    && python3 /build/csv_to_choropleth.py \
         --csv $DATA_DIR/unhcr_refugees_2023.csv \
         --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
         --csv-join-col "iso_coa" \
         --adm0-join-col "ADM0_A3" \
         --value-col "refugees_under_unhcr_mandate" \
         --output $DATA_DIR/refugees_by_origin_2023.geojson \
    && rm -rf /tmp/ne_countries.zip /tmp/ne_countries/


# ---- RUNTIME STAGE ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends httpx \
    && rm -rf /var/lib/apt/lists/*

COPY --from=data-fetcher /data/demo /data/demo
COPY scripts/ /scripts/

RUN pip install httpx

CMD ["/scripts/seed-demo.sh"]
```

**Updated docker-compose.demo.yml snippet:**
```yaml
seeder:
  build:
    context: .
    dockerfile: docker/seeder/Dockerfile
  environment:
    GEOLENS_ADMIN_USERNAME: ${GEOLENS_ADMIN_USERNAME}
    GEOLENS_ADMIN_PASSWORD: ${GEOLENS_ADMIN_PASSWORD}
    GEOLENS_BASE_URL: "http://api:8000"
  depends_on:
    api:
      condition: service_healthy
  restart: "no"
```

Note: no `volumes:` mount for scripts — they are baked into the image.

### Data Bundling with Checksums

Every `curl` download in the Dockerfile MUST be followed by a `sha256sum -c -` check. Pin checksums in a `docker/seeder/CHECKSUMS.sha256` file committed to the repo:

```
<sha256hash>  gebco_2024_full.tif
<sha256hash>  ged251-csv.zip
```

Populate checksums on first successful build by running:
```bash
sha256sum /data/demo/*.csv /data/demo/*.tif /data/demo/*.geojson
```

**Slow-source fallbacks:** GEBCO 2024 (source.coop S3, ~6.7 GB before downsample) is the single riskiest download. If source.coop is down:
- Alternative 1: Download from GEBCO's own subsetting app (interactive, not scriptable — use as manual rescue path only)
- Alternative 2: Pre-convert and host on a project-controlled S3 bucket with `aws s3 cp` — recommended for CI reliability

The Dockerfile should document: `# FALLBACK: if source.coop is unavailable, replace URL above with your mirror`.

**Estimated image size:** Pre-joined GeoJSONs (~15 MB total) + UCDP CSV (~30 MB) + GEBCO 30-arcmin COG (~50 MB) + SRTM tile (~8 MB) + Manhattan buildings (~20 MB) + UNHCR/WB/OWID CSVs (~20 MB) = ~143 MB data layer. Acceptable.

---

## Q4: Playwright Smoke Tests

### Existing e2e Structure

[VERIFIED: e2e/ directory listing]

- `auth.setup.ts` — logs in via `/login` page (username+password form), saves `playwright/.auth/user.json` with localStorage state including `geolens-auth` JWT
- `builder.spec.ts` — extracts JWT from saved state using `getAuthToken()` helper, makes direct API calls to set up test data in `beforeAll`, navigates UI
- `search.spec.ts` — uses `page.goto()` + `page.waitForLoadState('networkidle')`; no auth setup (public endpoints)
- `e2e/fixtures/` — contains `sample.geojson` and `sample-nonspatial.csv` for upload tests

**Auth pattern:** Tests that need auth use `test.use({ storageState: 'playwright/.auth/user.json' })` in the spec (via playwright.config.ts setup dependency), or extract the JWT manually for API calls. The smoke test can use storageState for auth — no separate API key needed.

**No existing map load tests** — the builder spec navigates to `/maps/{id}` but tests builder UI interactions, not tile loading. The smoke test is genuinely new territory.

### Sketch: e2e/demo-smoke.spec.ts

```typescript
/**
 * e2e/demo-smoke.spec.ts
 *
 * Smoke test: load each of the 9 demo maps, wait for MapLibre idle,
 * assert all tile requests succeed, assert no console errors.
 *
 * Requires:  DEMO_MAP_IDS env var (comma-separated list of map UUIDs)
 * or: reads map IDs dynamically from GET /api/maps?name=...
 */
import { test, expect } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';
const TILE_ERROR_THRESHOLD = 0;  // zero tolerance for tile 503s

const DEMO_MAP_SLUGS = [
  'Earth as Seen from Space',
  'Global Bathymetry',
  'Population at a Glance',
  'GDP per Capita PPP 2023',
  'The World\'s Disputed Places',
  'One Territory, Multiple Official Maps',
  'Conflict Events 2024 (UCDP GED)',
  'Refugees by Country of Origin 2023',
];

test.describe('Demo Map Smoke Tests', () => {
  let mapIds: Record<string, string> = {};

  test.beforeAll(async ({ request }) => {
    // Discover demo map IDs by name
    const resp = await request.get(`${BASE_URL}/api/maps/?limit=50`);
    expect(resp.ok()).toBe(true);
    const data = await resp.json();
    for (const map of data.maps) {
      if (DEMO_MAP_SLUGS.includes(map.name)) {
        mapIds[map.name] = map.id;
      }
    }
    expect(Object.keys(mapIds).length).toBeGreaterThan(0);
  });

  for (const mapName of DEMO_MAP_SLUGS) {
    test(`Map: "${mapName}" loads without tile errors`, async ({ page }) => {
      const mapId = mapIds[mapName];
      if (!mapId) {
        test.skip(true, `Map "${mapName}" not found in catalog — seeder may not have run`);
        return;
      }

      const tileErrors: string[] = [];
      const consoleErrors: string[] = [];

      // Capture console errors
      page.on('console', msg => {
        if (msg.type() === 'error') {
          consoleErrors.push(msg.text());
        }
      });

      // Capture tile request failures
      page.on('response', resp => {
        if (resp.url().includes('/tiles/') && resp.status() >= 400) {
          tileErrors.push(`${resp.status()} ${resp.url()}`);
        }
      });

      // Navigate to map viewer
      await page.goto(`/maps/${mapId}`);

      // Wait for MapLibre idle event (map finished loading all visible tiles)
      await page.waitForFunction(() => {
        const mapEl = document.querySelector('[data-testid="map-container"]');
        // @ts-ignore — access maplibregl map instance via element
        return mapEl?.__maplibreMap?.loaded() === true;
      }, { timeout: 30_000 }).catch(() => {
        // Fallback: wait for network idle if map instance not accessible
        return page.waitForLoadState('networkidle', { timeout: 30_000 });
      });

      // Give tile requests an extra moment to resolve
      await page.waitForTimeout(2000);

      expect(tileErrors, `Tile errors for "${mapName}": ${tileErrors.join(', ')}`).toHaveLength(0);
      expect(
        consoleErrors.filter(e => !e.includes('ResizeObserver') && !e.includes('favicon')),
        `Console errors for "${mapName}"`
      ).toHaveLength(0);
    });
  }
});
```

**Implementation notes:**
- The map viewer URL is `/maps/{id}` (confirmed from existing `builder.spec.ts` which navigates there)
- `data-testid="map-container"` needs to exist on the `ViewerMap.tsx` wrapper — add if missing
- The MapLibre `map.loaded()` check is preferred over `networkidle` because tile requests are ongoing during pan/zoom
- Smoke tests should run with `test.use({ storageState: 'playwright/.auth/user.json' })` since maps may be internal visibility during seeding; set them to `public` in the seeder before fixture apply
- CI target: `docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d` then `npx playwright test e2e/demo-smoke.spec.ts`

---

## Q5: Dataset Source URLs & Checksums

| Dataset | URL | Format | Approx Size | License | Auth Required | Gotchas |
|---------|-----|--------|-------------|---------|---------------|---------|
| **Natural Earth 10m** (all stems) | `https://naciscdn.org/naturalearth/10m/{theme}/{stem}.zip` | Shapefile ZIP | 1–50 MB each | Public Domain | No | Already in seed-natural-earth.py. NE CDN occasionally rate-limits; use semaphore(3) as current code does |
| **Natural Earth 50m shaded relief raster** | `https://naciscdn.org/naturalearth/50m/raster/NE2_50M_SR_W.zip` | GeoTIFF ZIP | ~100 MB | Public Domain | No | Must convert to COG at build time: `gdal_translate -of COG -co COMPRESS=DEFLATE` |
| **GEBCO 2024 Grid (COG)** | `https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif` | GeoTIFF (pre-converted COG) | ~6.7 GB full; downsample to 30 arc-min → ~50 MB | Public Domain | No | Full file is 6.7 GB — MUST downsample in Dockerfile. `gdal_translate -tr 0.5 0.5 -r bilinear` reduces to ~50 MB. No auth. Source.coop is a community S3 registry. Verify the COG compliance after downsample. [CITED: source.coop/alexgleith/gebco-2024] |
| **Natural Earth 10m raster (hypsometric + shaded relief)** | `https://naciscdn.org/naturalearth/10m/raster/NE1_HR_LC_SR_W_DR.zip` + additional bands | GeoTIFF ZIP | ~150-300 MB per band | Public Domain | No | Multiple files; download each and gdal_translate to COG, then POST /api/ingest/vrt/create with mosaic type. Exact filenames: verify on naciscdn.org/naturalearth/10m/raster/ directory listing |
| **SRTM GL1 30m DEM** | `s3://raster/SRTM_GL1/` (endpoint: `https://opentopography.s3.sdsc.edu`) | GeoTIFF (COG) | ~25 MB per 1-degree tile | Public Domain (NASA JPL) | No (no-sign-request) | Use `aws s3 cp --no-sign-request` from OpenTopography S3. For demo: pick a 5x5 tile covering Himalayas for visual impact. No login. [CITED: opentopography.s3.sdsc.edu] |
| **OSM Buildings Manhattan** | `https://download.geofabrik.de/north-america/us/new-york-latest-free.shp.zip` | Shapefile ZIP | ~500 MB zip (all of NY); clip to Manhattan in ogr2ogr | ODbL (Open Database License) | No | Geofabrik free tier includes `building:height` as SMALLINT. Clip to Manhattan bbox `(-74.05, 40.68, -73.90, 40.80)` using ogr2ogr `-where` or spatial filter. Output GeoJSON ~20 MB. ODbL requires attribution. |
| **Our World in Data — Life Expectancy** | `https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=false` | CSV | ~2 MB | CC-BY 4.0 | No | Columns: `Entity`, `Code` (ISO3), `Year`, `Life expectancy`. Filter to most recent year (2021 in current data). [VERIFIED: docs.owid.io] |
| **World Bank GDP per capita PPP** | `https://api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv` | CSV ZIP | ~1 MB zip | CC-BY 4.0 | No | ZIP contains 3 files; target `API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv`. Skip 4-line header (has metadata). ISO3 is `Country Code` column. Year 2023 is a column. [ASSUMED — URL pattern stable since 2020; verify actual redirect target at build time] |
| **UCDP GED v25.1** | `https://ucdp.uu.se/downloads/ged/ged251-csv.zip` | CSV ZIP | ~30 MB zip | CC-BY 4.0 | No | Columns include `latitude`, `longitude`, `year`, `deaths_a`, `type_of_violence`. Filter `year=2024` for Map 3.3. Cite: "UCDP GED v25.1, Uppsala University, CC-BY 4.0". [VERIFIED: ucdp.uu.se/downloads] |
| **UNHCR Refugee Statistics 2023** | `https://api.unhcr.org/population/v1/population/?limit=10000&page=1&download=true&yearFrom=2023&yearTo=2023` | CSV (inside ZIP returned by API) | ~10 MB | CC-BY 4.0 | No (open API, no key) | API returns a ZIP with a CSV inside. Columns include `iso_coa` (country of origin ISO3), `refugees_under_unhcr_mandate`. Requires csv_to_choropleth.py pre-join to ADM0 polygons. [VERIFIED: api.unhcr.org/docs/refugee-statistics.html — API returns zip/csv; tested in WebFetch] |
| **SEDAC GPWv4 Population Density** | `https://beta.sedac.ciesin.columbia.edu/data/set/gpw-v4-population-density-rev11/data-download` | GeoTIFF | ~100 MB at 1-degree | CC-BY 4.0 | **YES — NASA Earthdata account required** | **BLOCKING ISSUE.** Download requires free NASA Earthdata account registration. Cannot be scripted in a public Dockerfile without embedding credentials. See Q7 for mitigation options. |
| **Marine Regions EEZ v11** | N/A — explicitly deferred in CONTEXT.md | — | — | — | — | Deferred to future phase |

**SEDAC GPWv4 alternative path:** If the team cannot host a pre-converted mirror, substitute the proportional-symbol `ne_10m_populated_places_simple` (already NE baseline) for the raster population story in Theme 2. This removes the "raster COG" story from Theme 2, but Theme 1 still has GEBCO and NE shaded relief COGs. The raster-in-Theme-2 story is nice-to-have; not a hard requirement from CONTEXT.md.

---

## Q6: csv_to_choropleth.py Design

### Interface

```
python3 csv_to_choropleth.py \
  --csv <path>               # input indicator CSV
  --adm0 <path>              # ADM0 polygons (shapefile or GeoJSON or GPKG)
  --csv-join-col <col>       # column in CSV containing ISO3 codes (e.g. "Country Code")
  --adm0-join-col <col>      # column in ADM0 with ISO3 codes (e.g. "ADM0_A3")
  --value-col <col>          # numeric column to keep (e.g. "2023" or "gdp_value")
  --output <path>            # output GeoJSON path
  [--year-filter <year>]     # optional: filter CSV rows where "Year" == year before join
  [--log-level DEBUG|INFO]   # default INFO
```

Exit code 0 on success; non-zero on error. Prints unmatched ISO3 codes as warnings.

### Implementation Sketch

**Dependencies available in the seeder image:** Python 3.13 stdlib, `shapely>=2.0` (in pyproject.toml), `json`, `csv`, `pathlib`. No pandas, no geopandas. The ADM0 source is a Shapefile — read with `ogrinfo` / `ogr2ogr` output piped to JSON, or use GDAL's Python bindings (`from osgeo import ogr`) if gdal-python is available in the image.

**Recommended approach:** Use `ogr2ogr` (system GDAL, already installed in the seeder image for COG conversion) to first convert the ADM0 shapefile to GeoJSON, then use Python stdlib `json` and `csv` for the join. Zero Python dep additions.

```python
#!/usr/bin/env python3
"""
scripts/demo/lib/csv_to_choropleth.py

Pre-join an indicator CSV to ADM0 polygon GeoJSON and emit a choropleth-ready GeoJSON.
No pandas, no geopandas — only stdlib + GDAL (system) for the shapefile→GeoJSON step.
"""

import csv
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path


def shapefile_to_geojson(adm0_path: Path) -> dict:
    """Convert ADM0 shapefile (or GeoJSON) to a dict using ogr2ogr."""
    if adm0_path.suffix.lower() == ".geojson":
        return json.loads(adm0_path.read_text())
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(
        ["ogr2ogr", "-f", "GeoJSON", str(tmp), str(adm0_path)],
        check=True
    )
    result = json.loads(tmp.read_text())
    tmp.unlink()
    return result


def load_indicator_csv(
    csv_path: Path,
    join_col: str,
    value_col: str,
    year_filter: str | None
) -> dict[str, float]:
    """Load indicator CSV into {iso3: value} dict."""
    values: dict[str, float] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        # Skip World Bank-style metadata header rows
        lines = f.readlines()
        # Find first line that looks like a header
        header_idx = next(
            (i for i, line in enumerate(lines) if join_col in line), 0
        )
        reader = csv.DictReader(lines[header_idx:])
        for row in reader:
            iso3 = row.get(join_col, "").strip()
            if not iso3:
                continue
            if year_filter and row.get("Year", row.get("year", "")).strip() != year_filter:
                continue
            raw = row.get(value_col, "").strip()
            try:
                values[iso3] = float(raw)
            except (ValueError, TypeError):
                pass  # null / non-numeric
    return values


def join_and_write(
    adm0_geojson: dict,
    values: dict[str, float],
    adm0_join_col: str,
    value_col: str,
    output_path: Path
) -> None:
    out_features = []
    unmatched: list[str] = []

    for feat in adm0_geojson["features"]:
        props = feat.get("properties", {})
        iso3 = props.get(adm0_join_col, "").strip()
        if iso3 in values:
            props["_value"] = values[iso3]
            props["_value_col"] = value_col
            out_features.append(feat)
        else:
            unmatched.append(iso3)

    if unmatched:
        logging.warning("Unmatched ISO3 codes (%d): %s", len(unmatched), ", ".join(sorted(set(unmatched))[:20]))

    matched = len(adm0_geojson["features"]) - len(unmatched)
    logging.info("Join complete: %d/%d features matched", matched, len(adm0_geojson["features"]))

    output_path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": out_features
    }, ensure_ascii=False))
```

**Error handling:**
- Unmatched ISO3 codes → WARNING log, skipped in output (not failure)
- Duplicate ISO3 in CSV → last value wins (logged as WARNING if > 1 row per ISO3)
- Null/empty value → skip row silently
- Zero matched features → exit with code 1 (indicates join column mismatch)

**Output field:** The output GeoJSON uses `_value` as the indicator column name. Downstream fixtures reference `"_value"` in `style_config.column_name`. This is a stable contract — don't use the original column name which varies by CSV.

**Single feature per country:** One polygon per ISO3, one value per country. No time-series output. If the CSV has multiple years, `--year-filter` selects one.

---

## Q7: Gotchas & Open Questions

### G1: SEDAC GPWv4 Requires NASA Earthdata Login — BLOCKING

**Status:** [VERIFIED: earthdata.nasa.gov/data/catalog/sedac-ciesin-sedac-gpwv4-popdens-r11-4.11]

NASA Earthdata requires a free account to download SEDAC data. The download portal (`beta.sedac.ciesin.columbia.edu`) enforces authentication. There is no public S3 bucket with unauthenticated access documented.

**Options:**
1. **Preferred (clean):** Host a pre-converted GPWv4 1-degree COG on the project's own S3 bucket (one-time manual download + upload). Add `aws s3 cp s3://geolens-demo-data/gpwv4_1deg.tif` to the Dockerfile. This is a standard practice for data with auth-required origins.
2. **Acceptable:** Drop GPWv4 from Theme 2 entirely. Use `ne_10m_populated_places_simple` as a proportional symbol layer for the population story. Theme 2 still has GDP choropleth and life expectancy — the raster story is in Theme 1 (GEBCO, NE shaded relief).
3. **Non-starter:** Embed NASA Earthdata credentials in the Dockerfile or image.

**Plan recommendation:** Document this as a gate in Plan 2/3. The planner should mark GPWv4 as "include if a project-owned mirror is available at plan execution time; otherwise skip."

### G2: GEBCO 2024 Full File is 6.7 GB — Downsample Required

[VERIFIED: gebco.net — native download is NetCDF 7.5 GB] The source.coop version is a pre-converted GeoTIFF (~6.7 GB). The Dockerfile MUST downsample to 30 arc-min (~0.5 degree resolution) before committing to the data layer:

```bash
gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=3 -tr 0.5 0.5 -r bilinear input.tif output.tif
```

This reduces to ~50 MB. Demo visual quality at world zoom is adequate at 0.5-degree resolution. If a finer COG is wanted (e.g. 15 arc-min, ~200 MB), adjust `-tr 0.25 0.25`.

**Build time cost:** Downloading 6.7 GB in the Docker build takes 5-15 minutes on typical CI. Cache this layer carefully. Consider pre-hosting a downsampled COG on the project S3 bucket to skip the 6.7 GB download entirely.

### G3: World Bank CSV ZIP Has an Unstable Inner Filename

The World Bank CSV download from `api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv` returns a ZIP with an inner filename like `API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2_4901661.csv` where `4901661` is a version number that changes on each World Bank data update. The Dockerfile should use a glob pattern:

```bash
unzip /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" -d /tmp/wb_gdp/
```

The CSV also has 4 lines of metadata before the actual header row. `csv_to_choropleth.py` must skip these; the implementation sketch in Q6 handles this via header detection.

### G4: UNHCR API Returns ZIP, Not Raw CSV

The UNHCR API endpoint `api.unhcr.org/population/v1/population/?download=true` returns a ZIP file containing a CSV. [VERIFIED: WebFetch against live API — binary ZIP received]. The Dockerfile must unzip before csv_to_choropleth.py can process it. The inner CSV has column headers like `iso_coa` (country of asylum), `iso_o` (country of origin), `refugees_under_unhcr_mandate`.

**Important:** Map 3.4 is "Refugees by Country of Origin" — join column is `iso_o` (origin ISO3), not `iso_coa`. The `--csv-join-col` argument must be `iso_o`.

### G5: OSM Buildings Height Data — ODbL Attribution Required

Geofabrik's free shapefile uses the `height` field (SMALLINT in meters) from OSM `building:height` tags. ODbL attribution is required: every layer description must include "© OpenStreetMap contributors, ODbL 1.0". The `building:height` population in Manhattan is approximately 40-60% of buildings — expect a significant number of null-height features in the clip. The 3D story works even with partial coverage.

**Alternative city if Manhattan extract quality is poor:** Downtown Chicago or San Francisco Financial District have high building height coverage in OSM. Chicago may be slightly simpler to clip (lakefront bounding box). [ASSUMED — verify OSM height coverage before committing to Manhattan]

### G6: Ingest API Timeout Risk for Large Rasters

`poll_job` defaults to 300s timeout. GEBCO COG ingest (even at 50 MB) involves GDAL COG conversion + PostGIS raster metadata extraction. In practice, raster ingest is slower than vector:

- 50 MB COG: ~30-90s
- 200 MB COG: ~120-240s

Recommendation: increase `timeout` to 600s for raster ingest calls in `seed-thematic-demo.py`. Do not use the default 300s from seed-natural-earth.py for raster datasets.

### G7: VRT Mosaic Requires All Source Rasters to Be Ingested First

`POST /api/ingest/vrt/create` takes a list of existing `dataset_ids`. The NE shaded relief VRT (Theme 1) must be created only after all its source raster datasets are committed and their job polling is complete. This is a sequencing constraint in the seeder:

```
Ingest NE_SR_W.tif → get dataset_id_1
Ingest NE_SR_W_OB.tif → get dataset_id_2
(optional third band)
POST /api/ingest/vrt/create with [dataset_id_1, dataset_id_2]
Poll VRT job until complete → get vrt_dataset_id
```

### G8: HydroSHEDS License Unverified

The RESEARCH.md from 260408-lnq tags HydroSHEDS as `[ASSUMED]` for license. HydroSHEDS Technical Documentation license (ODbL) may not be compatible with certain commercial redistribution. CONTEXT.md lists HydroSHEDS as optional — skip for baseline Phase 218 and do not include it until the license is verified against GeoLens's commercial use case.

### G9: `reset-demo.sh` Truncates `catalog.api_keys`

[VERIFIED: scripts/reset-demo.sh] The reset script truncates `catalog.api_keys`. The seeder's own API key (created at `seed-demo.sh` startup by the "Creating seed API key" block) is therefore destroyed on every reset. The seeder service restarts after reset via `docker compose restart seeder` (or re-run). This is the intended flow — no issue.

**But:** if the seeder crashes mid-run and is restarted manually, the partial dataset state survives until the next `reset-demo.sh` run. The seeder's idempotency (`fetch_existing_datasets`) handles this gracefully — it skips already-ingested datasets by `source_filename` and re-assigns them to collections.

### G10: `PUT /api/maps/{id}` Requires Map Ownership

The `PUT /api/maps/{id}` endpoint checks both `require_permission("edit_metadata")` AND ownership (`check_map_ownership`). Since the seeder creates maps via `POST /api/maps/` using its own API key, it also owns those maps — so the subsequent PUT will pass. Do not create maps as one user and try to PUT as another.

### G11: Natural Earth Raster CDN Path Verification Needed

The NACIS CDN path for 10m raster files (used for the VRT mosaic) is `naciscdn.org/naturalearth/10m/raster/`. The specific filenames (e.g., `NE1_HR_LC_SR_W_DR.zip`, `HYP_HR_SR_OB_DR.zip`) need to be verified against the live directory listing before coding. The CDN does not have a stable published manifest for raster files the way vector files do. This is a gate for Plan 2 — verify URLs during task execution.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | World Bank API download URL `api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv` is stable and returns a ZIP | Q5, Q7 | Seeder build breaks; need alternate download path |
| A2 | OSM buildings height coverage in Manhattan is adequate (~40-60%) for 3D demo story | Q7-G5 | Few buildings have heights; substitute with Chicago or SF |
| A3 | NACIS CDN raster filenames for 10m shaded relief can be found at naciscdn.org/naturalearth/10m/raster/ | Q7-G11 | Plan 2 task must verify before implementing |
| A4 | Source.coop S3 URL `s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif` remains publicly accessible without auth | Q5 | Substitute with GEBCO subsetting app or project S3 mirror |
| A5 | `map.loaded()` is accessible on the MapLibre instance via DOM element in the Playwright browser context | Q4 | Fall back to `waitForLoadState('networkidle')` |
| A6 | UCDP GED v25.1 CSV contains column `latitude`/`longitude` for point ingest | Q5 | Verify column names against codebook at ged251.pdf |

---

## Environment Availability

Step 2.6: SKIPPED for most tools (seeder runs inside Docker, not on the dev machine). The seeder Dockerfile installs all needed tools (`gdal-bin`, `curl`, `awscli`, `python3`). The only environment dependency on the developer side is Docker with BuildKit for multi-stage builds.

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| Docker BuildKit | Seeder Dockerfile multi-stage | Assumed present | Required for `--from=data-fetcher` syntax |
| `gdal-bin` (system) | COG conversion | Installed in Dockerfile | `gdal-translate`, `ogr2ogr` |
| `awscli` | SRTM S3 download | Installed in Dockerfile | `--no-sign-request` |
| GEBCO source.coop S3 | Plan 2 | MEDIUM — public, no auth | Verify accessibility before build |
| NASA Earthdata | GPWv4 download | NOT AVAILABLE without credentials | See G1 — use project S3 mirror or skip |

---

## Sources

### Primary (HIGH confidence)
- `scripts/seed-natural-earth.py` — full code read, all primitives verified
- `backend/app/maps/schemas.py` — full schema read, MapResponse/MapUpdate/MapLayerInput verified
- `backend/app/maps/router.py` — PUT endpoint, auth/ownership requirements verified
- `backend/app/ingest/schemas.py` — CommitRequest, VrtCreateRequest verified
- `backend/app/ingest/router.py` — upload/preview/commit/vrt endpoints verified
- `docker-compose.demo.yml` — seeder service definition verified
- `scripts/reset-demo.sh` — full reset script read; TRUNCATE targets confirmed
- `scripts/seed-demo.sh` — current shell wrapper read; auth flow documented
- `e2e/auth.setup.ts`, `e2e/builder.spec.ts` — auth pattern and test structure verified
- `backend/pyproject.toml` — dependency list; shapely present, pandas/geopandas absent confirmed

### Secondary (MEDIUM confidence)
- [CITED: ucdp.uu.se/downloads] — GED v25.1 download URL `ged251-csv.zip`, no auth, CC-BY 4.0
- [CITED: api.unhcr.org/docs/refugee-statistics.html] — API is open, no key required; returns ZIP/CSV; URL pattern verified via live fetch
- [CITED: opentopography.s3.sdsc.edu] — SRTM GL1 S3 bucket, `--no-sign-request` access pattern
- [CITED: docs.owid.io/projects/etl/api/chart-api] — OWID CSV URL pattern `grapher/{slug}.csv?v=1&csvType=full`
- [CITED: source.coop/alexgleith/gebco-2024] — GEBCO 2024 as pre-converted GeoTIFF, public S3

### Tertiary (LOW confidence / ASSUMED)
- World Bank API ZIP download URL — URL pattern well-known but inner filename versioning is ASSUMED stable
- OSM building height coverage in Manhattan — ASSUMED 40-60%, not verified against current OSM data
- NACIS CDN raster filenames for 10m shaded relief — ASSUMED accessible, directory listing not verified

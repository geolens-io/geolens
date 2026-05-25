# Adirondack High Peaks — Marketing Data Pipeline

Reproducible scripts that download, mosaic, and ingest the data behind the GeoLens "Adirondack High Peaks" marketing maps. The pipeline produces:

- 1 DEM raster (USGS 3DEP 1m LiDAR-derived) covering Mt. Marcy, Algonquin, and the Lake Placid region.
- 1 aerial raster (TNM NAIP when available; otherwise tiled NY State 12in orthoimagery, 2022-2025 mosaic).
- 5 vector overlays (APA Blue Line polygon, NYSDEC Hiking Trails, APA Land Classification, NHD flowlines, NHD waterbodies).
- 1 curated point dataset (complete official Adirondack 46er High Peaks list).
- 1-2 saved maps composed via the GeoLens Maps API.

## AOI

Locked bbox (WGS84): `-74.05, 44.08, -73.85, 44.32` — roughly 12 mi east-west by 16 mi north-south, covering Lake Placid village, Mirror Lake, Heart Lake, ADK Loj, Avalanche Lake, Mt. Marcy, and Algonquin Peak.

## Prerequisites

1. Docker stack running healthy at `localhost:8080` (`docker compose ps` shows all 5 services healthy).
2. `>= 25 GB free` in the repo's working directory (`.scratch/adk-data/` will land here).
3. Python 3.11+ with `httpx` available. The repo's `.venv` already has it; use `.venv/bin/python` for the scripts.
4. **No host GDAL required.** The COG-building scripts run all GDAL operations inside the `geolens-api-1` container via `docker exec`.
5. GeoLens admin credentials (default `admin` / `admin` in dev).

## Run order

```bash
cd /Users/ishiland/Code/geolens

# 1. Download DEM tiles (~2.3 GB, 9 tiles)
.venv/bin/python scripts/marketing-data/adk-high-peaks/fetch_dem.py

# 2. Mosaic + reproject + COG-convert the DEM (~1.4 GB output)
bash scripts/marketing-data/adk-high-peaks/build_dem_cog.sh

# 3. Fetch aerial imagery (TNM NAIP first; NY State tiled orthos fallback)
.venv/bin/python scripts/marketing-data/adk-high-peaks/fetch_aerial.py

# 4. Reproject the aerial to web mercator + COG-convert
bash scripts/marketing-data/adk-high-peaks/build_aerial_cog.sh

# 5. Fetch vectors from ArcGIS REST services (APA + NYSDEC + USGS NHD)
.venv/bin/python scripts/marketing-data/adk-high-peaks/fetch_vectors.py

# 6. AOI-clip vectors (defense — most are already server-side AOI-filtered)
bash scripts/marketing-data/adk-high-peaks/clip_vectors.sh

# 7. Ingest everything + compose marketing map(s)
.venv/bin/python scripts/marketing-data/adk-high-peaks/compose_marketing_maps.py
```

The pipeline is idempotent: every step skips already-completed work, so re-running is safe.

## Data sources

| # | Source | URL | Format | License |
|---|--------|-----|--------|---------|
| 1 | USGS 3DEP 1m DEM | https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Digital%20Elevation%20Model%20(DEM)%201%20meter | GeoTIFF tiles, EPSG:26918 (UTM 18N NAD83) | Public domain |
| 2 | TNM NAIP imagery | https://tnmaccess.nationalmap.gov/api/v1/products | GeoTIFF products when available | Public domain |
| 3 | NY State 2022-2025 orthos fallback | https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer | Tiled dynamic ArcGIS exportImage | NY State (public, attribution requested) |
| 4 | APA Adirondack Park Boundary | https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/BluelinePolygon/FeatureServer/0 | Feature Service polygon | NY State / APA (public) |
| 5 | NYSDEC Hiking Trails | https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/DEC_Trails/FeatureServer/1 | Feature Service polyline | NY DEC (public) |
| 6 | APA Land Classification | https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/AdirondackParkLandClassification/FeatureServer/0 | Feature Service polygon | NY State / APA (public) |
| 7 | USGS NHD Flowlines/Waterbodies | https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer | MapServer feature layers | Public domain |
| 8 | ADK 46ers list | https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/Summits/FeatureServer | Generated GeoJSON points (46 features) | Coordinates from APA Summits / USGS GNIS |

## Outputs

| Path | Size | Note |
|------|------|------|
| `.scratch/adk-data/dem/USGS_1M_*.tif` | ~2.3 GB | 9 raw 1m DEM tiles (gitignored) |
| `.scratch/adk-data/aerial/tnm_naip_query.json` | small | Exact TNM NAIP query/response evidence |
| `.scratch/adk-data/aerial/naip_tiles/` | varies | TNM NAIP GeoTIFFs when available |
| `.scratch/adk-data/aerial/ny_orthos_tiles/` | varies | NY orthos tiled fallback GeoTIFFs with sidecar `.tfw` + `.prj` |
| `.scratch/adk-data/cogs/adk_high_peaks_dem_1m.tif` | ~1.4 GB | Mosaicked + EPSG:3857 COG (ingested as DEM raster) |
| `.scratch/adk-data/cogs/adk_high_peaks_ny_orthos_tiled_3857.tif` | varies | EPSG:3857 COG for aerial layer |
| `.scratch/adk-data/vectors/*.geojson` | ~1.5 MB | Raw + AOI-clipped vectors |
| `.scratch/adk-data/vectors/adk_46er_peaks.geojson` | ~50 KB | Complete official 46er peaks generated from APA Summits |
| `scripts/marketing-data/adk-high-peaks/ingest_manifest.yaml` | ~3 KB | Documentation-only manifest (committed) |

## Follow-up: Higher-fidelity aerial

This pipeline now queries TNM for NAIP first and records the exact response in `.scratch/adk-data/aerial/tnm_naip_query.json`. If TNM still returns no NAIP products for the AOI, it falls back to NY State `wms/Latest/MapServer` orthos as a 4x4 grid of 4096x4096 exports instead of a single soft export.

The fallback yields 16384x16384 effective pixels over the AOI before COG conversion, enough for z14-z16 marketing screenshots. NYS DHSES orthos portal downloads may still provide native county tiles, but that flow requires manual UI/email delivery and remains outside this automated pipeline.

## Disk cleanup

After successful ingest the raw downloads are no longer needed (datasets are stored in MinIO/local storage by GeoLens):

```bash
rm -rf .scratch/adk-data/dem .scratch/adk-data/aerial
# Keep .scratch/adk-data/cogs for a few days in case re-ingest is needed
```

## Known limitations

- **USGS NAIP via TNM API may be unavailable** for this AOI. The pipeline records exact TNM query evidence on every run, then uses the tiled NY State orthos fallback when needed.
- **APA Blue Line is the whole-park polygon**, not just the local arc — the AOI is entirely inside the park interior so clipping the polygon would lose its meaning. The polygon serves as a visual context for "we're inside the Adirondack Park" on the saved map.
- **APA Summits FeatureServer coordinates are GNIS-derived** and may differ slightly from modern GPS summit points. The complete 46er dataset preserves APA source attributes plus official 46er rank/elevation fields.

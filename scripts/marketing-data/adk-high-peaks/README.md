# Adirondack High Peaks — Marketing Data Pipeline

Reproducible scripts that download, mosaic, and ingest the data behind the GeoLens "Adirondack High Peaks" marketing maps. The pipeline produces:

- 1 DEM raster (USGS 3DEP 1m LiDAR-derived) covering Mt. Marcy, Algonquin, and the Lake Placid region.
- 1 aerial raster (NY State 12in orthoimagery, 2022-2025 mosaic).
- 3 vector overlays (APA Blue Line polygon, NYSDEC Hiking Trails, APA Land Classification).
- 1 curated point dataset (12 of the Adirondack 46er High Peaks that fall inside the AOI).
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

# 3. Fetch NY State 12in aerial (~33 MB GeoTIFF, single tile)
.venv/bin/python scripts/marketing-data/adk-high-peaks/fetch_aerial.py

# 4. Reproject the aerial to web mercator + COG-convert (~3.5 MB output)
bash scripts/marketing-data/adk-high-peaks/build_aerial_cog.sh

# 5. Fetch vectors from ArcGIS Online (APA + NYSDEC FeatureServers)
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
| 2 | NY State 2022-2025 orthos | https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer | Dynamic ArcGIS exportImage | NY State (public, attribution requested) |
| 3 | APA Adirondack Park Boundary | https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/BluelinePolygon/FeatureServer/0 | Feature Service polygon | NY State / APA (public) |
| 4 | NYSDEC Hiking Trails | https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/DEC_Trails/FeatureServer/1 | Feature Service polyline | NY DEC (public) |
| 5 | APA Land Classification | https://services2.arcgis.com/8krRUWgifzA4cgL3/arcgis/rest/services/AdirondackParkLandClassification/FeatureServer/0 | Feature Service polygon | NY State / APA (public) |
| 6 | ADK 46ers list | Curated `peaks_46.geojson` in this directory | GeoJSON points (12 features) | Coordinates from USGS GNIS via APA Summits FeatureServer |

## Outputs

| Path | Size | Note |
|------|------|------|
| `.scratch/adk-data/dem/USGS_1M_*.tif` | ~2.3 GB | 9 raw 1m DEM tiles (gitignored) |
| `.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tif` | ~33 MB | Raw NY orthos 4096×4096 GeoTIFF with sidecar `.tfw` + `.prj` |
| `.scratch/adk-data/cogs/adk_high_peaks_dem_1m.tif` | ~1.4 GB | Mosaicked + EPSG:3857 COG (ingested as DEM raster) |
| `.scratch/adk-data/cogs/adk_high_peaks_ny_orthos_3857.tif` | ~3.5 MB | EPSG:3857 COG for aerial layer |
| `.scratch/adk-data/vectors/*.geojson` | ~1.5 MB | Raw + AOI-clipped vectors |
| `scripts/marketing-data/adk-high-peaks/peaks_46.geojson` | ~3 KB | Curated 12 peaks (committed) |
| `scripts/marketing-data/adk-high-peaks/ingest_manifest.yaml` | ~3 KB | Documentation-only manifest (committed) |

## Follow-up: Higher-fidelity aerial

This pipeline ships with the NY State `wms/Latest/MapServer` orthos — 12-inch native resolution downsampled to 4096×4096 (~6 m/px effective in the COG). For maximum marketing fidelity at z17+, two upgrades are possible:

1. **Tiled fetch** — modify `fetch_aerial.py` to do a 4×4 grid of 4096×4096 requests, mosaic in the COG step. Yields 16384×16384 effective ≈ 1.5 m/px.
2. **NYS DHSES orthos portal** (https://orthos.dhses.ny.gov/) — the public download portal exposes native 1ft Essex County orthos as a download. This requires manual UI interaction (draw rectangle, email-link delivery) so it was deferred from this pipeline. Once the user runs that flow and drops a zip at `.scratch/adk-data/aerial/orthos.zip`, modify `build_aerial_cog.sh` to unzip + mosaic instead of consuming the single TIFF.

## Disk cleanup

After successful ingest the raw downloads are no longer needed (datasets are stored in MinIO/local storage by GeoLens):

```bash
rm -rf .scratch/adk-data/dem .scratch/adk-data/aerial
# Keep .scratch/adk-data/cogs for a few days in case re-ingest is needed
```

## Known limitations

- **USGS NAIP via TNM API is unavailable** for this AOI as of 2026-05-24 (TNM returns 0 items for any NAIP query in NY). The pipeline uses NY State's own orthos service instead. See API-ISSUES.md (third-party section) for details.
- **APA Blue Line is the whole-park polygon**, not just the local arc — the AOI is entirely inside the park interior so clipping the polygon would lose its meaning. The polygon serves as a visual context for "we're inside the Adirondack Park" on the saved map.
- **APA Summits FeatureServer only lists 2 peaks** (Marcy + Algonquin, both >5000 ft) in the AOI. The 46ers list includes ~10 more peaks between 4000-5000 ft in this AOI — those are hand-curated in `peaks_46.geojson` from the canonical Bob Marshall 1925 list with USGS GNIS coordinates.

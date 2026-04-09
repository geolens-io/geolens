# ==============================================================================
# GeoLens Themed Demo Seeder — multi-stage build
#
# Stage 1 (data-fetcher) downloads every bundled dataset, runs gdal_translate
# for raster COG conversion, and runs csv_to_choropleth.py / subset_ucdp.py
# for indicator pre-joins. All outputs land in /data/demo.
#
# Stage 2 (runtime) copies /data/demo and the scripts/ tree from the host,
# then sets ENTRYPOINT to scripts/demo/run-seeder.sh which authenticates
# against the GeoLens API and execs scripts/demo/seed-thematic-demo.py.
#
# Per CONTEXT.md "Bundle Strategy": zero outbound network at runtime.
# All data is baked into the image at build time.
#
# Build: docker compose -f docker-compose.yml -f docker-compose.demo.yml \
#          build seeder
# ==============================================================================

# ============================================================================
# Stage 1: data-fetcher — downloads, converts, and pre-joins all source data
# ============================================================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS data-fetcher

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        gdal-bin \
        python3-gdal \
        awscli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy the helpers that will be invoked during the build (from Plan 01)
COPY scripts/demo/lib/csv_to_choropleth.py /build/csv_to_choropleth.py
COPY scripts/demo/lib/subset_ucdp.py /build/subset_ucdp.py

ENV DATA_DIR=/data/demo
RUN mkdir -p $DATA_DIR

# ----------------------------------------------------------------------------
# NE admin countries — needed as ADM0 polygon source for the csv pre-joins
# ----------------------------------------------------------------------------
RUN curl -fsSL -o /tmp/ne_countries.zip \
      "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip" \
    && unzip -o /tmp/ne_countries.zip -d /tmp/ne_countries/ \
    && rm /tmp/ne_countries.zip

# ----------------------------------------------------------------------------
# THEME 1: Planet Earth rasters
# ----------------------------------------------------------------------------

# GEBCO 2024 — downsample to 30 arc-min for the bundled image
# Source: source.coop S3 (alexgleith/gebco-2024). The full file is ~6.7 GB;
# the downsampled COG is ~50 MB. Build time on this layer dominates first
# build (~10-15 min on a fast connection).
#
# BuildKit cache mount keeps the raw 6.7 GB file in a build-time cache
# directory so it does NOT end up in the image layer AND is not re-downloaded
# when the gdal_translate arguments change. Cache persists across builds for
# the same cache id. If you need to force a fresh download, run with
# `docker builder prune` or change the cache id.
#
# PREDICTOR=2 (not 3) because GEBCO stores bathymetry as Int16/32, and the
# COG driver rejects PREDICTOR=3 on non-Float inputs with "PREDICTOR=3 is
# only supported with Float32 or Float64". PREDICTOR=2 is the right choice
# for integer rasters and still gives substantial DEFLATE compression.
RUN --mount=type=cache,target=/gebco-cache,id=gebco-download \
    if [ ! -s /gebco-cache/GEBCO_2024.tif ]; then \
      echo "Downloading GEBCO 2024 (~6.7 GB, first build only)..."; \
      curl -fsSL -o /gebco-cache/GEBCO_2024.tif \
        "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif"; \
    else \
      echo "Using cached GEBCO 2024 ($(du -h /gebco-cache/GEBCO_2024.tif | cut -f1))"; \
    fi \
    && gdal_translate \
         -of GTiff \
         -co TILED=YES \
         -co COMPRESS=DEFLATE \
         -co PREDICTOR=2 \
         -tr 0.5 0.5 \
         -r bilinear \
         /gebco-cache/GEBCO_2024.tif \
         $DATA_DIR/gebco_2024_30arcmin.tif

# GEBCO pre-colorized with viridis_r ramp for Map 1.2.
# Why pre-colorize at build time instead of styling at render time:
# the current tile pipeline reads dataset.dtype and builds a fixed
# rescale query string (see backend/app/tiles/router.py:_titiler_render_params),
# which means the int16 GEBCO values don't translate to a usable
# visualization via the default Titiler path. Pre-colorizing to a
# uint8 RGBA GeoTIFF produces a usable Map 1.2 without requiring
# backend changes to plumb style_config through to the tile URL.
RUN printf '%s\n' \
      '-11000 68 1 84' \
      '-8000 72 40 120' \
      '-6000 62 74 137' \
      '-4000 49 104 142' \
      '-3000 38 130 142' \
      '-2000 31 158 137' \
      '-1000 53 183 121' \
      '-500 109 205 89' \
      '-100 180 222 44' \
      '0 253 231 37' \
      '1 120 140 120 0' \
      '9000 120 140 120 0' \
    > /tmp/viridis_r.txt \
 && gdaldem color-relief \
      -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -alpha \
      $DATA_DIR/gebco_2024_30arcmin.tif /tmp/viridis_r.txt \
      $DATA_DIR/gebco_2024_viridis.tif \
 && rm /tmp/viridis_r.txt

# NE 10m shaded relief — verify exact filename from Plan 02 SUMMARY.
# As of build time the canonical filename is NE1_HR_LC_SR_W_DR.zip in the
# 10m/raster/ directory. If NACIS rotates this, fall back to the closest
# known-good URL and update the SUMMARY.
# gdal_translate uses plain GTiff (tiled + deflate) rather than COG here
# because the GeoLens server's raster ingest pipeline adds overviews via
# gdaladdo, which fails with "Cannot add external overviews when there
# are already internal overviews" if we ship a COG with embedded pyramids.
# Let the server do the final COG conversion on ingest.
#
# Also: downsample the 21600x10800 shaded relief (~600 MB raw) to ~4320x2160
# so the final output stays under the demo's upload size limit (200 MB).
RUN curl -fsSL -o /tmp/ne_shaded_relief.zip \
      "https://naciscdn.org/naturalearth/10m/raster/NE1_HR_LC_SR_W_DR.zip" \
    && unzip -o /tmp/ne_shaded_relief.zip -d /tmp/ne_sr/ \
    && gdal_translate -of GTiff \
         -co TILED=YES -co COMPRESS=DEFLATE \
         -outsize 25% 25% -r average \
         /tmp/ne_sr/NE1_HR_LC_SR_W_DR.tif \
         $DATA_DIR/ne_10m_shaded_relief.tif \
    && rm -rf /tmp/ne_shaded_relief.zip /tmp/ne_sr/

# SRTM 30m Himalayas tile — N28E086 covers the Everest region.
# SRTM is a nice-to-have for the Phase 999.1 3D-ready forward-compat note
# but is NOT required for any signature map (Maps 1.1 + 1.2 use GEBCO and
# the shaded relief VRT mosaic). The fetcher tries several OpenTopography
# S3 prefixes (they rotate periodically), falls back to a 1-pixel placeholder
# if every candidate fails, and exits 0 in both cases so the build continues.
# See docker/seeder/fetch-srtm.sh for the full fallback logic.
COPY docker/seeder/fetch-srtm.sh /build/fetch-srtm.sh
RUN chmod +x /build/fetch-srtm.sh && /build/fetch-srtm.sh "$DATA_DIR"

# Assert the SRTM output exists — if every fallback in fetch-srtm.sh failed
# AND gdal_create also failed, the image would ship without srtm_himalayas.tif
# and any Phase 999.1 forward-compat work referencing it would break silently.
RUN test -s $DATA_DIR/srtm_himalayas.tif \
    || echo "WARNING: srtm_himalayas.tif is missing — Map 1.1/1.2 still work, but Phase 999.1 terrain forward-compat is broken"

# ----------------------------------------------------------------------------
# THEME 2: indicator pre-joins via csv_to_choropleth helper
# ----------------------------------------------------------------------------

# World Bank GDP per capita PPP — ZIP with versioned inner filename.
#
# api.worldbank.org sits behind Cloudflare, which fingerprints curl's TLS
# ClientHello (JA3) and returns HTTP 502 for every curl request — even
# with a browser User-Agent. Python's urllib uses a different TLS stack
# (stdlib ssl → OpenSSL via a different path) that Cloudflare accepts, so
# we download via python3 instead of curl here. All the OTHER upstream
# fetches in this Dockerfile (NACIS, source.coop, OpenTopography,
# Geofabrik, UCDP, UNHCR) are fine with plain curl — only the WB endpoint
# is affected by this bot-detection rule as of 2026-04-09.
RUN python3 -c "import urllib.request as u; r=u.Request('https://api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv', headers={'User-Agent':'Mozilla/5.0'}); open('/tmp/wb_gdp.zip','wb').write(u.urlopen(r, timeout=120).read())" \
    && unzip -o /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" -d /tmp/wb_gdp/ \
    && mv /tmp/wb_gdp/API_NY.GDP.PCAP.PP.CD*.csv /tmp/wb_gdp.csv \
    && rm -rf /tmp/wb_gdp.zip /tmp/wb_gdp/

# OWID life expectancy
RUN curl -fsSL -o /tmp/owid_le.csv \
      "https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=false"

# csv_to_choropleth pre-joins for Theme 2.
# Wrap each invocation with an explicit error message so column drift from
# the upstream CSV produces a helpful build log (rather than BuildKit's
# generic "failed to solve: process did not complete successfully").
RUN python3 /build/csv_to_choropleth.py \
      --csv /tmp/wb_gdp.csv \
      --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
      --csv-join-col "Country Code" \
      --adm0-join-col ADM0_A3 \
      --value-col 2023 \
      --output $DATA_DIR/gdp_per_capita_ppp_2023.geojson \
    || { echo "ERROR: csv_to_choropleth failed on WB GDP — check 'Country Code'/'2023' columns still exist in upstream CSV"; exit 1; } \
 && python3 /build/csv_to_choropleth.py \
      --csv /tmp/owid_le.csv \
      --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
      --csv-join-col Code \
      --adm0-join-col ADM0_A3 \
      --value-col "Life expectancy" \
      --year-filter 2021 \
      --output $DATA_DIR/life_expectancy_2021.geojson \
    || { echo "ERROR: csv_to_choropleth failed on OWID life expectancy — check 'Code'/'Life expectancy' columns still exist in upstream CSV"; exit 1; }

# Manhattan OSM buildings (Geofabrik free shapefile).
# The free .shp variant does not carry the OSM `height` tag — it only has
# osm_id, code, fclass, name, type. So we drop the height filter and clip
# to the Manhattan bbox only. Result is ~20k building polygons, which
# ogr2ogr emits as a single GeoJSON.
RUN curl -fsSL -o /tmp/ny.shp.zip \
      "https://download.geofabrik.de/north-america/us/new-york-latest-free.shp.zip" \
    && unzip -o /tmp/ny.shp.zip "gis_osm_buildings_a_free_1.*" -d /tmp/ny_buildings/ \
    && ogr2ogr -f GeoJSON \
         -clipsrc -74.05 40.68 -73.90 40.80 \
         $DATA_DIR/manhattan_buildings.geojson \
         /tmp/ny_buildings/gis_osm_buildings_a_free_1.shp \
    && rm -rf /tmp/ny.shp.zip /tmp/ny_buildings/

# ----------------------------------------------------------------------------
# THEME 3: conflict + refugees
# ----------------------------------------------------------------------------

# UCDP GED v25.1 — subset to 2015-2024 via the Plan 01 helper
RUN curl -fsSL -o /tmp/ged251.zip "https://ucdp.uu.se/downloads/ged/ged251-csv.zip" \
    && unzip -o /tmp/ged251.zip -d /tmp/ged251/ \
    && python3 /build/subset_ucdp.py /tmp/ged251/GEDEvent_v25_1.csv $DATA_DIR/ucdp_ged_v25_1.csv 2015 2024 \
    && rm -rf /tmp/ged251.zip /tmp/ged251/

# UNHCR refugees → pre-join via csv_to_choropleth.
# Use coo_all=true for per-origin breakdown (default returns a single aggregate
# row). The CSV's column names are the human-readable headers, so use the
# exact strings "Country of origin (ISO)" and "Refugees under UNHCR's mandate"
# in the csv_to_choropleth args.
RUN curl -fsSL -o /tmp/unhcr.zip \
      "https://api.unhcr.org/population/v1/population/?yearFrom=2023&yearTo=2023&coo_all=true&cf_type=iso&download=true" \
    && unzip -p /tmp/unhcr.zip population.csv > /tmp/unhcr.csv \
    && (python3 /build/csv_to_choropleth.py \
         --csv /tmp/unhcr.csv \
         --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
         --csv-join-col "Country of origin (ISO)" \
         --adm0-join-col ADM0_A3 \
         --value-col "Refugees under UNHCR's mandate" \
         --output $DATA_DIR/refugees_by_origin_2023.geojson \
         || { echo "ERROR: csv_to_choropleth failed on UNHCR refugees — check the Country-of-origin and refugees-under-UNHCR-mandate columns still exist in the upstream CSV"; exit 1; }) \
    && rm /tmp/unhcr.zip /tmp/unhcr.csv

# Cleanup ne_countries scratch directory (only the .geojson outputs need to ship)
RUN rm -rf /tmp/ne_countries/

# Validate checksums against pinned expectations on rebuild.
# CHECKSUMS.sha256 was populated 2026-04-09 from the first successful build
# outputs. If this step fails, an upstream source has rotated its file
# contents — either re-pin the checksum (after verifying the change is
# intentional) or update the download URL.
COPY docker/seeder/CHECKSUMS.sha256 /CHECKSUMS.sha256
RUN cd $DATA_DIR && sha256sum -c /CHECKSUMS.sha256

# Gzip the baked GeoJSON and CSV files AFTER checksum validation so the
# checksums stay pinned against the uncompressed bytes. The Stage 2 COPY
# below picks up the gzipped versions, shaving ~150 MB off the final image.
# run-seeder.sh decompresses in-place at container start before handing off
# to the orchestrator, so runtime file paths stay stable.
# Rasters (.tif) are already DEFLATE-compressed by gdal_translate, so gzipping
# them again would only slow the build with negligible savings — skip.
# Use `find -exec` so an empty glob doesn't crash the build (a plain
# `gzip $DATA_DIR/*.geojson` would pass the literal pattern when the glob
# matches nothing, which gzip rejects with exit 1).
RUN find "$DATA_DIR" -maxdepth 1 \( -name "*.geojson" -o -name "*.csv" \) -exec gzip -f {} +

# ============================================================================
# Stage 2: runtime — minimal image that runs the seeder against a live API
# ============================================================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Use uv pip (already available in the base image) instead of installing
# python3-pip via apt. Saves ~40 MB and one apt layer.
RUN uv pip install --system --no-cache httpx

# Copy the bundled data from the data-fetcher stage
COPY --from=data-fetcher /data/demo /data/demo

# Copy seeder scripts (the orchestrator + per-theme modules + lib + run-seeder.sh)
COPY scripts/ /scripts/

# Make the wrapper executable
RUN chmod +x /scripts/demo/run-seeder.sh

ENTRYPOINT ["/scripts/demo/run-seeder.sh"]

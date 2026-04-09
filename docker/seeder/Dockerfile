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
# build (~10-15 min on a fast connection). BuildKit caches it aggressively
# unless the URL changes.
RUN curl -fsSL -o /tmp/gebco_full.tif \
      "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif" \
    && gdal_translate \
         -of COG \
         -co COMPRESS=DEFLATE \
         -co PREDICTOR=3 \
         -tr 0.5 0.5 \
         -r bilinear \
         /tmp/gebco_full.tif \
         $DATA_DIR/gebco_2024_30arcmin.tif \
    && rm /tmp/gebco_full.tif

# NE 10m shaded relief — verify exact filename from Plan 02 SUMMARY.
# As of build time the canonical filename is NE1_HR_LC_SR_W_DR.zip in the
# 10m/raster/ directory. If NACIS rotates this, fall back to the closest
# known-good URL and update the SUMMARY.
RUN curl -fsSL -o /tmp/ne_shaded_relief.zip \
      "https://naciscdn.org/naturalearth/10m/raster/NE1_HR_LC_SR_W_DR.zip" \
    && unzip -o /tmp/ne_shaded_relief.zip -d /tmp/ne_sr/ \
    && gdal_translate -of COG -co COMPRESS=DEFLATE \
         /tmp/ne_sr/NE1_HR_LC_SR_W_DR/NE1_HR_LC_SR_W_DR.tif \
         $DATA_DIR/ne_10m_shaded_relief.tif \
    && rm -rf /tmp/ne_shaded_relief.zip /tmp/ne_sr/

# SRTM 30m Himalayas tile — N28E086 covers the Everest region
# Public S3 endpoint via OpenTopography (--no-sign-request)
RUN aws s3 cp \
      s3://raster/SRTM_GL1/SRTM_GL1_srtm/N28E086.hgt \
      /tmp/srtm_tile.hgt \
      --endpoint-url https://opentopography.s3.sdsc.edu \
      --no-sign-request \
    && gdal_translate -of COG -co COMPRESS=DEFLATE \
         /tmp/srtm_tile.hgt $DATA_DIR/srtm_himalayas.tif \
    && rm /tmp/srtm_tile.hgt

# ----------------------------------------------------------------------------
# THEME 2: indicator pre-joins via csv_to_choropleth helper
# ----------------------------------------------------------------------------

# World Bank GDP per capita PPP — ZIP with versioned inner filename
RUN curl -fsSL -o /tmp/wb_gdp.zip \
      "https://api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv" \
    && unzip -o /tmp/wb_gdp.zip "API_NY.GDP.PCAP.PP.CD_DS2_en_csv_v2*.csv" -d /tmp/wb_gdp/ \
    && mv /tmp/wb_gdp/API_NY.GDP.PCAP.PP.CD*.csv /tmp/wb_gdp.csv \
    && rm -rf /tmp/wb_gdp.zip /tmp/wb_gdp/

# OWID life expectancy
RUN curl -fsSL -o /tmp/owid_le.csv \
      "https://ourworldindata.org/grapher/life-expectancy.csv?v=1&csvType=full&useColumnShortNames=false"

# csv_to_choropleth pre-joins for Theme 2
RUN python3 /build/csv_to_choropleth.py \
      --csv /tmp/wb_gdp.csv \
      --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
      --csv-join-col "Country Code" \
      --adm0-join-col ADM0_A3 \
      --value-col 2023 \
      --output $DATA_DIR/gdp_per_capita_ppp_2023.geojson \
 && python3 /build/csv_to_choropleth.py \
      --csv /tmp/owid_le.csv \
      --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
      --csv-join-col Code \
      --adm0-join-col ADM0_A3 \
      --value-col "Life expectancy" \
      --year-filter 2021 \
      --output $DATA_DIR/life_expectancy_2021.geojson

# Manhattan OSM buildings (Geofabrik free shapefile)
RUN curl -fsSL -o /tmp/ny.shp.zip \
      "https://download.geofabrik.de/north-america/us/new-york-latest-free.shp.zip" \
    && unzip -o /tmp/ny.shp.zip "gis_osm_buildings_a_free_1.*" -d /tmp/ny_buildings/ \
    && ogr2ogr -f GeoJSON \
         -clipsrc -74.05 40.68 -73.90 40.80 \
         -where "height IS NOT NULL" \
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

# UNHCR refugees → pre-join via csv_to_choropleth (origin = iso_o per 218-RESEARCH.md G4)
RUN curl -fsSL -o /tmp/unhcr.zip \
      "https://api.unhcr.org/population/v1/population/?limit=10000&page=1&download=true&yearFrom=2023&yearTo=2023" \
    && unzip -p /tmp/unhcr.zip > /tmp/unhcr.csv \
    && python3 /build/csv_to_choropleth.py \
         --csv /tmp/unhcr.csv \
         --adm0 /tmp/ne_countries/ne_10m_admin_0_countries.shp \
         --csv-join-col iso_o \
         --adm0-join-col ADM0_A3 \
         --value-col refugees_under_unhcr_mandate \
         --output $DATA_DIR/refugees_by_origin_2023.geojson \
    && rm /tmp/unhcr.zip /tmp/unhcr.csv

# Cleanup ne_countries scratch directory (only the .geojson outputs need to ship)
RUN rm -rf /tmp/ne_countries/

# Optional: validate checksums against pinned expectations on rebuild.
# Uncomment after the first successful build and CHECKSUMS.sha256 has been
# populated with real values from the data-fetcher stage outputs.
# COPY docker/seeder/CHECKSUMS.sha256 /CHECKSUMS.sha256
# RUN cd $DATA_DIR && sha256sum -c /CHECKSUMS.sha256

# ============================================================================
# Stage 2: runtime — minimal image that runs the seeder against a live API
# ============================================================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --break-system-packages --no-cache-dir httpx

# Copy the bundled data from the data-fetcher stage
COPY --from=data-fetcher /data/demo /data/demo

# Copy seeder scripts (the orchestrator + per-theme modules + lib + run-seeder.sh)
COPY scripts/ /scripts/

# Make the wrapper executable
RUN chmod +x /scripts/demo/run-seeder.sh

ENTRYPOINT ["/scripts/demo/run-seeder.sh"]

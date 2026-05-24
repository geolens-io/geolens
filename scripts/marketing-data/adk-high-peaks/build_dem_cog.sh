#!/usr/bin/env bash
# Mosaic + reproject + COG-convert the downloaded DEM (or NAIP) tiles.
#
# Usage:
#   ./build_dem_cog.sh                # build DEM COG
#   ./build_dem_cog.sh --aerial       # build NAIP COG
#
# Idempotent: skips if the output COG already exists.
# Uses docker exec into geolens-api-1 for GDAL (host GDAL not required).
#
# Inputs (relative to repo root):
#   .scratch/adk-data/dem/USGS_1M_*.tif      (DEM mode)
#   .scratch/adk-data/aerial/*.tif           (NAIP mode)
#
# Outputs:
#   .scratch/adk-data/cogs/adk_high_peaks_dem_1m.tif      (DEM mode)
#   .scratch/adk-data/cogs/adk_high_peaks_naip_3857.tif   (NAIP mode)

set -euo pipefail

AOI_BBOX=(-74.05 44.08 -73.85 44.32)
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CONTAINER="${GEOLENS_API_CONTAINER:-geolens-api-1}"

MODE="dem"
if [[ "${1:-}" == "--aerial" ]]; then
  MODE="aerial"
fi

if [[ "$MODE" == "dem" ]]; then
  INPUT_DIR="$REPO_ROOT/.scratch/adk-data/dem"
  GLOB_PATTERN="USGS_1M_*.tif"
  OUTPUT_TIF="$REPO_ROOT/.scratch/adk-data/cogs/adk_high_peaks_dem_1m.tif"
  RESAMPLING="bilinear"
  LABEL="DEM 1m"
else
  INPUT_DIR="$REPO_ROOT/.scratch/adk-data/aerial"
  GLOB_PATTERN="*.tif"
  OUTPUT_TIF="$REPO_ROOT/.scratch/adk-data/cogs/adk_high_peaks_naip_3857.tif"
  RESAMPLING="cubic"
  LABEL="NAIP aerial"
fi

mkdir -p "$(dirname "$OUTPUT_TIF")"

if [[ -f "$OUTPUT_TIF" ]]; then
  size_mb=$(du -m "$OUTPUT_TIF" | cut -f1)
  echo "SKIP: $OUTPUT_TIF already exists (${size_mb} MB)"
  exit 0
fi

# Count input tiles
shopt -s nullglob
INPUT_TILES=("$INPUT_DIR"/$GLOB_PATTERN)
shopt -u nullglob
if [[ ${#INPUT_TILES[@]} -eq 0 ]]; then
  echo "ERROR: no tiles in $INPUT_DIR matching $GLOB_PATTERN" >&2
  exit 1
fi

echo "Building $LABEL COG from ${#INPUT_TILES[@]} tiles in $INPUT_DIR"

# The container has ReadonlyRootfs=true, so /tmp (tmpfs) is in-container-writable
# but NOT a valid docker-cp destination. Use the named-volume mount /app/staging
# instead (mode 0775, owned by appuser:appgroup, writable + visible to host via
# the geolens_upload_staging Docker named volume).
WORKDIR_CONTAINER="/app/staging/marketing-cog-build"

echo "Staging input dir in container at $WORKDIR_CONTAINER..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"
docker exec "$CONTAINER" mkdir -p "$WORKDIR_CONTAINER/${MODE}" "$WORKDIR_CONTAINER/cogs"

# Copy input tiles into container
for tile in "${INPUT_TILES[@]}"; do
  fname=$(basename "$tile")
  echo "  Copying $fname into container..."
  docker cp "$tile" "$CONTAINER:$WORKDIR_CONTAINER/${MODE}/$fname"
done

# Build VRT (mosaic), clip to AOI bbox, then convert to COG
VRT_PATH="$WORKDIR_CONTAINER/cogs/${MODE}_mosaic.vrt"
TIF_PATH="$WORKDIR_CONTAINER/cogs/$(basename "$OUTPUT_TIF")"

echo "Building VRT (mosaic)..."
docker exec "$CONTAINER" bash -c "
  cd $WORKDIR_CONTAINER/${MODE} && \
  gdalbuildvrt -overwrite -resolution highest $VRT_PATH ${GLOB_PATTERN}
"

echo "Inspecting VRT..."
docker exec "$CONTAINER" gdalinfo "$VRT_PATH" | head -15

echo "Reprojecting + clipping + COG-converting (this may take 2-10 min)..."
docker exec "$CONTAINER" bash -c "
  gdalwarp \
    -t_srs EPSG:3857 \
    -te ${AOI_BBOX[0]} ${AOI_BBOX[1]} ${AOI_BBOX[2]} ${AOI_BBOX[3]} \
    -te_srs EPSG:4326 \
    -r $RESAMPLING \
    -of COG \
    -co COMPRESS=DEFLATE \
    -co BLOCKSIZE=512 \
    -co OVERVIEWS=AUTO \
    -co RESAMPLING=$RESAMPLING \
    -co NUM_THREADS=ALL_CPUS \
    -overwrite \
    $VRT_PATH \
    $TIF_PATH
"

echo "Validating COG layout..."
docker exec "$CONTAINER" gdalinfo "$TIF_PATH" | grep -E "(LAYOUT|TILING_SCHEME|Size is|Pixel Size)" || true

echo "Copying COG back to host..."
docker cp "$CONTAINER:$TIF_PATH" "$OUTPUT_TIF"

echo "Cleaning up container staging..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"

size_mb=$(du -m "$OUTPUT_TIF" | cut -f1)
echo "DONE: $OUTPUT_TIF (${size_mb} MB)"

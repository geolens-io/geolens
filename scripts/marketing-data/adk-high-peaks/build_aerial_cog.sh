#!/usr/bin/env bash
# Convert fetched aerial tiles (TNM NAIP when available, otherwise NY orthos
# tiled fallback) into a proper EPSG:3857 web-mercator COG ready for ingest.
#
# Input preference:
#   1. .scratch/adk-data/aerial/naip_tiles/*.tif
#   2. .scratch/adk-data/aerial/ny_orthos_tiles/*.tif
#   3. .scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tif (+ sidecars)
# Output: .scratch/adk-data/cogs/adk_high_peaks_ny_orthos_tiled_3857.tif
#
# Uses docker exec into geolens-api-1 for GDAL (host GDAL not required).

set -euo pipefail

AOI_BBOX=(-74.05 44.08 -73.85 44.32)
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CONTAINER="${GEOLENS_API_CONTAINER:-geolens-api-1}"

NAIP_TILE_DIR="$REPO_ROOT/.scratch/adk-data/aerial/naip_tiles"
NY_TILE_DIR="$REPO_ROOT/.scratch/adk-data/aerial/ny_orthos_tiles"
LEGACY_INPUT_TIF="$REPO_ROOT/.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tif"
LEGACY_INPUT_TFW="$REPO_ROOT/.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tfw"
LEGACY_INPUT_PRJ="$REPO_ROOT/.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.prj"
OUTPUT_TIF="$REPO_ROOT/.scratch/adk-data/cogs/adk_high_peaks_ny_orthos_tiled_3857.tif"

mkdir -p "$(dirname "$OUTPUT_TIF")"

if [[ -f "$OUTPUT_TIF" && "${FORCE_REBUILD:-0}" != "1" ]]; then
  size_mb=$(du -m "$OUTPUT_TIF" | cut -f1)
  echo "SKIP: $OUTPUT_TIF already exists (${size_mb} MB). Set FORCE_REBUILD=1 to replace it."
  exit 0
fi

WORKDIR_CONTAINER="/app/staging/marketing-cog-build-aerial"

echo "Staging input in container..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"
docker exec "$CONTAINER" mkdir -p "$WORKDIR_CONTAINER/input" "$WORKDIR_CONTAINER/cogs"

SOURCE_LABEL=""
if compgen -G "$NAIP_TILE_DIR/*.tif" > /dev/null; then
  SOURCE_LABEL="TNM NAIP tiles"
  docker cp "$NAIP_TILE_DIR/." "$CONTAINER:$WORKDIR_CONTAINER/input/"
elif compgen -G "$NY_TILE_DIR/*.tif" > /dev/null; then
  SOURCE_LABEL="NY orthos tiled fallback"
  docker cp "$NY_TILE_DIR/." "$CONTAINER:$WORKDIR_CONTAINER/input/"
elif [[ -f "$LEGACY_INPUT_TIF" ]]; then
  SOURCE_LABEL="legacy single NY orthos export"
  docker cp "$LEGACY_INPUT_TIF" "$CONTAINER:$WORKDIR_CONTAINER/input/aerial.tif"
  docker cp "$LEGACY_INPUT_TFW" "$CONTAINER:$WORKDIR_CONTAINER/input/aerial.tfw"
  docker cp "$LEGACY_INPUT_PRJ" "$CONTAINER:$WORKDIR_CONTAINER/input/aerial.prj"
else
  echo "ERROR: no aerial input found. Run fetch_aerial.py first." >&2
  exit 1
fi

echo "Input source: $SOURCE_LABEL"
docker exec "$CONTAINER" bash -c "
  shopt -s nullglob
  tiles=( $WORKDIR_CONTAINER/input/*.tif )
  if [[ \${#tiles[@]} -eq 0 ]]; then
    echo 'ERROR: no staged .tif input files' >&2
    exit 1
  fi
  gdalbuildvrt $WORKDIR_CONTAINER/aerial.vrt \"\${tiles[@]}\"
"

echo "Inspecting input..."
docker exec "$CONTAINER" gdalinfo "$WORKDIR_CONTAINER/aerial.vrt" | head -20

OUTPUT_BASENAME=$(basename "$OUTPUT_TIF")
echo "Reprojecting + clipping + COG-converting..."
docker exec "$CONTAINER" bash -c "
  gdalwarp \
    -s_srs EPSG:4326 \
    -t_srs EPSG:3857 \
    -te ${AOI_BBOX[0]} ${AOI_BBOX[1]} ${AOI_BBOX[2]} ${AOI_BBOX[3]} \
    -te_srs EPSG:4326 \
    -r cubic \
    -of COG \
    -co COMPRESS=JPEG \
    -co JPEG_QUALITY=85 \
    -co BLOCKSIZE=512 \
    -co OVERVIEWS=AUTO \
    -co RESAMPLING=CUBIC \
    -co NUM_THREADS=ALL_CPUS \
    -overwrite \
    $WORKDIR_CONTAINER/aerial.vrt \
    $WORKDIR_CONTAINER/cogs/$OUTPUT_BASENAME
"

echo "Validating COG..."
docker exec "$CONTAINER" gdalinfo "$WORKDIR_CONTAINER/cogs/$OUTPUT_BASENAME" | grep -E "(LAYOUT|TILING_SCHEME|Size is|Pixel Size|COMPRESSION)" || true

echo "Copying back to host..."
docker cp "$CONTAINER:$WORKDIR_CONTAINER/cogs/$OUTPUT_BASENAME" "$OUTPUT_TIF"

echo "Cleaning up container staging..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"

size_mb=$(du -m "$OUTPUT_TIF" | cut -f1)
echo "DONE: $OUTPUT_TIF (${size_mb} MB)"

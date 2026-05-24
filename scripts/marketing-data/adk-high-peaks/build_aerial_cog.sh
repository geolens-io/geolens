#!/usr/bin/env bash
# Convert the NY-orthos aerial TIFF (WGS84 with world-file georeferencing) into
# a proper EPSG:3857 web-mercator COG ready for ingest.
#
# Input:  .scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tif (+ .tfw + .prj)
# Output: .scratch/adk-data/cogs/adk_high_peaks_ny_orthos_3857.tif
#
# Uses docker exec into geolens-api-1 for GDAL (host GDAL not required).

set -euo pipefail

AOI_BBOX=(-74.05 44.08 -73.85 44.32)
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CONTAINER="${GEOLENS_API_CONTAINER:-geolens-api-1}"

INPUT_TIF="$REPO_ROOT/.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tif"
INPUT_TFW="$REPO_ROOT/.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.tfw"
INPUT_PRJ="$REPO_ROOT/.scratch/adk-data/aerial/adk_high_peaks_ny_orthos_latest.prj"
OUTPUT_TIF="$REPO_ROOT/.scratch/adk-data/cogs/adk_high_peaks_ny_orthos_3857.tif"

mkdir -p "$(dirname "$OUTPUT_TIF")"

if [[ ! -f "$INPUT_TIF" ]]; then
  echo "ERROR: input $INPUT_TIF missing. Run fetch_aerial.py first." >&2
  exit 1
fi

if [[ -f "$OUTPUT_TIF" ]]; then
  size_mb=$(du -m "$OUTPUT_TIF" | cut -f1)
  echo "SKIP: $OUTPUT_TIF already exists (${size_mb} MB)"
  exit 0
fi

WORKDIR_CONTAINER="/app/staging/marketing-cog-build-aerial"

echo "Staging input in container..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"
docker exec "$CONTAINER" mkdir -p "$WORKDIR_CONTAINER/cogs"

docker cp "$INPUT_TIF" "$CONTAINER:$WORKDIR_CONTAINER/aerial.tif"
docker cp "$INPUT_TFW" "$CONTAINER:$WORKDIR_CONTAINER/aerial.tfw"
docker cp "$INPUT_PRJ" "$CONTAINER:$WORKDIR_CONTAINER/aerial.prj"

echo "Inspecting input..."
docker exec "$CONTAINER" gdalinfo "$WORKDIR_CONTAINER/aerial.tif" | head -15

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
    $WORKDIR_CONTAINER/aerial.tif \
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

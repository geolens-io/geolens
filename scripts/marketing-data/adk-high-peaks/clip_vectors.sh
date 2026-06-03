#!/usr/bin/env bash
# Clip the downloaded vectors to the AOI bbox using ogr2ogr inside the API container.
# Generates *_aoi.geojson files alongside the raw downloads.
#
# Inputs: .scratch/adk-data/vectors/{apa_blue_line, nysdec_hiking_trails,
#         apa_land_classification, nhd_flowlines, nhd_waterbodies}.geojson
# Outputs: .scratch/adk-data/vectors/*_aoi.geojson (same shape, AOI-clipped)
#
# Note: most vector downloads were already AOI-filtered server-side at
# ArcGIS query time. Re-clipping is a defense
# against features that crossed the bbox edge — keeps every feature fully inside.
# The third (Blue Line) is the whole-park polygon which we INTENTIONALLY keep
# whole; we still produce a *_aoi.geojson copy for downstream consistency.

set -euo pipefail

AOI=(-74.05 44.08 -73.85 44.32)   # W S E N (ogr2ogr -clipsrc order)
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CONTAINER="${GEOLENS_API_CONTAINER:-geolens-api-1}"
WORKDIR_CONTAINER="/app/staging/marketing-vector-clip"

VECTORS_HOST="$REPO_ROOT/.scratch/adk-data/vectors"

if [[ ! -d "$VECTORS_HOST" ]]; then
  echo "ERROR: $VECTORS_HOST does not exist. Run fetch_vectors.py first." >&2
  exit 1
fi

INPUTS=(apa_blue_line nysdec_hiking_trails apa_land_classification nhd_flowlines nhd_waterbodies)

echo "Staging vectors in container ($WORKDIR_CONTAINER)..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"
docker exec "$CONTAINER" mkdir -p "$WORKDIR_CONTAINER"

for stem in "${INPUTS[@]}"; do
  src="$VECTORS_HOST/${stem}.geojson"
  if [[ ! -f "$src" ]]; then
    echo "  WARN: $src missing — skipping" >&2
    continue
  fi
  docker cp "$src" "$CONTAINER:$WORKDIR_CONTAINER/${stem}.geojson"
done

for stem in "${INPUTS[@]}"; do
  src_container="$WORKDIR_CONTAINER/${stem}.geojson"
  dst_container="$WORKDIR_CONTAINER/${stem}_aoi.geojson"

  # Check existence in container
  if ! docker exec "$CONTAINER" test -f "$src_container"; then
    continue
  fi

  echo "  Clipping ${stem}.geojson -> ${stem}_aoi.geojson..."
  # For the Blue Line polygon we don't clip — it would crop the polygon to a
  # rectangle and lose the actual boundary curve. Just copy.
  if [[ "$stem" == "apa_blue_line" ]]; then
    docker exec "$CONTAINER" cp "$src_container" "$dst_container"
  else
    docker exec "$CONTAINER" ogr2ogr \
      -f GeoJSON \
      -t_srs EPSG:4326 \
      -clipsrc "${AOI[0]}" "${AOI[1]}" "${AOI[2]}" "${AOI[3]}" \
      -overwrite \
      "$dst_container" \
      "$src_container"
  fi

  docker cp "$CONTAINER:$dst_container" "$VECTORS_HOST/${stem}_aoi.geojson"

  size_kb=$(du -k "$VECTORS_HOST/${stem}_aoi.geojson" | cut -f1)
  feat_count=$(python3 -c "
import json
with open('$VECTORS_HOST/${stem}_aoi.geojson') as f:
    d = json.load(f)
print(len(d.get('features', [])))
")
  echo "    OK: ${stem}_aoi.geojson  size=${size_kb}KB  features=${feat_count}"
done

echo "Cleaning up container staging..."
docker exec "$CONTAINER" rm -rf "$WORKDIR_CONTAINER"

echo "Done. AOI-clipped vectors at $VECTORS_HOST/*_aoi.geojson"

#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 OUTPUT.geojson" >&2
  exit 2
fi

output=$1
if [ -e "$output" ]; then
  echo "Refusing to overwrite $output" >&2
  exit 2
fi

for tool in curl unzip ogr2ogr shasum python3; do
  command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 2; }
done

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
archive="$scratch/canopy.zip"
curl -fLsS --retry 3 \
  'https://data.cityofnewyork.us/api/views/by9k-vhck/files/bcbd4999-42cf-420f-9917-66419c5d8d8f?filename=Tree_Canopy_Change.zip' \
  -o "$archive"
echo 'ee33f316e770fa3173892df3a334304dbd96f21eb7ffa76a550f80b57f571663  '"$archive" | shasum -a 256 -c -
unzip -q "$archive" -d "$scratch"

source_gdb="$scratch/Tree_Canopy_Change/NYC_TreeCanopyChange_2010_2017.gdb"
ogr2ogr -f GeoJSON "$output" "$source_gdb" NYC_TreeCanopyChange_2010_2017 \
  -spat -73.989 40.722 -73.973 40.734 -spat_srs EPSG:4326 \
  -t_srs EPSG:4326 -clipdst -73.989 40.722 -73.973 40.734 \
  -select Class -lco RFC7946=YES

python3 - "$output" <<'PY'
import collections
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    features = json.load(stream)["features"]
classes = collections.Counter(feature["properties"]["Class"] for feature in features)
if not 1_000 <= len(features) <= 20_000 or set(classes) != {"No Change", "Gain", "Loss"}:
    raise SystemExit(f"Unexpected canopy subset: {len(features)} features, {dict(classes)}")
print(f"Prepared {len(features)} canopy polygons: {dict(classes)}")
PY
shasum -a 256 "$output"

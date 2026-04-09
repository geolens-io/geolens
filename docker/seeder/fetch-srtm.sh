#!/usr/bin/env bash
# ==============================================================================
# fetch-srtm.sh — best-effort SRTM 30 m tile fetcher used by the seeder
# Dockerfile (Stage 1 / data-fetcher). Extracted from a 4-deep nested RUN
# block for readability; same semantics.
#
# Usage: fetch-srtm.sh <DATA_DIR>
#
# Downloads the N28E086 SRTM GL1 tile (Himalayan region, covers Everest) and
# converts it to a DEFLATE GeoTIFF at $DATA_DIR/srtm_himalayas.tif.
#
# OpenTopography has rotated the SRTM GL1 S3 prefixes multiple times. We try
# a few known paths, then fall back to a 1-pixel placeholder so the build
# doesn't block the other datasets — SRTM is only used by forward-compat
# Phase 999.1 terrain work, not by any signature map.
# ==============================================================================
set -u  # intentionally NOT -e: we want to keep going on individual failures

DATA_DIR="${1:?fetch-srtm.sh: missing DATA_DIR positional argument}"
TILE_NAME="N28E086.hgt"
TMP_TILE="/tmp/srtm_tile.hgt"
ENDPOINT="https://opentopography.s3.sdsc.edu"
OUT="${DATA_DIR}/srtm_himalayas.tif"

# Candidate S3 keys — OpenTopography shuffles the prefix periodically.
CANDIDATES=(
    "s3://raster/SRTM_GL1/SRTM_GL1_srtm/N28/${TILE_NAME}"
    "s3://raster/SRTM_GL1/${TILE_NAME}"
    "s3://raster/SRTM_GL1_srtm/${TILE_NAME}"
)

fetch_tile() {
    for src in "${CANDIDATES[@]}"; do
        if aws s3 cp "${src}" "${TMP_TILE}" \
                --endpoint-url "${ENDPOINT}" --no-sign-request 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

if ! fetch_tile; then
    echo "SRTM download failed — creating 1-pixel placeholder so the file exists"
    gdal_create -of GTiff -outsize 1 1 -burn -9999 \
                -a_srs EPSG:4326 -a_ullr 86 29 87 28 \
                "${TMP_TILE}" 2>/dev/null || true
fi

if [ -s "${TMP_TILE}" ]; then
    gdal_translate -of GTiff -co TILED=YES -co COMPRESS=DEFLATE \
        "${TMP_TILE}" "${OUT}" 2>/dev/null || \
        echo "SRTM gdal_translate failed — Map 1.1 and 1.2 do not depend on it"
    rm -f "${TMP_TILE}"
else
    echo "SRTM step skipped — Map 1.1 and 1.2 do not depend on it"
fi

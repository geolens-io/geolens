#!/usr/bin/env bash
# ==============================================================================
# run-seeder.sh — wrapper for the thematic demo seeder.
#
# Authenticates against the GeoLens API, creates an API key, and execs the
# scripts/demo/seed-thematic-demo.py orchestrator with that key. Used as the
# ENTRYPOINT of docker/seeder/Dockerfile (Plan 218-05).
#
# Replaces the old scripts/seed-demo.sh which only seeded raw Natural Earth
# datasets. The thematic seeder produces 3 collections, all 9 signature maps,
# and applies the bundled fixtures from scripts/demo/fixtures/maps/.
#
# Auth + API-key lifecycle is handled by scripts/demo/lib/create_api_key.py
# (extracted from earlier embedded Python heredocs for testability).
# ==============================================================================
set -euo pipefail

export GEOLENS_BASE_URL="${GEOLENS_BASE_URL:-http://api:8000}"
export GEOLENS_ADMIN_USERNAME="${GEOLENS_ADMIN_USERNAME:-admin}"
export GEOLENS_ADMIN_PASSWORD="${GEOLENS_ADMIN_PASSWORD:-admin}"
MAX_RETRIES=30
RETRY_INTERVAL=5
CREATE_KEY_PY="/scripts/demo/lib/create_api_key.py"

echo "=== GeoLens Thematic Demo Seeder Wrapper ==="
echo "Base URL: ${GEOLENS_BASE_URL}"

# ---------------------------------------------------------------------------
# Decompress bundled data.
# The Dockerfile gzips all .geojson and .csv outputs after checksum validation
# to shave ~150 MB off the shipped image. Rasters (.tif) are left alone
# (already DEFLATE-compressed by gdal_translate). Decompress them in-place
# here so the orchestrator's hard-coded local_path lookups in themes/*.py
# still resolve. No-op on subsequent invocations in the same container.
# ---------------------------------------------------------------------------
if ls /data/demo/*.gz >/dev/null 2>&1; then
    echo "Decompressing bundled data files..."
    gunzip -f /data/demo/*.gz
fi

# ---------------------------------------------------------------------------
# Cleanup trap — always rotate the demo-seed key away on exit (graceful or
# abnormal). This prevents stale keys from accumulating when the container is
# SIGTERM'd mid-run. SEED_TOKEN is set after successful auth below; if the
# trap fires before then, delete-key silently no-ops.
# ---------------------------------------------------------------------------
cleanup() {
    set +e
    if [ -n "${SEED_TOKEN:-}" ]; then
        python3 "${CREATE_KEY_PY}" delete-key demo-seed 2>/dev/null || true
    fi
}
trap cleanup SIGTERM SIGINT EXIT

# ---------------------------------------------------------------------------
# Pre-fetch external data sources (USGS DEM, NYC PLUTO, Census, NIFC).
# fetch_external.py is idempotent — skips files already present with non-zero
# size. Failure here aborts the run before the orchestrator tries to ingest
# missing files.
# ---------------------------------------------------------------------------
echo "Pre-fetching external demo data..."
python3 /scripts/demo/fetch_external.py || {
    echo "ERROR: fetch_external.py failed" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Bridge host->container canonical path. fetch_external.py writes to
# /scripts/demo/raw/external/ (the /scripts/ mount). The orchestrator's
# theme local_paths point to /data/demo/external/. Copy across so the
# orchestrator's Path(entry["local_path"]).exists() check at
# seed-thematic-demo.py:215/251 passes.
#
# Real cp failures (perms, no disk) must propagate; only an empty source
# directory is silently OK (intermediate `.partial` files are skipped via
# explicit glob exclusion).
# ---------------------------------------------------------------------------
mkdir -p /data/demo/external
SRC_DIR=/scripts/demo/raw/external
if [ -d "${SRC_DIR}" ] && [ -n "$(ls -A "${SRC_DIR}" 2>/dev/null)" ]; then
    # Use shopt-style glob via find to skip .partial sidecars left by an
    # interrupted fetch_external.py run (per code-review MA-02).
    find "${SRC_DIR}" -mindepth 1 -maxdepth 1 ! -name '*.partial' -exec cp -rL {} /data/demo/external/ \;
fi

# ---------------------------------------------------------------------------
# Wait for API to be ready
# ---------------------------------------------------------------------------
echo "Waiting for API..."
for i in $(seq 1 "${MAX_RETRIES}"); do
    if python3 -c "import urllib.request; urllib.request.urlopen('${GEOLENS_BASE_URL}/health')" 2>/dev/null; then
        echo "API is ready."
        break
    fi
    if [ "$i" -eq "${MAX_RETRIES}" ]; then
        echo "ERROR: API did not become ready after $((MAX_RETRIES * RETRY_INTERVAL))s" >&2
        exit 1
    fi
    sleep "${RETRY_INTERVAL}"
done

# ---------------------------------------------------------------------------
# Authenticate — emits access_token on stdout.
# ---------------------------------------------------------------------------
echo "Authenticating as ${GEOLENS_ADMIN_USERNAME}..."
SEED_TOKEN="$(python3 "${CREATE_KEY_PY}" login)" || {
    echo "ERROR: Authentication failed" >&2
    exit 1
}
export SEED_TOKEN

# ---------------------------------------------------------------------------
# Rotate demo-seed API key (idempotent: delete + create fresh) and capture
# the plaintext key for the orchestrator.
# ---------------------------------------------------------------------------
echo "Creating seed API key..."
API_KEY="$(python3 "${CREATE_KEY_PY}" rotate-key)" || {
    echo "ERROR: Failed to obtain API key" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Run the FROZEN thematic orchestrator from Plan 01.
# All bundled data is at /data/demo (baked into the image by Stage 1 of the
# multi-stage Dockerfile). The cache dir is also under /data/demo so any
# Natural Earth CDN fetches the orchestrator might do are cached locally.
#
# We use `python3 ... "$@"` rather than `exec` so the EXIT trap above still
# runs after the orchestrator returns (and rotates the API key away).
# ---------------------------------------------------------------------------
echo "Running scripts/demo/seed-thematic-demo.py..."
python3 /scripts/demo/seed-thematic-demo.py \
    --api-key "${API_KEY}" \
    --base-url "${GEOLENS_BASE_URL}" \
    --cache-dir /data/demo/cache

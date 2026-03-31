#!/usr/bin/env bash
# ==============================================================================
# seed-demo.sh — Seed GeoLens demo with sample Natural Earth data
#
# Called by the seeder service in docker-compose.demo.yml.
# Waits for the API, logs in to get an API key, then runs the Natural Earth
# seed script with a representative subset of datasets.
# ==============================================================================
set -euo pipefail

BASE_URL="${GEOLENS_BASE_URL:-http://api:8000}"
USERNAME="${GEOLENS_ADMIN_USERNAME:-admin}"
PASSWORD="${GEOLENS_ADMIN_PASSWORD:-admin}"
MAX_RETRIES=30
RETRY_INTERVAL=5

echo "=== GeoLens Demo Seeder ==="
echo "Base URL: ${BASE_URL}"

# ---------------------------------------------------------------------------
# Wait for API to be ready
# ---------------------------------------------------------------------------
echo "Waiting for API..."
for i in $(seq 1 "${MAX_RETRIES}"); do
    if python -c "import urllib.request; urllib.request.urlopen('${BASE_URL}/health')" 2>/dev/null; then
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
# Authenticate and create an API key
# ---------------------------------------------------------------------------
echo "Authenticating as ${USERNAME}..."
TOKEN=$(SEED_USERNAME="${USERNAME}" SEED_PASSWORD="${PASSWORD}" SEED_URL="${BASE_URL}" \
    python3 -c '
import urllib.request, urllib.parse, json, sys, os
data = urllib.parse.urlencode({
    "username": os.environ["SEED_USERNAME"],
    "password": os.environ["SEED_PASSWORD"],
}).encode()
req = urllib.request.Request(os.environ["SEED_URL"] + "/api/auth/login", data=data)
resp = urllib.request.urlopen(req)
print(json.loads(resp.read())["access_token"])
') || { echo "ERROR: Authentication failed" >&2; exit 1; }

echo "Creating seed API key..."
# Delete existing demo-seed key if present, then create fresh
# (plaintext key is only returned at creation time)
API_KEY=$(SEED_TOKEN="${TOKEN}" SEED_URL="${BASE_URL}" \
    python3 -c '
import urllib.request, json, sys, os

url = os.environ["SEED_URL"]
headers = {
    "Authorization": "Bearer " + os.environ["SEED_TOKEN"],
    "Content-Type": "application/json",
}

# List existing keys and delete demo-seed if found
req = urllib.request.Request(url + "/api/api-keys/", headers=headers)
resp = urllib.request.urlopen(req)
keys = json.loads(resp.read())
for k in keys:
    if k.get("name") == "demo-seed":
        dreq = urllib.request.Request(
            url + "/api/api-keys/" + str(k["id"]) + "/",
            headers=headers,
            method="DELETE",
        )
        urllib.request.urlopen(dreq)
        break

# Create fresh key
data = json.dumps({"name": "demo-seed"}).encode()
req = urllib.request.Request(url + "/api/api-keys/", data=data, headers=headers, method="POST")
resp = urllib.request.urlopen(req)
print(json.loads(resp.read())["key"])
') || { echo "ERROR: Failed to obtain API key" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Check if data already seeded (idempotent)
# ---------------------------------------------------------------------------
DATASET_COUNT=$(SEED_API_KEY="${API_KEY}" SEED_URL="${BASE_URL}" \
    python3 -c '
import urllib.request, json, os
req = urllib.request.Request(os.environ["SEED_URL"] + "/api/datasets/?limit=1")
req.add_header("X-API-Key", os.environ["SEED_API_KEY"])
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
print(data.get("total", len(data.get("items", []))))
') || { echo "ERROR: Failed to check dataset count" >&2; exit 1; }

if [ "${DATASET_COUNT}" -gt 0 ]; then
    echo "Data already seeded (${DATASET_COUNT} datasets found). Skipping."
    exit 0
fi

# ---------------------------------------------------------------------------
# Seed with representative Natural Earth datasets
# ---------------------------------------------------------------------------
echo "Seeding Natural Earth datasets..."

# Seed a curated subset: countries, states, coastlines, lakes, rivers, airports, cities
DEMO_DATASETS=(
    "ne_10m_admin_0_countries"
    "ne_10m_admin_1_states_provinces"
    "ne_10m_coastline"
    "ne_10m_lakes"
    "ne_10m_rivers_lake_centerlines"
    "ne_10m_airports"
    "ne_10m_populated_places_simple"
    "ne_10m_roads"
    "ne_10m_urban_areas"
    "ne_10m_glaciated_areas"
    "ne_10m_reefs"
    "ne_10m_land"
    "ne_10m_ocean"
    "ne_10m_geography_regions_polys"
    "ne_10m_railroads"
    "ne_10m_ports"
    "ne_10m_time_zones"
    "ne_10m_admin_0_boundary_lines_land"
    "ne_10m_geographic_lines"
    "ne_10m_playas"
)

for dataset in "${DEMO_DATASETS[@]}"; do
    echo "  Seeding: ${dataset}"
    uv run python /scripts/seed-natural-earth.py \
        --api-key "${API_KEY}" \
        --base-url "${BASE_URL}" \
        --dataset "${dataset}" \
        --cache-dir /tmp/ne-cache \
        || echo "  WARNING: Failed to seed ${dataset}, continuing..."
done

# ---------------------------------------------------------------------------
# Set all datasets to public visibility
# ---------------------------------------------------------------------------
echo "Setting all datasets to public visibility..."
SEED_API_KEY="${API_KEY}" SEED_URL="${BASE_URL}" \
    python3 -c '
import urllib.request, json, os

url = os.environ["SEED_URL"]
api_key = os.environ["SEED_API_KEY"]

req = urllib.request.Request(url + "/api/datasets/?limit=200")
req.add_header("X-API-Key", api_key)
resp = urllib.request.urlopen(req)
datasets = json.loads(resp.read()).get("items", [])

for ds in datasets:
    ds_id = ds["id"]
    data = json.dumps({"visibility": "public"}).encode()
    patch = urllib.request.Request(
        url + "/api/datasets/" + str(ds_id) + "/",
        data=data,
        method="PATCH",
    )
    patch.add_header("X-API-Key", api_key)
    patch.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(patch)
    except Exception as e:
        print(f"  Warning: Could not set {ds_id} to public: {e}")
'

echo "=== Demo seeding complete ==="

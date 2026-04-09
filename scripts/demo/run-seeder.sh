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
# ==============================================================================
set -euo pipefail

BASE_URL="${GEOLENS_BASE_URL:-http://api:8000}"
USERNAME="${GEOLENS_ADMIN_USERNAME:-admin}"
PASSWORD="${GEOLENS_ADMIN_PASSWORD:-admin}"
MAX_RETRIES=30
RETRY_INTERVAL=5

echo "=== GeoLens Thematic Demo Seeder Wrapper ==="
echo "Base URL: ${BASE_URL}"

# ---------------------------------------------------------------------------
# Wait for API to be ready
# ---------------------------------------------------------------------------
echo "Waiting for API..."
for i in $(seq 1 "${MAX_RETRIES}"); do
    if python3 -c "import urllib.request; urllib.request.urlopen('${BASE_URL}/health')" 2>/dev/null; then
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
# Authenticate (form-encoded login per backend/tests/test_auth.py contract)
# ---------------------------------------------------------------------------
echo "Authenticating as ${USERNAME}..."
TOKEN=$(SEED_USERNAME="${USERNAME}" SEED_PASSWORD="${PASSWORD}" SEED_URL="${BASE_URL}" \
    python3 -c '
import urllib.request, urllib.parse, json, os
data = urllib.parse.urlencode({
    "username": os.environ["SEED_USERNAME"],
    "password": os.environ["SEED_PASSWORD"],
}).encode()
req = urllib.request.Request(os.environ["SEED_URL"] + "/api/auth/login/", data=data)
resp = urllib.request.urlopen(req)
print(json.loads(resp.read())["access_token"])
') || { echo "ERROR: Authentication failed" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Create or recreate the demo-seed API key (idempotent: delete + create fresh)
# The plaintext key is only returned at creation time, so we cannot reuse a
# stored key — we always rotate.
# ---------------------------------------------------------------------------
echo "Creating seed API key..."
API_KEY=$(SEED_TOKEN="${TOKEN}" SEED_URL="${BASE_URL}" \
    python3 -c '
import urllib.request, urllib.error, json, os

url = os.environ["SEED_URL"]
headers = {
    "Authorization": "Bearer " + os.environ["SEED_TOKEN"],
    "Content-Type": "application/json",
}

# List existing keys and delete demo-seed if present.
# GET /auth/api-keys/ returns {"items": [...]}; POST returns the bare key object.
req = urllib.request.Request(url + "/api/auth/api-keys/", headers=headers)
resp = urllib.request.urlopen(req)
body = json.loads(resp.read())
keys = body.get("items", body) if isinstance(body, dict) else body
for k in keys:
    if k.get("name") == "demo-seed":
        dreq = urllib.request.Request(
            url + "/api/auth/api-keys/" + str(k["id"]),
            headers=headers,
            method="DELETE",
        )
        try:
            urllib.request.urlopen(dreq)
        except urllib.error.HTTPError as e:
            if e.code not in (204, 404):
                raise
        break

# Create fresh key
data = json.dumps({"name": "demo-seed"}).encode()
req = urllib.request.Request(url + "/api/auth/api-keys/", data=data, headers=headers, method="POST")
resp = urllib.request.urlopen(req)
print(json.loads(resp.read())["key"])
') || { echo "ERROR: Failed to obtain API key" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Exec the FROZEN thematic orchestrator from Plan 01.
# All bundled data is at /data/demo (baked into the image by Stage 1 of the
# multi-stage Dockerfile). The cache dir is also under /data/demo so any
# Natural Earth CDN fetches the orchestrator might do are cached locally.
# ---------------------------------------------------------------------------
echo "Running scripts/demo/seed-thematic-demo.py..."
exec python3 /scripts/demo/seed-thematic-demo.py \
    --api-key "${API_KEY}" \
    --base-url "${BASE_URL}" \
    --cache-dir /data/demo/cache

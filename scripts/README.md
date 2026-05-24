# Scripts

Utility scripts for GeoLens administration and data seeding.

## Seed Scripts

### `seed-ago-data.py`

Imports public datasets from an ArcGIS Online organization into GeoLens via the service connector API.

Discovers all public Feature/Map Services in the org and ingests each layer directly from the ArcGIS REST endpoint using GDAL's ESRIJSON driver (no intermediate GeoJSON download). This stores the `source_url` on each dataset, enabling future updates via the UI's Re-Upload dialog or the `--update` flag.

After import, each dataset is enriched with AGO metadata:
- **Source organization** from `accessInformation`
- **License** from `licenseInfo` (HTML stripped)
- **Keywords** from AGO `tags`
- **Summary** from layer `description` or item `snippet`

Layers are assigned to a collection named after the organization.

```bash
# Prerequisites
pip install httpx

# Dry run — list discoverable layers without importing
python scripts/seed-ago-data.py --dry-run

# Import all layers
python scripts/seed-ago-data.py --api-key <key>

# Import from a different org
python scripts/seed-ago-data.py --org-url https://otherorg.maps.arcgis.com --api-key <key>

# Upsert — import new layers AND refresh existing ones
python scripts/seed-ago-data.py --api-key <key> --update

# Control parallelism (default: 1)
python scripts/seed-ago-data.py --api-key <key> --concurrency 3

# Set job poll timeout (default: 1200s)
python scripts/seed-ago-data.py --api-key <key> --timeout 1800
```

| Flag | Default | Description |
|------|---------|-------------|
| `--org-url` | `https://njhighlands.maps.arcgis.com` | ArcGIS Online organization URL |
| `--api-key` | `$GEOLENS_API_KEY` | GeoLens API key (or env var) |
| `--base-url` | `http://localhost:8080` | GeoLens base URL |
| `--dry-run` | off | List layers without importing |
| `--update` | off | Upsert mode: import new layers and refresh existing ones from source |
| `--concurrency` | 1 | Max parallel ingest streams |
| `--timeout` | 1200 | Job poll timeout in seconds |

**Behavior by mode:**

| Layer state | Default | `--update` |
|-------------|---------|------------|
| New (not in catalog) | Import | Import |
| Exists (matched by `source_url`) | Skip | Refresh via reupload API |

**Environment variables:**

| Variable | Description |
|----------|-------------|
| `GEOLENS_API_KEY` | GeoLens API key (alternative to `--api-key`) |
| `GEOLENS_BASE_URL` | GeoLens base URL (alternative to `--base-url`) |
| `ARCGIS_ORG_URL` | ArcGIS org URL (alternative to `--org-url`) |

### `seed-natural-earth.py`

Imports Natural Earth vector datasets (countries, states, coastlines, etc.) for base map data.

### `seed-perf-data.py`

Generates synthetic large datasets for performance testing.

### `seed-e2e.py`

Creates minimal test datasets for end-to-end test suites.

## Shell Scripts

| Script | Purpose |
|--------|---------|
| `install.sh` | First-run installer — see below |
| `init-db.sh` | Initialize the PostGIS database schema |
| `init-test-db.sh` | Initialize a host-accessible `geolens_test` database with the extensions, schemas, and roles expected by CI and local debugging |
| `restore.sh` | Restore a database backup |
| `check-env.sh` | Validate required environment variables |
| `run-baseline.sh` | Run performance baselines |
| `analyze-query-plans.sh` | Analyze slow query plans |
| `cleanup-test-pollution.sql` | Remove leftover test data |

### `install.sh`

First-run installer for a self-hosted GeoLens stack. Verifies prerequisites
(`git`, `docker`, Docker Compose v2), generates a `JWT_SECRET_KEY` (via
`openssl rand -hex 32`, with `/dev/urandom` fallback), seeds admin
credentials in `.env`, checks the configured `DB_PORT` / `API_PORT` /
`FRONTEND_PORT` are free, and runs `docker compose up -d`.

```bash
# From inside a checkout
bash scripts/install.sh

# Or have the script clone for you
GEOLENS_INSTALL_DIR=geolens bash <(curl -fsSL https://raw.githubusercontent.com/geolens-io/geolens/main/scripts/install.sh)

# Non-interactive — env vars override the prompts
GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD='change-me' bash scripts/install.sh
```

| Variable | Purpose |
|----------|---------|
| `GEOLENS_REPO_URL` | Override the clone URL (default: `https://github.com/geolens-io/geolens.git`) |
| `GEOLENS_INSTALL_DIR` | Directory to clone into when not already in a checkout (default: `geolens`) |
| `GEOLENS_ADMIN_USERNAME` | Skip the admin-username prompt with this value |
| `GEOLENS_ADMIN_PASSWORD` | Skip the admin-password prompt with this value |

Re-running the script is idempotent — existing `.env` values (including a
real `JWT_SECRET_KEY`) are preserved. Only missing or empty values are
populated.

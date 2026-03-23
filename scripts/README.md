# Scripts

Utility scripts for GeoLens administration and data seeding.

## Seed Scripts

### `seed-ago-data.py`

Imports public datasets from an ArcGIS Online organization into GeoLens.

Discovers all public Feature/Map Services in the org, downloads each layer as GeoJSON, and ingests via the upload API. Layers are assigned to a collection named after the organization. Layer descriptions from AGO are captured as dataset summaries.

```bash
# Prerequisites
pip install httpx

# Dry run — list discoverable layers without importing
python scripts/seed-ago-data.py --dry-run

# Import all layers
python scripts/seed-ago-data.py --api-key <key>

# Import from a different org
python scripts/seed-ago-data.py --org-url https://otherorg.maps.arcgis.com --api-key <key>

# Resume a partial run (caches downloaded GeoJSON locally)
python scripts/seed-ago-data.py --api-key <key> --cache-dir /tmp/ago-cache

# Control parallelism (default: 3)
python scripts/seed-ago-data.py --api-key <key> --concurrency 5
```

| Flag | Default | Description |
|------|---------|-------------|
| `--org-url` | `https://njhighlands.maps.arcgis.com` | ArcGIS Online organization URL |
| `--api-key` | `$GEOLENS_API_KEY` | GeoLens API key |
| `--base-url` | `http://localhost:8080` | GeoLens base URL |
| `--dry-run` | off | List layers without importing |
| `--cache-dir` | none | Cache downloaded GeoJSON for resumable runs |
| `--concurrency` | 3 | Max parallel download+ingest streams |

Re-running the script is safe — it skips layers that already exist in the catalog (matched by `source_filename`).

### `seed-natural-earth.py`

Imports Natural Earth vector datasets (countries, states, coastlines, etc.) for base map data.

### `seed-perf-data.py`

Generates synthetic large datasets for performance testing.

### `seed-e2e.py`

Creates minimal test datasets for end-to-end test suites.

## Shell Scripts

| Script | Purpose |
|--------|---------|
| `init-db.sh` | Initialize the PostGIS database schema |
| `init-test-db.sh` | Initialize a test database |
| `restore.sh` | Restore a database backup |
| `check-env.sh` | Validate required environment variables |
| `run-baseline.sh` | Run performance baselines |
| `analyze-query-plans.sh` | Analyze slow query plans |
| `cleanup-test-pollution.sql` | Remove leftover test data |

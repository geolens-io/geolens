# Scripts

Utility scripts for GeoLens administration and data seeding.

## Seed scripts

### `seed-showcase.py`

Builds three demo maps from public, openly licensed data against a running stack:

- **Manhattan Skyline**: every Lower + Midtown building footprint extruded to its real
  surveyed roof height and color-graded by height (NYC Open Data).
- **New York Income**: a data-driven quantile choropleth of median household income by
  county (USDA ERS Atlas of Rural & Small-Town America).
- **The Matterhorn** (`--with-terrain`): a 3D terrain mesh + hillshade from a swisstopo
  swissALTI3D VRT mosaic, with OpenStreetMap climbing routes (white-cased) and named peaks
  draped on the terrain.

```bash
pip install httpx

# Build the Manhattan + income maps
python scripts/seed-showcase.py --username admin --password admin

# Also build the Matterhorn 3D-terrain hero (downloads ~9 swissALTI3D COG tiles)
python scripts/seed-showcase.py --username admin --password admin --with-terrain

# Build just one map
python scripts/seed-showcase.py --only income
```

| Flag | Default | Description |
|------|---------|-------------|
| `--base-url` | `http://localhost:8080` (`$GEOLENS_BASE_URL`, fallback `$GEOLENS_URL`) | GeoLens base URL |
| `--username` | `admin` (`$GEOLENS_ADMIN_USERNAME`) | Admin username |
| `--password` | `admin` (`$GEOLENS_ADMIN_PASSWORD`) | Admin password |
| `--with-terrain` | off | Also build the Matterhorn terrain hero |
| `--only` | unset | Build only `manhattan`, `income`, or `matterhorn` |

Requires internet access to the upstream open-data sources (NYC Open Data, USDA ERS,
OpenStreetMap, swisstopo). The script is non-idempotent. Each run POSTs new maps.

## Shell scripts

| Script | Purpose |
|--------|---------|
| `install.sh` | First-run installer (see below) |
| `preflight-env.sh` | Statically validate `.env` (JWT secret, admin creds) before boot via `make preflight` / `make dev` |
| `check-env.sh` | Probe the running stack's env, DB connectivity, and GDAL via `make doctor` (requires the stack up) |
| `init-db.sh` | Initialize the PostGIS database schema (mounted into the db container's init) |
| `init-test-db.sh` | Initialize a host-accessible `geolens_test` database (extensions, schemas, roles) for local `psql` debugging. Not used by CI. CI and pytest each bootstrap their own test databases. |
| `backup-entrypoint.sh` | Scheduled `pg_dump` backups with retention + optional S3 upload (the default Docker Compose backup service) |
| `restore.sh` | Restore a database backup |
| `run-baseline.sh` | Run performance baselines |
| `analyze-query-plans.sh` | Analyze slow query plans |
| `cleanup-test-pollution.sql` | Remove leftover test data (manual `psql`) |

## Build & release glue

Wired into the `Makefile` / `package.json`, not run by operators directly:

| Script | Purpose |
|--------|---------|
| `flatten_openapi_defs.py` | Post-process `backend/openapi.json` for the SDK generators. Runs stdlib-only via `uv run --no-project` outside the backend venv (`make sdks`) |
| `sync_sdk_versions.py` | Sync the generated SDK package versions (`make sdks`) |
| `check-readme-locales.mjs` | Verify the README locale stubs stay in sync (`npm run check:readme-locales`) |

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

# Non-interactive: env vars override the prompts
GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD='change-me' bash scripts/install.sh
```

| Variable | Purpose |
|----------|---------|
| `GEOLENS_REPO_URL` | Override the clone URL (default: `https://github.com/geolens-io/geolens.git`) |
| `GEOLENS_INSTALL_DIR` | Directory to clone into when not already in a checkout (default: `geolens`) |
| `GEOLENS_REF` | Install a specific ref instead of the latest release tag: a tag (e.g. `v1.2.0`) or a branch (e.g. `main`). Tags are checked out by their fully-qualified `refs/tags/` ref so a same-named branch cannot shadow them. |
| `GEOLENS_ADMIN_USERNAME` | Skip the admin-username prompt with this value |
| `GEOLENS_ADMIN_PASSWORD` | Skip the admin-password prompt with this value |

Re-running the script is idempotent. Existing `.env` values (including a
real `JWT_SECRET_KEY`) are preserved. Only missing or empty values are
populated.

# Scripts

Utility scripts for GeoLens administration and data seeding.

## Seed scripts

### `seed-showcase.py`

Builds the marketing showcase maps from public, openly licensed data against a running
stack — the Manhattan skyline (3D extrusion), New York income choropleth, world airports
(clustered), recent earthquakes, world countries/rivers, the Restless Earth composite
story map (quakes + tectonic plate boundaries + major cities), a "Discover the World"
collection, and — behind flags — the Matterhorn 3D-terrain and Sentinel-2 true-color
heroes. The authoritative map list, data sources, and the API gotchas each builder
encodes live in the script's module docstring.

```bash
pip install httpx

# Build the default showcase set
python scripts/seed-showcase.py \
  --username "${GEOLENS_ADMIN_USERNAME:-admin}" \
  --password "$GEOLENS_ADMIN_PASSWORD"

# Also build the Matterhorn 3D-terrain hero (downloads ~62 swissALTI3D COG tiles)
python scripts/seed-showcase.py \
  --username "${GEOLENS_ADMIN_USERNAME:-admin}" \
  --password "$GEOLENS_ADMIN_PASSWORD" \
  --with-terrain

# Build just one map (restless additionally needs earthquakes + countries seeded first)
python scripts/seed-showcase.py \
  --username "${GEOLENS_ADMIN_USERNAME:-admin}" \
  --password "$GEOLENS_ADMIN_PASSWORD" \
  --only income

# Swap a fresh USGS 30-day feed into the earthquake datasets (in place), then exit.
# Run every week or two so "last 30 days" stays honest on a long-lived instance.
python scripts/seed-showcase.py \
  --username "${GEOLENS_ADMIN_USERNAME:-admin}" \
  --password "$GEOLENS_ADMIN_PASSWORD" \
  --refresh-quakes
```

| Flag | Default | Description |
|------|---------|-------------|
| `--base-url` | `http://localhost:8080` (`$GEOLENS_BASE_URL`, fallback `$GEOLENS_URL`) | GeoLens base URL |
| `--username` | `admin` (`$GEOLENS_ADMIN_USERNAME`) | Admin username |
| `--password` | `$GEOLENS_ADMIN_PASSWORD` | Admin password |
| `--with-terrain` | off | Also build the Matterhorn terrain hero |
| `--with-sentinel2` | off | Also build the Sentinel-2 true-color hero |
| `--only` | unset | Build one showcase (`manhattan`, `income`, `matterhorn`, `airports`, `earthquakes`, `countries`, `rivers`, `restless`, `sentinel2`, `collection`) |
| `--force` | off | Re-create showcase maps/datasets even if they already exist |
| `--refresh-quakes` | off | Refresh the earthquake datasets from the USGS feed, then exit |

Requires internet access to the upstream open-data sources (NYC Open Data, USDA ERS,
OurAirports, USGS, Natural Earth, OpenStreetMap, swisstopo, Element84 Earth Search).
Maps are skipped if they already exist (`--force` recreates them); each forced run
POSTs new maps/datasets rather than updating in place.

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
| `check_public_surface.py` | Scan tracked public source surfaces for launch-sensitive wording (`make public-surface-check` / `npm run check:public-surface`) |
| `public_surface_gate.json` | Configure scan boundaries, forbidden pattern IDs, and exact allowlist entries |
| `check_deployed_surface.py` | Check live marketing/docs pages after deploy (`make deployed-surface-check` / `npm run check:deployed-surface`) |
| `deployed_surface_gate.json` | Configure deployed page URLs plus required and forbidden assertion IDs |

Allowlist entries in `public_surface_gate.json` must name an exact path, pattern ID, match, and rationale. Wildcard allowlist paths and stale entries fail the gate.

Run `make deployed-surface-check` after a marketing or docs deploy that affects
install, OGC, backup, or self-hosted provider copy. The command fetches
`https://getgeolens.com/` and selected `https://docs.getgeolens.com/` pages,
then reports any missing required copy or stale deployed copy.

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
GEOLENS_ADMIN_USERNAME=admin \
GEOLENS_ADMIN_PASSWORD="$(openssl rand -base64 24)" \
bash scripts/install.sh
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

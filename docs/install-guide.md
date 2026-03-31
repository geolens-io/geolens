# GeoLens Installation Guide

Step-by-step guide to deploy GeoLens from scratch using Docker Compose.

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| Docker Engine | 24.0+ | [Install Docker](https://docs.docker.com/engine/install/) |
| Docker Compose | v2.20+ | Included with Docker Desktop; standalone install via `docker compose version` |
| RAM | 4 GB | PostgreSQL + PostGIS + API + Worker + Frontend |
| Disk | 10 GB | Base images + data volumes; scale with dataset size |
| Ports | 3 ports | Default: 8080 (Frontend), 5434 (PostgreSQL), 8001 (API) |

## Quick Start

### 1. Clone the repository

```bash
git clone <repository-url> geolens
cd geolens
```

### 2. Configure environment

Copy the example environment file and customize it:

```bash
cp .env.example .env
```

Open `.env` in your editor and set production values. At minimum, change these:

```env
# Database credentials
POSTGRES_DB=geolens
POSTGRES_USER=geolens
POSTGRES_PASSWORD=<strong-password>

# Authentication
JWT_SECRET_KEY=<random-256-bit-string>
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=<strong-admin-password>

# Host ports (adjust if any conflict with existing services)
DB_PORT=5434
API_PORT=8001
FRONTEND_PORT=8080
```

Generate a secure JWT secret:

```bash
openssl rand -hex 32
```

See [Configuration Reference](./configuration-reference.md) for all available settings.

### 3. Start all services

```bash
docker compose up -d
```

This builds and starts the following services:

| Service | Description | Internal Port | Host Port |
|---|---|---|---|
| `db` | PostgreSQL 17 + PostGIS 3.6 | 5432 | `$DB_PORT` (5434) |
| `migrate` | Alembic migrations (runs once, then exits) | -- | -- |
| `api` | FastAPI backend (Uvicorn) | 8000 | `$API_PORT` (8001) |
| `worker` | Background ingestion worker | 8001 | -- |
| `titiler` | Raster tile server (COG/GeoTIFF) | 8000 | -- |
| `frontend` | Static SPA (nginx proxy) | 8080 | `$FRONTEND_PORT` (8080) |

On first start, the `migrate` service runs Alembic migrations to set up the database schema. It exits after completion, and the API waits for it to finish before starting.

### 4. Verify installation

Wait for all services to become healthy (about 30-60 seconds):

```bash
docker compose ps
```

All services should show `healthy` status. Then verify the API:

```bash
# Health check
curl http://localhost:8080/health

# Login with admin credentials (use values from your .env)
curl -X POST http://localhost:8080/api/auth/login \
  -d "username=<your-admin-username>&password=<your-admin-password>"
```

The login response returns a JWT token:

```json
{"access_token": "eyJ...", "token_type": "bearer"}
```

Visit `http://localhost:8080` in your browser to access the web interface.

## Initial Setup

### Default admin account

The system creates an admin user on first startup using the `GEOLENS_ADMIN_USERNAME` and `GEOLENS_ADMIN_PASSWORD` environment variables. These must be set in your `.env` file.

After your first login, change the admin password or create a new admin account and deactivate the default one:

```bash
# Get auth token (use your admin credentials from .env)
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -d "username=$GEOLENS_ADMIN_USERNAME&password=$GEOLENS_ADMIN_PASSWORD" | jq -r '.access_token')

# Create a new admin user
curl -X POST http://localhost:8080/api/admin/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "newadmin", "password": "secure-password", "role": "admin"}'
```

### Verify services

| Service | URL | Expected |
|---|---|---|
| Web UI | http://localhost:8080 | Login page |
| API docs | http://localhost:8080/api/docs | Swagger UI |
| Health | http://localhost:8080/health | `{"status": "ok"}` |
| PostgreSQL | `psql -h localhost -p 5434 -U geolens` | Database prompt |

## Stopping and Starting

### Stop all services (preserves data)

```bash
docker compose down
```

### Start services

```bash
docker compose up -d
```

### Stop and remove all data

```bash
docker compose down -v
```

The `-v` flag removes Docker volumes (`pgdata` and `upload_staging`), deleting all database data and uploaded files.

### View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f db
```

## Upgrading

### Standard upgrade

```bash
# Pull latest code
git pull

# Rebuild and restart (the migrate service runs Alembic automatically)
docker compose up -d --build
```

Alembic migrations run automatically when the API container starts, so database schema changes are applied without manual intervention.

### Database-only upgrade

If only the database schema changed:

```bash
docker compose restart api
```

The `migrate` service will run migrations before the API starts.

## Data Persistence

Data is stored in two Docker volumes:

| Volume | Purpose | Path inside container |
|---|---|---|
| `pgdata` | PostgreSQL data directory | `/var/lib/postgresql/data` |
| `upload_staging` | Uploaded files awaiting ingestion | `/app/staging` |

These volumes persist across `docker compose down` (without `-v`). See [Admin Guide](./admin-guide.md) for backup procedures.

## Troubleshooting

### Missing `.env` file

If you see a `ValidationError` with "Field required" errors on startup:

```
pydantic_core._pydantic_core.ValidationError: 3 validation errors for Settings
```

You forgot to create the `.env` file. Copy the template:

```bash
cp .env.example .env
docker compose up -d
```

### Migration warnings on startup

You may see log messages like:

```
INFO: Migrations already applied by migrate service (or database not ready yet)
```

This is expected and harmless. The dedicated `migrate` service runs Alembic migrations before the API starts. The API and worker entrypoints also attempt migrations as a safety net — when the `migrate` service has already applied them, the entrypoint logs this informational message and proceeds normally.

### Port conflicts

If a port is already in use, change it in `.env`:

```env
FRONTEND_PORT=8081
API_PORT=8002
DB_PORT=5435
```

Then restart:

```bash
docker compose down && docker compose up -d
```

### Out of memory

If the database or API crashes with OOM errors:

- Increase Docker memory allocation (Docker Desktop: Settings > Resources > Memory)
- Minimum recommended: 4 GB for all services
- For large datasets: 8 GB+

### Services not starting

Check the startup order and health:

```bash
# View startup logs
docker compose logs --tail=50 db
docker compose logs --tail=50 api

# Check health status
docker compose ps
```

Common issues:
- **db not healthy**: Check `POSTGRES_USER` and `POSTGRES_PASSWORD` match in `.env`
- **api not starting**: Verify database is healthy first; check migration errors in API logs
- **frontend 502 errors**: Upstream API not ready yet; wait 30 seconds and retry

### Export 500 errors (staging permission denied)

If `/api/datasets/{id}/export` returns HTTP 500, verify staging writability inside the API container:

```bash
docker compose exec api sh -lc '\
  dir=${UPLOAD_STAGING_DIR:-/app/staging}; \
  mkdir -p "$dir/exports" && \
  touch "$dir/.geolens-write-test" "$dir/exports/.geolens-write-test" && \
  rm -f "$dir/.geolens-write-test" "$dir/exports/.geolens-write-test"'
```

Run the runtime export verification spec after permissions are corrected:

```bash
npm run e2e -- e2e/export-runtime.spec.ts
```

Expected success signals:
- Exports pass for `gpkg`, `geojson`, `shp`, and `csv` with attachment payload integrity (SQLite header, FeatureCollection JSON, zip members, CSV header row).
- `target_crs=EPSG:3857` export shows projected coordinate semantics (not only HTTP 200).
- `bbox` and `where` exports are true subsets (feature/property assertions pass).
- Audit logs include `dataset.export` entries with export parameters.

If the writability check fails:
- Fix ownership/permissions on the mounted staging path so uid:gid `1001:1001` can write.
- Or set `UPLOAD_STAGING_DIR` in `.env` to a writable directory and restart services with `docker compose up -d --build`.
- Re-run `npm run e2e -- e2e/export-runtime.spec.ts` to confirm full runtime behavior.

### GDAL/OGR errors during ingestion

The API container includes GDAL. If file ingestion fails:

```bash
# Check API logs for OGR errors
docker compose logs api | grep -i "ogr\|gdal\|error"
```

Supported upload formats: `.zip` (Shapefile), `.gpkg` (GeoPackage), `.geojson`, `.json`, `.csv`

### Database connection errors

Verify the database is accessible:

```bash
docker compose exec db pg_isready -U geolens -d geolens
```

If the database is unreachable from the API, ensure the `POSTGRES_HOST` is set to `db` (the Docker service name).

### Reset to clean state

To completely reset the installation:

```bash
docker compose down -v
docker compose up -d
```

This removes all data and starts fresh with the default admin account.

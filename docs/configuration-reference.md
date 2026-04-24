# GeoLens Configuration Reference

All environment variables used by GeoLens, their defaults, and descriptions. Set these in the `.env` file at the project root.

## Database

| Variable | Default | Required | Description |
|---|---|---|---|
| `POSTGRES_DB` | `geolens` | Yes | PostgreSQL database name |
| `POSTGRES_USER` | `geolens` | Yes | PostgreSQL superuser username |
| `POSTGRES_PASSWORD` | None (required) | Yes | PostgreSQL superuser password. Generate with `openssl rand -base64 24`. |
| `POSTGRES_HOST` | `db` | No | Database hostname. Use `db` for Docker Compose (service name). |
| `POSTGRES_PORT` | `5432` | No | Database port (internal). The host-mapped port is configured separately. |

## Authentication

| Variable | Default | Required | Description |
|---|---|---|---|
| `JWT_SECRET_KEY` | None (required) | Yes | Secret key for signing JWT tokens. Generate with `openssl rand -hex 32`. |
| `JWT_ALGORITHM` | `HS256` | No | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | No | JWT token lifetime in minutes |
| `GEOLENS_ADMIN_USERNAME` | None (required) | Yes | Username for the automatically created admin account |
| `GEOLENS_ADMIN_PASSWORD` | None (required) | Yes | Password for the initial admin account |
| `REGISTRATION_ENABLED` | `false` | No | Whether self-registration is enabled. When `false`, only admins can create users. |

## Upload Settings

| Variable | Default | Required | Description |
|---|---|---|---|
| `UPLOAD_MAX_SIZE_MB` | `500` | No | Maximum upload file size in megabytes |
| `UPLOAD_STAGING_DIR` | `/app/staging` | No | Directory for temporary file storage during ingestion/export. Must be writable by the API runtime user (uid:gid `1001:1001`). Mapped to `upload_staging` Docker volume. |
| `UPLOAD_ALLOWED_EXTENSIONS` | `.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls` | No | Comma-separated list of allowed file extensions for upload |
| `PRESIGNED_MULTIPART_THRESHOLD_MB` | `100` | No | Files larger than this (MB) use multipart presigned S3 URLs. Only applies when `STORAGE_PROVIDER=s3`. |

### `UPLOAD_STAGING_DIR` Writability Requirement

GeoLens validates staging writability at startup and before export execution. Both `UPLOAD_STAGING_DIR` and `${UPLOAD_STAGING_DIR}/exports` must allow write access for the API runtime user.

Quick validation command:

```bash
docker compose exec api sh -lc '\
  dir=${UPLOAD_STAGING_DIR:-/app/staging}; \
  mkdir -p "$dir/exports" && \
  touch "$dir/.geolens-write-test" "$dir/exports/.geolens-write-test" && \
  rm -f "$dir/.geolens-write-test" "$dir/exports/.geolens-write-test"'
```

If this command fails, fix ownership/permissions on the mounted path or set `UPLOAD_STAGING_DIR` to a writable directory, then restart the API container.

## Job Queue

| Variable | Default | Required | Description |
|---|---|---|---|
| `PROCRASTINATE_SCHEMA` | `catalog` | No | PostgreSQL schema for the Procrastinate job queue tables |

## Public URLs

| Variable | Default | Required | Description |
|---|---|---|---|
| `PUBLIC_APP_URL` | `http://localhost:8080` | No | Browser-facing app URL. Used for share links and OAuth redirect URIs. |
| `PUBLIC_API_URL` | `http://localhost:8080/api` | No | Externally-reachable API base URL. Used in OGC self/collection/next link hrefs. |
| `PUBLIC_BASE_URL` | None | No | **Deprecated.** Legacy alias for `PUBLIC_API_URL`. Use `PUBLIC_API_URL` instead. |

## CORS

| Variable | Default | Required | Description |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `""` (same-origin only) | No | Comma-separated list of allowed origins for cross-origin API requests. Required when the frontend is served from a different domain than the API. |

## Tile Serving & CDN

| Variable | Default | Required | Description |
|---|---|---|---|
| `TILE_CACHE_TTL` | `300` | No | Tile cache TTL in seconds |
| `TILE_SIGNING_SECRET` | None (falls back to `JWT_SECRET_KEY`) | No | Secret for signing tile request URLs. Set separately when you want to rotate tile secrets without invalidating JWT tokens. |
| `CDN_BASE_URL` | None | No | CDN origin URL for tile delivery. When set, the frontend requests tiles from this URL instead of the API. |

## Logging

| Variable | Default | Required | Description |
|---|---|---|---|
| `LOG_JSON` | `false` | No | Output logs in structured JSON format. Recommended for production. When enabled, Swagger UI (`/api/docs`) is disabled. |
| `LOG_LEVEL` | `INFO` | No | Log level. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Storage Provider

| Variable | Default | Required | Description |
|---|---|---|---|
| `STORAGE_PROVIDER` | `local` | No | Storage backend for uploaded files. Options: `local`, `s3`. |
| `S3_ENDPOINT` | None | When `s3` | S3-compatible endpoint URL. Leave unset for AWS S3. For MinIO: `http://minio:9000`. |
| `S3_BUCKET` | None | When `s3` | S3 bucket name. |
| `S3_ACCESS_KEY_ID` | None | When `s3` | S3 access key ID. |
| `S3_SECRET_ACCESS_KEY` | None | When `s3` | S3 secret access key. |
| `S3_REGION` | `us-east-1` | No | S3 region. |
| `S3_ALLOW_HTTP` | `false` | No | Allow HTTP (non-TLS) connections to S3 endpoint. Enable for local MinIO. |
| `S3_ADDRESSING_STYLE` | `auto` | No | S3 addressing style. Options: `auto`, `path`, `virtual`. Use `path` for MinIO. |

## Managed Database / SSL

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL_OVERRIDE` | None | No | Full PostgreSQL connection URL for managed databases (RDS, Cloud SQL). Overrides individual `POSTGRES_*` variables. |
| `DATABASE_SSL_MODE` | `prefer` | No | Database SSL mode. Options: `disable`, `prefer`, `require`, `verify-full`. |
| `DATABASE_SSL_CA_CERT` | None | When `verify-full` | Path to CA certificate file for database SSL verification. |
| `DATABASE_POOL_PRE_PING` | `true` | No | Enable connection pool pre-ping to detect broken connections before use. Adds slight latency per checkout. Set to `false` only if you need to disable this for a specific environment. |
| `DB_USE_EXTERNAL_POOLER` | `false` | No | Enable external connection pooler mode (PgBouncer, RDS Proxy). Disables prepared statements. |

## Connection Pool Tuning

These variables control the SQLAlchemy connection pool. Ignored when `DB_USE_EXTERNAL_POOLER` is `true`.

| Variable | Default | Required | Description |
|---|---|---|---|
| `DB_POOL_SIZE` | `10` | No | Maximum number of persistent connections in the pool. |
| `DB_MAX_OVERFLOW` | `5` | No | Maximum number of additional connections beyond `DB_POOL_SIZE`. |
| `DB_POOL_TIMEOUT` | `30` | No | Seconds to wait for a connection from the pool before raising an error. |
| `DB_POOL_RECYCLE` | `1800` | No | Seconds after which a connection is recycled (replaced). Prevents stale connections with managed databases. |
| `TILE_POOL_MIN_SIZE` | `2` | No | Minimum connections in the dedicated asyncpg tile query pool. |
| `TILE_POOL_MAX_SIZE` | `10` | No | Maximum connections in the dedicated asyncpg tile query pool. |

## Cache

| Variable | Default | Required | Description |
|---|---|---|---|
| `REDIS_URL` | None | No | Redis/Valkey connection URL for cross-instance caching. Leave unset for in-memory caching (single-instance default). Example: `redis://valkey:6379/0`. |

## Backup

These variables configure the `backup` service (enable with `docker compose --profile backup up -d`).

| Variable | Default | Required | Description |
|---|---|---|---|
| `BACKUP_SCHEDULE` | `0 2 * * *` | No | Cron expression for automated database backups. Default: daily at 2:00 AM UTC. |
| `BACKUP_RETENTION_DAILY` | `7` | No | Number of daily backups to retain locally. |
| `BACKUP_RETENTION_WEEKLY` | `4` | No | Number of weekly (Sunday) backups to retain locally. |
| `BACKUP_S3_ENABLED` | `false` | No | Enable off-site backup upload to S3-compatible storage. Uses `S3_*` credentials. |

## Worker

| Variable | Default | Required | Description |
|---|---|---|---|
| `WORKER_SHUTDOWN_TIMEOUT` | `30` | No | Graceful shutdown timeout for the background worker in seconds |

## Authentication (Additional)

| Variable | Default | Required | Description |
|---|---|---|---|
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | No | JWT refresh token lifetime in days. |

## Configuration Lockdown

| Variable | Default | Required | Description |
|---|---|---|---|
| `ENV_ONLY_CONFIG` | `false` | No | When `true`, all admin-overridable settings are locked to their environment values. The PersistentConfig DB layer is bypassed for reads and returns 403 on writes. Use for hardened production deployments where operators want to prevent runtime configuration changes via the admin UI. |
| `GEOLENS_EDITION` | (auto-detected) | No | Override the auto-detected edition. Options: `community`, `enterprise`. Without this variable, the edition is `enterprise` if any plugin extensions are loaded, otherwise `community`. Controls which feature flags and UI elements are available. |

## Enterprise Extensions

| Variable | Default | Required | Description |
|---|---|---|---|
| `GEOLENS_ENTERPRISE_PATH` | `/enterprise` | No | Path to the geolens-enterprise package inside the container. Used by entrypoint scripts to auto-install enterprise extensions on startup. Set via `docker-compose.enterprise.yml` volume mount. |

## AWS Marketplace (BYOL/AMI billing)

These variables enable AWS Marketplace metering for instances launched from the GeoLens AWS Marketplace listing. They are unset by default and only need configuration when running the marketplace AMI. Setting `AWS_MARKETPLACE_PRODUCT_CODE` triggers a one-time `RegisterUsage` call to the AWS metering API on application startup.

| Variable | Default | Required | Description |
|---|---|---|---|
| `AWS_MARKETPLACE_PRODUCT_CODE` | None | No | AWS Marketplace product code. Setting this enables hourly metering via the AWS metering API. Leave unset for non-marketplace deployments. |
| `AWS_MARKETPLACE_PUBLIC_KEY_VERSION` | `1` | No | Public key version used for `RegisterUsage` signature verification. Only relevant when `AWS_MARKETPLACE_PRODUCT_CODE` is set. |

## AI & LLM

GeoLens supports two AI subsystems: **inference** (chat, map generation, metadata drafts) and **embeddings** (semantic search). They can use different providers.

API keys are set exclusively via environment variables. All other AI settings (provider, model, base URL) can also be overridden at runtime from the admin Settings > AI tab.

### Inference (Chat / Map Generation)

| Variable | Default | Required | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | None | No | Anthropic API key. When set, Anthropic is the default inference provider. |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | No | Default Anthropic model name (admin-overridable). |
| `OPENAI_API_KEY` | None | No | OpenAI-compatible API key. Used for inference when Anthropic key is absent, and always used for embeddings. |
| `OPENAI_MODEL` | `gpt-4o` | No | Default OpenAI-compatible model name (admin-overridable). |
| `OPENAI_BASE_URL` | None | No | Custom endpoint for OpenAI-compatible providers (Ollama, Groq, Together). Leave unset for default OpenAI. |

### Embeddings (Semantic Search)

Embeddings always use the OpenAI-compatible API. Anthropic does not provide an embedding endpoint.

| Variable | Default | Required | Description |
|---|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | No | Embedding model name (admin-overridable). |
| `EMBEDDING_DIMS` | `1536` | No | Expected vector dimensions (admin-overridable, auto-detectable from admin UI). |
| `EMBEDDING_BASE_URL` | None | No | Separate endpoint for embeddings. Falls back to `OPENAI_BASE_URL` if unset. |

### Common Provider Configurations

**Anthropic inference + OpenAI embeddings** (recommended):
```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

**OpenAI for everything:**
```env
OPENAI_API_KEY=sk-...
```

**Anthropic inference + Ollama embeddings:**
```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=ollama          # any non-empty value
EMBEDDING_BASE_URL=http://ollama:11434/v1
EMBEDDING_MODEL=nomic-embed-text
```

**Ollama for everything:**
```env
OPENAI_API_KEY=ollama          # any non-empty value
OPENAI_BASE_URL=http://ollama:11434/v1
OPENAI_MODEL=llama3
EMBEDDING_MODEL=nomic-embed-text
```

## Host Port Mapping

These variables control which ports are exposed on the Docker host. They do not affect internal container communication.

| Variable | Default | Description |
|---|---|---|
| `DB_PORT` | `5432` | Host port for PostgreSQL. Set to `5434` in `.env.example` to avoid conflicts. |
| `API_PORT` | `8000` | Host port for the FastAPI backend. Set to `8001` in `.env.example`. |
| `FRONTEND_PORT` | `8080` | Host port for the frontend. |

## Internal Service Ports

These are fixed inside Docker containers and are not configurable:

| Service | Port | Protocol |
|---|---|---|
| PostgreSQL (`db`) | 5432 | TCP |
| FastAPI (`api`) | 8000 | HTTP |
| Worker (`worker`) | 8001 | HTTP (health only) |
| Titiler (`titiler`) | 8000 | HTTP |
| Frontend (`frontend`) | 5173 | HTTP (Vite dev server) |

## Docker Volumes

| Volume | Purpose | Mount Point |
|---|---|---|
| `pgdata` | PostgreSQL data persistence | `/var/lib/postgresql/data` on `db` |
| `upload_staging` | Uploaded file staging area | `/app/staging` on `api` |

## Example .env File

```env
# Database
POSTGRES_DB=geolens
POSTGRES_USER=geolens
POSTGRES_PASSWORD=secure-db-password

# Auth
JWT_SECRET_KEY=a1b2c3d4e5f6...  # Use: openssl rand -hex 32
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=secure-admin-password

# AI (optional — omit to disable AI features)
ANTHROPIC_API_KEY=sk-ant-...     # Inference (chat, map generation)
OPENAI_API_KEY=sk-...            # Embeddings (semantic search)

# Ports (non-default to avoid conflicts)
DB_PORT=5434
API_PORT=8001
FRONTEND_PORT=8080
```

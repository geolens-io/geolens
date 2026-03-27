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
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | No | JWT token lifetime in minutes |
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

## Worker

| Variable | Default | Required | Description |
|---|---|---|---|
| `WORKER_SHUTDOWN_TIMEOUT` | `30` | No | Graceful shutdown timeout for the background worker in seconds |

## Enterprise Extensions

| Variable | Default | Required | Description |
|---|---|---|---|
| `GEOLENS_ENTERPRISE_PATH` | `/enterprise` | No | Path to the geolens-enterprise package inside the container. Used by entrypoint scripts to auto-install enterprise extensions on startup. Set via `docker-compose.enterprise.yml` volume mount. |

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
| Frontend (`frontend`) | 8080 | HTTP |

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

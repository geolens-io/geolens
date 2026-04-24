# GeoLens Upgrade Guide

How to upgrade GeoLens between versions.

## Standard Upgrade

For most upgrades (patch and minor versions):

```bash
# Pull latest code
git pull

# Rebuild and restart — migrations run automatically
docker compose up -d --build
```

The `migrate` service runs Alembic migrations before the API starts, so database schema changes are applied automatically.

## Major Version Upgrades

Major versions may include breaking changes. Always read the [Changelog](../CHANGELOG.md) for the target version before upgrading.

### Pre-upgrade checklist

1. **Back up your database** before any major upgrade:

   ```bash
   docker compose exec db pg_dump -U geolens geolens > backup-$(date +%Y%m%d).sql
   ```

2. **Review the changelog** for breaking changes, removed features, or required configuration changes.

3. **Check `.env.example`** for new required environment variables. Compare with your current `.env`:

   ```bash
   diff <(grep -v '^#' .env.example | grep -v '^$' | cut -d= -f1 | sort) \
        <(grep -v '^#' .env | grep -v '^$' | cut -d= -f1 | sort)
   ```

4. **Run the upgrade:**

   ```bash
   git pull
   docker compose down
   docker compose up -d --build
   ```

5. **Verify** all services are healthy:

   ```bash
   docker compose ps
   curl http://localhost:8080/health
   ```

### Rollback

If an upgrade fails, restore from backup:

```bash
# Stop services
docker compose down

# Check out previous version
git checkout v<previous-version>

# Restore database
docker compose up -d db
docker compose exec -T db psql -U geolens -d geolens < backup-YYYYMMDD.sql

# Restart all services
docker compose up -d --build
```

## Version-Specific Notes

### Unreleased — `JWT_SECRET_KEY` minimum length

The backend now enforces a **32-character minimum** on `JWT_SECRET_KEY` at startup (HS256 requires ≥ 256 bits of entropy). A deployment with a shorter secret will fail fast on the next restart with:

```
FATAL: JWT_SECRET_KEY must be at least 32 characters. Generate one with: openssl rand -hex 32
```

**Before upgrading**, verify your secret length:

```bash
echo -n "$JWT_SECRET_KEY" | wc -c
```

If it reports fewer than 32, generate a replacement and update your `.env`:

```bash
JWT_SECRET_KEY=$(openssl rand -hex 32)
```

**Rotating the key invalidates all issued JWT tokens** — all users will be logged out and need to sign in again. Plan the rotation during a low-traffic window, or coordinate with your user base.

The fresh-install default in `.env.example` (`dev-only-change-me-in-production`, 32 chars) passes the validator unchanged, so new deployments are unaffected.

**Other env hardening in this release:**

- Secret fields (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `S3_SECRET_ACCESS_KEY`, `TILE_SIGNING_SECRET`) are now stored as Pydantic `SecretStr` internally. Values are masked in logs, `repr()`, and validation-error output. Application behavior is unchanged — this is a defense-in-depth improvement.
- `LOG_LEVEL` values are now validated against the stdlib logging set (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). A typo like `LOG_LEVEL=verbose` now fails at startup instead of crashing later.
- Two previously undocumented env vars — `ENV_ONLY_CONFIG` and `GEOLENS_EDITION` — are now documented in `.env.example`. Neither is required.
- The `backend/.env` symlink has been removed. Host-side workflows (`cd backend && uv run pytest`) now resolve `./.env` at the project root via the Settings `env_file` path. No action required unless you had local scripts depending on `backend/.env` as a literal path.
- `VITE_API_PROXY_TARGET` (docker-compose.yml frontend service) was renamed to `API_PROXY_TARGET`. The old name still works for one release via a fallback in `vite.config.ts` — update your local compose overrides when convenient.

### Unreleased — Landing page removal

The landing page has been removed. The root route (`/`) now serves the Search page directly. The `SHOW_LANDING_PAGE` environment variable has been removed from backend config and the branding API.

**What this means:**
- Existing bookmarks to `/` will show the Search page instead of the landing page.
- The `/search` route redirects to `/` — existing `/search` bookmarks continue to work.
- Remove `SHOW_LANDING_PAGE` from your `.env` if present (it is ignored but produces no error).

### About 1.0.0 (the public release)

GeoLens 1.0.0 is the first public release. Prior to 1.0.0, the project was internally versioned as 2.0 → 13.0 during pre-public development. Those legacy versions never shipped to anyone outside the project.

If you somehow have a checkout from a pre-1.0.0 internal build:

- **No data migration is required.** The 1.0.0 schema is compatible with the most recent pre-public versions; Alembic migrations apply normally on the first 1.0.0 startup.
- **The version number resets, but the codebase moves forward.** 1.0.0 is the cumulative state of all prior internal work, not a downgrade.
- **No `git checkout v13.x` rollback path exists from 1.0.0.** If you need to roll back, restore from the database backup you took before upgrading (see [Pre-upgrade checklist](#pre-upgrade-checklist)).
- **No environment variables changed at the 1.0.0 boundary.** Your existing `.env` from any pre-public build continues to work without modification.

For all subsequent upgrades, follow the standard procedure above.

### v12.x → v13.0

- **Open-core architecture**: Enterprise extension points added. No action needed for community edition users.
- **Security hardening**: CORS configuration tightened. If you use cross-origin API access, verify `CORS_ALLOWED_ORIGINS` is set in your `.env`.
- **Docker images**: Base images pinned to specific digests. Rebuild with `--build` flag.

### v10.x → v11.0

- **Performance optimizations**: New database indexes added via migration. The migration may take a few minutes on large datasets.

### v9.x → v10.0

- **Raster support**: New `titiler` service added to `docker-compose.yml`. Ensure your deployment includes this service for raster/COG tile rendering.

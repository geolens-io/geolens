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

### v12.x → v13.0

- **Open-core architecture**: Enterprise extension points added. No action needed for community edition users.
- **Security hardening**: CORS configuration tightened. If you use cross-origin API access, verify `CORS_ALLOWED_ORIGINS` is set in your `.env`.
- **Docker images**: Base images pinned to specific digests. Rebuild with `--build` flag.

### v10.x → v11.0

- **Performance optimizations**: New database indexes added via migration. The migration may take a few minutes on large datasets.

### v9.x → v10.0

- **Raster support**: New `titiler` service added to `docker-compose.yml`. Ensure your deployment includes this service for raster/COG tile rendering.

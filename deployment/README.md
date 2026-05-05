# GeoLens Deployment Packaging

This directory contains production-oriented deployment packaging. The Docker
Compose files at the repository root remain the local development path.

## Helm Chart

`deployment/helm/geolens` deploys the API, worker, frontend, and one-shot
migration job against externally managed Postgres and optional Redis.

Render locally:

```bash
helm template geolens deployment/helm/geolens \
  --set secrets.databaseUrlOverride='postgresql+asyncpg://geolens:change-me@postgres/geolens' \
  --set secrets.secretKey='change-me'
```

Install with an existing Kubernetes secret:

```bash
helm upgrade --install geolens deployment/helm/geolens \
  --set secrets.existingSecret=geolens-secrets \
  --set api.publicAppUrl=https://maps.example.com \
  --set api.publicApiUrl=https://maps.example.com/api
```

The chart does not install Postgres, S3, Redis, or enterprise dependencies.
Those remain operator-owned services or image-build inputs.

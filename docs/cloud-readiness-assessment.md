# Cloud Platform Readiness Assessment

Assessment of GeoLens deployment readiness across cloud platforms. Covers architecture fit, blockers, and recommended actions for each target.

**Date:** 2026-03-09

---

## Architecture Summary

GeoLens is a multi-service application:

| Service | Role | Key Dependencies |
|---------|------|-----------------|
| **API** | FastAPI, catalog, tiles, OGC endpoints | PostGIS, S3/local storage, Redis (optional) |
| **Worker** | Procrastinate job queue, ogr2ogr ingestion | PostGIS, shared staging dir or S3 |
| **Frontend** | React SPA served by nginx | Reverse-proxies `/api/*` to API |
| **Database** | PostgreSQL 17 + PostGIS + pgvector + pg_trgm | — |

**Cloud-ready patterns already in place:**
- All configuration via environment variables (pydantic-settings)
- Pluggable storage: `STORAGE_PROVIDER=local` or `s3`
- Pluggable cache: in-memory (default) or Redis (`REDIS_URL`)
- Managed DB support: `DATABASE_URL_OVERRIDE`, SSL modes, external pooler (`DB_USE_EXTERNAL_POOLER`)
- Health endpoints: API `/health`, Worker `/health/live` + `/health/ready`
- Prometheus metrics: API + Worker on `/metrics`
- Multi-stage Docker builds, non-root users, structured JSON logging
- Procrastinate (Postgres-based job queue) — no Celery/RabbitMQ dependency

**Primary architectural concern:** API and Worker share `UPLOAD_STAGING_DIR` (`/app/staging`) via Docker volume for file ingestion. In S3 mode, the handoff uses S3 keys instead, but some code paths (exports, non-presigned uploads) still write to the staging dir.

---

## Platform Scorecard

| Platform | Readiness | Key Blocker |
|----------|-----------|-------------|
| AWS ECS (Fargate) | **Mostly Ready** | S3 mode eliminates blockers; IAM role support for boto3 is a nice-to-have |
| Google Cloud Run | **Needs Work** | Worker doesn't fit request-driven model; no shared filesystem; limited temp disk |
| Kubernetes (any) | **Mostly Ready** | No Helm chart/manifests yet; architecture is a natural fit |
| DO Droplets | **Ready** | docker-compose works as-is |
| DO App Platform | **Needs Work** | No shared volumes; 4 GiB disk limit; requires S3 mode |
| DO Managed Kubernetes | **Mostly Ready** | No Helm chart; no ReadWriteMany PVC (requires S3 mode) |
| AWS Marketplace AMI | **Mostly Ready** | Needs Packer template, first-boot script, metering SDK |
| AWS Marketplace ECS | **Mostly Ready** | Needs CloudFormation template, task definitions, metering SDK |
| AWS Marketplace Helm | **Needs Work** | No Helm chart exists |

---

## AWS ECS (Fargate)

**What works:**
- API, Worker, Frontend map to 3 separate ECS services
- ALB health checks on `/health` (API) and `/health/ready` (Worker)
- Secrets Manager for env var injection
- RDS PostgreSQL with PostGIS + pgvector via `DATABASE_URL_OVERRIDE` + SSL
- S3 native (`STORAGE_PROVIDER=s3`, leave `S3_ENDPOINT` unset)
- ElastiCache Redis/Valkey via `REDIS_URL`
- `LOG_JSON=true` + CloudWatch Logs driver
- Prometheus `/metrics` for Container Insights or AMP
- RDS Proxy supported via `DB_USE_EXTERNAL_POOLER=true`
- Migration runs as ECS RunTask (one-shot) before deploying API/Worker

**Blockers:** None with S3 storage mode. Local storage mode requires EFS shared volume between API and Worker tasks.

**Recommended actions:**
1. Support boto3 default credential chain for IAM task roles (currently requires explicit `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY`)
2. Use `DB_USE_EXTERNAL_POOLER=true` with RDS Proxy
3. Resource sizing: API ~1 vCPU/2 GB, Worker ~2 vCPU/4 GB (GDAL processing)
4. Plan connection budget: each API instance opens up to ~25 DB connections (SQLAlchemy pool 10+5 overflow + tile pool 10)

---

## Google Cloud Run

**What works:**
- API and Frontend deploy as separate Cloud Run services
- Cloud SQL PostgreSQL via Auth Proxy
- Secret Manager for env vars
- Health startup probe on `/health`
- FastAPI async handles high concurrency well

**Blockers:**
1. **Worker service** — Procrastinate runs a long-lived LISTEN/NOTIFY loop, not request-driven. Options: Cloud Run with `--no-cpu-throttling` + min-instances=1, or deploy Worker on GKE/Compute Engine instead.
2. **No shared filesystem** — `STORAGE_PROVIDER=s3` (GCS via S3-compatible API or native GCS) is mandatory.
3. **Temp disk limits** — Cloud Run's `/tmp` is in-memory tmpfs. Large file processing (500 MB uploads) could exhaust available memory during ogr2ogr operations.

**Recommended actions:**
1. Deploy Worker on GKE or Compute Engine
2. Set min-instances=1 for API to avoid cold starts (GDAL + SQLAlchemy startup is 5-10s)
3. Use GCS S3-compatible endpoint or implement a native `GCSStorageProvider`
4. Ensure aggressive temp file cleanup for staging dir

---

## Kubernetes (GKE, EKS, AKS, DOKS)

**What works:**
- API Deployment, Worker Deployment, Frontend Deployment, Migration Job
- Liveness probes: API `/health`, Worker `/health/live`
- Readiness probes: API `/health` (returns 503 when degraded), Worker `/health/ready`
- ConfigMaps/Secrets map directly to env-var-driven config
- HPA on CPU/custom metrics for API; Worker scales on queue depth
- Standard Ingress with path-based routing
- Prometheus ServiceMonitor scraping on ports 8000 (API) and 8001 (Worker)
- Compatible with any managed PostgreSQL + S3-compatible storage

**Blockers:** None. Kubernetes is the most natural fit for this architecture.

**Needs work:**
- No Helm chart or Kustomize manifests exist
- No resource requests/limits defined
- Shared staging PVC requires ReadWriteMany (not available on all providers, e.g., DO Block Storage is RWO only) — use S3 mode instead

**Recommended actions:**
1. Create Helm chart with parameterized values for all env vars
2. Define resource requests/limits per component
3. Add PodDisruptionBudgets (minAvailable: 1 for API and Worker)
4. Use init container for migrations
5. Prefer `STORAGE_PROVIDER=s3` to avoid PVC complexity

---

## DigitalOcean

### Droplets (Docker Compose)

**Readiness: Ready** — existing `docker-compose.yml` runs directly.

- Shared `upload_staging` volume works natively
- Custom `db/Dockerfile` with PostGIS + pgvector builds and runs
- All health checks, entrypoints, and non-root user patterns work

**Sizing:**
- Minimum: 4 GB RAM / 2 vCPU ($24/mo)
- Recommended: 8 GB RAM / 4 vCPU ($48/mo) for production with concurrent ingestion
- Attach Block Storage volume for Docker data directory

**Considerations:**
- No HA — single point of failure
- Use backup service with `BACKUP_S3_ENABLED=true` to offload to Spaces
- Expose only port 8080 (nginx) externally

### App Platform

**Readiness: Needs Work**

- Supports Dockerfile-based builds and Worker components
- DO Managed PostgreSQL has PostGIS, pgvector, pg_trgm
- **No shared volumes** between components — `STORAGE_PROVIDER=s3` with Spaces is mandatory
- **4 GiB ephemeral disk limit** — large geospatial files during ogr2ogr processing could hit this
- nginx reverse proxy config needs adjustment (Docker DNS resolver `127.0.0.11` doesn't work; must use App Platform internal routing)
- Migration runs as a Job component (supported)

### Managed Kubernetes (DOKS)

**Readiness: Mostly Ready**

Same as general Kubernetes assessment, plus:
- DO Container Registry (DOCR) for images
- DO Managed PostgreSQL for database (all extensions supported)
- DO Spaces for S3-compatible storage
- DO LoadBalancer works with standard K8s Service type
- Block Storage volumes are ReadWriteOnce only — use S3 mode for shared staging

### DO Managed PostgreSQL

**Readiness: Ready**

All required extensions confirmed supported: PostGIS, pgvector (`vector`), pg_trgm.

One gap: the `geolens_reader` role creation in `init-db.sh` requires `CREATEROLE` privilege, which DO Managed PostgreSQL does not grant. Create this role manually or skip it (non-critical read-only access role).

### DO Spaces

**Readiness: Mostly Ready**

Existing `S3StorageProvider` works with Spaces. Configuration:
```
S3_ENDPOINT=https://nyc3.digitaloceanspaces.com
S3_BUCKET=geolens-uploads
S3_REGION=nyc3
```

One issue: `addressing_style: "path"` is hardcoded in `s3.py`. DO Spaces supports path-style but recommends virtual-hosted. A configurable `S3_ADDRESSING_STYLE` env var would improve forward compatibility.

---

## AWS Marketplace

### AMI Listing

**Readiness: Mostly Ready** — packages the docker-compose stack onto a single EC2 instance.

| Artifact | Status | Effort |
|----------|--------|--------|
| Packer template (AMI build pipeline) | Does not exist | Medium |
| First-boot config script (secret generation, `.env` creation) | Does not exist | Medium |
| AWS Marketplace Metering SDK (`RegisterUsage`) | Does not exist | High |
| Security scan (AMI Inspector) | Not yet run | Low |
| EULA / usage instructions | Do not exist | Low |

**Recommended pricing:** Start with BYOL or Hourly. Hourly requires a single `RegisterUsage` call in API startup, guarded by `AWS_MARKETPLACE_PRODUCT_CODE` env var. The `boto3` dependency already exists.

### Container Listing (ECS)

**Readiness: Mostly Ready**

| Artifact | Status | Effort |
|----------|--------|--------|
| Push images to Marketplace ECR | Not done | Low |
| ECS Task Definition templates | Do not exist | Medium |
| CloudFormation template (VPC, RDS, ECS, ALB, S3, IAM) | Does not exist | High |
| Metering SDK integration | Does not exist | High |

**Architecture on ECS:**
- API: Fargate service behind ALB, port 8000
- Worker: Fargate service, no LB, port 8001 for health only
- Frontend: Fargate service behind ALB, port 8080
- Migration: RunTask (one-shot) before API starts
- RDS PostgreSQL, S3 bucket, ElastiCache (optional), EFS (optional for local storage mode)

### Helm Chart Listing (EKS)

**Readiness: Needs Work** — no Helm chart exists.

Required structure:
```
helm/geolens/
  Chart.yaml
  values.yaml
  templates/
    api-deployment.yaml
    api-service.yaml
    worker-deployment.yaml
    frontend-deployment.yaml
    frontend-service.yaml
    ingress.yaml
    migration-job.yaml
    configmap.yaml
    secret.yaml
    serviceaccount.yaml
    hpa.yaml
    _helpers.tpl
```

Key `values.yaml` parameters: image registry/tag per component, database URL/SSL/pooler settings, storage provider/S3 config, auth secrets, ingress settings, resource requests/limits, replica counts.

AWS Marketplace Helm requirements: all images in Marketplace-managed ECR, image refs parameterized via `values.yaml`, chart pushed as OCI artifact.

**Effort:** ~2-3 days including testing.

### Licensing & Metering

| Model | Integration Effort | Notes |
|-------|-------------------|-------|
| BYOL | None | Simplest to list |
| Hourly/Annual | Low | Single `RegisterUsage` call at API startup |
| Usage-based (metered) | High | `MeterUsage` hourly with dimension values; dimensions locked after listing |

**Recommendation:** Start with BYOL or Hourly. Add metered pricing later as a tier upgrade.

### CloudFormation Quick Start

**Readiness: Needs Work** — no templates exist.

Required resources: VPC + subnets, RDS PostgreSQL, ECS Fargate cluster + services, ALB with HTTPS, S3 bucket, ElastiCache (optional), Secrets Manager, CloudWatch log groups, IAM roles.

Typically 1000-2000 lines of YAML. Consider AWS CDK for maintainability.

---

## Prioritized Recommendations

### Critical (before any cloud deployment)

1. **Audit S3-mode upload flow end-to-end** — Verify that when `STORAGE_PROVIDER=s3`, both API and Worker operate without a shared filesystem. Check all code paths writing to `UPLOAD_STAGING_DIR` (exports, non-presigned uploads).
2. **Temp file cleanup** — Verify staging dir files are cleaned up after ingestion success or failure. Container disk is limited and ephemeral.

### High Priority

3. **Make `S3_ADDRESSING_STYLE` configurable** — New env var in `config.py`, one line change in `s3.py`. Unblocks clean DO Spaces and other S3-compatible provider support.
4. **Support boto3 default credential chain** — Allow `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` to be unset, falling back to IAM roles. More secure for AWS deployments.
5. **Connection budget documentation** — Each API instance: up to 25 connections (SQLAlchemy 10+5 + tile pool 10). Each Worker: ~11 (SQLAlchemy 10 + Procrastinate 1). With N API replicas + M Workers: N*25 + M*11 total. Managed DBs typically cap at 80-200.
6. **Resource sizing documentation** — API: 1 vCPU/2 GB. Worker: 2 vCPU/4 GB (GDAL processing). Frontend: 0.25 vCPU/256 MB.

### Medium Priority

7. **Helm chart** — Highest-leverage single artifact; serves DOKS, EKS, GKE, and self-managed K8s.
8. **Packer AMI template** — Reuses existing docker-compose stack for AWS Marketplace AMI listing.
9. **`RegisterUsage` API call** — Minimal code change in `main.py` startup, unlocks AWS Marketplace Hourly pricing.
10. **ECS task definition templates** — Reference existing container images with proper CPU/memory, secrets, health checks.

### Lower Priority

11. CloudFormation Quick Start template
12. DO App Platform `app.yaml` spec
13. Native GCS storage provider
14. Asymmetric JWT signing (RS256) for key rotation
15. CDK alternative to raw CloudFormation

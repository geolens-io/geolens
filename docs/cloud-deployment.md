# Cloud Deployment Guide

Deploy GeoLens on managed cloud services instead of a single Docker Compose host. This guide covers AWS, Google Cloud Platform, and DigitalOcean with step-by-step instructions for each provider.

## Overview

### What Changes

A Docker Compose deployment runs all services on a single host: PostgreSQL, the API, a background worker, and the frontend. A cloud deployment replaces some of these with managed services while keeping the application containers unchanged.

```
Docker Compose (single host)          Cloud (managed services)
------------------------------         --------------------------------
PostgreSQL container        -->        Managed PostgreSQL (RDS, Cloud SQL, DO Managed DB)
Local file storage          -->        S3-compatible object storage (S3, GCS, Spaces)
In-memory cache             -->        Managed Redis/Valkey (ElastiCache, Memorystore)
API container               -->        API container on ECS, Cloud Run, or App Platform
Worker container            -->        Worker container (separate task/service)
Frontend container          -->        Frontend container (static SPA via CDN or object storage)
```

The application itself is unchanged. All cloud configuration is done through environment variables. See [Configuration Reference](./configuration-reference.md) for the complete variable list.

For the Docker Compose baseline, see the [Install Guide](./install-guide.md).

## Prerequisites (All Providers)

Before deploying on any cloud provider, complete these steps.

### PostGIS Extension

GeoLens requires PostgreSQL 15+ (tested with 17) with PostGIS 3.x. All three providers support PostGIS on their managed PostgreSQL offerings, but it must be explicitly enabled.

### Database Initialization SQL

The Docker Compose setup runs `scripts/init-db.sh` automatically. On managed databases, you must run the equivalent SQL manually via `psql` or a database console.

Connect to your managed database and run:

```sql
-- Required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Required schemas
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS data;

-- Read-only role for tile queries
CREATE ROLE geolens_reader NOLOGIN;
GRANT USAGE ON SCHEMA data TO geolens_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader;
```

### S3 CORS Policy for Presigned Uploads

GeoLens uses presigned URLs for browser-based file uploads directly to your storage bucket. The bucket must allow cross-origin requests. Apply this CORS policy (adjust `AllowedOrigins` to your domain):

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["https://your-domain.com"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3600
    }
  ]
}
```

For development or testing, you can temporarily use `["*"]` for `AllowedOrigins`, but restrict this in production.

### SSL Certificates

All managed database providers support (and typically require) SSL connections. GeoLens supports SSL through two environment variables:

- `DATABASE_SSL_MODE` -- set to `require` (most providers) or `verify-full` (GCP with CA cert)
- `DATABASE_SSL_CA_CERT` -- path to CA certificate file (required for `verify-full`)

### Alembic Migrations

Database schema migrations run automatically when the API container starts. After pointing the API at your managed database, simply start the container and Alembic will apply any pending migrations.

---

## AWS (RDS + S3 + ElastiCache)

### Database: Amazon RDS for PostgreSQL

1. **Create an RDS instance** with PostgreSQL 15+ (tested with 17) engine.

2. **Enable PostGIS.** PostGIS is included in the default RDS parameter group for PostgreSQL. After the instance is available, connect via `psql` and run:

   ```bash
   psql -h geolens-db.abc123.us-east-1.rds.amazonaws.com -U geolens -d geolens
   ```

3. **Run the init SQL** from the [Prerequisites](#database-initialization-sql) section. RDS does not support creating roles from the AWS console -- you must use `psql`.

4. **Verify extensions:**

   ```sql
   SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis', 'pg_trgm');
   ```

### Storage: Amazon S3

1. **Create an S3 bucket:**

   ```bash
   aws s3 mb s3://geolens-uploads --region us-east-1
   ```

2. **Configure CORS** on the bucket:

   ```bash
   aws s3api put-bucket-cors --bucket geolens-uploads --cors-configuration '{
     "CORSRules": [
       {
         "AllowedOrigins": ["https://your-domain.com"],
         "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
         "AllowedHeaders": ["*"],
         "ExposeHeaders": ["ETag"],
         "MaxAgeSeconds": 3600
       }
     ]
   }'
   ```

3. **Create an IAM user** with programmatic access and attach a policy with these permissions:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:GetObject",
           "s3:PutObject",
           "s3:DeleteObject",
           "s3:ListBucket"
         ],
         "Resource": [
           "arn:aws:s3:::geolens-uploads",
           "arn:aws:s3:::geolens-uploads/*"
         ]
       }
     ]
   }
   ```

4. **Note:** Leave `S3_ENDPOINT` unset for native AWS S3. The SDK uses the default S3 endpoint automatically.

### Cache (Optional): Amazon ElastiCache

For multi-instance deployments, create an ElastiCache Redis or Valkey cluster for cross-instance cache consistency.

1. **Create a cluster** in the same VPC as your application. A single-node `cache.t3.micro` is sufficient for most workloads.

2. **Security group:** Allow inbound TCP port 6379 from your application security group.

Single-instance deployments can skip this. GeoLens defaults to in-memory caching when `REDIS_URL` is not set.

### Container Deployment

Run GeoLens containers on **ECS Fargate** or **EC2 with Docker Compose**:

- **API** serves the catalog, tile gateway, and feature endpoints.
- **Worker** runs background ingestion tasks (same image, different entrypoint).
- **Frontend** serves the static SPA (can also be hosted on S3/CloudFront).

### Networking

See [AWS Security Groups](./aws-security-groups.md) for security group configuration.

For HTTPS:

1. Create an ACM certificate for your domain.
2. Create an ALB with an HTTPS listener using the ACM certificate.
3. Route ALB traffic to the `frontend` container on port 5173 (or to the `api` container on port 8000 if your frontend is hosted separately on S3/CloudFront).
4. Restrict the instance/task security group to accept the target port only from the ALB security group.

### Complete `.env` Example (AWS)

```env
# --- Managed Database (Amazon RDS for PostgreSQL) ---
DATABASE_URL_OVERRIDE=postgresql://geolens:MySecurePass@geolens-db.abc123.us-east-1.rds.amazonaws.com:5432/geolens
DATABASE_SSL_MODE=require
# DATABASE_POOL_PRE_PING defaults to true since 1.0.0; no need to set explicitly.

# --- Storage (Amazon S3) ---
STORAGE_PROVIDER=s3
S3_BUCKET=geolens-uploads
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
S3_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
# S3_ENDPOINT is intentionally unset for native AWS S3

# --- Cache (Amazon ElastiCache) ---
REDIS_URL=redis://geolens-cache.abc123.0001.use1.cache.amazonaws.com:6379/0

# --- Application ---
PUBLIC_APP_URL=https://geolens.example.com
PUBLIC_API_URL=https://geolens.example.com/api
JWT_SECRET_KEY=<openssl rand -hex 32>
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=<strong-password>
LOG_JSON=true
```

---

## Google Cloud Platform (Cloud SQL + GCS + Memorystore)

### Database: Cloud SQL for PostgreSQL

1. **Create a Cloud SQL instance** with PostgreSQL 15+ (tested with 17) and the `postgis` database flag enabled.

   ```bash
   gcloud sql instances create geolens-db \
     --database-version=POSTGRES_15 \
     --tier=db-custom-2-4096 \
     --region=us-central1 \
     --database-flags=cloudsql.enable_pgaudit=off
   ```

2. **Create the database and user:**

   ```bash
   gcloud sql databases create geolens --instance=geolens-db
   gcloud sql users create geolens --instance=geolens-db --password=<password>
   ```

3. **Connect** via Cloud SQL Auth Proxy or direct IP:

   ```bash
   # Using Cloud SQL Auth Proxy (recommended)
   cloud-sql-proxy geolens-project:us-central1:geolens-db &
   psql -h 127.0.0.1 -U geolens -d geolens
   ```

   Or allow a direct IP connection and connect via the instance's public/private IP.

4. **Run the init SQL** from the [Prerequisites](#database-initialization-sql) section.

5. **SSL configuration.** For `verify-full` mode, download the server CA certificate:

   ```bash
   gcloud sql ssl server-ca-certs list --instance=geolens-db --format="value(cert)" > server-ca.pem
   ```

   Mount this file into your container and set `DATABASE_SSL_CA_CERT=/certs/server-ca.pem`.

### Storage: Google Cloud Storage (S3-Compatible)

GeoLens connects to GCS using S3-compatible access via HMAC keys.

1. **Create a bucket:**

   ```bash
   gcloud storage buckets create gs://geolens-uploads --location=us-central1
   ```

2. **Generate HMAC keys** for S3-compatible access:

   ```bash
   gcloud storage hmac create your-service-account@project.iam.gserviceaccount.com
   ```

   This returns an `accessId` and `secret`. Use these as `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`.

3. **Configure CORS:**

   Create a `cors.json` file:

   ```json
   [
     {
       "origin": ["https://your-domain.com"],
       "method": ["GET", "PUT", "POST", "DELETE"],
       "responseHeader": ["ETag"],
       "maxAgeSeconds": 3600
     }
   ]
   ```

   Apply it:

   ```bash
   gcloud storage buckets update gs://geolens-uploads --cors-file=cors.json
   ```

4. **Set the S3 endpoint** to `https://storage.googleapis.com` and **region** to `auto`.

**Note:** GCS S3-compatibility has been verified for standard operations. For large file uploads using multipart (files over 10 MB), test your specific workflow. If multipart issues arise, consider using smaller upload chunks or native GCS APIs as a future enhancement.

### Cache (Optional): Memorystore for Redis

1. **Create a Memorystore instance:**

   ```bash
   gcloud redis instances create geolens-cache \
     --size=1 \
     --region=us-central1 \
     --redis-version=redis_7_0
   ```

2. **Get the connection IP:**

   ```bash
   gcloud redis instances describe geolens-cache --region=us-central1 --format="value(host)"
   ```

3. Set `REDIS_URL=redis://<memorystore-ip>:6379/0`.

Memorystore instances are only accessible from within the same VPC. Ensure your application runs in the same network.

### Container Deployment

Run GeoLens on **Cloud Run** or **Compute Engine (GCE) with Docker Compose**:

- **Cloud Run:** Deploy the API and Worker as separate Cloud Run services. Connect to Cloud SQL via the built-in Cloud SQL connector or Cloud SQL Auth Proxy sidecar.
- **GCE:** Use Docker Compose on a VM instance, similar to the local setup but with managed database and storage env vars.

### HTTPS / TLS Termination

GeoLens does not include a TLS terminator. Terminate HTTPS at the edge using one of:

- **Cloud Load Balancing (HTTPS LB)** with a Google-managed certificate. Point the LB at your Cloud Run service URL or GCE instance group. Cloud Run services already terminate HTTPS by default at `*.run.app` URLs.
- **Cloud Run custom domain mapping** — bind your domain to a Cloud Run service and Cloud Run will provision and renew the certificate automatically.
- **Caddy or Traefik** running on the same GCE instance as Docker Compose, with automatic Let's Encrypt issuance.

After terminating TLS, set `PUBLIC_APP_URL=https://your-domain.com` and `PUBLIC_API_URL=https://your-domain.com/api` so OGC self-links and OAuth redirects use the public HTTPS URL.

### Complete `.env` Example (GCP)

```env
# --- Managed Database (Cloud SQL for PostgreSQL) ---
DATABASE_URL_OVERRIDE=postgresql://geolens:MySecurePass@10.20.30.40:5432/geolens
DATABASE_SSL_MODE=verify-full
DATABASE_SSL_CA_CERT=/certs/server-ca.pem
# DATABASE_POOL_PRE_PING defaults to true since 1.0.0; no need to set explicitly.

# --- Storage (GCS via S3-Compatible API) ---
STORAGE_PROVIDER=s3
S3_ENDPOINT=https://storage.googleapis.com
S3_BUCKET=geolens-uploads
S3_ACCESS_KEY_ID=GOOGTS7C7FUP3EXAMPLE
S3_SECRET_ACCESS_KEY=bGoa+V7g/yqDXvKRqq+JTFn4uQZbPiQJoEXAMPLE
S3_REGION=auto

# --- Cache (Memorystore for Redis) ---
REDIS_URL=redis://10.0.0.5:6379/0

# --- Application ---
PUBLIC_APP_URL=https://geolens.example.com
PUBLIC_API_URL=https://geolens.example.com/api
JWT_SECRET_KEY=<openssl rand -hex 32>
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=<strong-password>
LOG_JSON=true
```

---

## DigitalOcean (Managed DB + Spaces)

### Database: DigitalOcean Managed PostgreSQL

1. **Create a Managed Database cluster** with PostgreSQL 15+ (tested with 17).

   ```bash
   doctl databases create geolens-db \
     --engine pg \
     --version 15 \
     --region nyc1 \
     --size db-s-1vcpu-1gb \
     --num-nodes 1
   ```

2. **Add Trusted Sources.** DigitalOcean managed databases reject all connections by default. Add your application's IP address, Droplet, or App Platform resource as a trusted source in the database console or via CLI:

   ```bash
   doctl databases firewalls append <db-id> --rule ip_addr:<your-app-ip>
   ```

3. **Enable PostGIS.** Connect via `psql` using the connection string from the database console and run:

   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   ```

4. **Run the remaining init SQL** from the [Prerequisites](#database-initialization-sql) section (schemas, roles, grants).

5. **Connection details:**
   - Default port is **25060** (not 5432)
   - SSL is required -- append `?sslmode=require` to your connection string
   - Get the connection string from the database console or:

   ```bash
   doctl databases connection <db-id> --format URI
   ```

### Storage: DigitalOcean Spaces

1. **Create a Space:**

   ```bash
   doctl spaces create geolens-uploads --region nyc3
   ```

   Or create via the DigitalOcean console.

2. **Generate an API key.** In the DigitalOcean console, go to API > Spaces Keys and generate a new key pair. Use the Key as `S3_ACCESS_KEY_ID` and the Secret as `S3_SECRET_ACCESS_KEY`.

3. **Configure CORS** on the Space. Use the S3-compatible API:

   ```bash
   aws s3api put-bucket-cors \
     --endpoint-url https://nyc3.digitaloceanspaces.com \
     --bucket geolens-uploads \
     --cors-configuration '{
       "CORSRules": [
         {
           "AllowedOrigins": ["https://your-domain.com"],
           "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
           "AllowedHeaders": ["*"],
           "ExposeHeaders": ["ETag"],
           "MaxAgeSeconds": 3600
         }
       ]
     }'
   ```

4. **Set the S3 endpoint** to `https://<region>.digitaloceanspaces.com` (e.g., `https://nyc3.digitaloceanspaces.com`).

### Cache

Options for caching on DigitalOcean:

- **DigitalOcean Managed Redis** -- available in select regions. Create via the console and use the provided connection URL.
- **Self-hosted Valkey** on a Droplet -- install Valkey and point `REDIS_URL` at it. GeoLens uses redis-py which is compatible with both Redis and Valkey.
- **Skip** -- for single-instance deployments, the default in-memory cache works without any external service.

### Container Deployment

Run GeoLens on **App Platform** or a **Droplet with Docker Compose**:

- **App Platform:** Deploy the API and Worker as separate services. Set environment variables in the app spec.
- **Droplet:** SSH into the Droplet, clone the repo, and run `docker compose up -d` with cloud env vars -- same as local but pointing at managed services.

### HTTPS / TLS Termination

DigitalOcean offers two simple paths to HTTPS:

- **App Platform** — automatically provisions and renews a Let's Encrypt certificate when you bind a custom domain to your app. No manual certificate management required.
- **Droplet + Caddy or Traefik** — install Caddy or Traefik on the Droplet alongside Docker Compose; both automatically request and renew Let's Encrypt certificates and proxy traffic to the `frontend` container on port 5173.

After enabling HTTPS, set `PUBLIC_APP_URL=https://your-domain.com` and `PUBLIC_API_URL=https://your-domain.com/api`.

### Complete `.env` Example (DigitalOcean)

```env
# --- Managed Database (DigitalOcean Managed PostgreSQL) ---
DATABASE_URL_OVERRIDE=postgresql://geolens:MySecurePass@geolens-db-do-user-123456-0.db.ondigitalocean.com:25060/geolens?sslmode=require
DATABASE_SSL_MODE=require
# DATABASE_POOL_PRE_PING defaults to true since 1.0.0; no need to set explicitly.

# --- Storage (DigitalOcean Spaces) ---
STORAGE_PROVIDER=s3
S3_ENDPOINT=https://nyc3.digitaloceanspaces.com
S3_BUCKET=geolens-uploads
S3_ACCESS_KEY_ID=DO00EXAMPLE1234567890
S3_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz1234567890EXAMPLE
S3_REGION=nyc3

# --- Cache (optional -- uncomment if using managed Redis) ---
# REDIS_URL=redis://geolens-cache-do-user-123456-0.db.ondigitalocean.com:25061/0

# --- Application ---
PUBLIC_APP_URL=https://geolens.example.com
PUBLIC_API_URL=https://geolens.example.com/api
JWT_SECRET_KEY=<openssl rand -hex 32>
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=<strong-password>
LOG_JSON=true
```

---

## Migration Checklist

Follow these steps to migrate from a Docker Compose deployment to cloud managed services.

1. **Provision managed database.** Create a PostgreSQL 15+ (tested with 17) instance with PostGIS on your cloud provider (RDS, Cloud SQL, or Managed DB).

2. **Run init SQL.** Connect to the managed database via `psql` and run the initialization SQL from the [Prerequisites](#database-initialization-sql) section (extensions, schemas, roles).

3. **Migrate data.** Export from your Docker Compose database and import to the managed database:

   ```bash
   # Export from Docker Compose DB
   docker compose exec db pg_dump -U geolens -Fc geolens > geolens_backup.dump

   # Import to managed database
   pg_restore -h <managed-db-host> -U geolens -d geolens geolens_backup.dump
   ```

4. **Run Alembic migrations.** Point the API container at the new database and start it. Migrations run automatically on startup -- no manual Alembic commands needed.

5. **Provision object storage.** Create an S3, GCS, or Spaces bucket and configure the CORS policy from the [Prerequisites](#s3-cors-policy-for-presigned-uploads) section.

6. **Provision cache (optional).** Create a Redis or Valkey instance if running multiple application instances. Skip for single-instance deployments.

7. **Update environment variables.** Replace Docker Compose defaults with cloud values. See the provider-specific `.env` examples above. Key variables to set:
   - `DATABASE_URL_OVERRIDE` -- managed database connection string
   - `DATABASE_SSL_MODE` -- typically `require`
   - `STORAGE_PROVIDER=s3` with `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
   - `S3_ENDPOINT` -- set for GCS and Spaces; leave unset for AWS S3
   - `REDIS_URL` -- if using managed cache

8. **Deploy containers.** Start the API, Worker, and Frontend containers on your cloud platform (ECS, Cloud Run, App Platform, or Docker Compose on a VM).

9. **Verify health.** Confirm all providers are connected:

   ```bash
   curl https://your-domain.com/health
   ```

   The response should show all providers reporting ok.

10. **Update `PUBLIC_APP_URL` and `PUBLIC_API_URL`.** Use the public frontend URL for `PUBLIC_APP_URL` (for example `https://geolens.example.com`) and the externally reachable API base for `PUBLIC_API_URL` (for example `https://geolens.example.com/api`). These drive browser redirects, OGC self-links, and generated distribution URLs.

---

## Monitoring & Observability

GeoLens exposes Prometheus-format metrics from the API and worker containers. There is no built-in dashboard — point your existing observability stack at the metrics endpoint, or run a lightweight Prometheus + Grafana pair next to the application.

### Metrics endpoint

The API exposes `/metrics` in Prometheus text format on the same port as the rest of the API. The endpoint is unauthenticated and excluded from the OpenAPI schema. Useful series include:

| Metric | Type | Description |
|---|---|---|
| `http_requests_total{handler,method,status}` | counter | All HTTP requests handled by FastAPI (from `prometheus_fastapi_instrumentator`) |
| `http_request_duration_seconds{handler,method}` | histogram | Request latency by route handler |
| `http_requests_inprogress{handler,method}` | gauge | Currently in-flight requests |
| `geolens_db_pool_checkedout` | gauge | Connections checked out from the SQLAlchemy pool |
| `geolens_db_pool_checkedin` | gauge | Idle connections in the pool |
| `geolens_db_pool_overflow` | gauge | Overflow connections currently open |
| `geolens_db_pool_size` | gauge | Configured pool size |
| `geolens_jobs_queue_depth{queue}` | gauge | Procrastinate jobs in `todo` state by queue |
| `geolens_jobs_active{queue}` | gauge | Procrastinate jobs in `doing` state by queue |
| `geolens_jobs_completed_total{queue}` | counter | Successfully completed Procrastinate jobs |
| `geolens_jobs_failed_total{queue}` | counter | Failed Procrastinate jobs |

### Scraping with Prometheus

Add a scrape target to your Prometheus configuration:

```yaml
scrape_configs:
  - job_name: geolens
    metrics_path: /metrics
    static_configs:
      - targets: ['geolens-api.internal:8000']
```

For Cloud Run, use the [Managed Service for Prometheus](https://cloud.google.com/managed-prometheus). For ECS, use the [AWS Distro for OpenTelemetry collector](https://aws-otel.github.io/) sidecar.

### Recommended dashboards

A starter Grafana dashboard JSON is intentionally not bundled — your existing dashboards for FastAPI/Uvicorn services will work as-is once the scrape target is added. At a minimum, panels should cover:

- Request rate, error rate (5xx percentage), and p95 latency per endpoint
- DB connection pool exhaustion (`checked_out` ≥ `pool_size`)
- Tile cache hit ratio (alert below 50% sustained)
- Ingestion job failure rate

### Logs

The API and worker write structured logs to stdout. Set `LOG_JSON=true` in production to emit one JSON object per line, which any log aggregator (CloudWatch Logs, Cloud Logging, Loki, Datadog) can ingest without parsing rules.

### Health checks

Use `GET /health` for liveness/readiness probes:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /health
    port: 8000
  periodSeconds: 10
```

The endpoint returns 200 with `{"status": "ok"}` when the database is reachable.

---

## Troubleshooting

### PostGIS extension not available

**Error:** Alembic migration fails with `type "geometry" does not exist`.

**Cause:** PostGIS extension was not created on the managed database.

**Fix:** Connect via `psql` and run:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

On AWS RDS, PostGIS is available by default in the PostgreSQL engine. On GCP and DigitalOcean, it must be explicitly created.

### Missing pg_trgm extension

**Error:** Search queries fail with errors about missing operator classes.

**Cause:** The `pg_trgm` extension was not created during database setup.

**Fix:**

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### S3 CORS errors on presigned uploads

**Error:** Browser console shows `No 'Access-Control-Allow-Origin' header` errors when uploading files.

**Cause:** The storage bucket does not have a CORS policy allowing cross-origin requests from your domain.

**Fix:** Apply the CORS policy from the [Prerequisites](#s3-cors-policy-for-presigned-uploads) section. Make sure `AllowedOrigins` includes your application's domain.

### DATABASE_URL_OVERRIDE format issues

**Error:** Application fails to start with connection errors or `could not translate host name`.

**Cause:** The connection URL format is incorrect for the provider.

**Fix:** GeoLens automatically converts `postgresql://` to `postgresql+asyncpg://` and strips `sslmode` from the URL query string (it uses `DATABASE_SSL_MODE` instead). Use a standard `postgresql://` URL:

```
DATABASE_URL_OVERRIDE=postgresql://user:password@host:port/dbname
```

Do not include `+asyncpg` in the URL -- the application adds it automatically.

### GCS S3-compatibility endpoint

**Error:** Storage operations fail with `403 Forbidden` or `invalid signature` errors when using GCS.

**Cause:** GCS requires the S3-compatible endpoint and HMAC credentials, not the default GCS API.

**Fix:** Set `S3_ENDPOINT=https://storage.googleapis.com`, `S3_REGION=auto`, and use HMAC key credentials (not standard GCP service account keys).

### DigitalOcean trusted sources

**Error:** Connection to managed database times out or is refused.

**Cause:** DigitalOcean managed databases require explicitly adding trusted sources (IP addresses or resources) before accepting connections.

**Fix:** Add your application's IP address or DigitalOcean resource as a trusted source in the database firewall settings:

```bash
doctl databases firewalls append <db-id> --rule ip_addr:<your-app-ip>
```

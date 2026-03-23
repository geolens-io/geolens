# Resource Sizing

CPU and memory recommendations per service for each deployment target. All K8s values match the defaults in the [geolens-helm](https://github.com/geolens-io/geolens-helm) chart's `values.yaml`.

## Kubernetes

Resource requests and limits per service. Scale by adding replicas, not by increasing per-pod resources.

### Small (Development)

| Service | Replicas | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|----------|-------------|-----------|----------------|--------------|
| API | 1 | 500m | 1000m | 1 Gi | 2 Gi |
| Worker | 1 | 1000m | 2000m | 2 Gi | 4 Gi |
| Frontend | 1 | 125m | 250m | 128 Mi | 256 Mi |

**Database:** db.t3.micro (RDS) or DO 1 GB managed PostgreSQL

### Medium (Production)

| Service | Replicas | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|----------|-------------|-----------|----------------|--------------|
| API | 3 | 500m | 1000m | 1 Gi | 2 Gi |
| Worker | 1 | 1000m | 2000m | 2 Gi | 4 Gi |
| Frontend | 1 | 125m | 250m | 128 Mi | 256 Mi |

**Database:** db.t3.medium (RDS) or DO 4 GB managed PostgreSQL

### Large (High Traffic)

| Service | Replicas | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|----------|-------------|-----------|----------------|--------------|
| API | 5 | 500m | 1000m | 1 Gi | 2 Gi |
| Worker | 2 | 1000m | 2000m | 2 Gi | 4 Gi |
| Frontend | 1 | 125m | 250m | 128 Mi | 256 Mi |

**Database:** db.t3.large (RDS) or DO 8 GB managed PostgreSQL

> Enable HPA (`api.autoscaling.enabled: true`) to scale API replicas automatically based on CPU utilization. See `values.yaml` for configuration.

## AMI (Single-Host EC2)

All services run via Docker Compose on a single instance. Choose based on dataset volume and ingestion frequency.

| Tier | Instance Type | vCPU | RAM | Use Case |
|------|---------------|------|-----|----------|
| Small | t3.medium | 2 | 4 GB | Minimum for Docker Compose (API + Worker + DB) |
| Medium | t3.large | 2 | 8 GB | Production with PostGIS query headroom |
| Large | t3.xlarge | 4 | 16 GB | Heavy ingestion, large datasets |

**Database:** Embedded PostgreSQL on the same host, or external RDS for durability.

## Droplet (Single-Host DigitalOcean)

Same as AMI -- all services on one host via Docker Compose.

| Tier | Droplet Size | vCPU | RAM | Use Case |
|------|-------------|------|-----|----------|
| Small | s-2vcpu-4gb | 2 | 4 GB | Minimum for Docker Compose |
| Medium | s-4vcpu-8gb | 4 | 8 GB | Production workloads |
| Large | s-8vcpu-16gb | 8 | 16 GB | Heavy ingestion, large datasets |

**Database:** Embedded PostgreSQL on the same host, or DO Managed PostgreSQL for durability.

## Storage

All tiers require persistent storage for uploaded datasets and PostGIS data. Plan for:

- **OS + Docker images:** ~10 GB
- **PostGIS data directory:** Size depends on dataset volume (start with 50 GB, expand as needed)
- **Upload staging:** Matches your largest expected upload file

For cloud-specific deployment instructions, see [Cloud Deployment](./cloud-deployment.md).

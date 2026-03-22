# Connection Budget

GeoLens uses SQLAlchemy async connection pooling. Each API or Worker replica maintains its own connection pool to the database.

## Per-Replica Math

From `backend/app/database.py`:

```python
pool_size = 10       # baseline connections kept open
max_overflow = 5     # additional connections under load
# Total: 15 max connections per replica
```

Each replica can hold up to **15** database connections at peak load.

## Quick Reference

| Topology | API Replicas | Worker Replicas | Max DB Connections |
|----------|-------------|-----------------|-------------------|
| Dev (1+1) | 1 | 1 | 30 |
| Production (3+1) | 3 | 1 | 60 |
| High traffic (5+2) | 5 | 2 | 105 |

## RDS Instance Recommendations

RDS PostgreSQL `max_connections` by instance type:

| Instance | RAM | max_connections | Fits Topology |
|----------|-----|----------------|---------------|
| db.t3.micro | 1 GB | ~112 | Dev (30) |
| db.t3.small | 2 GB | ~225 | Production (60), High traffic (105) |
| db.t3.medium | 4 GB | ~450 | All with headroom |
| db.t3.large | 8 GB | ~900 | All with headroom |
| db.r6g.large | 16 GB | ~1,700 | All with headroom |

## DigitalOcean Managed PostgreSQL

| Plan (RAM) | Available Connections | Fits Topology |
|------------|----------------------|---------------|
| 1 GB | 22 | Too tight for Dev (30) |
| 2 GB | 47 | Dev (30) |
| 4 GB | 97 | Production (60), High traffic (105) |
| 8 GB | 197 | All with headroom |
| 16 GB | 397 | All with headroom |

> **Note:** The DO 1 GB plan only allows 22 connections, which is below the 30 needed for a minimal 1+1 topology. Use 2 GB minimum.

## Minimum Database by Topology

| Topology | Min RDS | Min DO |
|----------|---------|--------|
| Dev (1+1) | db.t3.micro (112) | 2 GB (47) |
| Production (3+1) | db.t3.small (225) | 4 GB (97) |
| High traffic (5+2) | db.t3.small (225) | 4 GB (97) |

## External Pooler Mode

When `DB_USE_EXTERNAL_POOLER=true`, SQLAlchemy switches to `NullPool` (no connection pooling). In this mode the connection budget is managed by your external pooler (PgBouncer, RDS Proxy, etc.) instead of SQLAlchemy, and the per-replica math above does not apply.

See [Configuration Reference](./configuration-reference.md) for all database-related environment variables.

# GeoLens

**AI-powered spatial data catalog with a built-in map builder.**

Upload your GIS data, search and preview it instantly, build styled interactive maps, and share or export — all from a single Docker Compose stack. Optional AI features let you chat with your maps, generate metadata, and search semantically.

[![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](LICENSE)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-ready-blue?logo=docker)](docker-compose.yml)
[![GitHub last commit](https://img.shields.io/github/last-commit/Carto-Concepts/geolens)](https://github.com/Carto-Concepts/geolens/commits/main)

<p align="center">
  <img src="docs/images/geolens-hero.png" alt="GeoLens — dataset detail with interactive map preview" width="900">
</p>

<p align="center">
  <img src="docs/images/geolens-catalog.png" alt="GeoLens — searchable data catalog with filters" width="900">
</p>

### Why GeoLens?

Most open-source GIS catalogs (GeoServer, GeoNode) are heavyweight Java stacks designed for enterprise IT teams. GeoLens is a lightweight Python/React stack that runs in a single `docker compose up` and gives you a modern catalog with a visual map builder and optional AI features — chat-driven map editing, semantic search, and automated metadata — out of the box.

## Features

| | |
|---|---|
| **Map Builder** | Create multi-layer interactive maps with custom styling, filters, and labels |
| **AI Chat** | Talk to your map — style layers, filter data, and run spatial queries in natural language (Claude or OpenAI) |
| **Semantic Search** | Find datasets by meaning, not just keywords, powered by pgvector embeddings |
| **AI Metadata** | One-click AI-generated summaries, keywords, lineage, and quality statements for any dataset |
| **Search & Discovery** | Full-text search, spatial/bbox filtering, type facets, keyword tags, and collection browsing |
| **Vector & Raster** | Upload Shapefiles, GeoJSON, GeoPackage, CSV, GeoTIFF, COG, and VRT — served as vector tiles (ST_AsMVT) or raster tiles (Titiler) |
| **Export** | Download in GeoJSON, Shapefile, GeoPackage, CSV, or KML |
| **Sharing & Embeds** | Public share links and embeddable map iframes with token-based access control |
| **OGC API** | Standards-compliant Features and Tiles endpoints |
| **Admin Panel** | User management, roles, audit logging, AI provider configuration |
| **i18n** | English, Spanish, French, German |
| **Auth** | JWT + API key authentication for UI and programmatic access |

## Quick Start

**Prerequisites:** Docker Engine 24+ and Docker Compose v2.

```bash
git clone https://github.com/Carto-Concepts/geolens.git
cd geolens
docker compose up -d
```

Open `http://localhost:8080` — log in with `admin` / `admin` and change the password.

### Seed with sample data

Populate your catalog with 130 [Natural Earth](https://www.naturalearthdata.com/) vector datasets in one command:

```bash
pip install httpx
python scripts/seed-natural-earth.py --api-key admin
```

The script downloads, ingests, and organizes datasets into collections automatically. Re-runs are idempotent.

## Architecture

| Component | Technology |
| --- | --- |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Frontend | React 19, Vite, TanStack Query, MapLibre GL |
| Database | PostgreSQL + PostGIS + pgvector |
| Raster Tiles | Titiler |
| Object Storage | S3-compatible (MinIO for local dev) |
| Cache | Valkey (Redis-compatible) |
| Reverse Proxy | nginx |

## Cloud Deployment

See [docs/cloud-deployment.md](docs/cloud-deployment.md) for AWS, DigitalOcean, and Kubernetes guides.

## Contributing

Contributions are welcome. Please open an issue to discuss proposed changes before submitting a pull request.

## License

GeoLens is licensed under the [Business Source License 1.1](LICENSE).

- **Free** for your organization's internal use, including commercial organizations and consultant deployments for clients.
- **Restricted** from being offered as a hosted/managed service to third parties.
- **Converts to MIT** on 2030-02-17.

See [LICENSE-FAQ.md](LICENSE-FAQ.md) for plain-English answers to common questions.

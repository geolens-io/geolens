# GeoLens

**Your team's spatial data, searchable in one place.**

Upload Shapefiles, GeoTIFFs, GeoPackages, or CSVs. GeoLens stores everything in PostGIS, indexes it with pgvector + pg_trgm for semantic and fuzzy search, and serves OGC APIs that QGIS, ArcGIS, and MapLibre clients connect to natively. Built on FastAPI and React. Deployed with one command.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC Compliant](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
git clone https://github.com/geolens-io/geolens.git && cd geolens
cp .env.example .env && docker compose up -d
# Open http://localhost:8080 — login: admin / admin
```

<p align="center">
  <img src="docs/images/geolens-map-builder.png" alt="GeoLens map builder composing multi-layer interactive maps" width="900" />
  <br />
  <em>Upload a shapefile, get a searchable, previewable, exportable dataset in minutes</em>
</p>

## Try the Themed Demo

GeoLens ships with three themed demo collections — **Planet Earth** (raster + VRT mosaics), **Global Development & People** (indicator choropleths), and **Borders, Boundaries & Contested Space** (geopolitics done carefully) — and nine signature maps that load deterministically with one command:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

After the seeder image build completes (most of the time is the GEBCO 2024 download — ~10–15 minutes on a fast connection, cached on rebuild), open http://localhost:8080 and navigate to **Maps**. The signature stories include:

- **Earth as Seen from Space** — bathymetry + topography + ice on a dark world view
- **Global Bathymetry** — GEBCO 2024 ocean floor with viridis colormap
- **Population at a Glance** — proportional-symbol populated places, sized by population
- **GDP per Capita PPP 2023** — country choropleth from World Bank Open Data
- **The World's Disputed Places** — every disputed area Natural Earth tracks
- **One Territory, Multiple Official Maps** — Kashmir as China, India, and Pakistan see it (toggle the layers!)
- **Conflict Events 2024** — UCDP Georeferenced Event Dataset, fatal events of organized violence
- **Refugees by Country of Origin 2023** — UNHCR statistics joined to country polygons

All data is bundled at image build time — **no outbound network calls at runtime**. The demo can be reset every 24 hours by the included `reset` service. To force a full reset:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml exec reset /scripts/reset-demo.sh
docker compose -f docker-compose.yml -f docker-compose.demo.yml restart seeder
```

Source attribution and licenses for every demo dataset are documented on each dataset's detail page. All bundled data is CC-BY 4.0, ODbL 1.0, or Public Domain.

## Why GeoLens?

Spatial data ends up scattered -- shapefiles on shared drives, tables in database schemas, rasters in cloud buckets, metadata in spreadsheets. Finding the right dataset means asking Slack or grepping file servers. Sharing it means exporting, emailing, and hoping the CRS matches.

GeoLens replaces that workflow:

- **One catalog** -- upload Shapefiles, GeoPackages, GeoTIFFs, or CSVs and they become searchable, previewable, and exportable in minutes
- **Works with your tools** -- OGC API Features/Records, STAC 1.1, direct tile URLs for QGIS, ArcGIS, and MapLibre
- **Semantic + spatial search** -- find datasets by meaning, not just keywords, powered by pgvector and pg_trgm full-text search
- **Built-in map builder** -- compose multi-layer maps, style them, and share via public link or embeddable iframe
- **AI-assisted (optional)** -- chat with your maps, auto-generate descriptions, search by natural language. Bring any OpenAI-compatible API key or skip it entirely

## See It in Action

Search datasets by meaning, not just keywords:

```bash
# Semantic search -- finds "hydrology" datasets even when you search "rivers"
curl 'http://localhost:8080/api/search/datasets/?q=rivers+near+mountains&limit=3' \
  -H 'Authorization: Bearer <token>' | jq '.features[].properties.title'
```

Every dataset is also a standard OGC API Features endpoint:

```bash
# GeoJSON features with bbox filter -- works in QGIS, ArcGIS, any OGC client
curl 'http://localhost:8080/api/collections/ne_10m_admin_0_countries/items?bbox=-10,35,30,60&limit=5'
```

Connect directly from QGIS: **Layer > Add WFS / OGC API Features** and point at `http://localhost:8080/api/`.

See [FEATURES.md](FEATURES.md) for a detailed feature overview.

## Features

### Map Builder and Sharing

- Multi-layer interactive maps with drag-and-drop ordering, styling, and per-layer filters
- Point, line, and polygon styling with color ramps and category breaks
- Share maps via public links or embeddable `<iframe>` snippets
- Raster (COG) and vector layers side by side

### AI-Powered (Optional)

- Chat with your maps -- ask natural-language questions, AI adds and styles layers
- Semantic vector search across metadata using pgvector with HNSW indexing
- Auto-generated dataset descriptions and tags on ingest
- Works with any OpenAI-compatible API (OpenAI, Anthropic, Ollama); fully functional without it

### Search and Discovery

- Full-text and trigram search (pg_trgm) across dataset names, descriptions, and metadata
- Spatial search with bounding box and map-drawn filters
- Faceted filtering by format, tags, collections, and record type
- Semantic search powered by pgvector (optional)
- Saved searches for repeated workflows

### Data Ingestion and Export

- **Vector:** Shapefile, GeoPackage, GeoJSON, CSV, XLSX upload and ingestion
- **Raster:** GeoTIFF and Cloud-Optimized GeoTIFF (COG) with automatic conversion
- **Mosaics:** VRT-based raster mosaics from multiple source files
- **Export:** GeoJSON, Shapefile, GeoPackage, CSV, with CRS reprojection
- Provenance tracking and metadata editing

### Standards and Interop

- OGC API - Features and OGC API - Records compliant
- STAC 1.1 catalog endpoint
- Direct tile URLs for QGIS, ArcGIS, MapLibre, and any OGC client
- API key authentication for external tool integration
- JWT + OAuth 2.0/OIDC, RBAC with per-dataset permissions

<details>
<summary>Enterprise and Security</summary>

- JWT authentication with refresh tokens
- API key management per user
- OAuth 2.0 / OIDC support (Google, Microsoft, generic providers)
- Role-based access control (RBAC) with per-dataset permissions
- Audit logging for all administrative actions
- Internationalization: English, Spanish, French, German

</details>

## Screenshots

<p align="center">
  <img src="docs/images/geolens-catalog.png" alt="GeoLens Catalog View" width="900" />
  <br />
  <em>Catalog view with search, spatial filters, and dataset cards</em>
</p>

<p align="center">
  <img src="docs/images/geolens-dataset.png" alt="GeoLens Dataset Detail" width="900" />
  <br />
  <em>Dataset detail with map preview, metadata, and attribute table</em>
</p>

## Quick Start

**Prerequisites:** Docker Engine 24+ and Docker Compose v2. Minimum host: 4 GB RAM and 10 GB free disk for the base stack and a small dataset; 8 GB+ RAM recommended for raster work or catalogs above ~100 datasets. See [Resource Sizing](docs/resource-sizing.md) for production sizing.

```bash
git clone https://github.com/geolens-io/geolens.git
cd geolens
cp .env.example .env
docker compose up -d
```

Wait about 60 seconds for services to start, then open [http://localhost:8080](http://localhost:8080). Log in with `admin` / `admin`.

Verify all services are healthy:

```bash
docker compose ps
```

For production deployment, see the [Install Guide](docs/install-guide.md). For upgrading, see the [Upgrade Guide](docs/upgrade-guide.md).

### Demo Mode

Run a pre-populated demo instance with sample Natural Earth data:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d
```

The demo overlay auto-seeds 20 representative datasets, sets them to public visibility, and resets data every 24 hours. See `.env.demo` for configuration.

### Seed Data

Populate the catalog with 130 [Natural Earth](https://www.naturalearthdata.com/) 1:10m datasets:

```bash
pip install httpx  # one-time dependency on the host
python scripts/seed-natural-earth.py --api-key admin
```

The script downloads from the [NACIS CDN](https://naciscdn.org/naturalearth/), skips duplicates on re-run, and creates two collections (Cultural 10m, Physical 10m). Use `--dry-run` to preview or `--theme cultural` to filter by theme.

## Architecture

| Component | Technology |
|-----------|-----------|
| Frontend | React 19, Vite, MapLibre GL v5, TanStack Query, Tailwind CSS |
| Backend API | FastAPI (Python), GDAL/ogr2ogr, Procrastinate (task queue) |
| Raster Tiles | Titiler (COG tile server) |
| Object Storage | MinIO (S3-compatible, local dev) or any S3 provider |
| Cache | Valkey (tile and query cache) |
| Database | PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm |
| Reverse Proxy | Nginx (production) / Vite dev proxy (development) |

## Configuration

All configuration is managed through environment variables in `.env`. See the [Configuration Reference](docs/configuration-reference.md) for the full list of options with defaults and descriptions.

## Documentation

| Guide | Description |
|-------|-------------|
| [Install Guide](docs/install-guide.md) | Step-by-step deployment with Docker Compose |
| [Upgrade Guide](docs/upgrade-guide.md) | Upgrading between versions with rollback procedures |
| [Configuration Reference](docs/configuration-reference.md) | All environment variables and their defaults |
| [Admin Guide](docs/admin-guide.md) | User management, datasets, system health |
| [Cloud Deployment](docs/cloud-deployment.md) | AWS, GCP, and DigitalOcean deployment guides |
| [Widget Development](docs/widget-development.md) | Build custom map builder widgets |
| [API Reference](#see-it-in-action) | Interactive Swagger UI at `/api/docs` when running |

## Community

- [GitHub Discussions](https://github.com/geolens-io/geolens/discussions) -- questions, ideas, show and tell
- [Contributing Guide](.github/CONTRIBUTING.md) -- development setup, code style, and PR guidelines

## License

GeoLens is licensed under the [Apache License 2.0](LICENSE).

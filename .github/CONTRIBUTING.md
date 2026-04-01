# Contributing to GeoLens

Thanks for your interest in contributing to GeoLens. This guide covers the development setup, code conventions, and pull request process.

No CLA required -- the Apache 2.0 license covers all contributions.

## Development Setup

GeoLens runs entirely in Docker -- you don't need Python, Node.js, or PostgreSQL installed locally.

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/geolens.git
cd geolens
```

### 2. Start the stack

```bash
cp .env.example .env
docker compose up -d
```

The app will be available at [http://localhost:8080](http://localhost:8080). Default credentials: `admin` / `admin`.

### 3. Verify services are running

```bash
docker compose ps
```

All services (db, migrate, api, worker, frontend, titiler) should show as healthy or exited (migrate exits after completing).

### Making changes

- **Backend (FastAPI):** Edit files under `backend/`. The API container mounts the source directory and reloads on changes.
- **Frontend (React):** Edit files under `frontend/`. Vite provides hot module replacement through the Nginx proxy.
- **Migrations:** Add new Alembic migrations under `backend/alembic/versions/`. Run with `docker compose exec api alembic upgrade head`.

### Running tests

**Backend:**

```bash
docker compose exec api pytest
docker compose exec api pytest tests/unit -v     # Unit tests only
docker compose exec api pytest tests/api -v      # API integration tests
```

**Frontend:**

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run test -- --watch  # Watch mode
```

## Code Style

Code style is enforced by linters and formatters. Run them before submitting a PR:

- **Backend:** `ruff check` and `ruff format` (configured in `pyproject.toml`)
- **Frontend:** ESLint and Prettier (configured in project root)
- **All user-facing strings** must be added to all 4 locale files (en, fr, es, de) under `frontend/src/i18n/locales/`

Check both before committing:

```bash
# Backend
docker compose exec api ruff check .
docker compose exec api ruff format --check .

# Frontend
docker compose exec frontend npx eslint src/
docker compose exec frontend npx prettier --check src/
```

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add bbox spatial filter to catalog search
fix: correct CRS reprojection for EPSG:4326 exports
docs: update install guide with MinIO configuration
test: add unit tests for tile token validation
chore: bump maplibre-gl to v5.1
refactor: extract tile URL builder into shared utility
```

Keep the subject line under 72 characters. Use the body for additional context when needed.

## Pull Requests

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes, commit with conventional commit messages.
3. Push your branch and open a pull request against `main`.
4. Fill out the PR description -- explain what changed and why.
5. Ensure CI checks pass (linting, tests, build).

If a PR template exists at `.github/PULL_REQUEST_TEMPLATE.md`, your PR description will be pre-populated with the template.

### PR guidelines

- Keep PRs focused -- one feature or fix per PR.
- Include tests for new functionality.
- Update documentation if your change affects user-facing behavior.
- Add locale strings to all 4 language files if you introduce new UI text.

## Project Structure

```
geolens/
├── backend/                    # FastAPI application
│   ├── alembic/                # Database migrations
│   ├── app/
│   │   ├── admin/              # Admin dashboard stats & management
│   │   ├── ai/                 # AI chat, metadata generation, SQL sandbox
│   │   ├── assets/             # Static asset URL helpers
│   │   ├── audit/              # Audit log (who changed what)
│   │   ├── auth/               # Authentication (JWT, OAuth, API keys)
│   │   ├── cache/              # Caching layer (memory, Redis, tile cache)
│   │   ├── collections/        # Dataset collection grouping
│   │   ├── config_ops/         # Import/export of server configuration
│   │   ├── datasets/           # Dataset CRUD, reupload, VRT, export
│   │   ├── dcat/               # DCAT metadata serialization
│   │   ├── embed_tokens/       # Secure embed/share token management
│   │   ├── embeddings/         # pgvector semantic search embeddings
│   │   ├── export/             # Data export (GeoPackage, Shapefile, etc.)
│   │   ├── extensions/         # Feature-toggle extension points
│   │   ├── features/           # GeoJSON feature read/write per dataset
│   │   ├── health/             # Health check endpoint
│   │   ├── ingest/             # File & service ingestion (ogr2ogr pipeline)
│   │   ├── jobs/               # Background job tracking
│   │   ├── layers/             # Map layer style definitions
│   │   ├── maps/               # Saved map compositions
│   │   ├── metrics/            # Prometheus metrics & connection pool stats
│   │   ├── middleware/         # CORS, logging, security, body-limit
│   │   ├── models/             # Shared SQLAlchemy base model
│   │   ├── ogc/                # OGC API - Features endpoint
│   │   ├── raster/             # Raster/COG processing and VRT mosaics
│   │   ├── records/            # Unified record discovery API
│   │   ├── runtime/            # Staging directory management
│   │   ├── sandbox/            # Safe SQL execution sandbox
│   │   ├── search/             # Catalog search & saved searches
│   │   ├── services/           # External service probing (ArcGIS, WFS)
│   │   ├── settings/           # App settings (basemaps, auth, toggles)
│   │   ├── stac/               # STAC catalog endpoint
│   │   ├── storage/            # File storage abstraction (local, S3)
│   │   ├── tiles/              # Vector tile serving & token signing
│   │   ├── utils/              # Shared geo utilities
│   │   ├── validation/         # Dataset quality & completeness checks
│   │   └── vector/             # Vector quicklook generation
│   ├── scripts/                # Backend helper scripts
│   └── tests/                  # pytest tests (unit/ and api/)
├── frontend/                   # React + Vite application
│   └── src/
│       ├── api/                # API client functions (one file per domain)
│       ├── components/
│       │   ├── admin/          # Admin dashboard & settings panels
│       │   ├── auth/           # Login/register forms
│       │   ├── builder/        # Map builder (layers, styles, filters)
│       │   ├── collections/    # Collection cards & membership
│       │   ├── create/         # Dataset creation dialog
│       │   ├── dataset/        # Dataset detail tabs & editors
│       │   ├── drawing/        # Spatial drawing tools
│       │   ├── error/          # Error boundaries & fallbacks
│       │   ├── import/         # File/service import workflow
│       │   ├── layout/         # Navbar, page chrome
│       │   ├── map/            # Shared map components (popups, basemap)
│       │   ├── map-widgets/    # Map toolbar widgets (measure, etc.)
│       │   ├── maps/           # Map list & create dialog
│       │   ├── search/         # Search bar, filters, result cards
│       │   ├── settings/       # User settings panels
│       │   ├── ui/             # Reusable primitives (shadcn/ui)
│       │   └── viewer/         # Public map viewer components
│       ├── hooks/              # React hooks (one per feature domain)
│       ├── i18n/               # i18next config & locale files (en/fr/es/de)
│       ├── lib/                # Pure utility functions & constants
│       ├── pages/              # Top-level route pages
│       │   └── admin/          # Admin sub-pages
│       ├── stores/             # Zustand stores (auth, search, drawing)
│       └── types/              # Shared TypeScript type definitions
├── docker-compose.yml          # Dev stack (db, api, worker, frontend, titiler)
├── scripts/                    # Project-level scripts (DB init, etc.)
├── e2e/                        # End-to-end tests
└── docs/                       # Documentation
```

Most backend modules follow a consistent pattern:

| File | Purpose |
|---|---|
| `router.py` | FastAPI route handlers |
| `service.py` | Business logic (called by the router) |
| `schemas.py` | Pydantic request/response models |
| `models.py` | SQLAlchemy ORM models |

## First Contribution

New to the project? Look for issues labeled **good-first-issue** in the [issue tracker](https://github.com/geolens-io/geolens/issues). These are scoped, well-described tasks suitable for getting familiar with the codebase.

If you're unsure where to start, open an issue describing what you'd like to work on and we'll point you in the right direction.

## Reporting Security Issues

If you discover a security vulnerability, please report it responsibly. **Do not open a public issue.** Instead, follow the process in our [Security Policy](SECURITY.md).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

We will acknowledge your report within 48 hours and work with you on a fix before any public disclosure.

## Questions?

Open a [discussion](https://github.com/geolens-io/geolens/discussions) or file an issue. We're happy to help.

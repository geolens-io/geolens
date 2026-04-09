# Changelog

All notable changes to GeoLens are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note on version history.** GeoLens 1.0.0 marks the first public release. Prior to 1.0.0, the project was internally versioned as 2.0 → 13.0 during pre-public development. The legacy entries below 1.0.0 are preserved for historical context only — they do not represent prior public releases. There is no migration path from any pre-1.0.0 version; 1.0.0 is the first version anyone outside the project has run.

## [Unreleased]

### Added
- Astro-based marketing site scaffold (phases 212-214)
- `seed_tiles` CLI script for pre-seeding Redis tile cache
- Public map viewer UX improvements and legend unification
- 3D data and maps support feasibility design doc

### Removed
- **SAML support has been removed.** The OAuth provider system shipped with `provider_type='saml'` accepted by the API but no working SAML login flow ever existed (only an XML metadata parser). An admin could create a SAML provider and have it appear on the login page, but clicking it produced no authentication. The dead code path has been removed across the stack:
  - `provider_type='saml'` is no longer accepted by the OAuth API; the database CHECK constraint has been tightened to `('oidc', 'google', 'microsoft')`.
  - The `oauth_providers` table loses 4 columns: `idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`. Any pre-existing SAML provider rows are deleted by the migration before the constraint tightens.
  - The `chk_users_auth_provider` constraint on `users.auth_provider` is also tightened to `('local', 'oidc', 'oauth')`.
  - The `app/auth/saml/` Python module (XML metadata parser) is removed.
  - The admin UI no longer offers SAML in the OAuth provider dropdown; the metadata-XML upload field, SP Entity ID, and ACS URL display are removed.
  - SAML i18n keys are removed from all 4 locales (en, es, de, fr).

### Changed
- Landing page removed — root route (`/`) now serves the Search page directly. The previous `/search` route is no longer used; existing bookmarks redirect to `/`.
- `SHOW_LANDING_PAGE` environment variable removed from backend config and branding API.
- Internal documentation moved to a gitignored `docs-internal/` directory; only user-facing docs remain in `docs/`.
- Connection pool pre-ping now defaults to `True` to detect broken connections in managed databases.
- Top-level `CONTRIBUTING.md` consolidated into `.github/CONTRIBUTING.md`.
- OAuth `client_id` and `client_secret` are now required fields when creating a provider (previously optional placeholders for the SAML branch).

### Fixed
- **Security:** upgraded `anthropic` from 0.86.0 to 0.88.0 to patch CVE-2026-34450 and CVE-2026-34452.
- Pydantic constraints added to user-input string fields (basemaps, OAuth, settings) to prevent oversized payloads.
- Embedding backfill now returns a structured 502 on provider failures instead of swallowing exceptions.
- Embedding stats endpoint guards against missing `record_embeddings` table during early bootstrap.
- Embedding OpenAI client uses `max_retries=2` for transient failure resilience.
- Embedding auto-detect and column rebuild log exceptions instead of swallowing them.
- OGC catch-all 500 handler returns RFC 7807 `ProblemDetail` format.
- Datasets router uses HTTP status constants and explicit return type annotations.
- Last-admin guard extracted to a shared private method to prevent admin lockout regressions.
- Settings updates batched into a single query with deferred commits for performance.
- Branding update now routes through the unified settings endpoint with type alignment.
- Admin router authorization, CBAC, and audit logging hardened (admin audit remediation).
- Builder bug-fix sweep: 68 files, 181 findings from the builder audit (filter persistence, layer styling, drag-and-drop, raster controls).
- Database tuning sweep: PostgreSQL `random_page_cost` and `jit` settings, missing foreign-key indexes added on high-traffic tables, backup service hardening.
- Test audit + post-implementation audit remediation: type safety, resilience, KISS refactors across backend.
- Themed demo seeder (Phase 218) post-implementation audit remediation:
  - Orchestrator now propagates non-zero exit codes when any fixture fails to apply, so Docker Compose correctly reports seeder failures instead of hiding them behind a successful bash exit.
  - `apply_fixture` is idempotent across re-runs: GET-by-name is checked before POST so repeated seeder runs update existing demo maps in place instead of accumulating duplicate catalog entries.
  - Seeder `run-seeder.sh` wrapper now installs a SIGTERM/SIGINT/EXIT trap that rotates the `demo-seed` API key on exit (graceful or abnormal), preventing stale keys from accumulating when the container is killed mid-run.
  - Seeder auth + API-key lifecycle extracted from embedded bash heredocs into a lint-testable `scripts/demo/lib/create_api_key.py` module.
  - Bundled demo data (GeoJSON + CSV) is gzipped after checksum validation in Stage 1 of the seeder Dockerfile and decompressed in-place at container start, shaving ~290 MB off the `/data/demo` layer. Combined with the `uv pip install --system httpx` swap (replacing apt's `python3-pip`) and other layer optimizations, the total shipped seeder image shrunk from **637 MB → 261 MB** (~376 MB total savings). Rasters left untouched because they're already DEFLATE-compressed.
  - World Bank GDP CSV is now fetched via `python3 -c "urllib.request..."` instead of curl inside the Dockerfile's data-fetcher stage. Cloudflare started JA3-fingerprinting and blocking curl on `api.worldbank.org`, returning HTTP 502 for every curl request regardless of headers or TLS version; Python's stdlib `ssl` module presents a different TLS fingerprint that Cloudflare accepts. Only the one affected RUN step was changed — all other upstream fetches (NACIS, source.coop, OpenTopography, OWID, Geofabrik, UCDP, UNHCR) still use curl and still work.
  - Seeder service in `docker-compose.demo.yml` now depends on `worker: service_healthy` in addition to `api: service_healthy`, closing a cold-start race where ingest jobs could be submitted before the Celery worker was ready.
  - `BuilderMap` mirrors the `ViewerMap` `data-tiles-loaded` DOM attribute that flips to `true` on the maplibre `idle` event, giving the Playwright demo-smoke suite a deterministic signal on both the authenticated `/maps/:id` editor path and the anonymous public viewer. Replaces 16 s of arbitrary `waitForTimeout(2_000)` across the 8 required demo maps, so the suite now completes ~17 s faster per run.

## [1.0.0] - 2026-04-01

### Added
- Heatmap visualization mode in map builder with gradient legend, opacity controls, and render mode toggle
- Widget system for map builder — measurement tool, layer legend, basemap picker as sidebar widgets
- Layer adapter infrastructure decoupling render logic from map builder core
- Search result card redesigned with 4-band layout, inline thumbnails, and auto-description
- Map thumbnails migrated from inline base64 to storage with `useMapThumbnail` hook
- Static basemap thumbnail assets replacing generated ImageMagick thumbnails
- Public maps browsing for anonymous users
- VRT mosaic creation button on bulk import review page
- Bulk dataset delete endpoint
- Audit log export endpoint (CSV and JSON)
- Config-ops validate endpoint wired into admin frontend
- Centralized query key factory for TanStack Query hooks
- Heatmap gradient legend with Low/High labels
- Anonymous public browsing support
- `language` field added to records via new Alembic migration
- Design guide token system with status-colors utility and WCAG 2.1 AA compliance

### Changed
- Squashed 12 incremental Alembic migrations into single foundational schema
- Datasets router split into sub-routers with `get_dataset_service_url` helper
- Batched collection and map lookup queries to eliminate N+1 patterns
- Filter editor rebuilt with OR combinator and raw JSON toggle for resilience
- Data-driven styling generalized to support radius and width beyond color
- Comprehensive i18n remediation — formatting standards, RTL support, Unicode handling
- Frontend state management refactored with typed search store and centralized query keys
- Widget placement API redesigned with `WidgetAnchor` and `WidgetPlacement` discriminated union
- Basemap toggle redesigned with thumbnail trigger, labeled popover, and right-opening layout

### Fixed
- ArcGIS preview fetches capped with `result_limit=5` and timeout increased to 120s to prevent 502 errors
- Basemap switching now preserves user layers; stable ref prevents `setStyle` race conditions
- Orphaned basemap layers skipped in `transformStyle` to prevent source-not-found errors
- COG download uses browser-native streaming with authenticated fetch
- Export permission check restored on COG download endpoint
- Non-spatial ArcGIS tables skip spatial post-processing
- Trailing slashes normalized across all API routes
- Collection dataset response aligned with canonical dataset response
- AI rate limiting and raster RBAC parity
- OGC/STAC/DCAT standards compliance gaps resolved
- Docker config hardened — restart policies, security headers, PostGIS image pinned to 17-3.5
- PostgreSQL tuned with `random_page_cost=1.1` and `jit=off`
- Missing foreign key indexes added on high-traffic join/cascade tables
- `BuilderMap` mousemove throttled with `requestAnimationFrame`
- Embedding client cached with LLM timeouts to prevent event loop blocking
- OOM risks fixed in S3 upload and reupload file hash
- Deprecated `HTTP_422_UNPROCESSABLE_ENTITY` references replaced
- Raster and spreadsheet types included in default allowed extensions

## [13.0] - 2026-03-27

### Added
- Open-core architecture with enterprise extension points
- Plugin entrypoint system for modular feature loading
- CI pipeline with path-filtered conditional jobs, security scanning (bandit + pip-audit), and E2E tests
- Docker image publishing to GHCR with Trivy scan gate and SBOM attestation

### Changed
- Upgraded all dependencies (backend and frontend) to latest stable versions
- Pinned Docker base images to specific digests for reproducible builds

### Fixed
- IDOR vulnerabilities in dataset and map endpoints
- CORS configuration tightened to explicit allowed origins
- Rate limiting added to authentication endpoints
- Graceful shutdown and init process in Docker containers

## [12.3] - 2026-03-21

### Added
- Keyboard-accessible map builder with full tab navigation
- Builder save/load unit and E2E tests
- Alembic migrations run automatically on API container startup

### Fixed
- Basemap E2E test selector alignment
- Missing i18n keys in builder components

## [12.2] - 2026-03-19

### Added
- No-tile badge for raster datasets without a configured tile URL
- Tile error tracking and hero state machine for raster/VRT previews

### Fixed
- Raster hero state now correctly shows no-tile badge instead of infinite spinner

## [12.1] - 2026-03-17

### Added
- Smart timestamps in audit log (relative for recent, absolute for older entries)
- Client-side search on collections browse page
- Responsive overflow tabs on dataset detail panel

### Fixed
- Login form test selector ambiguity
- Missing i18n keys for dataset card provenance fallback
- Trailing slash on collections/datasets API call causing 307 redirect

## [12.0] - 2026-03-17

### Added
- Record-first discovery architecture -- catalog now surfaces individual records, not just datasets
- Keyword facet picker integrated into filter panel
- Search ranking with faceted filtering backend
- Publish button wired to dataset status endpoint

### Changed
- Catalog search rewritten around record-level results
- Filter panel now supports keyword facets alongside existing filters

### Fixed
- Keyword URL encoding in search queries
- Missing i18n metadata keys

## [11.0] - 2026-03-16

### Added
- Performance regression test suite for 5 critical API paths
- Load test framework with tuning documentation
- Connection pool and query optimization for large catalogs

## [10.1] - 2026-03-15

### Added
- VRT-based raster mosaics from multiple source GeoTIFFs
- Sources tab on dataset detail showing VRT member files
- Delete guard UX showing dependent VRT links on 409 conflict
- VRT i18n keys for all 4 locales (en, de, es, fr)

### Fixed
- VRT regeneration banner and error display
- SQL string concatenation bugs in VRT source link queries
- AlertDialogAction auto-close behavior on 409 delete errors

## [10.0] - 2026-03-14

### Added
- Raster dataset support -- upload GeoTIFF and Cloud-Optimized GeoTIFF (COG) files
- Automatic COG conversion for non-optimized GeoTIFFs
- Raster tile serving via Titiler integration
- Raster layer controls in map builder (opacity, band selection)
- AI chat awareness of raster datasets with set_opacity action
- `layer_type` field round-trip in saved maps

### Changed
- Map builder layer item rendering now conditional on vector vs raster type
- TileToken schema extended to union of vector and raster token types

## [8.2] - 2026-03-10

### Added
- Inline-editable share link settings (title, description, allowed origins)
- PATCH endpoints for share tokens and embed tokens
- SharePanel redesigned with inline editing replacing read-only summary

## [8.0] - 2026-03-09

### Added
- Spatial intelligence -- AI can execute spatial queries and display results as ephemeral map layers
- Ephemeral result layer rendering with dismiss UI
- Backend GeoJSON extraction from spatial query results
- Semantic search powered by pgvector
- Related datasets discovery based on vector similarity
- Semantic search toggle in filter panel

### Changed
- Enterprise configuration consolidated and cleaned up
- AI prompts optimized for spatial query generation

## [7.2] - 2026-03-08

### Added
- pgvector-based semantic search across dataset metadata
- Related datasets API endpoint and frontend card
- Semantic search toggle with store and API support

## [6.2] - 2026-03-07

### Added
- OAuth 2.0 / OIDC authentication support
- Enterprise configuration management UI
- Settings tabs reorganized into sidebar sub-navigation
- Config import/export functionality

### Fixed
- File dialog double-trigger on config import
- Missing sidebar translation keys for config and permissions sections

## [6.0] - 2026-03-03

### Added
- Redis circuit breaker for cache provider resilience
- Procrastinate queue splitting with file-size-based routing
- Upload limits admin UI with database-driven enforcement
- CORS deployment documentation
- Type-safe filter specifications replacing `unknown[]` types

### Changed
- Production hardening across 9 phases (102-110)
- Abort cleanup wired into collection membership manager

## [3.0] - 2026-02-28

### Added
- Collections for organizing datasets into groups
- Batch dataset operations
- Dataset export in multiple formats (GeoJSON, Shapefile, GeoPackage, CSV)
- CRS reprojection on export

## [2.4] - 2026-02-26

### Added
- Theme support (light/dark) with system preference detection
- Admin settings API for basemaps, map defaults, and feature toggles
- Basemap utilities and theme-aware basemap selection
- Admin layout with sidebar navigation

## [2.0] - 2026-02-22

### Added
- Initial public release
- PostGIS-backed spatial data catalog
- Full-text and spatial search
- Vector file upload and ingestion (Shapefile, GeoPackage, GeoJSON, CSV)
- Interactive map preview with MapLibre GL
- OGC API - Features compliance
- JWT authentication with role-based access control
- Docker Compose deployment

[Unreleased]: https://github.com/geolens-io/geolens/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/geolens-io/geolens/releases/tag/v1.0.0
[13.0]: https://github.com/geolens-io/geolens/compare/v12.3...v13.0
[12.3]: https://github.com/geolens-io/geolens/compare/v12.2...v12.3
[12.2]: https://github.com/geolens-io/geolens/compare/v12.1...v12.2
[12.1]: https://github.com/geolens-io/geolens/compare/v12.0...v12.1
[12.0]: https://github.com/geolens-io/geolens/compare/v11.0...v12.0
[11.0]: https://github.com/geolens-io/geolens/compare/v10.1...v11.0
[10.1]: https://github.com/geolens-io/geolens/compare/v10.0...v10.1
[10.0]: https://github.com/geolens-io/geolens/compare/v8.2...v10.0
[8.2]: https://github.com/geolens-io/geolens/compare/v8.0...v8.2
[8.0]: https://github.com/geolens-io/geolens/compare/v7.2...v8.0
[7.2]: https://github.com/geolens-io/geolens/compare/v6.2...v7.2
[6.2]: https://github.com/geolens-io/geolens/compare/v6.0...v6.2
[6.0]: https://github.com/geolens-io/geolens/compare/v3.0...v6.0
[3.0]: https://github.com/geolens-io/geolens/compare/v2.4...v3.0
[2.4]: https://github.com/geolens-io/geolens/compare/v2.0...v2.4
[2.0]: https://github.com/geolens-io/geolens/releases/tag/v2.0

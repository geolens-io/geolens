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
- **Post-impl audit 2026-04-10 follow-ups** (`docs-internal/audits/post-impl-20260410-HANDOFF.md`):
  - **S1 — source `geom`/`geometry` column collision (P1):** vector uploads with an attribute literally named `geom` or `geometry` no longer crash `ogr2ogr` at CREATE TABLE time. `run_ogr2ogr`/`run_ogr2ogr_service` now use `GEOMETRY_NAME=_geolens_geom` as a placeholder, which `ensure_geom_column` renames to `geom` after `rename_reserved_columns` has moved the source attribute to `src_geom`. Regression test lives in `tests/test_ingest_column_preservation.py::test_source_geom_attribute_renamed_to_src_geom`; the `reserved_names.geojson` fixture once again includes a source `geom` attribute.
  - **S2 — cross-module mypy cleanup (P1):** resolved 7 errors in `app/datasets/service.py` (including the UUID-vs-Dataset attr-defined errors in `get_related_datasets`), 2 in `app/storage/provider.py`, 2 in `app/public_urls.py`, 6 in `app/audit/service.py`, 3 in `app/maps/service.py`, 3 in `app/persistent_config.py`, and 1 in `app/services/preview.py`. `mypy` is now clean across `app/ingest/`, `app/datasets/service.py`, and the audited supporting modules.
  - **S3 — structured ingest warnings surfaced to the UI (P2):** `JobStatusResponse` now exposes `warnings`, `archive_failed`, and `temporal_parse_errors` alongside the existing `warning_message`. A new `IngestWarningsBanner` component renders reserved-name renames, Shapefile DBF collisions, archive failures, and temporal-parse failures in `JobProgress` on the upload success screen AND permanently on the dataset detail page. A new `GET /jobs/by-dataset/{dataset_id}` endpoint powers the persistent banner by looking up the most recent ingest job for a dataset with visibility filtering. Translations added for en/de/es/fr.
  - **Post-impl audit test coverage gaps closed:** added 31 new tests across the helpers introduced by the audit — `_resolve_effective_srid` (5 tests), `_detect_and_override_geometry` (5), `_archive_original_file` (3), `_bind_task_log_context` (3), `_parse_temporal_fields` (8), `create_vrt_job` (5), `GET /jobs/by-dataset/{id}` (6), and `JobStatusResponse` warning surfacing (6). Keeps every new helper regressible in isolation.
  - **Flaky test resolved:** `test_publish_blocked_when_hard_validation_fails` is no longer flaky. Two back-to-back full-suite runs (1848/1848 each) completed cleanly — the `_geolens_geom` collision fix, transaction/session hygiene changes, and the structlog contextvar clearing in `_bind_task_log_context` likely removed the fixture leakage.
  - **N1 — worker log correlation (P3, R-18/R-24):** each ingest task entry point (`ingest_file`, `ingest_service`, `reupload_file`, `reupload_service`, `ingest_raster`, `ingest_vrt`, `regenerate_vrt`) now binds `job_id` + task name to structlog contextvars so operators can correlate log lines from concurrent uploads without manual grep-stitching.
  - **N2 — validation-failure file retention (P3):** removed the inline `Path(file_path).unlink(missing_ok=True)` on validation failure in `ingest_file`. The `finally` block's retry-preserving cleanup is now authoritative so retryable validation failures keep the local upload around.
  - **N3 — quicklook failure phase (P3):** quicklook commit failures are now tagged with `phase="commit"` vs `phase="generate"` so operators can distinguish "PostGIS query died" from "session commit died" when reading logs.
  - **N4 — HTTPException re-raise ordering (P3):** documented the except clause ordering requirement in `router.upload_file` so future refactors don't silently rewrite 4xx → 500.
  - **N5 — temporal parse errors surfaced to UI (P3):** raster ingest now persists unparseable `temporal_start`/`temporal_end` values to `job.user_metadata.temporal_parse_errors`, which the new warnings banner displays so users know which values were dropped.
  - **K1 — `ingest_file` phase helpers (P3, partial):** extracted `_resolve_effective_srid`, `_detect_and_override_geometry`, and `_archive_original_file` helpers from the 260-line `ingest_file` task body.
  - **K3-PRE — VRT test mock warnings:** `test_vrt_source_management_174.py::TestRegenerateVrtTask` no longer emits `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` — `mock_session.add` is now explicitly bound to a synchronous `MagicMock` to match real SQLAlchemy semantics.
  - **K5 — `create_vrt` validation moved to service layer (P3, KISS-10):** `create_vrt_job` lives in `app/ingest/service.py`; the router handler is now a 3-line wrapper.
  - **K7 — `_finalize_ingest` IngestContext refactor (P3, KISS-2):** the 11-parameter signature is now a dataclass. Both `ingest_file` and `ingest_service` construct a single `IngestContext` instead of repeating the call-site noise.
- **Post-impl audit 2026-04-10 **B** follow-ups** — a narrow-scope audit of the above remediation work itself surfaced 22 new findings. 5 were fixed in the original session; the remaining 14 landed as a follow-up pass (see `docs-internal/audits/post-impl-20260410-HANDOFF-REMAINING.md`). Fixes landed in this session:
  - **RESILIENCE-1 (P1):** `_archive_original_file` had an unguarded `session.commit()` inside its best-effort exception block. A transient DB error during archive-metadata persistence (deadlock, pooler drop) would propagate out of the helper and flip the already-successful ingest into a `failed` job via the outer task `except Exception`, triggering Procrastinate retries and potentially producing duplicate datasets. The metadata commit is now wrapped in its own try/except with rollback-on-failure, matching the quicklook commit pattern. Regression test: `test_archive_original_file_commit_failure_does_not_raise`.
  - **KISS-1/CLEANUP-1 (P2):** removed the dead `assumes_4326` parameter from `_resolve_effective_srid` that was being `del`'d immediately on entry.
  - **KISS-3/CLEANUP-3/TYPE-6 (P2):** deleted the unused `IngestJobUserMetadata` TypeScript interface that had zero references in the codebase (the named-key + `[key: string]: unknown` index signature also defeated type safety for the listed fields).
  - **RESILIENCE-3 (P3):** `IngestWarningsBanner` on `DatasetPage` now only renders when `datasetJob?.status === 'complete'`, matching the `JobProgress.tsx` gate. Prevents showing warnings from a failed re-import on the still-functional dataset page.
  - **RESILIENCE-4 (P3):** `_archive_original_file` warning log now includes `dataset_id` as a structured kwarg (previously only embedded in `archive_key`), and the error string is consistently truncated to 500 chars.
  - **TYPE-1/TYPE-2/TYPE-3 (P2 + P3):** closed the backend→frontend ingest-warning contract. `_append_job_warning` now accepts an `IngestJobWarning` TypedDict union (`app/ingest/warnings.py`) built via `make_reserved_rename_warning` / `make_dbf_truncation_warning` producers; `JobStatusResponse.warnings` is a Pydantic discriminated union (`ReservedRenameWarning | DbfTruncationCollisionWarning`) validated per-entry in `_job_to_status_response` — malformed or unknown-kind entries are logged and dropped rather than 500ing the endpoint. `JobStatusResponse.temporal_parse_errors` narrowed to `dict[Literal["temporal_start", "temporal_end"], str]`. New regression tests in `test_jobs_router.py` (unknown-kind drop, temporal-key narrowing) and `test_ingest_ogr_pure.py` (producer→Pydantic round-trip).
  - **RESILIENCE-2 (P2):** `create_vrt_job` now wraps `ingest_vrt.defer_async` in a try/except that marks the already-committed IngestJob `failed` before re-raising, so a Procrastinate outage returns a clean 503 instead of leaving a pending orphan that waits 60 minutes for stale-cleanup. Regression test: `test_defer_failure_marks_job_failed_and_raises_503`.
  - **PERF-1 (P3):** `_extract_common_layer_metadata` now populates `columns` from the target layer's `fields`, so shapefile ingest no longer has to spawn a second `run_ogrinfo_preview` subprocess just to get the column list for the DBF collision detector. The text-fallback path (GDAL < 3.7) still falls through to the preview helper.
  - **PERF-2 (P3):** `useDatasetJobStatus` upgraded from `staleTime: 5 min` to `staleTime: Infinity` + `gcTime: 30 min` since the underlying ingest metadata is immutable once the dataset exists. Stops refetch-on-mount and caches 404 ("no job") responses across navigations.
  - **PERF-3 (P3):** added `index=True` to `IngestJob.dataset_id` in the ORM to match the existing `ix_catalog_ingest_jobs_dataset_id` migration. Prevents Alembic autogenerate from re-adding the index and keeps tests that skip migrations honest about the index.
  - **PERF-4 (P3):** `query_audit_logs` switched from two sequential round trips (list + count) to `COUNT(*) OVER ()` on the main query, halving the endpoint's latency for the audit-log page. Empty-slice pagination still falls back to a count-only query so "page out of range" returns the correct total.
  - **CLEANUP-2 (P3):** inlined the redundant `x_column`/`y_column`/`geom_column` locals in `ingest_file` into the `user_wants_geom` boolean — they were re-derived inside `_detect_and_override_geometry` anyway.
  - **CLEANUP-4 (P3):** `reupload_file` now calls `_archive_original_file` via a new `log_message` + `commit=False` knob, removing the inlined duplicate archive block. The reupload path rides the existing `status=complete` commit so the archive-failed flag is durable without a second round trip.
  - **KISS-2 (P3):** `_detect_and_override_geometry` now returns `str | None` instead of `tuple[bool, str | None]` — the bool was always `True` at the only callsite because the caller guarded on the exact inverse condition. Also added a `_validate_table_name` call at the top (**RESILIENCE-5**) to match the rest of `metadata.py`'s defense-in-depth convention.
  - **TYPE-4 (P3):** annotated `**extra: object` in `_bind_task_log_context` instead of implicit `Any`.
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

### Operators
- Environments that created public raster datasets before the anonymous raster viewer fix may still have `catalog.records` rows stuck at `record_status='draft'`. Review and backfill only those public raster rows before the next release:

```sql
SELECT id, title, visibility, record_status, created_at
FROM catalog.records
WHERE record_type = 'raster_dataset'
  AND record_status = 'draft'
  AND visibility = 'public';

UPDATE catalog.records
   SET record_status = 'published',
       published_at = NOW()
 WHERE record_type = 'raster_dataset'
   AND record_status = 'draft'
   AND visibility = 'public';
```

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

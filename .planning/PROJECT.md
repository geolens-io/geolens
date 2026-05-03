# GeoLens

## What This Is

An on-premises, PostGIS-native GIS data catalog that lets GIS analysts, data engineers, and non-technical staff search, preview, and export geospatial datasets — both vector and raster — through a fast, search-first web UI. Built on a "database-first" architecture using FastAPI for catalog, tile serving (ST_AsMVT for vector, Titiler for raster), feature serving, metadata, search, RBAC, and job orchestration.

Shipped 38 milestones (v1.0-v1.6, v1.8-v1.9, v2.0-v2.6, v3.0-v7.0, v7.2-v7.3, v8.0-v8.2, v9.0-v9.1, v10.0-v12.3). Production-hardened with refresh token auth, non-root containers, Trivy CI scanning, Prometheus metrics, automated S3 backups, Redis circuit breaker, magic byte file validation, and route-based code splitting. Cloud-ready with provider-agnostic storage (S3), caching (Redis/Valkey), managed database support, and presigned uploads. Full-featured GIS catalog with faceted search (FTS + pgvector + keyword/org/CRS facets + ranking boosts), map preview, export, collections, layer creation/editing, AI-assisted map building, related dataset discovery, raster dataset support (COG ingest, tile serving, export), VRT mosaics with lifecycle management, STAC 1.1 export for raster interop, publication lifecycle (draft/ready/internal/published), and internationalization (i18n). Accessible UI with 44px mobile touch targets, keyboard-focusable tables, WCAG AA badge contrast, semantic collection markup, responsive detail headers, and raster/VRT preview resilience with bounded retry. Deployable by other organizations via `docker compose up`.

## Current State

45 milestones delivered (v1.0-v1.6, v1.8-v1.9, v2.0-v2.6, v3.0-v7.0, v7.2-v7.3, v8.0-v8.2, v9.0-v9.1, v10.0-v13.3; plus v14.0 marketing site shipped from `getgeolens.com` repo on 2026-04-13). v1.7 Marketplace & Distribution paused at Phase 40 (AWS AMI Build). Open-core architecture is **A-grade ship-ready** — Apache 2.0 licensed core, enterprise extensions register via `importlib.metadata` entry_points, auto-generated Python + TypeScript SDKs from `backend/openapi.json`, Apache-2.0 `geolens` CLI on PyPI (login/scan/publish/export-stac), SAML enterprise overlay with SP-initiated SSO + JIT provisioning + audited attribute→role mapping, documented + tested edition lifecycle (operator runbooks, admin SAML→local conversion endpoint, round-trip symmetry test), **fully extensible audit + billing seams** (write-side `AuditSink` Protocol with per-sink failure isolation; `BillingExtension` startup hook with `core/marketplace.py` extracted to enterprise overlay), and **decomposed catalog domain** (1407-LOC god-module split into 5 cohesive sub-modules behind a thin façade). Latest audit grades: Boundary Integrity **A+** (zero 🟡 risks), Seam Quality **B+**, Coupling Health **B** (catalog god-module decomposed; log_action 65→7 chokepoint sites), OSS Surface A−. Overall readiness **3.85/4.0 (A)** per `post-impl-20260501-b.md`.

The marketing and documentation web properties (v14.0 + v15.0 + 999.5 cross-repo style alignment) and their planning artifacts moved to the `getgeolens.com` repo on 2026-04-26 — see `~/Code/getgeolens.com/.planning/` for active docs-site work.

## Last Milestone (this repo): v13.3 Boundary A+ Cleanup (shipped 2026-05-01)

**Delivered:** 3 phases (222-224), 18 plans, 15/15 requirements satisfied — see [milestones/v13.3-ROADMAP.md](milestones/v13.3-ROADMAP.md).

- **AuditSink Protocol + 65-site chokepoint** — extensible audit-emission seam with per-sink failure isolation (`structlog.exception()` swallows + logs without breaking surrounding business operation). `audit_emit()` facade replaces 65 direct `log_action()` calls; only 7 references remain (definition site + DefaultAuditSink shim + docstrings). CI guard `test_no_log_action_calls_outside_audit_service` enforces invariant (Phase 222).
- **AWS Marketplace billing extracted** — `core/marketplace.py` deleted; `Settings.aws_marketplace_*` removed; generic `BillingExtension.on_startup()` dispatch loop in `api/main.py:184-209` with `asyncio.wait_for(timeout=10s)` + per-extension try/except. AWS Marketplace overlay subscribes via `geolens-enterprise/billing/` entry-point. Boundary Integrity grade A → **A+** (Phase 223).
- **Catalog god-module decomposed** — `backend/app/modules/catalog/datasets/domain/service.py` 1407 → 87 LOC thin re-export façade. Five cohesive sub-modules (create/query/lifecycle/metadata/relationships) each <500 LOC. 23 public symbols preserved across 47 consumer files via explicit named re-exports + `__all__`. DECOUPLE-04 architecture-guard test prevents future bypass (Phase 224).
- **SQL-safety single source of truth** — `_sql_safety.py` consolidates `SAFE_TABLE_NAME_RE` + `SAFE_COLUMN_NAME_RE` + `_safe_table_ref` (was redefined 6× pre-cleanup). Architecture guard extended to forbid external imports of the private module.
- **`IngestionResult` Pydantic model** — collapses `create_dataset` 17-kwarg signature to a single typed parameter object (with legacy-kwargs back-compat for existing test fixtures).
- **Three new architecture-guard Makefile targets** — `audit-sink-discipline`, `billing-extraction-discipline`, `catalog-domain-discipline`.

<details>
<summary>Earlier milestone — v13.2 Edition Lifecycle Hardening (shipped 2026-04-30)</summary>

**Delivered:** 2 phases (220-221), 9 plans, 7/7 requirements satisfied — see [milestones/v13.2-ROADMAP.md](milestones/v13.2-ROADMAP.md).

- **Operator runbooks for the full lifecycle** — `docs/edition-deactivation.md` (186 lines, 10 sections) for enterprise→community downgrade and `docs/edition-reactivation.md` for re-upgrade. `docs/saml.md` cross-links to the new runbook and labels `alembic downgrade -1` as the destructive path with mandatory `pg_dump` pre-step (Phase 220).
- **SAML data preservation verified** — `backend/tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data` confirms `oauth_providers` rows + 4 `deferred=True` SAML columns + `oauth_accounts` linkages survive a registry-clear deactivation. `lifecycle` pytest marker registered + run by default in CI when overlay installed (Phase 220).
- **CI overlay install with graceful fork-PR fallback** — `.github/workflows/ci.yml` conditionally checks out `geolens-enterprise` based on `GEOLENS_ENTERPRISE_TOKEN` secret presence; pytest runs with lifecycle marker INCLUDED when available, deselected on fork PRs without secret (Phase 220).
- **Admin SAML→local conversion endpoint** — `POST /admin/users/{user_id}/convert-saml-to-local/` (audit action `user.convert_saml_to_local`) flips a SAML user to local-password in a single transaction, preserving `users.id` (every FK referencing it stays intact) and deleting only the SAML `oauth_accounts` linkage. Self-conversion blocked with 422 (Phase 221).
- **Round-trip symmetry guaranteed** — `test_deactivate_reactivate_roundtrip_preserves_saml_data` drives the registry through a full cycle and asserts losslessness across the 4 deferred SAML columns + `oauth_accounts` linkage + User row + a seeded `audit_log` row (Phase 221).

</details>

<details>
<summary>Earlier milestone — v13.1 Open-Core Separation P1 (shipped 2026-04-29)</summary>

8 phases (212-219), 30 plans, 21/21 requirements satisfied — see [milestones/v13.1-ROADMAP.md](milestones/v13.1-ROADMAP.md).

- Open-core boundary closed: `core/` no longer imports from `modules/settings/`; `auth/visibility.py` relocated to `catalog/authorization.py` with broadened architecture-guard (212, 213).
- `IdentityProtocol` extracted: 51 cross-domain `User` import sites retyped to `Identity`; `get_identity_extension()` hook lets enterprise overlays register custom backends without core changes (214).
- Auto-generated SDKs: Python (`pip install geolens`) + TypeScript (`@geolens/sdk`) regenerate one-shot via `make sdks`; `make sdks-check` CI gate prevents drift (215).
- `geolens` CLI MVP: Apache-2.0 standalone tool consuming only the generated SDK (zero hand-rolled HTTP); `login` (keyring + headless), `scan`, `publish`, `export stac` (216).
- SAML enterprise overlay: `geolens-enterprise` registers via entry_points with dual `AuthExtension` + `IdentityExtension`; admin UI 3-layer gated; SAML implementation lives outside core (217).
- Audit gate met: Phase 218 produced closing audit; Phase 219 closed OAuth IdP→role mapping P0 surfaced by Phase 218 via `is_enterprise()` schema + service gate; audit doc amended in place to VERIFIED (218, 219).

</details>

**Concurrent shipped work (cross-repo, prior to v13.1):**
- v14.0 Marketing Site (executed in `getgeolens.com` repo, shipped 2026-04-13).
- 999.1-999.4 backlog (3D viewer toggle, PostGIS 3D detection, GeoJSON-Z delivery endpoint, shared vector staging pipeline) — executed in **this repo** as backend/frontend work; phase artifacts remain under `.planning/phases/999.1-*..999.4-*`.

## Current Milestone: v13.4 Boundary Closeout

**Goal:** Close the last 🔴 seams from `oc-separation-audit-20260430-b.md` — invert the catalog↔processing cycle, make AI providers extensible, and finish remaining open-core publish hygiene — so v14.0 can launch on architecturally clean ground.

**Target features:**
- ProcessingPort Protocol (Phase 225) — invert catalog↔processing cycle, with inline architecture guard
- AIProviderExtension Protocol (Phase 226) — replace hardcoded provider dispatch with extensible Protocol
- SAML test fixture cleanup (Phase 227) — stop polluting `git status` after every test run
- Run cold PyPI/npm publish workflows (Phase 228) — convert WIRED → SHIPPED for SDKs + CLI
- CatalogPort Protocol (Phase 230) — invert the remaining catalog→processing direction symmetrically
- EmbeddingProviderExtension Protocol (Phase 231) — remove the final module-level provider-SDK import from `processing/`
- Post-impl audit at close (Phase 229) — audit Phases 225-228 plus 230/231 before milestone close

**Audit-grade targets:** Boundary Integrity A+ (hold); Coupling Health B → **A−** (both catalog↔processing directions inverted via Phases 225 + 230); Seam Quality B+ → **A−** (AI + embeddings provider seams closed via Phases 226 + 231).

## Core Value

Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Requirements

### Validated

- ✓ Search-first catalog UI with text, spatial, temporal, and tag-based filtering — v1.0
- ✓ Dataset preview: map visualization, attribute table, metadata card, and download options — v1.0
- ✓ Ingestion pipeline: upload files (Shapefile, GeoJSON, GeoPackage, CSV) and load into PostGIS via ogr2ogr — v1.0
- ✓ Export pipeline: export datasets to GeoJSON, Shapefile, GeoPackage, CSV via ogr2ogr — v1.0
- ✓ OGC API – Features via pg_featureserv — v1.0
- ✓ Vector tile serving via pg_tileserv for map previews — v1.0
- ✓ OGC API – Records-aligned metadata/search endpoints in catalog service — v1.0
- ✓ OGC Records Part 1 conformance URIs and per-record conformsTo arrays — Phase 183
- ✓ Source organization and CRS filter controls in search UI — Phase 183
- ✓ Metadata model: keywords/tags, spatial extent, organization/owner, temporal range, CRS, row count — v1.0
- ✓ Simple local authentication (username/password) with OIDC-ready architecture — v1.0
- ✓ App-level RBAC for dataset access control — v1.0
- ✓ Dataset registry with audit logging — v1.0
- ✓ Docker Compose packaging for single-node on-prem deployment — v1.0
- ✓ Performance: sub-second search, instant tile rendering, efficient large-file ingestion — v1.0
- ✓ OGC API landing page and conformance for machine client auto-detection — v1.1
- ✓ Enriched catalog records with assets, bbox, navigation links, and OGC properties — v1.1
- ✓ Dynamic collection metadata with spatial/temporal extents and catalog summaries — v1.1
- ✓ Hypermedia pagination with next/prev links for lossless catalog traversal — v1.1
- ✓ API key authentication for machine clients — v1.1
- ✓ CQL2 text and JSON filtering with RBAC-safe query pipeline — v1.1
- ✓ Queryables and record schema endpoints for schema introspection — v1.1
- ✓ Saved search deduplication with unique constraint upsert — v1.2
- ✓ MapLibre vector tile layers render without console errors — v1.2
- ✓ Geometry type consistent uppercase casing across ingestion and display — v1.2
- ✓ OGC API links use correct public base URL from request or configuration — v1.2
- ✓ Test suite isolated on dedicated database, dev DB clean — v1.2
- ✓ Admin dashboard Storage Used shows real PostGIS consumption — v1.2
- ✓ Audit log displays username of actor for each event — v1.2
- ✓ Import UI with drag-and-drop file upload, bulk upload, and job progress tracking — v1.3
- ✓ Pre-import preview with detected columns, sample rows, CRS, geometry type, and editable metadata — v1.3
- ✓ Register existing PostGIS table through the UI — v1.3
- ✓ Ingestion error recovery with retry failed jobs and better error messages — v1.3
- ✓ Self-registration with admin approval flow and "pending approval" screen — v1.3
- ✓ Admin chooses role (viewer/editor/admin) at user approval time — v1.3
- ✓ Admin can create, edit, and delete users through the UI — v1.3
- ✓ Admin can view, create, and revoke API keys for any user — v1.3
- ✓ Admins and editors can edit dataset metadata (name, description, tags, visibility) through the UI — v1.3
- ✓ Hard delete datasets with type-to-confirm safety step — v1.3
- ✓ Per-dataset change history on dataset detail page (filtered audit log) — v1.3
- ✓ Admin dashboard Jobs tab showing all ingestion jobs across all users — v1.3
- ✓ Frontend unit tests with Vitest and React Testing Library for stores, route guards, and components — v1.4
- ✓ Structured JSON logging via structlog with request correlation IDs and dev/prod toggle — v1.4
- ✓ Request logging middleware with method, path, status code, and duration tracking — v1.4
- ✓ Database backup/restore scripts with retention rotation and environment validation — v1.4
- ✓ CI pipeline with frontend-test job and coverage reporting for both backend and frontend — v1.4
- ✓ Playwright E2E tests covering auth, search, dataset detail, admin panel, and upload flows — v1.4
- ✓ CI e2e-test job running full-stack browser tests against Docker Compose with failure artifact upload — v1.4
- ✓ Flat, multi-membership collections with name, description, and aggregated spatial/temporal extents — v1.5
- ✓ Collection management UI for admins/editors (create, edit, delete, manage dataset membership) — v1.5
- ✓ Collection landing pages with search/filter within collection — v1.5
- ✓ Collection browser page with cards showing dataset count and extent preview — v1.5
- ✓ Dataset re-upload with atomic table swap preserving identity, metadata, and memberships — v1.5
- ✓ Schema diff preview comparing old and new columns, types, and row counts before re-upload commit — v1.5
- ✓ Version history tracking for re-uploaded datasets with timestamp, user, and file/schema changes — v1.5
- ✓ Comprehensive UI/UX design guide establishing GeoLens brand identity, color palette, typography, spacing, and component patterns — v1.6
- ✓ Clean professional visual direction (Stripe/Linear style) with generous whitespace and subtle accents — v1.6
- ✓ Consistent component library — all base components (buttons, cards, inputs, badges, tables) follow the design system — v1.6
- ✓ Every page refactored to follow the guide — search, dataset detail, collections, import, admin, auth flows — v1.6
- ✓ Light mode only — v1.6
- ✓ Layer filters with visual builder (field/operator/value dropdowns), stored on MapLayer, rendered via MapLibre filter expressions — v1.9
- ✓ Per-layer labels with attribute picker, font size, color, and halo via MapLibre symbol layers — v1.9
- ✓ Data-driven styling (categorical and graduated) with Brewer color ramps for fills, lines, and circles — v1.9
- ✓ Layer drag-and-drop reordering to change draw order in the map builder — v1.9
- ✓ Feature popups showing attribute table on click with formatted values — v1.9
- ✓ Layer rename with custom display names independent of dataset name — v1.9
- ✓ Natural-language map generation from prompt with automatic dataset search and layer creation — v1.9
- ✓ Conversational AI chat for map editing (filters, styles, labels, visibility, add/remove layers) with tool calling — v1.9
- ✓ Multi-provider LLM support (Anthropic native tool_use + OpenAI-compatible API for Ollama/Groq/Together) — v1.9
- ✓ Admin AI status card with runtime enable/disable toggle persisted in DB with TTL cache — v1.9
- ✓ CLI seed script downloads all 130 Natural Earth 1:10m datasets from NACIS CDN with retry and caching — v2.0
- ✓ Three-step API ingestion (upload/preview/commit) with srid_override=4326 and job polling — v2.0
- ✓ Auto-generated human-readable names and thematic tags from Natural Earth naming conventions — v2.0
- ✓ Idempotent re-runs with catalog check, concurrent ingestion (3 parallel streams), and collection grouping — v2.0
- ✓ Service URL tab on Import page for WFS and ArcGIS Feature Service URLs — v2.1
- ✓ SSRF validation blocking private IPs and non-HTTP schemes on all remote URL requests — v2.1
- ✓ Auto-detection of WFS vs ArcGIS services with unified layer listing — v2.1
- ✓ ogrinfo-based layer preview with columns, CRS, geometry type, sample rows, and feature count — v2.1
- ✓ ogr2ogr ingestion for WFS (native driver) and ArcGIS (ESRIJSON with auto-pagination) — v2.1
- ✓ Automatic CRS reprojection to WGS84 during service import (-t_srs EPSG:4326) — v2.1
- ✓ Optional auth token forwarding (Bearer for WFS, query param for ArcGIS) — never persisted — v2.1
- ✓ Full post-processing parity: geom_4326, mercator clip, reader grants, metadata extraction, quality score — v2.1
- ✓ Native FastAPI feature-serving endpoints with paginated GeoJSON, bbox/property filtering, and RBAC — v2.2
- ✓ pg_featureserv removed from Docker stack, reducing deployment from 6 to 5 services — v2.2
- ✓ Frontend ServiceUrls and map components point to FastAPI feature endpoint — v2.2
- ✓ Human-readable slugified table names for new dataset ingestions with collision suffix handling — v2.2
- ✓ Existing UUID-named tables continue working without changes — v2.2
- ✓ Discovery endpoint scans PostGIS database for unregistered spatial tables — v2.2
- ✓ Table picker UI with multi-select checkboxes replaces text input for registering existing tables — v2.2
- ✓ Bulk-register multiple discovered tables at once with per-table error isolation — v2.2
- ✓ Editor/admin can create new empty layers by choosing geometry type and name — v2.3
- ✓ Created layers become full catalog datasets with complete post-processing pipeline — v2.3
- ✓ Draw points, lines, polygons on the map with Terra Draw toolbar (point, line, polygon, rectangle, circle, freehand modes) — v2.3
- ✓ Drawn features persist to PostGIS and appear in map tiles immediately — v2.3
- ✓ Select and move existing features, edit vertices, delete features — v2.3
- ✓ Edit attribute values on individual features via attribute form — v2.3
- ✓ Add/remove attribute columns on existing layers with validation against allowlists — v2.3
- ✓ Undo last drawing action while in draw mode (button + Ctrl+Z/Cmd+Z) — v2.3
- ✓ Vertex snapping to nearby features for precise alignment — v2.3
- ✓ Write operations (create layer, feature CRUD, schema changes) gated by RBAC — v2.3
- ✓ Dark/light mode toggle in Navbar with system color scheme detection and preference persistence — v2.4
- ✓ FOUC prevention when dark mode is active — v2.4
- ✓ Distinctive emerald brand accent color across both themes with dark mode design tokens — v2.4
- ✓ All hardcoded colors replaced with semantic tokens, MapLibre controls themed, hover states and transitions — v2.4
- ✓ Admin panel with sidebar navigation, deep-linkable routes, and dedicated Settings section — v2.4
- ✓ Existing admin functionality preserved in new layout — v2.4
- ✓ Admin manages basemap presets and custom basemaps via XYZ/TMS tile URL — v2.4
- ✓ Users see admin basemaps in picker across all map views with auto-switch on theme change — v2.4
- ✓ Admin sets default map center/zoom, map views use admin defaults — v2.4
- ✓ Self-registration and AI chat feature toggles with immediate effect — v2.4
- ✓ Provider-agnostic storage (local + S3), caching (in-memory + Redis/Valkey), managed database support with SSL — v5.0
- ✓ Presigned S3 uploads for large files, CDN tile delivery, admin infrastructure dashboard — v5.0
- ✓ Cloud deployment documentation for AWS, GCP, and DigitalOcean — v5.0
- ✓ nginx gzip compression, per-IP rate limiting, static asset caching, security headers — v6.0
- ✓ Non-root Docker containers with CI Trivy scanning and SBOM attestation — v6.0
- ✓ Route-based code splitting with React.lazy for all page components — v6.0
- ✓ Refresh token auth with proactive auto-refresh and configurable CORS — v6.0
- ✓ Magic byte file validation, zip bomb detection, admin-configurable upload limits — v6.0
- ✓ Prometheus metrics for HTTP requests, job queues, connection pools, and tile cache — v6.0
- ✓ Automated database backups with S3 off-site replication, retention, and restore validation — v6.0
- ✓ Redis circuit breaker, priority queue routing, frontend type cleanup — v6.0
- ✓ Canonical dataset detail hierarchy with single title, above-the-fold key metadata, and role-aware editable affordances — v6.1
- ✓ Segmented edit context model (Geometry/Attributes/Metadata) with dirty-switch guardrails — v6.1
- ✓ Editable vs read-only field affordances with consistent helper text on dataset detail — v6.1
- ✓ Service URL re-upload with schema diff preview, atomic swap, and identity preservation — v6.1
- ✓ Validation troubleshooting guidance and quality score freshness with cadence semantics — v6.1
- ✓ Provenance attribution on detail pages, search cards, and all mutation audit paths — v6.1
- ✓ Admin sidebar flattened with settings promoted to top-level entries — v6.1
- ✓ "Powered by GeoLens" footer link to GitHub repository — v6.1
- ✓ PersistentConfig generic class with env-var default, DB override, and ENV_ONLY kill switch — v6.2
- ✓ Centralized config registry with unified admin settings page (6 tabs) replacing scattered settings — v6.2
- ✓ Admin UI for auth token lifetimes, CORS origins, LLM provider/model, log level, and tile cache TTL — v6.2
- ✓ Granular per-role permission toggles (upload, create layers, export, edit metadata, manage collections, AI chat) — v6.2
- ✓ OAuth/OIDC provider management via admin UI (Google, Microsoft, generic OIDC) with encrypted secrets — v6.2
- ✓ OAuth/OIDC login flow with PKCE, auto-account creation, email-based account linking, and group-to-role mapping — v6.2
- ✓ Config export/import API with dry-run diff preview and merge/overwrite modes — v6.2
- ✓ Audit trail for all admin setting changes with old/new values — v6.2
- ✓ Infrastructure connectivity validation endpoint (S3, Redis, OIDC) — v6.2

- ✓ FastAPI tile gateway with ST_AsMVT replacing pg_tileserv — v7.0
- ✓ Signed tile access (HMAC URL tokens) replacing nginx auth_request — v7.0
- ✓ Procrastinate worker separated from API into its own container — v7.0
- ✓ Standalone SPA frontend (no nginx dependency) with runtime env config — v7.0
- ✓ FastAPI middleware for gzip, rate limiting, security headers (nginx removed) — v7.0
- ✓ Alembic migrate service for startup migrations — v7.0
- ✓ nginx reverse proxy removed from runtime topology — v7.0

- ✓ pgvector extension with record_embeddings table and HNSW index — v7.2
- ✓ Embedding generation pipeline via Procrastinate (ingest hook, metadata update hook, backfill command) — v7.2
- ✓ SEMANTIC_SEARCH_ENABLED admin toggle and embedding health probe in admin dashboard — v7.2
- ✓ Hybrid search combining FTS + vector results via Reciprocal Rank Fusion (RRF) — v7.2
- ✓ Frontend semantic search toggle gated by AI enabled + embeddings exist — v7.2
- ✓ AI search_datasets tool enhanced with hybrid search for better map generation and chat — v7.2
- ✓ Related datasets endpoint with overview tab card row on dataset detail page — v7.2
- ✓ Smarter keyword suggestions via embedding similarity in metadata generators — v7.2

- ✓ SQL sandbox with sqlglot AST validation enforcing single-SELECT-only queries — v8.0
- ✓ RBAC table allowlist restricting SQL queries to user-visible datasets — v8.0
- ✓ Safe SQL execution with READ ONLY transactions, 30s timeout, 1000-row cap — v8.0
- ✓ Error sanitization pipeline with generic user messages and full server-side logging — v8.0
- ✓ Text-to-SQL engine with DDL schema context and PostGIS-aware generation prompt — v8.0
- ✓ Natural language data questions answered via LLM-generated PostGIS SQL in chat — v8.0
- ✓ Narrative plain-text answers interpreting query results in chat — v8.0
- ✓ Streaming stage progression feedback during SQL query execution — v8.0
- ✓ Actionable error messages for query failures (timeout, no results, permission denied) — v8.0
- ✓ Ephemeral result layers rendering spatial query geometry as temporary GeoJSON overlays — v8.0
- ✓ Ephemeral layer dismiss UI with feature count badge and auto-zoom to results — v8.0
- ✓ PATCH endpoint for share token expiration with ownership check and audit logging — v8.2
- ✓ PATCH endpoint for embed token domain restrictions with cache invalidation — v8.2
- ✓ Inline-editable expiration and domain fields in SharePanel with toast feedback — v8.2
- ✓ Value persistence across panel reopen via query invalidation — v8.2

- ✓ Map copy/fork with RBAC-filtered layer duplication, lineage tracking, and collision-safe naming — v10.0
- ✓ Map browse page with search, sort, filter, grid/list toggle, and author attribution on cards — v10.0
- ✓ Map metadata info modal and button tray restructure in map builder — v10.0
- ✓ Dataset-to-maps cross-reference ("Used in Maps"), adaptive SVG previews, and auto-capture thumbnails — v10.0
- ✓ Raster schema foundation with record_type discriminator, raster_assets table, and Titiler Docker service — v10.0
- ✓ COG ingest pipeline with automatic conversion, metadata extraction, quicklook thumbnails, and raster-aware delete — v10.0
- ✓ RBAC-gated raster tile serving via Titiler with auth-check endpoint and credential isolation — v10.0
- ✓ Raster catalog integration with DatasetResponse raster fields, COG download, and connect URLs — v10.0
- ✓ Raster search and import UI with type filter, raster badges, quicklook thumbnails, and raster detail pages — v10.0
- ✓ Map builder raster layers with opacity control, conditional layer controls, AI awareness, and persistent layer_type — v10.0
- ✓ PostgreSQL profiling infrastructure (pg_stat_statements + auto_explain) and synthetic seed script for 1000+ datasets — v11.0
- ✓ Locust load testing suite with weighted traffic scenarios for all critical API paths — v11.0
- ✓ Baseline measurement report with p50/p95/p99 latencies under 10-user concurrent load — v11.0
- ✓ Keyset cursor pagination replacing LIMIT/OFFSET for constant-time page access — v11.0
- ✓ Redis tile cache with gzip-compressed MVT bytes and Prometheus counters — v11.0
- ✓ B-tree GID indexes on high-traffic tables and PostgreSQL memory/autovacuum tuning — v11.0
- ✓ Configurable connection pool parameters (DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE) — v11.0
- ✓ Performance regression test suite with @pytest.mark.perf markers for 5 critical endpoints — v11.0
- ✓ OGC Records Part 1 conformance URIs (record-core, record-core-query-parameters, json) at /conformance — v12.0
- ✓ Faceted search with /search/facets endpoint returning record_type, keywords, source_organization, srid groups — v12.0
- ✓ Type toggle badges with live counts (All, Vector, Raster, VRT, Collection) in search UI — v12.0
- ✓ Collections as first-class records in global search with member count badge and drill-down — v12.0
- ✓ OGC datetime interval parameter for temporal extent filtering — v12.0
- ✓ Modality-aware assets (raster records exclude vector links, vector records exclude raster links) — v12.0
- ✓ Unified assets dict with stac_assets emitted during transition period — v12.0
- ✓ Raster/VRT records include proj:epsg, proj:shape, gsd, bands with stac_extensions array — v12.0
- ✓ Publication lifecycle enum (draft/ready/internal/published) with state machine enforcement via PATCH /datasets/{id}/status — v12.0
- ✓ Asset URL security: signed URLs for STAC, proxy for local, public thumbnails for published — v12.0
- ✓ STAC 1.1 export: /stac/ catalog, /stac/items/{id}, /stac/collections/{id}, /stac/search with bbox/datetime/collections/ids — v12.0
- ✓ STAC API conformance classes declared — v12.0
- ✓ VRT generation tracking with vrt_generations table and backfill migration — v12.0
- ✓ VRT status/generations API endpoints and regeneration with advisory lock and atomic swap — v12.0
- ✓ VRT detail page Sources tab with generation history, source health, and regenerate button — v12.0
- ✓ Detail page refactored to shared skeleton with type-specific panels (Vector, Raster, VRT, Collection) — v12.0
- ✓ Keyword facet multi-select picker with search-as-you-type in FilterPanel — v12.0
- ✓ Search ranking boosts (published 2x, freshness 1.5x within 30 days) — v12.0
- ✓ All icon-only buttons have descriptive aria-labels for screen readers — v12.1
- ✓ Raster quicklook images have meaningful alt text with dataset name — v12.1
- ✓ Focus indicators visible on all interactive elements — v12.1
- ✓ Standard ErrorState/LoadingState components used consistently across all pages — v12.1
- ✓ All destructive buttons use variant="destructive" — v12.1
- ✓ Submit buttons show loading spinners when mutations are pending — v12.1
- ✓ Form spacing standardized (space-y-2 label+input, space-y-4 groups) — v12.1
- ✓ Icon sizes follow 4-tier design guide system — v12.1
- ✓ Search cards show creation date fallback for never-edited datasets — v12.1
- ✓ Quality score badge uses neutral styling (not warning amber) — v12.1
- ✓ Every page sets contextual document title for browser tabs — v12.1
- ✓ Audit log timestamps show time-of-day for same-day entries — v12.1
- ✓ Collections browse page has client-side search/filter — v12.1
- ✓ Dataset detail tabs responsive on narrow viewports — v12.1
- ✓ Mobile tab triggers meet 44px touch target minimum with scroll-snap overflow — v12.2
- ✓ Tab overflow discoverable via gradient fade and snap-x scrolling — v12.2
- ✓ Scrollable table containers keyboard-focusable with visible focus ring and role=region — v12.2
- ✓ VRT status badges use centralized WCAG AA semantic colors on light and dark themes — v12.2
- ✓ Collection metadata card uses valid dl/dt/dd semantic markup — v12.2
- ✓ Collection detail header readable on mobile without title squeeze — v12.2
- ✓ Collection page uses intentional flat card+list layout (distinct from dataset tabs) — v12.2
- ✓ Dataset detail pages have no horizontal overflow at 375px on any record type — v12.2
- ✓ Page titles keep readable width with break-words, never collapse to single-word-per-line — v12.2
- ✓ Raster mobile header H1 visible even with Download COG action present — v12.2
- ✓ Secondary actions collapse behind overflow menu at mobile breakpoint — v12.2
- ✓ VRT preview failures stop after bounded retry budget (3 errors or >50% rate) — v12.2
- ✓ VRT/raster hero always shows one of: loaded preview, loading skeleton, or error with retry — v12.2
- ✓ Raster no-tile badge appears immediately for null tile_url datasets (no 10s timeout) — v12.2
- ✓ Users can work on maps comfortably on tablet and narrow desktop widths — v12.3
- ✓ Users can open AI chat on compact tablet widths without sacrificing map workspace — v12.3
- ✓ Users can collapse builder UI without hidden controls remaining tabbable — v12.3
- ✓ Users can scan and manipulate layers through progressively disclosed controls with type cues — v12.3
- ✓ Users can understand save state and key actions without icon-only affordances — v12.3
- ✓ Users see layer-type-appropriate icons and controls for vector, raster, and VRT layers — v12.3
- ✓ Engineers can change map-builder behavior through smaller modules with shared capability model — v12.3
- ✓ `core/` no longer imports from `modules/settings/`; layering inversion broken via `AppSetting` relocation to `core/db/models.py` — v13.1
- ✓ `auth/visibility.py` removed; 23 inbound callers migrated to `catalog/authorization.py` with no behavior change — v13.1
- ✓ `IdentityProtocol` defined in `core/identity.py`; 51 cross-domain `User` import sites retyped to `Identity` — v13.1
- ✓ Extension system exposes `get_identity_extension()` typed accessor; enterprise overlays register identity backends without core changes — v13.1
- ✓ Python SDK auto-generated from `backend/openapi.json`, Apache-2.0, ready for PyPI (live publish deferred per workflow_dispatch) — v13.1
- ✓ TypeScript SDK auto-generated from `backend/openapi.json`, Apache-2.0, ready for npm (live publish deferred per workflow_dispatch) — v13.1
- ✓ `make sdks` regenerates both SDKs one-shot; `make sdks-check` CI gate prevents drift — v13.1
- ✓ SDK version pins to OpenAPI snapshot version; release process documented in `docs/sdks.md` — v13.1
- ✓ `geolens` CLI distributed as Apache-2.0 PyPI package; works against any GeoLens instance with same code path — v13.1
- ✓ `geolens login` stores token in OS keyring with `--no-keyring` headless fallback — v13.1
- ✓ `geolens scan <dir>` walks directory and reports vector/raster files without uploading — v13.1
- ✓ `geolens publish <file>` uploads via SDK and reports dataset URL — v13.1
- ✓ `geolens export stac <id>` writes STAC 1.1 JSON for raster datasets — v13.1
- ✓ CLI consumes only the generated Python SDK — zero hand-rolled HTTP imports (CI grep + tomllib gates enforce) — v13.1
- ✓ SAML implementation lives entirely in `geolens-enterprise` repo (with documented Pitfall 11 carve-out for `deferred=True` ORM scaffolding) — v13.1
- ✓ Core auth-extension hook is the only seam SAML overlay registers into; `importlib.metadata` entry_points — v13.1
- ✓ Admin UI shows SAML tab only when enterprise edition detected; community returns 404 (3-layer gating) — v13.1
- ✓ SP-initiated SAML SSO with metadata XML endpoint, signed assertion validation, JIT provisioning via `find_or_create_oauth_user()` — v13.1
- ✓ Configurable SAML attribute → role mapping via `group_claim`/`group_role_mapping`; gated by `is_enterprise()` (Phase 219); audit-logged with `SECRET_FIELDS` redaction — v13.1
- ✓ Closing audit grades meet/exceed targets: Boundary A (≥A−), Seam Quality B (≥B), OSS Surface A− (≥C) — v13.1
- ✓ Operator runbook for enterprise→community downgrade (`docs/edition-deactivation.md`, 10 sections) — v13.2
- ✓ Operator runbook for community→enterprise re-upgrade (`docs/edition-reactivation.md`) — v13.2
- ✓ `docs/saml.md` no longer presents `alembic downgrade -1` as primary deactivation path; cross-links to runbook with mandatory `pg_dump` pre-step on destructive path — v13.2
- ✓ Disabling the enterprise edition without `alembic downgrade` preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns — verified by `test_overlay_removal_preserves_saml_data` in CI — v13.2
- ✓ Destructive alembic downgrade path documented with explicit data-export prerequisite — v13.2
- ✓ Admin SAML→local conversion endpoint preserves users.id (all FK referrers intact) — `POST /admin/users/{user_id}/convert-saml-to-local/` with audit action `user.convert_saml_to_local`, allow-listed audit details (no password material), 422-blocked self-conversion — v13.2
- ✓ Round-trip symmetry test confirms 4 `deferred=True` SAML columns + `oauth_accounts` linkage + User row + seeded `audit_log` row are lossless across deactivate→reactivate cycle — `test_deactivate_reactivate_roundtrip_preserves_saml_data` in CI — v13.2

### Active

_No active milestone. Run `/gsd-new-milestone` to populate from `.planning/REQUIREMENTS.md` once requirements are defined._

### Out of Scope

- New map authoring capabilities (3D, live collaboration, time sliders) — this milestone hardens the existing builder instead of widening scope
- AI capability expansion — AI chat and map generation stay as-is; the focus is usability, correctness, and maintainability
- Phone-specific map-builder optimization — this milestone targets tablet and desktop workflows only
- Power-user resizable/persisted sidebar widths — useful enhancement, but secondary to fixing the default tablet/desktop shell
- Full STAC certification — STAC 1.1 endpoints implemented and tested, formal certification deferred
- STAC for vector datasets — STAC is raster-centric; vector records served via OGC Records
- STAC temporal model (per-asset timestamps) — awkward for vector catalogs
- Automatic VRT regeneration on source change — manual-first, webhook/auto deferred until usage patterns understood
- Cursor-based catalog pagination (GAP-STD-08) — offset pagination works for <100K records; breaking change deferred
- Real-time collaboration / editing features — catalog is read/browse/export focused
- Raster band math / custom color ramps — MVP raster layers support opacity only
- Raster collections / time series — one record = one COG for MVP, collection model deferred
- PostGIS Raster (in-database raster storage) — COG-as-file is the model
- Raster nodata footprint masking — bbox polygon for MVP, precise footprint later
- Mobile-specific UI — responsive web is sufficient
- SAML/LDAP/AD integration — wire through Keycloak later, not MVP
- CQL2 advanced features (arithmetic, array functions) — basic subset sufficient for catalog use case
- Catalog federation / harvesting — single-instance on-prem deployment
- Full data versioning / snapshot rollback — version history tracks metadata; full rollback deferred
- Cursor-based catalog pagination (GAP-STD-08) — offset pagination works for <100K records; breaking change deferred
- Automatic VRT regeneration on source change — manual-first, webhook/auto deferred until usage patterns understood
- Dataset-level sharing with specific users/groups — admin RBAC sufficient for now
- Email notifications for registration approval and job completion — SMTP adds deployment complexity for on-prem
- OAuth/OIDC self-registration — local auth self-registration is right scope
- Soft delete / trash can — adds complexity, on-prem storage is finite
- Self-service role elevation — admin promotes manually, small admin count

## Context

- **Current state**: v12.0 shipped. 35 milestones delivered. Full-featured GIS catalog supporting vector, raster, and VRT datasets with faceted search (FTS + pgvector + keyword/org/CRS facets + ranking boosts), map preview, export, collections, layer creation/editing, AI-assisted map building, related dataset discovery, STAC 1.1 export for raster/VRT interop, publication lifecycle, VRT lifecycle management, and i18n (en/es/fr/de). Type-aware detail pages with shared skeleton and modality-specific panels.
- **Architecture**: Database-first. PostgreSQL 17 + PostGIS 3.5 is the system of record. FastAPI serves vector tiles (ST_AsMVT with signed URL tokens), raster tiles (via Titiler with RBAC-gated token endpoint), features (paginated GeoJSON with bbox/property filtering), catalog metadata, search, auth, OGC discovery, and job orchestration. Background worker runs Procrastinate ingestion tasks. Titiler serves XYZ raster tiles from COG files. Frontend is a static SPA served by nginx with reverse proxy to the API.
- **OGC Compliance**: OGC API Common Core, OGC API Records Core, OGC API Features Part 3 (Filtering/CQL2). Conformance classes declared at `/api/conformance`.
- **Users**: Mix of GIS analysts (power users), data engineers (API consumers), and non-technical staff (browsing/downloading). Search-first UI serves all three. Machine clients (QGIS, GDAL, scripts) can now consume the catalog programmatically.
- **Scale**: 130 Natural Earth 1:10m datasets imported via seed script. Synthetic seed script can populate 1000+ datasets for scale testing. Performance validated at 1000+ datasets with 10 concurrent users — search p50 < 100ms, tiles p50 < 50ms. Keyset pagination, Redis tile cache, and B-tree GID indexes ensure consistent performance at scale.
- **Deployment**: Docker Compose for local/on-prem (5 services: API, Worker, Frontend, Titiler, DB + backup sidecar). Cloud-ready with managed Postgres, S3 storage, Redis/Valkey cache. Ports: DB=5434, API=8001, Frontend=8080.
- **Frontend**: React 19 + TypeScript + Vite 7 + MapLibre GL JS 5 + TanStack Query 5 + Zustand 5 + Tailwind CSS 4 + shadcn/ui + react-dropzone + sonner.
- **Search**: PostgreSQL full-text search with tsvector generated columns (name at weight A, description at B, tags at C, column names + sample values at D) + PostGIS spatial intersection + JSONB facets. Optional pgvector semantic search with hybrid FTS+vector RRF ranking, graceful FTS fallback.
- **Documentation**: Install guide, configuration reference, and admin guide in `docs/`.

## Constraints

- **Tech stack**: Python + FastAPI backend, React frontend, PostgreSQL 17 / PostGIS 3.5, GDAL/ogr2ogr, pygeofilter
- **Standards**: OGC API Features (Part 1 + Part 3), OGC API Records (aligned subset), Mapbox Vector Tiles, CQL2
- **Deployment**: Docker Compose (on-prem) or cloud managed services (AWS/GCP/DO)
- **Auth**: Local auth + API key auth + refresh tokens + OAuth/OIDC (Google, Microsoft, generic OIDC via authlib)
- **Packaging**: Installable by other orgs — documented setup, seeded sample data, env var configuration

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| pg_featureserv + pg_tileserv over custom serving | Eliminates custom geospatial plumbing, OGC-compliant out of the box | ✓ Good initially — pg_featureserv replaced by native FastAPI in v2.2, pg_tileserv replaced by FastAPI tile gateway (ST_AsMVT) in v7.0 |
| PostgreSQL full-text search over OpenSearch | Keeps deployment to a single stateful system, sufficient for < 50 datasets | ✓ Good — sub-second search with tsvector generated columns and GIN index |
| Local auth first, OIDC later | Simplifies MVP, avoids IdP dependency for pilots | ✓ Good — AuthProvider Protocol enables OIDC swap without downstream changes |
| ogr2ogr for ingestion/export | Battle-tested format conversion, avoids bespoke writers | ✓ Good — handles 4 formats + CRS reprojection reliably |
| Docker Compose first, Helm later | Fastest path to deployable pilot | ✓ Good — single-command deployment verified |
| React + MapLibre GL JS for frontend | Strong ecosystem, performant vector tile rendering | ✓ Good — smooth pan/zoom with geometry-aware styling |
| Procrastinate over arq/Celery for job queue | PG-native, no Redis dependency, keeps single-database architecture | ✓ Good — async task processing with no additional services |
| Schema separation (catalog + data) | Isolate metadata from user data, least-privilege for tile/feature services | ✓ Good — tile queries use geolens_reader role with data schema only |
| Nginx auth_request for OGC service RBAC | Enforces access control without modifying pg_tileserv | Superseded — replaced by signed tile URLs (HMAC) in v7.0; nginx removed from topology |
| SVG bbox preview over WebGL mini-maps | Avoids WebGL context exhaustion on search result cards | ✓ Good — lightweight, no GPU resource contention |
| pygeofilter over custom CQL2 parser | Python CQL2 parser with SQLAlchemy backend, avoids building parser from scratch | ✓ Good — full CQL2 text + JSON support with minimal code |
| CQL2 filter applied after RBAC visibility | Prevents data leakage through crafted CQL2 queries | ✓ Good — RBAC always restricts results first |
| API key auth via SHA-256 hash | Raw key shown only at creation, stored as hash for security | ✓ Good — keys inherit user roles, no separate permission model |
| Pydantic model_json_schema() for queryables | Generates JSON Schema from existing model, avoids manual schema maintenance | ✓ Good — schema stays in sync with model automatically |
| ON CONFLICT upsert for saved searches | Constraint-based dedup avoids race conditions vs check-then-insert | ✓ Good — atomic, no duplicate rows possible |
| Dedicated geolens_test database for tests | Complete isolation from dev DB, session-scoped create/migrate/drop | ✓ Good — zero test pollution in dev, clean state each run |
| EXISTS subquery for storage stat | Filter to existing tables before pg_total_relation_size, one orphan doesn't zero total | ✓ Good — resilient to dataset records referencing dropped tables |
| User status column (pending/active/rejected/suspended) | Self-registration requires approval flow states beyond boolean is_active | ✓ Good — clean state machine, distinct error messages per status |
| 403 for deactivated users (not 401) | Credentials valid but access denied — semantically correct HTTP status | ✓ Good — clear distinction between bad credentials and denied access |
| Server-side ogrinfo for import preview | Avoids shipping GDAL to browser, leverages existing ogr2ogr infrastructure | ✓ Good — reliable format detection with zero client-side dependencies |
| User metadata as JSONB on IngestJob | Flexible key-value storage for user-edited name/description/tags/CRS without schema changes | ✓ Good — extensible, no migration needed for new metadata fields |
| Staging files preserved on failure | Enables retry without re-upload by keeping uploaded file on disk | ✓ Good — retry works instantly, no bandwidth wasted |
| Promise.allSettled for bulk upload | Parallel uploads with independent failure handling per file | ✓ Good — one failed file doesn't block others |
| outerjoin for admin jobs user lookup | created_by is nullable (SET NULL on user delete), inner join would drop orphaned jobs | ✓ Good — admin sees all jobs even after user deletion |
| Vitest with jsdom + module-level MapLibre mock | MapLibre GL crashes jsdom; mock at module level avoids import errors | ✓ Good — 37 tests pass, no WebGL context needed |
| structlog with ProcessorFormatter bridge | Existing stdlib loggers produce structured output without code changes | ✓ Good — JSON/console toggle via LOG_JSON env var |
| pg_dump -Fc for backups | Custom format enables compressed backups with selective restore | ✓ Good — reliable backup/restore with retention rotation |
| Playwright at project root (not frontend/) | E2E tests span full stack, not just frontend | ✓ Good — shared storageState, single config, Makefile target |
| storageState pattern for E2E auth | Login once in setup, reuse session across all tests | ✓ Good — fast test execution, auth spec overrides for login testing |
| CI coverage flags only (not in pytest addopts) | Avoids slowing local development with coverage instrumentation | ✓ Good — local dev fast, CI gets coverage reports |
| Dual Playwright reporter in CI | GitHub annotations + HTML report for CI debugging | ✓ Good — meaningful artifact upload, annotations in PR checks |
| Compute-on-read for collection extents | Aggregate bbox/temporal from member datasets at query time | ✓ Good — matches existing patterns, no denormalization needed at current scale |
| Atomic table swap for re-upload | ogr2ogr into staging table, then RENAME in single transaction | ✓ Good — tile/feature services never see partial data, zero downtime |
| Separate reupload_file Procrastinate task | Dedicated task vs branching existing ingest_file | ✓ Good — clean separation, no regression risk to ingestion |
| Synthesized Version 1 in frontend | VersionHistory creates v1 from dataset metadata when API has no version record | ✓ Good — existing datasets show version history without backfill migration |
| /catalog/collections router prefix | Avoids collision with OGC /collections router | ✓ Good — clean namespace separation, OGC collection endpoints remain available for future |
| OKLCH color space with @theme inline | Perceptually uniform, opacity modifiers via oklch(), reactive var() references | ✓ Good — consistent status colors, smooth gradient support |
| Inter variable font via @fontsource-variable | Self-hosted, no CDN dependency, variable weight support | ✓ Good — consistent typography across all pages |
| tw-animate-css for shadcn/ui animations | Drop-in animation fix, no framer-motion overhead | ✓ Good — dialogs, tooltips, dropdowns animate correctly |
| PageShell + PageHeader shared components | Enforce consistent layout without per-page inline styles | ✓ Good — all 6 authenticated pages use shared layout |
| Centralized status-colors.ts | Single source for all status badge colors | ✓ Good — zero hardcoded hex values in component files |
| Atomic AppLayout → PageShell migration | All pages migrated in single commit to avoid inconsistent state | ✓ Good — no intermediate broken states |
| Static dataset manifest over HTML scraping | NE releases are infrequent, hardcoded list is more reliable than parsing CDN pages | ✓ Good — 130 datasets, no fragile HTML parsing |
| srid_override=4326 for all NE datasets | All Natural Earth data is WGS84, avoids CRS auto-detection failures on .prj-less ZIPs | ✓ Good — consistent ingest across all datasets |
| httpx as sole external dependency (KISS) | Removed rich/tenacity for simplicity; hand-rolled retry equivalent to tenacity | ✓ Good — minimal dependency footprint |
| asyncio.TaskGroup + Semaphore(3) concurrency | Bounded parallelism without thread pool complexity | ✓ Good — ~3x speedup, per-task exception isolation |
| Atomic cache writes via tmp+rename | Prevents half-written ZIPs on interruption | ✓ Good — safe resume after Ctrl+C |
| 409 → GET fallback for collection idempotency | Create-or-get pattern avoids duplicate collections on re-run | ✓ Good — clean idempotency without pre-check race |
| ipaddress stdlib for SSRF validation | No external dep, covers all private ranges + link-local | ✓ Good — clean security gate, frozenset scheme allowlist |
| defusedxml for WFS XML parsing | Prevents XXE/billion laughs on untrusted WFS GetCapabilities | ✓ Good — drop-in replacement for ElementTree |
| httpx for async probe requests | Already in ecosystem, async-native, follows redirects | ✓ Good — clean timeout handling, Bearer header support |
| GDAL_HTTP_HEADERS env var for WFS auth | ogr2ogr/ogrinfo subprocess inherits Bearer token without URL mutation | ✓ Good — clean separation, token stays in headers not URLs |
| ArcGIS token as query parameter | ArcGIS REST API requires `&token=` on URL, not headers | ✓ Good — matches ArcGIS convention, works for all ArcGIS endpoints |
| model_dump(exclude={"token"}) for DB safety | Prevents token from reaching user_metadata, logs, or audit | ✓ Good — single exclusion point, no token in any persistent store |
| -t_srs EPSG:4326 for all service imports | Forces reprojection at import time, avoids SRID mismatch crashes | ✓ Good — consistent geom_4326 column regardless of source CRS |
| Procrastinate task args for token passing | Token in task args is transient (not persisted after execution) | ✓ Good — no DB storage, retry requires re-import by design |
| Native FastAPI feature endpoints over pg_featureserv | Reduces service count, simplifies RBAC, eliminates nginx auth_request for features | ✓ Good — 5-service stack, RBAC in FastAPI code, zero pg_featureserv maintenance |
| ST_AsGeoJSON + to_jsonb raw SQL for feature serving | Direct PostGIS rendering avoids ORM overhead and complex geometry serialization | ✓ Good — clean GeoJSON output with bbox/property filtering, matches OGC API Features structure |
| python-slugify for table naming | ASCII transliteration, underscore separator, 60-char max | ✓ Good — human-readable PostGIS tables (us_state_capitals vs ds_a1b2c3d4e5f6) |
| Collision suffix (_2, _3) with warning propagation | Avoids unique constraint errors while informing user of name adjustment | ✓ Good — warning stored in job metadata, surfaced via toast in frontend |
| information_schema discovery for unregistered tables | Standard SQL metadata tables, LEFT JOIN catalog.datasets to find gaps | ✓ Good — discovers tables regardless of how they were loaded into PostGIS |
| Per-table error isolation in bulk register | Independent try/except + commit/rollback per table in loop | ✓ Good — one failing table does not block others |
| POINT extent guard in create_dataset | Only set extent when WKT starts with POLYGON, skip degenerate POINT extents | ✓ Good — prevents Geometry(Polygon) type mismatch crash for single-point tables |
| Terra Draw (v1.25.0) for drawing library | Only MapLibre-compatible open-source option (MIT, OSGeo) | ✓ Good — polygon/line/point/rectangle/circle/freehand modes, select mode for editing |
| Zero new backend deps for feature CRUD | PostGIS ST_GeomFromGeoJSON + SQLAlchemy text() | ✓ Good — no ORM overhead, direct GeoJSON-to-PostGIS pipeline |
| useMemo for Terra Draw React integration | Tied to map instance, not useEffect, per terra-draw#197 | ✓ Good — prevents re-render bugs with @vis.gl/react-maplibre v8 |
| useRef for onFinish/onEditFinish callbacks | Avoids stale closures without triggering event listener re-registration | ✓ Good — clean callback pattern for Terra Draw event handlers |
| Ephemeral drawing store (no persist) | Drawing state should not survive page reload | ✓ Good — zustand store without persist middleware |
| Single-to-multi geometry promotion on INSERT | Terra Draw draws single geometries, promote to Multi for PostGIS | ✓ Good — ST_Multi wraps geometry transparently |
| Snapshot-based undo over command pattern | getSnapshot/clear/addFeatures simpler than command stack | ✓ Good — clean Terra Draw integration, history resets on mode change |
| ALTER TABLE for column CRUD | Strict regex + type whitelist prevents SQL injection | ✓ Good — defense-in-depth with Pydantic validation + service layer check |
| Tile filter per-layer for edit isolation | setFilter with gid exclusion hides original during editing | ✓ Good — no source removal avoids flickering |
| shadcn/ui ThemeProvider for dark mode | Zero new dependencies, ~40 LOC, `.dark` CSS class toggle | ✓ Good — FOUC-free with blocking inline script in index.html |
| OKLCH charcoal dark mode base (0.178 0.005 285) | Cool blue undertone distinguishes from pure black, perceptually uniform | ✓ Good — distinctive dark palette |
| DropdownMenu for theme toggle (not switch) | Clean 3-way selection (light/dark/system) without ambiguity | ✓ Good — system preference detection works correctly |
| transformStyle for basemap switching | Preserves all custom layers (tiles, drawings, highlights) across setStyle() | ✓ Good — zero layer loss during theme-based basemap switch |
| Sidebar CSS with oklch (not shadcn HSL defaults) | Design token consistency with existing OKLCH color space | ✓ Good — fixed outline variant hsl() wrapper to raw var() |
| catalog.app_settings JSONB for site-wide settings | Reuse existing settings store, no new tables | ✓ Good — basemaps, map defaults, feature toggles all use same store with TTL cache |
| Public GET endpoints for basemaps/map-defaults | Public viewer needs basemaps without auth | ✓ Good — only GET is public, PUT requires admin |
| XYZ-to-StyleSpecification conversion for raster tiles | OSM/Stamen use {z}/{x}/{y} URLs not .json style specs | ✓ Good — inline StyleSpecification with type: 'raster' source |
| Legacy basemap key mapping (positron→carto-positron) | Existing maps reference old basemap keys | ✓ Good — resolveBasemapId() handles backward compatibility |
| Registration toggle DB-backed with env var fallback | New installs use env var until first admin save | ✓ Good — smooth migration from static config to dynamic settings |
| obstore for S3 over boto3 | Rust-backed, async, provider-agnostic | ✓ Good — clean async file I/O with local and S3 backends |
| nginx proxy_cache for tiles over Varnish | Zero new services, existing nginx handles it | ✓ Good — RBAC-safe caching with user ID in cache key |
| Opaque refresh tokens with DB hash over JWT refresh | Revocable, auditable, no client-side token parsing | ✓ Good — SHA-256 hash stored, rotation on each refresh |
| puremagic for magic byte detection | Pure Python, no libmagic C dependency | ✓ Good — works in all Docker environments without system packages |
| prometheus-fastapi-instrumentator | Automatic HTTP metrics with minimal code | ✓ Good — histograms, counters, and custom collectors all on /metrics |
| Supercronic sidecar for backups | No custom Dockerfile needed, cron in container | ✓ Good — configurable schedule, S3 upload, retention policies |
| Circuit breaker for Redis cache | Auto-fallback to in-memory on Redis failure | ✓ Good — 5-failure threshold, 30s cooldown, health check bypasses breaker |
| Keep pg_tileserv over Martin | Purpose-built, good RBAC via nginx auth_request | Superseded — replaced by FastAPI tile gateway (ST_AsMVT) in v7.0 for cloud-native deployment |
| Centralized buildDatasetEditCapabilities | Single role-to-field editability source for all affordances | ✓ Good — consistent editable/read-only behavior across detail surfaces |
| Segmented edit context with controlled toggle-group | Prevents accidental empty deselection, enforces single-active context | ✓ Good — clean Geometry/Attributes/Metadata switching with dirty guardrails |
| Shared _apply_reupload_swap for file and service paths | DRY atomic swap, metadata refresh, quality recompute, version insertion | ✓ Good — both re-upload sources share identical post-commit invariants |
| Request-only token forwarding for service re-upload | Never persist credentials; user must re-supply token for retry | ✓ Good — zero secret storage risk, clear ephemeral security model |
| Centralized provenance actor resolver | Single fallback/redacted/never-edited derivation for detail and search | ✓ Good — consistent attribution formatting across all surfaces |
| In-transaction provenance stamping | Metadata writes stamp updated_by atomically with content mutation | ✓ Good — no provenance gaps from partial commits |
| Flat admin sidebar with SidebarSeparator | Settings children promoted to top-level, no click-through parent group | ✓ Good — 12 items with visual grouping divider |
| PersistentConfig[T] generic with env_default_factory | Dynamic defaults via callable, preserves test compatibility | ✓ Good — 16 config instances across 6 tabs |
| Scalar config values wrapped in {"v": value} JSONB | AppSetting stores JSONB, scalars need wrapping | ✓ Good — clean round-trip for all value types |
| DynamicCORSMiddleware always added (unconditional) | Empty origins = passthrough, no conditional middleware registration | ✓ Good — hot-reloadable CORS from PersistentConfig |
| require_permission() replacing require_role() | Capability-based access control enables admin-configurable permissions | ✓ Good — ~80 endpoints migrated across 13 routers |
| Fernet key derived from JWT_SECRET_KEY via HKDF | Cryptographic separation without additional secret management | ✓ Good — OAuth client secrets encrypted at rest |
| OAuth client built fresh per request (stateless) | No cached IdP state, clean per-request isolation | ✓ Good — authlib starlette integration works cleanly |
| Config import validates role_permissions before applying | Lockout prevention — unknown keys silently skipped for forward compat | ✓ Good — safe multi-instance config transfer |
| Vector dimension 1536 default with configurable EMBEDDING_DIMS | Matches text-embedding-3-small, most common embedding model | ✓ Good — PersistentConfig allows runtime override |
| HNSW index with m=16, ef_construction=64 | Balanced insert/query performance for catalog-scale datasets | ✓ Good — sub-second similarity queries |
| Content hash dedup for embeddings | Prevents redundant API calls when metadata unchanged | ✓ Good — significant cost savings on updates |
| Non-fatal embedding hooks via try/except | Embedding generation should never block ingestion | ✓ Good — zero ingestion failures from embedding errors |
| RRF k=60 for hybrid FTS+vector fusion | Standard RRF constant, balanced weighting of FTS and vector scores | ✓ Good — relevant results for both exact and conceptual queries |
| Cosine distance threshold 0.7 (similarity >= 0.3) | Filter noise from low-similarity vector results | ✓ Good — reused for both search and related datasets |
| Over-fetch limit*3 then RBAC filter for related datasets | Ensures enough results after permission filtering | ✓ Good — consistent top-N results across roles |
| Self-hiding card pattern for related datasets | Component returns null on loading/error/empty | ✓ Good — clean UX, no skeleton or toast clutter |
| expires_at=None in PATCH body removes expiration | Matches existing ShareTokenCreateRequest pattern | ✓ Good — consistent null semantics for "never expires" |
| Reuse origin validation in EmbedTokenUpdate | Same urlparse logic as EmbedTokenCreate | ✓ Good — consistent origin normalization |
| Only active tokens can be updated | Inactive/revoked tokens return 404 on PATCH | ✓ Good — prevents stale token modification |
| EmbedTokenResponse type (without raw_token) | Non-create responses don't include the raw token | ✓ Good — clean separation of create vs list types |
| Inline editing: clickable text toggles to input | Dotted-underline hint, check-mark save button | ✓ Good — discoverable without cluttering read-only view |
| ADR-001 for v12.0 locked decisions | 8 architectural decisions documented in single ADR before implementation | ✓ Good — clear guidance for all implementation phases |
| Record type taxonomy (4 types) | collection, vector_dataset, raster_dataset, vrt_dataset as discriminator enum | ✓ Good — clean type-aware branching throughout stack |
| Publication lifecycle enum | draft/ready/internal/published with ALLOWED_TRANSITIONS state machine | ✓ Good — frontend PublishButton sequences through all states |
| Separate /stac/ router | Isolated STAC API from OGC Records, clean concern separation | ✓ Good — independent STAC conformance, no OGC Record pollution |
| Multi-group facets in single endpoint | /search/facets returns record_type + keywords + org + srid in one call | ✓ Good — single network round-trip for all facet data |
| Aliased subqueries for facet counts | RecordKeyword alias avoids SQLAlchemy auto-correlation bugs | ✓ Good — correct counts with DRY filter application |
| Type-specific detail panels | Shared skeleton dispatches to VectorDetailPanel/RasterDetailPanel/VrtDetailPanel/CollectionDetailPanel | ✓ Good — each panel owns its tabs and content |
| Sequential status mutations via mutateAsync | PublishButton loops through intermediate states to comply with state machine | ✓ Good — backend enforces one-step transitions, frontend sequences them |
| sqlglot for SQL AST validation | Parse SQL to AST, enforce single-SELECT, extract table refs | ✓ Good — rejects writes/DDL/multi-statement at AST level |
| Dataclass for ValidatedQuery over Pydantic | Lightweight internal type, no serialization needed | ✓ Good — minimal overhead for internal pipeline |
| CTE alias exclusion from table access checks | find_all(exp.CTE) extracts aliases, prevents false rejections | ✓ Good — CTEs work correctly in sandbox queries |
| Dedicated engine.connect() for sandbox execution | Avoids transaction conflicts with caller's session | ✓ Good — clean isolation with own READ ONLY transaction |
| LIMIT N+1 fetch for row cap | Extra row signals truncation without count overhead | ✓ Good — client-aware truncation flag on SandboxResult |
| Error sanitization by exception type matching | Generic user messages, full details logged via structlog | ✓ Good — no internal details leak to users |
| COG-as-file storage model | Pixels in managed file/S3 store, metadata/footprint in PostGIS | ✓ Good — avoids PostGIS Raster bloat, clean separation |
| Separate Titiler raster tile service | Internal Docker service, no external port exposure | ✓ Good — auth-unaware Titiler with credential isolation |
| record_type discriminator on datasets | NOT NULL DEFAULT 'vector_dataset', drives conditional rendering | ✓ Good — clean raster/vector branching throughout stack |
| RBAC at GeoLens API, Titiler auth-unaware | Token endpoint validates access, embeds service credential in URL | ✓ Good — browser never sees Titiler credentials |
| Separate ingest_raster Procrastinate task | Dedicated task vs branching existing ingest_file | ✓ Good — clean separation, no regression risk |
| COG conversion via subprocess with GDAL_CACHEMAX limit | Prevents OOM in worker container | ✓ Good — safe resource isolation |
| Raster layers opacity-only for MVP | No band math or color ramps | ✓ Good — ships value fast, defers complexity |
| TileToken discriminated union (Vector/Raster) | kind field gates raster vs vector code paths | ✓ Good — type-safe frontend branching |

| pg_stat_statements + auto_explain for query profiling | Database-side profiling with no application code changes | ✓ Good — 5000 max, 100ms threshold, buffers+analyze |
| Locust function-based tasks over TaskSet classes | Simpler Locust 2.x pattern, easier to maintain | ✓ Good — clean per-endpoint scenario modules |
| Weighted traffic: tiles 40%, search 30%, browse 20%, detail 10% | Reflects real usage patterns where tiles are the hot path | ✓ Good — realistic load distribution |
| Synthetic seed via NE geometry jitter oversampling | Generates varied datasets from real geometries without external data | ✓ Good — 1000+ datasets with 4 geometry types |
| Warm-up + reset before measured run | Isolates cache-warm steady-state from cold-start noise | ✓ Good — pg_stat_statements reset after warm-up |
| Export p95=1200ms as top optimization target | ogr2ogr conversion overhead dominates export latency | Pending — Phase 180 should investigate |
| decode_responses=False for binary tile cache | MVT tiles are binary, JSON decode would corrupt | ✓ Good — separate TileCacheProvider from main RedisCacheProvider |
| Cache compressed gzip bytes in tile cache | Skip re-compression on cache hits | ✓ Good — 27% p50 tile latency improvement |
| Simple try/except for tile cache degradation | Advisory cache doesn't warrant circuit breaker complexity | ✓ Good — graceful fallback when Redis unavailable |
| Keep DB_POOL_SIZE=10 default | 40% utilization under 10-user load, zero overflow | ✓ Good — validated by Prometheus evidence |
| Keep TILE_CACHE_TTL=300s | Appropriate for infrequently-changing vector data | ✓ Good — balances freshness and performance |
| aria-label={t()} on all icon buttons | i18n-ready accessibility, consistent with existing patterns | ✓ Good — 10 components updated, screen reader support |
| variant="destructive" on AlertDialogAction | Replaces inline className with shadcn semantic variant | ✓ Good — 7 dialogs standardized |
| Loader2 spinner on all submit buttons | Consistent loading feedback across all forms and dialogs | ✓ Good — 11 buttons updated |
| space-y-2 / space-y-4 form spacing contract | Eliminates per-file spacing decisions | ✓ Good — 6 form components standardized |
| 4-tier icon size system (h-3/h-4/size-8/size-10) | Reduces cognitive load for icon sizing decisions | ✓ Good — 7 off-tier icons fixed |
| useDocumentTitle hook on all pages | Centralized title management with " - GeoLens" suffix | ✓ Good — 18 pages with descriptive browser tab titles |
| formatDateTimeSmart with toDateString() comparison | Simple today/yesterday detection without date library dependency | ✓ Good — 6 test cases covering all branches |
| Client-side collection search (limit=200 fetch-all) | Small collection counts don't justify server-side search endpoint | ✓ Good — instant filter with i18n empty state |
| overflow-x-auto on TabsList for responsive tabs | CSS-only solution, no JavaScript resize observer needed | ✓ Good — 4 detail panels responsive at 400px |
| min-h-11 + snap-x on TabsList for mobile touch targets | CSS-only 44px targets with scroll-snap; no JS resize observer | ✓ Good — verified 44px at 375px viewport |
| Gradient fade overlay for tab scroll affordance | CSS-only aria-hidden div, no scroll event listener | ✓ Good — zero JS overhead, subtle UX hint |
| tabIndex=0 + role=region on Table container | Standard WAI-ARIA pattern for scrollable regions | ✓ Good — keyboard accessible in all Table consumers |
| vrtGenerationColors centralized semantic map | Single source for VRT badge colors instead of inline Tailwind | ✓ Good — WCAG AA in light and dark themes |
| dl/dt/dd for collection metadata (not table/grid) | Semantic HTML for screen readers, natural responsive reflow | ✓ Good — 5 terms render with aria-label |
| flex-col md:flex-row on DatasetDetailHeader | Mobile stacking without JS breakpoint detection | ✓ Good — no overflow at 375px on any record type |
| flex-wrap replacing flex-shrink-0 on action containers | Buttons wrap instead of squeezing title; same fix on PageHeader | ✓ Good — applies to both dataset and collection headers |
| Hero state machine (loading/loaded/error) for raster/VRT | Explicit 3-state with bounded retry budget (3 attempts) | ✓ Good — no infinite spinners or blank areas |
| useEffect ordering: id-reset before no-tile skip | Prevents stale heroState when navigating between datasets | ✓ Good — effect dependency arrays are minimal and correct |
| useBuilderLayout hook with container queries | Responsive builder without media queries; isCompact drives sidebar/chat layout | ✓ Good — single source of layout truth |
| inert attribute on collapsed sidebar (not aria-hidden) | Removes all children from tab order AND screen reader tree atomically | ✓ Good — React 19 supports inert natively |
| 3 composable hooks from MapBuilderPage | useBuilderDialogs, useBuilderLayers, useBuilderSave — 1131→481 lines | ✓ Good — each hook independently testable |
| getLayerCapabilities shared capability model | Single function returns edit/style/export capabilities per layer type | ✓ Good — eliminated 4 inline type-checking branches |
| data-testid on interactive test targets | Explicit test selectors instead of fragile DOM structure queries | ✓ Good — basemap test no longer vacuously passes |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-03 — v13.4 Boundary Closeout updated after Phase 231 verification (CatalogPort + EmbeddingProviderExtension promotions reflected)*

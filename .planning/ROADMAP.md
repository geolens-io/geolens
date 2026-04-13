# Roadmap: GeoLens

## Milestones

- ✅ **v1.0 MVP** — Phases 1-8 (shipped 2026-02-13)
- ✅ **v1.1 Machine Readability** — Phases 9-13 (shipped 2026-02-14)
- ✅ **v1.2 QA & Polish** — Phases 14-16 (shipped 2026-02-14)
- ✅ **v1.3 Admin Control & Data Lifecycle** — Phases 17-21 (shipped 2026-02-15)
- ✅ **v1.4 Production Readiness** — Phases 22-27 (shipped 2026-02-15)
- ✅ **v1.5 Data Organization & Freshness** — Phases 28-31 (shipped 2026-02-15)
- ✅ **v1.6 UI/UX Polish** — Phases 32-35 (shipped 2026-02-15)
- ⏸️ **v1.7 Marketplace & Distribution** — Phases 36-42 (paused at Phase 40)
- ✅ **v1.8 Map Builder Core** — (shipped 2026-02-17)
- ✅ **v1.9 Map Builder AI** — (shipped 2026-02-21)
- ✅ **v2.0 Natural Earth Seed Script** — Phases 53-55 (shipped 2026-02-22)
- ✅ **v2.1 Service URL Importing** — Phases 56-60 (shipped 2026-02-23)
- ✅ **v2.2 Architecture Simplification** — Phases 61-63 (shipped 2026-02-23)
- ✅ **v2.3 Layer Creation & Editing** — Phases 64-67 (shipped 2026-02-24)
- ✅ **v2.4 Visual Identity & Admin Experience** — Phases 68-71 (shipped 2026-02-24)
- ✅ **v2.5 i18n** — (shipped 2026-02-25)
- ✅ **v2.6 Tile Architecture** — (shipped 2026-02-26)
- ✅ **v3.0 Design Overhaul** — (shipped 2026-02-28)
- ✅ **v5.0 Cloud-Ready Architecture** — (shipped 2026-03-02)
- ✅ **v6.0 Hardening & Production Readiness** — Phases 102-110 (shipped 2026-03-03)
- ✅ **v6.1 Dataset Detail UX & Provenance** — Phases 111-115 (shipped 2026-03-06)
- ✅ **v6.2 Enterprise Configuration & OAuth** — Phases 116-120 (shipped 2026-03-07)
- ✅ **v7.0 Stack Consolidation** — Phases 121-132 (shipped 2026-03-08)
- ✅ **v7.2 Semantic Search (pgvector)** — Phases 133-138 (shipped 2026-03-09)
- ✅ **v7.3 Map Page Polish** — Phases 139-143 (shipped 2026-03-09)
- ✅ **v8.0 Spatial Intelligence** — Phases 144-147 (shipped 2026-03-09)
- ✅ **v8.1 Secure Sharing & Embed Tokens** — Phases 148-151 (shipped 2026-03-10)
- ✅ **v8.2 Share Link Settings** — Phases 152-153 (shipped 2026-03-10)
- ✅ **v9.0 Cloud Marketplace Distribution** — Phases 154-160 (shipped 2026-03-11)
- ✅ **v9.1 Map Experience & Discovery** — Phases 161-164 (shipped 2026-03-11)
- ✅ **v10.0 Raster Support** — Phases 165-170 (shipped 2026-03-14)
- ✅ **v10.1 VRT Raster Mosaics** — Phases 171-177 (shipped 2026-03-15)
- ✅ **v11.0 Performance at Scale** — Phases 178-182 (shipped 2026-03-16)
- ✅ **v12.0 Record-First Discovery Architecture** — Phases 183-190 (shipped 2026-03-17)
- ✅ **v12.1 UI/UX Polish** — Phases 191-194 (shipped 2026-03-18)
- ✅ **v12.2 Record Detail Stabilization** — Phases 195-199 (shipped 2026-03-19)
- ✅ **v12.3 Map Builder Excellence** — Phases 200-205 (shipped 2026-03-21)
- ✅ **v13.0 Open-Core Pre-Release** — Phases 206-211 (shipped 2026-03-27)
- 🚧 **v14.0 getgeolens.com Marketing Site** — Phases 212-217 (in progress)

## Phases

<details>
<summary>✅ v13.0 Open-Core Pre-Release (Phases 206-211) - SHIPPED 2026-03-27</summary>

### v13.0 Open-Core Pre-Release

- [x] **Phase 206: Extension Seam Architecture** — Protocol interfaces, entry_point loader, edition detection, enterprise-gated 404s, refactor existing boundary code (EXT-01, EXT-02, EXT-03, EXT-04, EXT-05)
- [x] **Phase 207: Branding Toggle** — Removable "Powered by GeoLens" badge via PersistentConfig, enterprise-gated (COMP-04, COMP-05)
- [x] **Phase 208: Audit Log Export** — Streaming CSV/JSON export with date range and event type filters (COMP-01, COMP-02, COMP-03)
- [x] **Phase 209: SAML SSO** — Admin SAML IdP configuration, SP-initiated flow, assertion validation, user provisioning, login page integration (SAML-01, SAML-02, SAML-03, SAML-04, SAML-05)
- [x] **Phase 210: Enterprise Overlay Repo** — geolens-enterprise scaffold, entry_points, compose override, separate Alembic branch, end-to-end proof (REPO-01, REPO-02, REPO-03, REPO-04)
- [x] **Phase 211: Licensing & Public Documentation** — Apache 2.0 LICENSE, public README, quickstart, CONTRIBUTING.md (DOCS-01, DOCS-02, DOCS-03, DOCS-04)

### Phase 206: Extension Seam Architecture
**Goal**: The application discovers and loads enterprise extensions at startup without coupling core code to enterprise implementations, and enterprise-only endpoints are invisible in community mode
**Depends on**: Nothing (foundation phase)
**Requirements**: EXT-01, EXT-02, EXT-03, EXT-04, EXT-05
**Success Criteria** (what must be TRUE):
  1. Application starts successfully with no enterprise package installed and all existing features work identically
  2. When `geolens-enterprise` package is installed, `/api/edition` returns `enterprise` and lists available features; without it, returns `community`
  3. Protocol interfaces exist for auth, audit, and branding extension points with community-edition default implementations
  4. Existing enterprise-boundary code (OIDC advanced config, branding footer) uses extension seam interfaces instead of inline conditionals
  5. Requests to enterprise-gated API endpoints return 404 (not 403) when running in community mode
**Plans**: 3 plans
Plans:
- [x] 206-01-PLAN.md — Extension registry, protocols, defaults, edition detection, lifespan wiring
- [x] 206-02-PLAN.md — Edition API endpoint, frontend useEdition() hook
- [x] 206-03-PLAN.md — Refactor branding footer/badge to use edition seam

### Phase 207: Branding Toggle
**Goal**: Admins on enterprise edition can remove the "Powered by GeoLens" footer badge via an admin setting
**Depends on**: Phase 206 (extension seams, edition detection)
**Requirements**: COMP-04, COMP-05
**Success Criteria** (what must be TRUE):
  1. Admin can toggle "Powered by GeoLens" badge visibility from the admin settings UI and the change takes effect immediately across all pages
  2. In community edition, the branding toggle setting is not visible in admin UI and the badge is always shown
  3. Footer layout renders correctly with badge both visible and hidden (no broken whitespace or misaligned elements)
**Plans**: 2 plans
Plans:
- [x] 207-01-PLAN.md — Backend PersistentConfig and branding API endpoints
- [x] 207-02-PLAN.md — Frontend admin Appearance tab, badge conditional rendering
**UI hint**: yes

### Phase 208: Audit Log Export
**Goal**: Admins can download audit log data as CSV or JSON files for compliance evidence
**Depends on**: Phase 206 (edition detection for enterprise gating)
**Requirements**: COMP-01, COMP-02, COMP-03
**Success Criteria** (what must be TRUE):
  1. Admin can export audit logs as CSV with date range and event type filters applied, and the downloaded file opens correctly in a spreadsheet application
  2. Admin can export audit logs as JSON with the same filters, and the file is valid parseable JSON
  3. Export of 50K+ rows completes without the API process running out of memory (streaming delivery)
  4. Export button is visible in the admin audit log view with format selection
**Plans**: 2 plans
Plans:
- [x] 208-01-PLAN.md — Backend streaming CSV/JSON export endpoints with enterprise gating and tests
- [x] 208-02-PLAN.md — Frontend split button UI, blob download, i18n
**UI hint**: yes

### Phase 209: SAML SSO
**Goal**: Users can authenticate via SAML with a configured Identity Provider, and admins can set up SAML from the admin UI
**Depends on**: Phase 206 (auth extension seam, edition detection)
**Requirements**: SAML-01, SAML-02, SAML-03, SAML-04, SAML-05
**Success Criteria** (what must be TRUE):
  1. Admin can configure a SAML IdP from the admin UI by pasting metadata XML or entering entity ID and SSO URL, and sees the SP entity ID and ACS URL to provide to their IdP
  2. User clicking "Login with [SAML provider]" on the login page is redirected to the IdP, authenticates, and returns to GeoLens with a valid session
  3. SAML assertions with invalid signatures, expired timestamps, wrong audience, or replayed assertion IDs are rejected with appropriate error messages
  4. A user authenticating via SAML for the first time is auto-provisioned or linked to an existing account via the same flow used for OIDC
  5. SAML provider buttons appear on the login page alongside existing OIDC providers when a SAML IdP is configured and enabled
**Plans**: 2 plans
Plans:
- [x] 209-01-PLAN.md — Backend SAML infrastructure: migration, model/schema, pysaml2 modules, router, tests
- [x] 209-02-PLAN.md — Frontend admin SAML form, login page buttons, i18n
**UI hint**: yes

### Phase 210: Enterprise Overlay Repo
**Goal**: A private geolens-enterprise repo exists that installs as a pip package and proves the overlay pattern works end-to-end
**Depends on**: Phase 206, Phase 207, Phase 208, Phase 209 (all extension protocols must be stable)
**Requirements**: REPO-01, REPO-02, REPO-03, REPO-04
**Success Criteria** (what must be TRUE):
  1. `geolens-enterprise` repo has a `pyproject.toml` with entry_points that register with the core extension system, and `pip install -e .` succeeds
  2. Running `docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up` starts the application with enterprise features active
  3. Enterprise Alembic migrations run on a separate branch label and do not appear in core-only deployments
  4. At least one enterprise feature (branding toggle or SAML) is implemented in the enterprise repo and functions when the package is installed
**Plans**: 2 plans
Plans:
- [x] 210-01-PLAN.md — Enterprise package scaffold, core extension loader, Alembic multi-dir, compose overlay
- [x] 210-02-PLAN.md — Extract SAML/audit/branding to enterprise package, clean core

### Phase 211: Licensing & Public Documentation
**Goal**: The repository is ready for public consumption with proper licensing, clear documentation, and a working quickstart
**Depends on**: Phase 206-210 (all features complete, architecture stable)
**Requirements**: DOCS-01, DOCS-02, DOCS-03, DOCS-04
**Success Criteria** (what must be TRUE):
  1. Apache 2.0 LICENSE file exists at the repository root
  2. README.md describes the product for a first-time visitor: features, screenshots, and a 3-command quickstart (clone, docker compose up, open browser)
  3. A new user can go from `git clone` to a working deployment in under 10 minutes following the quickstart documentation
  4. CONTRIBUTING.md exists with development setup instructions, PR guidelines, and code style notes
**Plans**: 2 plans
Plans:
- [x] 211-01-PLAN.md — Apache 2.0 LICENSE, README with features and quickstart, CONTRIBUTING.md
- [x] 211-02-PLAN.md — Public documentation review and final polish

</details>

### 🚧 v14.0 getgeolens.com Marketing Site (In Progress)

**Milestone Goal:** Launch a public marketing site at getgeolens.com that converts GIS analysts and IT managers in enterprise/government toward self-hosted community deployment, with a secondary enterprise contact path.

**Note:** This milestone lives in a separate repo (`getgeolens.com`), not the GeoLens monorepo. Phase work targets that repo.

- [x] **Phase 212: Repo Bootstrap and Design System** — Initialize the getgeolens.com repo with Astro 6, Tailwind 4, GeoLens brand tokens, Cloudflare Pages deployment, and accessible layout shell (SITE-01, SITE-02, SITE-03, SITE-04, SITE-05, A11Y-01, A11Y-03) (completed 2026-04-05)
- [x] **Phase 213: SEO Infrastructure** — Build BaseHead component, Satori OG image endpoint, sitemap/robots, and JSON-LD so every page gets correct SEO automatically (SEO-01, SEO-02, SEO-03, SEO-04) (completed 2026-04-05)
- [x] **Phase 214: Product Preview Assets** — Create the three CSS-rendered browser-frame product previews (search UI, map builder, dataset detail) that make the product tangible to evaluators (ASSET-01, ASSET-02, ASSET-03) (completed 2026-04-05)
- [ ] **Phase 215: Homepage** — Build the primary conversion surface with outcome-focused hero, trust bar, feature highlights, product preview, and quickstart teaser (HOME-01, HOME-02, HOME-03, HOME-04, HOME-05)
- [ ] **Phase 216: Features and Quickstart Pages** — Build the /features capability breakdown and /quickstart docker-compose walkthrough (FEAT-01, FEAT-02, FEAT-03, QUICK-01, QUICK-02, QUICK-03)
- [x] **Phase 217: Accessibility Audit and Launch Gate** — Verify WCAG 2.1 AA compliance across all pages with Axe scan, keyboard navigation testing, and pre-launch checklist (A11Y-02, A11Y-04) (completed 2026-04-12)

## Phase Details

### Phase 212: Repo Bootstrap and Design System
**Goal**: The getgeolens.com repo exists, deploys to Cloudflare Pages on every push, and the design system enforces GeoLens brand tokens and WCAG 2.1 AA contrast from the first component
**Depends on**: Nothing (first phase of this milestone; separate repo)
**Requirements**: SITE-01, SITE-02, SITE-03, SITE-04, SITE-05, A11Y-01, A11Y-03
**Success Criteria** (what must be TRUE):
  1. Pushing to main deploys the site to Cloudflare Pages within 60 seconds, and every PR gets a unique preview URL
  2. A visitor on a 375px phone, 768px tablet, and 1280px desktop sees a properly laid-out page with no horizontal scroll or clipped content
  3. The shared nav contains the GeoLens logo, links to Home/Features/Quickstart, and a GitHub link; the footer contains project links, license badge, and "Powered by GeoLens" attribution
  4. Emerald accent color passes WCAG 2.1 AA contrast (4.5:1) against white backgrounds, verified by checking the chosen shade against the WCAG formula
  5. Every page rendered from the layout shell includes semantic HTML landmarks (nav, main, footer) and a correct headings hierarchy
**Plans**: 2 plans
Plans:
- [x] 212-01-PLAN.md — Astro 6 project scaffold, Tailwind 4, OKLCH design tokens, CI/Cloudflare config
- [x] 212-02-PLAN.md — Layout shell: SiteLayout, Nav, Footer, stub homepage
**UI hint**: yes

### Phase 213: SEO Infrastructure
**Goal**: Every page added to the site automatically gets correct SEO — unique title, description, OG image, canonical URL, sitemap entry, and structured data — without per-page manual work
**Depends on**: Phase 212
**Requirements**: SEO-01, SEO-02, SEO-03, SEO-04
**Success Criteria** (what must be TRUE):
  1. Every page has a unique `<title>` and `<meta name="description">` tag — confirmed by building the site and diffing HTML across pages
  2. A 1200x630 OG image PNG is generated at build time for each page, and the `og:image` meta tag points to it — verified by checking `dist/` after `astro build`
  3. `sitemap.xml` lists all pages and `robots.txt` allows crawlers — both exist at the site root after build
  4. The homepage `<head>` includes a valid JSON-LD block with `@type: SoftwareApplication`, product name, description, license, and URL
**Plans**: 2 plans
Plans:
- [x] 213-01-PLAN.md — SEO meta tags (canonical, OG, Twitter Card), sitemap filter, JSON-LD on homepage
- [x] 213-02-PLAN.md — Satori OG image generation pipeline (install, font, endpoint, wiring)

### Phase 214: Product Preview Assets
**Goal**: Three self-contained Astro components render stylized browser-frame product previews of the GeoLens search UI, map builder, and dataset detail page using only CSS and inline HTML — no external images or live backend required
**Depends on**: Phase 212
**Requirements**: ASSET-01, ASSET-02, ASSET-03
**Success Criteria** (what must be TRUE):
  1. A CSS-rendered browser-frame component showing the GeoLens search/catalog UI (dataset cards, search bar, filter facets) renders correctly in isolation and in a page context
  2. A CSS-rendered browser-frame component showing the map builder UI (map canvas with a visible layer panel or toolbar) renders correctly in isolation and in a page context
  3. A CSS-rendered browser-frame component showing the dataset detail page (metadata fields, map thumbnail area) renders correctly in isolation and in a page context
**Plans**: 2 plans
Plans:
- [x] 214-01-PLAN.md — BrowserFrame wrapper + SearchPreview (search bar, filter tabs, 3 dataset cards with SVG quicklooks)
- [x] 214-02-PLAN.md — MapBuilderPreview, DatasetDetailPreview, and visual review test page
**UI hint**: yes

### Phase 215: Homepage
**Goal**: The homepage converts a first-time visitor by communicating what GeoLens solves in the first viewport, establishing procurement trust signals, and routing analysts toward the quickstart and IT managers toward enterprise contact
**Depends on**: Phase 213, Phase 214
**Requirements**: HOME-01, HOME-02, HOME-03, HOME-04, HOME-05
**Success Criteria** (what must be TRUE):
  1. The hero section leads with an outcome-focused headline (not a technology description), a subtitle, and a "Get Started" CTA that is visible without scrolling on a 1280px desktop
  2. A trust signal bar with Apache 2.0, OGC API Compliant, and Self-Hosted badges appears near the hero and is visible in the first or second viewport on desktop
  3. A feature highlights section below the fold shows 3-4 key capabilities with icons and short descriptions
  4. The search UI product preview (from Phase 214) is embedded in a browser frame on the homepage with no layout shift or missing content
  5. A quickstart teaser section with a link to the /quickstart page is present and reachable via normal scrolling
**Plans**: TBD
**UI hint**: yes

### Phase 216: Features and Quickstart Pages
**Goal**: A technical evaluator can see the full capability depth on /features with product evidence for each capability, and a developer can go from zero to a running GeoLens instance in under 10 minutes following only the /quickstart page
**Depends on**: Phase 215
**Requirements**: FEAT-01, FEAT-02, FEAT-03, QUICK-01, QUICK-02, QUICK-03
**Success Criteria** (what must be TRUE):
  1. The /features page has sections for search, map builder, data ingestion, raster/VRT, AI chat, and RBAC — each with a description and key points
  2. Each capability section on /features includes a stylized product preview component alongside the description text
  3. The /features page has an OGC API compliance section that lists supported conformance classes by name
  4. The /quickstart page provides a complete step-by-step path from zero to a running GeoLens instance via docker compose, with individually copyable code blocks for each command
  5. The /quickstart page ends with an expected outcome section describing what the user sees after completing the guide
**Plans**: TBD
**UI hint**: yes

### Phase 217: Accessibility Audit and Launch Gate
**Goal**: Every page passes WCAG 2.1 AA accessibility verification — zero critical or serious Axe violations, full keyboard navigability, and a Lighthouse accessibility score of 95 or above — meeting the bar required for government procurement evaluation
**Depends on**: Phase 216
**Requirements**: A11Y-02, A11Y-04
**Success Criteria** (what must be TRUE):
  1. Running Axe against every page returns zero critical or serious violations
  2. A user navigating with only the keyboard (Tab, Enter, Space, Arrow keys) can reach and activate every interactive element on every page: nav links, CTAs, and code copy buttons
  3. Lighthouse accessibility score is 95 or above on desktop and mobile for every page
**Plans**: TBD

### Phase 218: Demo Themed Collections
**Goal**: Replace the current foundation-only Natural Earth demo with three themed collections (Planet Earth — Physical Systems; Global Development & People; Borders, Boundaries & Contested Space) and nine signature maps, seeded deterministically at `docker compose up`, so a prospect landing on the self-hosted demo sees a decisive value story in under 60 seconds instead of a flat reference catalog
**Depends on**: none (independent of 215/216/217 marketing site phases — can run in parallel)
**Requirements**: TBD (draft from 260408-lnq-PROPOSAL.md)
**Plans**: TBD

**Key decisions locked from proposal (260408-lnq) and A7 spike (260408-mgg):**
- Three themes, one collection each — no single monolithic story, no smorgasbord
- Geopolitics embraced carefully: Natural Earth disputed layers + UCDP GED (ACLED rejected — 3 EULA conflicts), UNHCR, Marine Regions. Neutral sourced framing.
- Static snapshots only — no API keys, no outbound internet at runtime
- Automation posture: automate data ingest + collection assignment; hand-curate the 9 signature maps in the UI and export as JSON fixtures
- A7 resolved (UNSUPPORTED): `csv_to_choropleth.py` helper pre-joins indicator CSVs to ADM0 polygons at seeder build time before ingest (Option C)
- Signature map: "One Territory, Multiple Official Maps" (Kashmir toggle across 3 NE country-specific shapefiles) is the conversation-starter

### Phase 219: regenerate_vrt Phase Extraction
**Goal**: Split `regenerate_vrt` (`backend/app/ingest/tasks.py:2093`, 231 lines, ~7 nesting levels) into three helpers — `_build_vrt_to_temp(ordered_assets, vrt_type, resolution_strategy, tmp_dir) -> Path`, `_validate_and_extract_vrt_metadata(vrt_path) -> dict`, and `_update_vrt_dataset_geometry(session, vrt_asset, metadata)` — so the 15 documented steps stay readable without changing behavior
**Depends on**: Integration fixture coverage against a real tiny VRT (mock-free tests) must exist before this phase can start — pair with K3-PRE-style follow-up work
**Requirements**: TBD (draft from post-impl-20260410-HANDOFF-REMAINING.md §K4)
**Plans**: TBD

**Key decisions locked from handoff (post-impl-20260410, validated 2026-04-11 via quick task 260411-a62):**
- Raster VRT tests currently use heavy mocking (`tests/test_vrt_source_management_174.py::TestRegenerateVrtTask`) — extracting phases without behavior parity is hard to verify by mock alone
- Do not attempt until integration fixture coverage exists (mock-free tests against a real tiny VRT)
- Raster VRT has historical flakiness — test coverage is non-negotiable

### Phase 220: CommitRequest Discriminated Union
**Goal**: Split the flat `CommitRequest` (`backend/app/ingest/schemas.py:97`, 1 required + 13 optional fields) into a shared `BaseCommitRequest` + three discriminated subclasses (`VectorCommitRequest`, `RasterCommitRequest`, `ServiceCommitRequest`), and refactor `commit_import` at `backend/app/ingest/router.py:495-540` to validate the request body against a server-dispatched subclass chosen by `_pick_commit_subclass(job)` (mirroring the three-way branch in `service.py:477-506`). Zero wire format change, zero OpenAPI drift, zero frontend coordination — field-applicability rules move from prose descriptions into the type system.
**Depends on**: None (discuss-phase narrowed scope to internal backend refactor; the OpenAPI contract is preserved via Option C — flat `CommitRequest` stays on the route signature while the handler re-validates against the subclass)
**Requirements**: INGEST-K6-01, INGEST-K6-02
**Plans**: 1 plan
Plans:
- [x] 220-01-PLAN.md — Schema split (Base + 3 subclasses), `_pick_commit_subclass` dispatch helper, handler refactor with `RequestValidationError`, new `test_commit_request_schemas.py` unit tests, new `TestCommitImportDispatch` integration class, REQUIREMENTS.md backfill, K6 handoff resolution marker

**Key decisions locked from discuss-phase (2026-04-11, see `220-CONTEXT.md`):**
- **D-01 (Discrimination):** Server-derived from job state (Option C). Flat `CommitRequest` stays on the route signature for OpenAPI + auto-422 on `title`. Handler re-validates `request.model_dump()` against the subclass chosen by `_pick_commit_subclass(job)`. Client body NEVER includes a `file_type` field.
- **D-02 (Validation strictness):** Silent extras. No `model_config = ConfigDict(extra='forbid')` — kitchen-sink bodies still commit cleanly, matching current behavior.
- **D-03 (Backward compatibility):** Internal-only refactor. No deprecation window, no `Accept-Version` header, no dual-mode query parameter.
- **D-04 (Field distribution):** Base = `title`, `summary`, `visibility`, `temporal_start`, `temporal_end`. Vector = base + `srid_override`, `layer_name`, `x_column`, `y_column`, `geom_column`. Raster = base + `srid_override`, `compression`, `resampling`, `nodata_override`. Service = base + `token`. `srid_override` is duplicated on Vector + Raster (not hoisted). `token` is Service-only.
- **D-05 (Tests):** Three layers — Pydantic unit tests per subclass, router integration tests per file_type, negative kitchen-sink test. Establishes direct router coverage for `POST /ingest/commit/{job_id}` which had ZERO prior tests.
- **D-06 (Frontend):** Zero changes. `frontend/src/types/api.ts:531` stays flat.
- **Critical correction to CONTEXT.md D-01 (from research):** Service jobs are NOT discriminated by `user_metadata.file_type == "service"` (that string does not exist anywhere in the codebase). They are discriminated by `job.source_url` being set — the dispatch helper mirrors the three-way branch used by `queue_ingest_job` at `service.py:477-506`.

### Phase 221: get_sample_values Sparse-Column Default Bump
**Goal**: Bump the default `sample_size` parameter on `get_sample_values` (`backend/app/ingest/metadata.py:208`) from 1000 to 10000 so sparse columns (e.g. 99%-null columns) yield sample values within the existing `LIMIT 10` display cap, preserving the CTE-batched approach at lines 269-274 as-is
**Depends on**: None
**Requirements**: INGEST-N6-01, INGEST-N6-02
**Plans**: 1 plan
Plans:
- [x] 221-01-PLAN.md — Default bump (1000 → 10000), docstring scan-width/RAM caveat, TestSparseColumnSampleValues regression class, REQUIREMENTS.md backfill

**Key decisions locked from handoff (post-impl-20260410, validated 2026-04-11 via quick task 260411-a62):**
- The CTE approach is dramatically faster than the pre-audit per-column `LIMIT 1000` pattern — do not revert
- Be aware of the side effect on base scan width + RAM under extreme row counts when raising the default
- No user complaints have been filed as of 2026-04-11 — promoted from observational to actionable on 2026-04-11

### Phase 222: persistent_config.py Runtime Validation via TypeAdapter
**Goal**: Replace the 3 `cast(T, ...)` sites at `backend/app/persistent_config.py:84, 88, 113` with `TypeAdapter[T].validate_python(unwrapped)` for runtime shape validation at the JSONB unwrap boundary, accepting the breaking change to `PersistentConfig`'s constructor that this requires
**Depends on**: None, but carries breaking changes to every call site that constructs a `PersistentConfig` instance
**Requirements**: TBD (draft from post-impl-20260410-HANDOFF-REMAINING.md §Type-5)
**Plans**: TBD

**Key decisions locked from 2026-04-11 research (validated via quick task 260411-a62):**
- `PersistentConfig` is declared `Generic[T]` with `T = TypeVar("T")` — `TypeAdapter[T].validate_python()` cannot work as a drop-in replacement because `T` is unbound at method-resolution time
- Implementation path requires EITHER reifying `T` by storing the type at `__init__` time OR accepting an explicit `adapter: TypeAdapter[T]` parameter on the constructor — pick one when planning
- The existing `cast(T, ...)` pattern matches the rest of the codebase's approach at generic boundaries — this phase consciously diverges from that convention for runtime safety at the config boundary
- The SecretStr migration (commits `a6371f9f`, `56c59cfd`) touched `app/config.py` and consumers, NOT `app/persistent_config.py` — these 3 cast sites are byte-for-byte unchanged since snapshot `f6a7f96a`

## Progress

**Execution Order:** 212 → 213 → 214 → 215 → 216 → 217

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 206. Extension Seam Architecture | v13.0 | 3/3 | Complete | 2026-03-27 |
| 207. Branding Toggle | v13.0 | 2/2 | Complete | 2026-03-27 |
| 208. Audit Log Export | v13.0 | 2/2 | Complete | 2026-03-27 |
| 209. SAML SSO | v13.0 | 2/2 | Complete | 2026-03-27 |
| 210. Enterprise Overlay Repo | v13.0 | 2/2 | Complete | 2026-03-27 |
| 211. Licensing & Public Documentation | v13.0 | 2/2 | Complete | 2026-03-27 |
| 212. Repo Bootstrap and Design System | v14.0 | 2/2 | Complete    | 2026-04-05 |
| 213. SEO Infrastructure | v14.0 | 2/2 | Complete    | 2026-04-05 |
| 214. Product Preview Assets | v14.0 | 2/2 | Complete    | 2026-04-05 |
| 215. Homepage | v14.0 | 0/? | Not started | - |
| 216. Features and Quickstart Pages | v14.0 | 0/? | Not started | - |
| 217. Accessibility Audit and Launch Gate | v14.0 | 2/2 | Complete    | 2026-04-12 |
| 218. Demo Themed Collections | v14.0 | 5/5 | Complete    | 2026-04-09 |
| 219. regenerate_vrt Phase Extraction | v14.0 | 0/? | Not started | - |
| 220. CommitRequest Discriminated Union | v14.0 | 1/1 | Complete    | 2026-04-11 |
| 221. get_sample_values Sparse-Column Default Bump | v14.0 | 1/1 | Complete    | 2026-04-11 |
| 222. persistent_config.py Runtime Validation via TypeAdapter | v14.0 | 1/1 | Complete    | 2026-04-11 |

## Backlog

Unsequenced ideas captured for future milestones. Use `/gsd-review-backlog` to promote to an active milestone.

### Phase 999.1: 3D Viewer Toggle (Terrain + Extrusions) (BACKLOG)

**Goal:** Add a 3D mode toggle to `ViewerMap.tsx` that enables MapLibre terrain (via Titiler `terrainrgb` algorithm on DEM rasters) and building extrusions (via `fill-extrusion` layer reading a height column). Viewer-only — Builder 3D support is a separate follow-on.

**Source:** Promoted from quick task [260408-aa5](../quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md) — feasibility spike recommended shipping this as the first 3D slice. All 7 open questions resolved in the design doc.

**Sizing:** MEDIUM (~5-8 tasks, frontend-heavy)
**Dependencies:** None — works on data already in PostGIS
**Requirements:** TBD — draft from DESIGN.md §7 Phase A row

**Key decisions locked from design doc:**
- Session-only 3D toggle (no schema changes)
- Hardcoded terrain exaggeration `1.5`
- Soft DEM detection heuristic + manual `is_dem` override
- Embed-token smoke test is an acceptance criterion
- Warn in layer style editor when a bound height column is removed on re-upload
- Viewer-only scope; defer BuilderMap.tsx 3D

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.2: PostGIS 3D Geometry Detection & Metadata (BACKLOG)

**Goal:** Add backend detection of 3D geometry on ingest. Record `ST_NDims`, `ST_Is3D`, `ST_ZMin`, `ST_ZMax` on the dataset record. Surface Z range in the dataset detail UI ("This dataset has 3D geometry — Z range: 12m to 847m"). Optional attribute-promotion strategy for point geometries (`elev` column).

**Source:** Promoted from quick task [260408-aa5](../quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md) — the design doc's critical finding is that Z survives GeoLens ingestion but is invisible to MVT. This phase surfaces Z in metadata and makes it queryable.

**Sizing:** MEDIUM (6 tasks across 3 plans)
**Dependencies:** None — can parallelize with Phase 999.1
**Requirements:** [D-01, D-02, D-03, D-04, D-05, D-06]

**Key decisions locked from design doc:**
- Alembic migration adds `is_3d`, `n_dims`, `z_min`, `z_max` to the dataset model
- Attribute promotion for point geometries is in scope (new `elev` numeric column)
- POLYHEDRALSURFACE / TIN handling: defer the UI-warning decision; add a STATE.md decision entry when this phase is promoted

**Plans:** 3/3 plans complete
Plans:
- [x] 999.2-01-PLAN.md — Migration, model, detection function, API schema
- [x] 999.2-02-PLAN.md — Ingest integration, elev column promotion
- [x] 999.2-03-PLAN.md — Frontend types and Z range UI

### Phase 999.3: GeoJSON-Z Delivery Endpoint

**Goal:** Add `/api/datasets/{id}/features.geojson?include_z=true` endpoint returning RFC 7946 GeoJSON with Z coordinates. Hard cap at 5,000 features with truncation metadata. Full auth/RBAC parity. Frontend auto-switches MVT vs GeoJSON-Z for small 3D datasets with subtle "3D preview" indicator.

**Source:** Promoted from quick task [260408-aa5](../quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md) — this is the non-MVT delivery path needed to expose true PostGIS 3D geometry (not just attribute heights) to the client.

**Sizing:** LARGE (7 tasks across 3 plans)
**Dependencies:** Phase 999.2 must ship first (needs `is_3d` metadata)
**Requirements:** [D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08]

**Plans:** 3/3 plans complete
Plans:
- [x] 999.3-01-PLAN.md — Backend endpoint: service function, router, auth/RBAC, tests
- [x] 999.3-02-PLAN.md — Schema propagation + adapter/sync GeoJSON branching
- [x] 999.3-03-PLAN.md — Frontend data fetch wiring, 3D preview indicator, visual verification

### Phase 999.4: Shared Vector Staging Pipeline (ingest_file ↔ reupload_file) (BACKLOG)

**Goal:** Extract a shared `_ingest_vector_into_staging(session, job, file_path, target_table) -> tuple[dict, bool]` helper covering the 9 shared pipeline steps (validate → ogrinfo → ogr2ogr → rename_reserved_columns → DBF collision detect → ensure_geom → clip → add_4326 → grant) that currently duplicate ~150 lines between `ingest_file` (`backend/app/ingest/tasks.py:523`, 232 lines) and `reupload_file` (`backend/app/ingest/tasks.py:1106`, 223 lines). Both callers retain their own step-8+ paths (create_dataset vs `_apply_reupload_swap`).

**Source:** Promoted from [post-impl-20260410-HANDOFF-REMAINING.md](../../docs-internal/audits/post-impl-20260410-HANDOFF-REMAINING.md#k2-kiss-5--shared-vector-staging-pipeline-between-ingest_file-and-reupload_file) — validated against the working tree on 2026-04-11 via quick task `260411-a62`; all line numbers, effort estimates, and blockers still hold.

**Sizing:** LARGE (4-6h)
**Dependencies:** None — but requires careful test coverage for both vector ingest paths

**Key decisions locked from handoff:**
- `_apply_reupload_swap` (`backend/app/ingest/tasks.py:990`) atomic-swap dance (RENAME live→live_old, RENAME staging→live, DROP live_old with `SET LOCAL lock_timeout = '5s'`) stays separate from the shared staging helper — it is the one real architectural divergence between the two paths
- Shared helper covers steps 1-7; `ingest_file` then calls `_finalize_ingest` / `create_dataset`, while `reupload_file` calls `_apply_reupload_swap`
- Needs a dedicated plan, not a drive-by refactor — effort estimate 4-6h holds

**Plans:** 2 plans
Plans:
- [ ] 999.4-01-PLAN.md — StagingResult dataclass + _ingest_vector_into_staging helper extraction + caller rewiring + unit tests
- [ ] 999.4-02-PLAN.md — Integration tests with real ogr2ogr through both ingest and reupload paths

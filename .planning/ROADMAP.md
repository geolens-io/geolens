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
- 🔲 **v13.0 Open-Core Pre-Release** — Phases 206-211

## Phases

### v13.0 Open-Core Pre-Release

- [ ] **Phase 206: Extension Seam Architecture** — Protocol interfaces, entry_point loader, edition detection, enterprise-gated 404s, refactor existing boundary code (EXT-01, EXT-02, EXT-03, EXT-04, EXT-05)
- [ ] **Phase 207: Branding Toggle** — Removable "Powered by GeoLens" badge via PersistentConfig, enterprise-gated (COMP-04, COMP-05)
- [ ] **Phase 208: Audit Log Export** — Streaming CSV/JSON export with date range and event type filters (COMP-01, COMP-02, COMP-03)
- [ ] **Phase 209: SAML SSO** — Admin SAML IdP configuration, SP-initiated flow, assertion validation, user provisioning, login page integration (SAML-01, SAML-02, SAML-03, SAML-04, SAML-05)
- [ ] **Phase 210: Enterprise Overlay Repo** — geolens-enterprise scaffold, entry_points, compose override, separate Alembic branch, end-to-end proof (REPO-01, REPO-02, REPO-03, REPO-04)
- [ ] **Phase 211: Licensing & Public Documentation** — Apache 2.0 LICENSE, public README, quickstart, CONTRIBUTING.md (DOCS-01, DOCS-02, DOCS-03, DOCS-04)

## Phase Details

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
- [ ] 206-01-PLAN.md — Extension registry, protocols, defaults, edition detection, lifespan wiring
- [ ] 206-02-PLAN.md — Edition API endpoint, frontend useEdition() hook
- [ ] 206-03-PLAN.md — Refactor branding footer/badge to use edition seam

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
- [ ] 208-01-PLAN.md — Backend streaming CSV/JSON export endpoints with enterprise gating and tests
- [ ] 208-02-PLAN.md — Frontend split button UI, blob download, i18n
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
**Plans**: [to be planned]
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
**Plans**: [to be planned]

### Phase 211: Licensing & Public Documentation
**Goal**: The repository is ready for public consumption with proper licensing, clear documentation, and a working quickstart
**Depends on**: Phase 206-210 (all features complete, architecture stable)
**Requirements**: DOCS-01, DOCS-02, DOCS-03, DOCS-04
**Success Criteria** (what must be TRUE):
  1. Apache 2.0 LICENSE file exists at the repository root
  2. README.md describes the product for a first-time visitor: features, screenshots, and a 3-command quickstart (clone, docker compose up, open browser)
  3. A new user can go from `git clone` to a working deployment in under 10 minutes following the quickstart documentation
  4. CONTRIBUTING.md exists with development setup instructions, PR guidelines, and code style notes
**Plans**: [to be planned]

---

<details>
<summary>✅ v12.3 Map Builder Excellence (Phases 200-205) — SHIPPED 2026-03-21</summary>

- [x] **Phase 200: Adaptive Builder Shell** — Responsive sidebar, container queries, Sheet chat overlay (completed 2026-03-21)
- [x] **Phase 201: Accessibility Semantics Hardening** — Inert sidebar, dialog descriptions, axe E2E (completed 2026-03-21)
- [x] **Phase 202: Workflow Discoverability & Feedback** — Compact layers, state-aware Save, action grouping (completed 2026-03-21)
- [x] **Phase 203: Builder Architecture Extraction** — 3 composable hooks, MapBuilderPage 1131→481 lines (completed 2026-03-21)
- [x] **Phase 204: Builder Regression Coverage** — 35 Vitest + 8 Playwright E2E tests (completed 2026-03-21)
- [x] **Phase 205: Builder Test & i18n Fixes** — Basemap selector fix, useBuilderSave tests, keyboard E2E, alembic entrypoint (completed 2026-03-21)

</details>

<details>
<summary>✅ v12.2 Record Detail Stabilization (Phases 195-199) — SHIPPED 2026-03-19</summary>

- [x] **Phase 195: A11y Hardening** - Touch targets, keyboard focus, and contrast fixes across shared components (completed 2026-03-19)
- [x] **Phase 196: Collection Shell** - Semantic markup and mobile header for collection detail page (completed 2026-03-19)
- [x] **Phase 197: Responsive Headers** - Mobile-safe dataset headers with action overflow menus (completed 2026-03-19)
- [x] **Phase 198: Preview Resilience** - Bounded VRT retries, fallback states, and raster hero composition (completed 2026-03-19)
- [x] **Phase 199: Raster No-Tile Hero Fix** - Fix heroState for null tile_url rasters so no-tile badge is reachable (completed 2026-03-19)

</details>

<details>
<summary>✅ v12.1 UI/UX Polish (Phases 191-194) — SHIPPED 2026-03-18</summary>

- [x] **Phase 191: Accessibility** - Aria-labels, alt text, and focus indicators (completed 2026-03-17)
- [x] **Phase 192: Component Consistency** - Shared components, button variants, loading states (completed 2026-03-17)
- [x] **Phase 193: Layout, Search & Browser Polish** - Form spacing, icon sizes, search fallbacks, document titles (completed 2026-03-17)
- [x] **Phase 194: Admin, Collections & Responsive** - Audit timestamps, collections search, responsive tabs (completed 2026-03-18)

</details>

<details>
<summary>✅ v12.0 Record-First Discovery Architecture (Phases 183-190) — SHIPPED 2026-03-17</summary>

- [x] **Phase 183: Quick Wins** - OGC conformance, org/CRS filters (completed 2026-03-16)
- [x] **Phase 184: Design Pass / ADR** - 8 locked architectural decisions (completed 2026-03-16)
- [x] **Phase 185: Search & Discovery Foundation** - Facets, type badges, collection search, datetime (completed 2026-03-16)
- [x] **Phase 186: Asset Normalization & Publication** - Unified assets, STAC properties, publication lifecycle (completed 2026-03-16)
- [x] **Phase 187: STAC Export Layer** - STAC 1.1 endpoints and validation (completed 2026-03-16)
- [x] **Phase 188: VRT Lifecycle** - Generation tracking, regeneration, source health (completed 2026-03-17)
- [x] **Phase 189: UI Polish & Remaining Search** - Detail panels, keyword facets, ranking boosts (completed 2026-03-17)
- [x] **Phase 190: Tech Debt Cleanup** - Status endpoint wiring, dead code, URL fix, i18n (completed 2026-03-17)

</details>

<details>
<summary>✅ v11.0 Performance at Scale (Phases 178-182) — SHIPPED 2026-03-16</summary>

- [x] **Phase 178: Data & Instrumentation** (completed 2026-03-16)
- [x] **Phase 179: Baseline Measurement** (completed 2026-03-16)
- [x] **Phase 180: Database & Query Optimization** (completed 2026-03-16)
- [x] **Phase 181: Connection Pool & Cache Tuning** (completed 2026-03-16)
- [x] **Phase 182: Performance Regression Tests** (completed 2026-03-16)

</details>

<details>
<summary>✅ v10.1 VRT Raster Mosaics (Phases 171-177) - SHIPPED 2026-03-15</summary>

- [x] **Phase 171: VRT Schema + Titiler Configuration** (completed 2026-03-14)
- [x] **Phase 172: Source Compatibility Validation Module** (completed 2026-03-14)
- [x] **Phase 173: VRT Generation Module + Creation API** (completed 2026-03-14)
- [x] **Phase 174: Source Management + Delete Guard** (completed 2026-03-14)
- [x] **Phase 175: Catalog API Extension** (completed 2026-03-14)
- [x] **Phase 176: Frontend VRT Creator** (completed 2026-03-14)
- [x] **Phase 177: Frontend VRT Dataset Detail** (completed 2026-03-15)

</details>

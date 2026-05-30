# Roadmap: GeoLens

## Current Milestone: v1035 Builder, Maps & Export Bug Sweep

**Goal:** Close the defects surfaced by quick task 260530-ezw + its production-readiness QA pass — one anonymous data leak (security blocker), four map-builder rendering/visibility bugs, an export-access gap, an app-wide console error, and supporting hygiene/regression coverage — so the maps/builder/export surfaces are production-ready. Fixes to existing files only: no new deps, migrations, or user-facing features.

**Granularity:** Standard (contained bug sweep — 5 cohesive phases, not one-per-requirement).
**Coverage:** 12/12 requirements mapped.

## Phases

- [ ] **Phase 1156: Vector-Tile Egress Authorization (SEC-01)** — Gate vector-tile data + tokens on `record_status=='published'` for anonymous callers, mirroring the raster path. Security blocker, ships first.
- [ ] **Phase 1157: Backend Export Access + Route Hygiene (EXP-01, EXP-02, API-01)** — Allow anonymous export of public+published datasets; pin unpublished/private export denial; add the `/collections/{id}/items/` trailing-slash alias.
- [ ] **Phase 1158: Builder Layer Visibility & DEM Consolidation (BLDR-01, BLDR-02, BLDR-03, BLDR-04)** — Raster basemap stays below data; terrain eye toggles 3D; one DEM row + render-mode pill; color-relief companion honors parent visibility.
- [ ] **Phase 1159: Maps/Search UI & Blob Hygiene (MAPS-01, MAPS-02, HYG-01)** — Eliminate the duplicate `createRoot()` console error; pin the search-page quicklook blob-URL fix; move `registerBlobUrlRevocation` out of render.
- [ ] **Phase 1160: Live Playwright MCP Close-Gate (QA-01)** — Orchestrator-driven live MCP verification of all fixes plus the standard gate; final before tag.

## Phase Details

### Phase 1156: Vector-Tile Egress Authorization
**Goal**: Anonymous callers can no longer obtain MVT feature data or a valid HMAC tile token for a `public`-but-not-`published` (draft/ready/internal) vector dataset — the vector path now enforces the same `visibility=='public' AND record_status=='published'` contract as raster.
**Depends on**: Nothing (first phase — security blocker, ships/verifies independently)
**Requirements**: SEC-01
**Success Criteria** (what must be TRUE):
  1. An anonymous `GET /tiles/{table}/{z}/{x}/{y}.pbf` request for a public-unpublished vector dataset returns 401/404 (today returns 200 + 1842 bytes of feature data).
  2. An anonymous `GET /tiles/token/{id}/` and the batch-token endpoint for a public-unpublished dataset return 401/404 instead of minting a valid HMAC token.
  3. Clustered point tiles (`cluster_tile_endpoint`) inherit the same status-aware denial.
  4. A public+published vector dataset still serves tiles + tokens to anonymous callers (no over-gating regression); owner/admin/embed-token paths unchanged.
  5. A regression test pins the anonymous tile-token + `.pbf` denial on a public-unpublished dataset.
**Plans**: TBD

### Phase 1157: Backend Export Access + Route Hygiene
**Goal**: Anonymous users can download a published-public dataset in every export format, unpublished/private/restricted export stays denied, and the OGC items route resolves with or without a trailing slash.
**Depends on**: Phase 1156 (shares the same backend auth-model area; sequence after the security gate is verified)
**Requirements**: EXP-01, EXP-02, API-01
**Success Criteria** (what must be TRUE):
  1. An anonymous `GET /datasets/{id}/export?format=geojson` (and gpkg/shp/csv) on a public+published dataset returns a real export body instead of 401.
  2. The authenticated path still enforces the `export` capability check.
  3. Anonymous and non-owner export of private/restricted/unpublished datasets returns 401/403/404, pinned by a regression test (seed/construct a draft vector dataset).
  4. `GET /collections/{id}/items/` (trailing slash) resolves identically to the no-slash form instead of 404.
**Plans**: TBD

### Phase 1158: Builder Layer Visibility & DEM Consolidation
**Goal**: The map builder renders basemap/data ordering, DEM rows, and DEM/terrain visibility toggles the way users expect — raster basemaps never occlude data, the terrain eye actually toggles 3D, one DEM row replaces the confusing triple stack, and hypsometric tint hides with its parent.
**Depends on**: Phase 1156 (independent surface — frontend builder; may proceed in parallel, ordered after the blocker for sequencing)
**Requirements**: BLDR-01, BLDR-02, BLDR-03, BLDR-04
**Success Criteria** (what must be TRUE):
  1. With `basemap_position='top'`, a raster/imagery basemap stays below the data layers and does not occlude them (pinned by a unit test in `UnifiedStackPanel.basemap-drag.test.tsx`).
  2. Toggling the visibility eye on a terrain-mode DEM layer attaches/detaches the 3D terrain (`getTerrain()` becomes null when hidden, re-attaches when shown), pinned by a test on `effectiveTerrainEnabled`.
  3. The layer stack shows a single clearly-labeled row per DEM dataset with a render-mode pill, with no separate stand-alone terrain layer row, and duplicate "Copy N of M" metadata surfaces accidental double-adds.
  4. Hiding a hillshade DEM layer with hypsometric tint also hides its `-colorrelief` companion, pinned by a test.
  5. `e2e:smoke:builder` and vitest stay green.
**Plans**: TBD
**UI hint**: yes

### Phase 1159: Maps/Search UI & Blob Hygiene
**Goal**: The app no longer logs the duplicate `createRoot()` console error, the search-page quicklook blob-URL fix is regression-protected, and the blob-revocation registration no longer runs as a side-effect during hook render.
**Depends on**: Nothing functionally (frontend hygiene); sequence after Phase 1158 to keep frontend work cohesive
**Requirements**: MAPS-01, MAPS-02, HYG-01
**Success Criteria** (what must be TRUE):
  1. Loading home/search, `/maps`, and dataset detail produces zero `ReactDOMClient.createRoot() on a container that has already been passed to createRoot()` console errors, pinned by a console-error assertion on at least one route.
  2. A regression test covers the search-page quicklook thumbnails (`useQuicklook` + `lib/blob-url-cache.ts`) so the blob-URL revoke-on-eviction fix cannot regress into `ERR_FILE_NOT_FOUND`.
  3. `registerBlobUrlRevocation(queryClient)` is invoked from an effect/memoized init rather than during hook render in `use-map-thumbnail.ts` and `use-quicklook.ts`, with behavior unchanged.
**Plans**: TBD
**UI hint**: yes

### Phase 1160: Live Playwright MCP Close-Gate
**Goal**: Every fix is proven on the live stack via orchestrator-driven Playwright MCP, and the standard automated gate is green, before tagging v1035.
**Depends on**: Phases 1156, 1157, 1158, 1159
**Requirements**: QA-01
**Success Criteria** (what must be TRUE):
  1. Live MCP confirms: SEC-01 anonymous tile/token on a public-unpublished dataset is denied; BLDR-01 raster basemap at `position='top'` keeps data visible; BLDR-02 terrain DEM eye toggles 3D on/off (`getTerrain()` null/set); BLDR-04 hiding a hypso-tinted DEM hides the tint; EXP-01 anonymous CSV/GeoJSON export of a public dataset returns a real body; MAPS-01 target routes show 0 `createRoot` errors.
  2. Orchestrator drives all MCP directly (executor subagents lack `mcp__playwright__*` — project memory `playwright-mcp-orchestrator-only`).
  3. Standard gate green: `npm run typecheck` 0, vitest green, `e2e:smoke:builder` green, focused backend tiles/export pytest green, i18n parity, `make openapi-check` no-drift.
**Plans**: TBD
**UI hint**: yes

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1156. Vector-Tile Egress Authorization | 0/TBD | Not started | - |
| 1157. Backend Export Access + Route Hygiene | 0/TBD | Not started | - |
| 1158. Builder Layer Visibility & DEM Consolidation | 0/TBD | Not started | - |
| 1159. Maps/Search UI & Blob Hygiene | 0/TBD | Not started | - |
| 1160. Live Playwright MCP Close-Gate | 0/TBD | Not started | - |

---

## Historical Milestones

- ✅ **v1034 Raster Stretch & Colormap Completion** — Phases 1152-1155 (shipped 2026-05-30, local tag `v1034`; per-band multi-band stretch + configurable percentile/σ bounds + seeded single-band raster fixture; Playwright MCP close-gate found + fixed two latent v1031/v1032 defects — colormap/stretch controls in an unmounted component + builder-private paint keys 422'd on save; 8/8 reqs; audit tech_debt/CLEAR-TO-TAG) — see [archive](milestones/v1034-ROADMAP.md)
- ✅ **v1033 Builder Terrain, Label & Render-Mode QA** — Phases 1148-1151 (shipped 2026-05-29, local tag `v1033`, CHANGELOG [1.8.0]; DEM render-mode persistence fix (3D terrain restores on load; raster "Render as" no longer reverts) + layer-list label indicator + point render-as consolidation + hillshade dual-consumer guard + bounded band-stats cache; 9/9 reqs; audit tech_debt/0-blockers) — see [archive](milestones/v1033-ROADMAP.md)
- ✅ **v1032 Builder Carry-Forward Resolution** — Phases 1144-1147 (shipped 2026-05-28, local tag `v1032`, CHANGELOG [1.7.0]; contour control CUT — `maplibre-contour` 0.1.0 incompatible with maplibre-gl 5.x, no upstream fix — plus single-band raster `percentile`/`stddev` stretch via Titiler `/cog/statistics`; 7/7 reqs) — see [archive](milestones/v1032-ROADMAP.md)
- ✅ **v1031 Builder Render-Mode & Share Polish** — Phases 1140-1143 (shipped 2026-05-28, local tag `v1031`; hypsometric tint + single-band raster colormap + fill-pattern editor controls, OG-image social cards + SharePanel ≤2 weights, orchestrator-driven Playwright MCP close-gate; 8/9 reqs — EDITOR-DEM-04 contour deferred → v1032) — see [archive](milestones/v1031-ROADMAP.md)

- ✅ **v1030 Map Builder Polish Sweep** — Phases 1133-1139 (shipped 2026-05-28, local tag `v1030`; audit-first builder walkthrough, Tier-1 map bugs + ≤800px polish, AI confirm-before-apply Shape-B staging, per-render-mode editor controls, share chips/presets/branding, easy-wins, 3-viewport Playwright MCP close-gate; 44/44 reqs) — see [archive](milestones/v1030-ROADMAP.md)

- ✅ **v1029 DCAT 3.0** — Phases 1129-1132 (shipped 2026-05-27; DCAT-US Schema v3.0 export/validation routes, official schema foundation, docs, OpenAPI/SDK refresh, and Playwright MCP API close gate) — see [archive](milestones/v1029-ROADMAP.md)
- ✅ **v1028 Map Builder Product Polish** — Phases 1124-1128 (shipped 2026-05-25; Builder Notes clear/persistence fixes, AI unavailable-state polish, workflow regression gates, ADK showcase/shared/embed verification, active smoke path renamed from demo to showcase, no separate demo-instance release gate)
- ✅ **v1027 Map Builder Architecture Simplification** — Phases 1118-1123 (shipped 2026-05-25; builder architecture baseline, basemap controller, shared composition sync, editor scene extraction, typed layer actions, fixture DRY-up, and Playwright MCP target-map verification)
- ✅ **v1026 Mapbuilder Style Reconciler** — Phases 1112-1117 (shipped 2026-05-25; canonical style reconciliation across adapters, manual controls, AI chat actions, persistence/viewer parity, high-DPI sprite routing, terrain activation retry, and Playwright MCP close gate)
- ✅ **v1025 Mapbuilder Polishing** — Phases 1107-1111 (shipped 2026-05-25; ADK 3D Relief deep QA, layer metadata fixes, marketing cartography, Playwright close gate, lint closeout)
- ✅ **v1024 ADK High Peaks Marketing-Ready** — Phases 1101-1106 (completed locally 2026-05-24; ADK marketing data/maps, builder ordering, terrain controls, error hygiene, and Playwright close gate)
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
- 🚀 **1.0.0 Public Release** — Version reset; backend/frontend bumped to 1.0.0 (shipped 2026-04-01)
- ✅ **v13.1 Open-Core Separation P1** — Phases 212-219 (shipped 2026-04-29) — see [archive](milestones/v13.1-ROADMAP.md)
- ✅ **v13.2 Edition Lifecycle Hardening** — Phases 220-221 (shipped 2026-04-30) — see [archive](milestones/v13.2-ROADMAP.md)
- ✅ **v13.3 Boundary A+ Cleanup** — Phases 222-224 (shipped 2026-05-01) — see [archive](milestones/v13.3-ROADMAP.md)
- ✅ **v13.4 Boundary Closeout** — Phases 225-231 (shipped 2026-05-03) — see [archive](milestones/v13.4-ROADMAP.md)
- ✅ **v13.5 Enterprise Governance Seams** — Phases 232-235 (shipped 2026-05-03) — see [archive](milestones/v13.5-ROADMAP.md)
- ✅ **v13.6 Catalog Maps/Search Service Decomposition** — Phases 236-240 (shipped 2026-05-04) — see [archive](milestones/v13.6-ROADMAP.md)
- ✅ **v13.7 Manifest-Driven Catalog Automation** — Phases 241-245 (shipped 2026-05-04) — see [archive](milestones/v13.7-ROADMAP.md)
- ✅ **v13.8 Map Builder Advanced Styling** — Phases 246-251 (shipped 2026-05-06) — see [archive](milestones/v13.8-ROADMAP.md)
- ✅ **v13.9 Map Builder Closeout** — Phases 252-256 (shipped 2026-05-06) — see [archive](milestones/v13.9-ROADMAP.md)
- ✅ **v13.10 GH Issues Hygiene** — Phase 257 (shipped 2026-05-07) — see [archive](milestones/v13.10-ROADMAP.md)
- ✅ **v13.11 Map Builder Polish & Quality Sweep** — Phases 258-262 (shipped 2026-05-07) — see [archive](milestones/v13.11-ROADMAP.md)
- ✅ **v13.12 Pre-Public Security & Audit Hardening** — Phases 263-270 (shipped 2026-05-07) — see [archive](milestones/v13.12-ROADMAP.md)
- ✅ **v13.13 Backlog Sweep** — Phases 271-279 (shipped 2026-05-07) — see [archive](milestones/v13.13-MILESTONE-AUDIT.md)
- ✅ **v13.14 Smoke Stabilization** — Phases 280-282 (shipped 2026-05-08) — see [archive](milestones/v13.14-ROADMAP.md)
- ✅ **v1000 Map Stack and Basemap Layer Controls** — Phases 1000-1001 (shipped 2026-05-11) — see [archive](milestones/v1000-ROADMAP.md)
- ✅ **v1001 Map Builder UI/UX Polish Sweep** — Phases 1002-1007 (shipped 2026-05-11) — see [archive](milestones/v1001-ROADMAP.md)
- ✅ **v1002 Layer Sidebar + Add Dataset Redesign** — Phases 1008-1013 (shipped 2026-05-12) — see [archive](milestones/v1002-ROADMAP.md)
- ✅ **v1003 Builder v1 Hardening** — Phases 1014-1018 (shipped 2026-05-12) — see [archive](milestones/v1003-ROADMAP.md)
- ✅ **v1004 Builder Renderer Expansion** — Phases 1019-1022 (shipped 2026-05-12) — see [archive](milestones/v1004-ROADMAP.md)
- ✅ **v1005 Builder Point Cluster Foundation** — Phases 1023-1026 (shipped 2026-05-12) — see [archive](milestones/v1005-ROADMAP.md)
- ✅ **v1006 Large Dataset Cluster Scaling** — Phases 1027-1031 (shipped 2026-05-12) — see [archive](milestones/v1006-ROADMAP.md)
- ✅ **v1007 Release Hygiene** — Phase 1032 (shipped 2026-05-12) — see [archive](milestones/v1007-ROADMAP.md)
- ✅ **v1008 Map Builder Sidebar Redesign** — Phases 1033-1038 (shipped 2026-05-14) — see [archive](milestones/v1008-ROADMAP.md)
- ✅ **v1009 Map Builder v1.5 (Polish)** — Phases 1039-1044 (shipped 2026-05-15) — see [archive](milestones/v1009-ROADMAP.md)
- ✅ **v1009.1 Builder Smoke Polish** — Phase 1045 (shipped 2026-05-15) — see [archive](milestones/v1009.1-ROADMAP.md)
- ✅ **v1010 Builder Performance & Code Quality** — Phases 1046-1048 (shipped 2026-05-16) — see [archive](milestones/v1010-ROADMAP.md)
- ✅ **v1010.1 Live Playwright MCP Smoke** — Phase 1049 (shipped 2026-05-17) — see [archive](milestones/v1010.1-ROADMAP.md)
- ✅ **v1010.2 Builder Smoke Carryover** — Phase 1050 (shipped 2026-05-17) — see [archive](milestones/v1010.2-ROADMAP.md)
- ✅ **v1011 Map Builder Polish & Bug Sweep** — Phase 1051 (shipped 2026-05-18) — see [archive](milestones/v1011-ROADMAP.md)
- ✅ **v1011.1 Builder Hygiene Carryover** — Phase 1052 (shipped 2026-05-18) — see [archive](milestones/v1011.1-ROADMAP.md)
- ✅ **v1012 New-User Hardening + Reupload** — Phases 1053-1056 (shipped 2026-05-19, public tag `v1.2.1`)
- ✅ **v1013 Ingest Hardening** — Phases 1057-1060 (shipped 2026-05-20, local tag `v1013`, public tag `v1.3.0`) — see [archive](milestones/v1013-ROADMAP.md)
- ✅ **v1014 Security Audit Remediation** — Phases 1061-1064 (shipped 2026-05-20, local tag `v1014`, public tag `v1.4.0`) — see [archive](milestones/v1014-ROADMAP.md)
- ✅ **v1015 Ingest/Export Lifecycle Hardening** — Phases 1065-1070 (shipped 2026-05-20, local tag `v1015`, public tag `v1.5.0`) — see [archive](milestones/v1015-ROADMAP.md)
- ✅ **v1016 Hardening Sweep** — Phases 1071-1074 (shipped 2026-05-21, local tag v1016, public tag v1.5.1) — see [archive](milestones/v1016-ROADMAP.md)
- ✅ **v1017 Test Infra & Audit Tail** — Phases 1075-1079 (shipped 2026-05-21, local tag `v1017`, public tag `v1.5.2`)
- ✅ **v1018 Hygiene — v1017 Tech-Debt Tail** — Phases 1080-1083 (shipped 2026-05-21, local tag `v1018`, public tag `v1.5.3`) — see [archive](milestones/v1018-ROADMAP.md)
- ✅ **v1019 Hygiene Tail — v1018 Frontend + xdist + Process** — Phases 1084-1086 (shipped 2026-05-22, local tag `v1019`, public tag `v1.5.4`) — see [archive](milestones/v1019-ROADMAP.md)
- ✅ **v1020 Fixture Isolation** — Phases 1087-1090 (shipped 2026-05-22, local tag `v1020`, public tag `v1.5.5`) — see [archive](milestones/v1020-ROADMAP.md)
- ✅ **v1021 Docker Rebuild Sweep + Engine-level Retry** — Phases 1091-1093 (shipped 2026-05-23, local tag `v1021`, public tag `v1.5.6`) — see [archive](milestones/v1021-ROADMAP.md)
- ✅ **v1022 Parallel-Test Cascade Closure + Hygiene Tail** — Phases 1094-1097 (shipped 2026-05-24, local tag `v1022`, public tag `v1.5.7`) — see [archive](milestones/v1022-ROADMAP.md)
- ✅ **v1023 CI Live-Verify + OOS Hygiene Tail** — Phases 1098-1100 (shipped 2026-05-24, local tag `v1023`, public tag `v1.5.8`)

## Up Next (candidate milestone)

### Builder v2 — editor-control + layer-type expansion

_Promoted from backlog 999.18 on 2026-05-30. Run `/gsd-new-milestone` to split the sub-groups below into sequenced phases (1156+)._

Map Builder feature-expansion items deferred from v1030. Three sub-groups — split independently at milestone planning (effort ranges from small editor controls to whole new layer subsystems):

- _Editor convenience:_ **EDITOR-SYMBOL-04** categorical icon mapping with real distinct-value query (`useColumnDistinctValues` exists post-WALK-01); **EDITOR-BASEMAP-06** custom basemap style URL override (architecture-shaped).
- _Layer-type expansion:_ Text/Annotation layer ("Render as Text"); Draw/annotation layer (text + shapes); LiDAR support.

**Source:** `milestones/v1030-REQUIREMENTS.md` §"v2 Requirements"
**Estimated effort:** Split per sub-group — editor-convenience items are polish-sized; layer-type expansion is feature-milestone work.

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 1/1 plans complete
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.13: Persistent connector registry (BACKLOG — P2)

**Goal:** Greenfield Enterprise-tier feature — `Connector` ORM (id, type, config_jsonb, schedule, last_sync_at, owner_id) + `ConnectorAdapter` Protocol + Celery beat scheduler integration + encrypted credential vault. Distinct from current stateless probes at `backend/app/modules/catalog/sources/adapters/{wfs,arcgis,stac,ogcapi}.py`.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #8 (🔴) / §7 P2
**Estimated effort:** 2–3 weeks
**Tier:** Enterprise — stored credentials + scheduled mirroring is an explicit Enterprise paywall per `docs-internal/GTM/free-vs-enterprise.md` §6.

Plans:

- [ ] TBD

---

### Phase 999.14: Helm chart + AMI Packer pipeline (BACKLOG — P2)

**Goal:** Build a `deployment/` directory with Helm chart for K8s deployments + Packer template for AWS Marketplace AMI distribution. Phase 223 wired the `BillingExtension` for AMI metering, but there's currently no path to actually ship the AMI image to AWS Marketplace.
**Source:** `oc-separation-audit-20260430-b.md` §4 (HIGH severity — no `deployment/`, no Helm, no AMI pipeline) → confirmed unchanged in `oc-separation-audit-20260502.md` §4 (structural gap unchanged) / §7 P2 (action item #13)
**Estimated effort:** 1–2 weeks

Plans:

- [ ] TBD

---

### Phase 999.15: SBOM + signed image distribution (BACKLOG — P2)

**Goal:** Add SBOM generation (CycloneDX or SPDX) + Cosign-signed images to the deployment pipeline. Typical enterprise procurement gate.
**Source:** `oc-separation-audit-20260430-b.md` §4 finding #4 / §7 P2
**Estimated effort:** 1 week

Plans:

- [ ] TBD

---

### Phase 999.16: Extract geolens-schemas package (BACKLOG — P2)

**Goal:** Extract `backend/app/standards/{stac,ogc,dcat}/` schemas + validators into a standalone `geolens-schemas` PyPI package (Apache-2.0). Embedded today; persistent OSS-surface gap per audits since v13.1 close.
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — schema/validator package not extractable) → confirmed unchanged in `oc-separation-audit-20260502.md` §6.1 (still no `schemas/` or `validators/` dir) / §7 P2 (action item #12)
**Estimated effort:** 1 week
**Unblocks:** Schema-validator OSS adoption beyond GeoLens consumers; reusable wedge for FAIR-aligned tooling.

Plans:

- [ ] TBD

---

*Roadmap updated: 2026-05-30 — backlog review: promoted 999.18 → Up Next (Builder v2 candidate milestone); removed stale 999.17 + 999.19 (both shipped in v1031 Phase 1142).*

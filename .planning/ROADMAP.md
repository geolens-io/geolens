# Roadmap: GeoLens

## Current Milestone

### v1031 Builder Render-Mode & Share Polish

**Goal:** Close the v1030 builder carry-forward backlog — add four new render-mode editor controls (DEM/raster and fill surfaces), complete shared-link social cards, and tidy SharePanel typography — then prove it all on the live builder via intensive Playwright MCP smoke.

**Phases:**

- [x] **Phase 1140: Raster & Terrain Editor Controls** — Add contour-line overlay, hypsometric tint ramps, and single-band colormap controls to the DEM/RasterEditor surfaces (backend Titiler colormap path scoped at plan-phase) (completed 2026-05-28)
- [ ] **Phase 1141: Fill-Pattern Editor Control** — Add fill-pattern authoring (curated built-in sprite set) to FillEditor; plan-time sizing call on built-in selection vs custom-upload backend
- [ ] **Phase 1142: OG-Image Social Cards & SharePanel Typography** — Wire OG/Twitter card meta to shared map links via the canvas-capture pipeline (Path A vs B decided at plan-phase); reduce SharePanel to ≤2 font weights
- [ ] **Phase 1143: Quality Sweep & Playwright Close-Gate** — Intensive live Playwright MCP smoke of new controls + share/OG flow, typecheck/lint/vitest/backend-pytest/`e2e:smoke:builder`/i18n parity, CHANGELOG, and OpenAPI/SDK refresh

## Phase Details

### Phase 1140: Raster & Terrain Editor Controls
**Goal**: Users can configure contour overlays, hypsometric tints, and single-band colormaps for DEM and raster layers directly in the editor
**Depends on**: Nothing (first feature phase; independent of Phase 1141 and 1142)
**Requirements**: EDITOR-DEM-04, EDITOR-DEM-05, EDITOR-RASTER-COLORMAP
**Success Criteria** (what must be TRUE):
  1. User can toggle a contour-line overlay on a DEM/terrain layer and adjust line styling (interval, color, weight)
  2. User can select a preset hypsometric tint ramp on a terrain/DEM layer and see elevation banding update on the map
  3. User can pick a colormap and stretch type for a single-band raster layer, with the map tile re-rendering to reflect the selection
  4. Existing DEM/raster editor controls (hillshade sliders, opacity, etc.) remain unaffected by the additions
**Plans**: 4 plans
  - [x] 1140-01-PLAN.md — Backend raster colormap params (allowlist-validated) + nginx cache-key fix + band_count on MapLayerResponse [EDITOR-RASTER-COLORMAP]
  - [x] 1140-02-PLAN.md — DEM contour-line overlay (maplibre-contour) toggle/interval/color/weight + companion line layer [EDITOR-DEM-04]
  - [x] 1140-03-PLAN.md — DEM hypsometric tint (native color-relief) preset ramp picker, hillshade-gated [EDITOR-DEM-05]
  - [x] 1140-04-PLAN.md — Single-band raster COLORMAP section (band_count gate) + colormap tile-URL re-render [EDITOR-RASTER-COLORMAP]
**UI hint**: yes

### Phase 1141: Fill-Pattern Editor Control
**Goal**: Users can apply a fill-pattern from a curated built-in sprite set to a fill-render-mode layer via the FillEditor
**Depends on**: Nothing (independent of Phase 1140 and 1142; shares close-gate with Phase 1143)
**Requirements**: EDITOR-FILL-01
**Success Criteria** (what must be TRUE):
  1. User sees a pattern-selection control in FillEditor when a fill-render-mode layer is active
  2. User can choose from a curated set of built-in patterns and the layer updates on the map immediately
  3. User can clear a pattern and return to a solid fill without requiring a page reload
  4. Existing fill controls (color, opacity, extrusion hint) are unaffected
**Plans**: 1 plan
  - [ ] 1141-01-PLAN.md — Built-in fill-pattern catalog + idempotent map registrar, IconPicker-style FillPatternPicker, FillEditor wiring (set/clear via owned fill-pattern paint), 4-locale i18n [EDITOR-FILL-01]
**UI hint**: yes

### Phase 1142: OG-Image Social Cards & SharePanel Typography
**Goal**: Shared map links emit valid OG/Twitter card meta backed by a 1200×630 preview image, and SharePanel uses ≤2 font weights
**Depends on**: Nothing (independent feature surface; no dependency on Phase 1140 or 1141)
**Requirements**: SHARE-08, SHARE-10
**Success Criteria** (what must be TRUE):
  1. Opening a shared map link in a social card previewer (e.g., Twitter card validator, LinkedIn) shows a 1200×630 map thumbnail
  2. The shared-viewer HTML includes `<meta property="og:image">` and `<meta name="twitter:card">` tags with a resolved image URL
  3. SharePanel renders at most 2 distinct font weights across all content sites (labels, values, helper text, headings)
  4. The OG-image pipeline uses the existing canvas-capture infrastructure — no `@vercel/og` or `satori` introduced
**Plans**: TBD
**UI hint**: yes

### Phase 1143: Quality Sweep & Playwright Close-Gate
**Goal**: All v1031 new controls and share/OG flows are verified on the live builder and all quality gates are green
**Depends on**: Phases 1140, 1141, 1142
**Requirements**: QA-01, QA-02, QA-03
**Success Criteria** (what must be TRUE):
  1. Live Playwright MCP smoke (orchestrator-driven) against `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd` exercises each new render-mode control and the share/OG flow with a committed evidence file
  2. Frontend typecheck + lint + vitest, focused backend pytest, `e2e:smoke:builder`, and i18n parity (en/de/es/fr) all pass with zero new failures
  3. CHANGELOG is updated for v1031 with measured feature descriptions
  4. OpenAPI snapshot and Python/TypeScript SDK artifacts are regenerated where backend routes or schemas changed (e.g., OG-image routes under Path A, raster colormap params)
**Plans**: TBD

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1140. Raster & Terrain Editor Controls | 4/4 | Complete    | 2026-05-28 |
| 1141. Fill-Pattern Editor Control | 0/1 | Not started | - |
| 1142. OG-Image Social Cards & SharePanel Typography | 0/TBD | Not started | - |
| 1143. Quality Sweep & Playwright Close-Gate | 0/TBD | Not started | - |

## Historical Milestones

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

### Phase 999.17: SHARE-08 — OG-image / social-card meta on shared links (BACKLOG — P2)

**Goal:** Add OG-image / social-card meta to shared map links. The live thumbnail pipeline emits 400×250 JPEG only (`frontend/src/hooks/use-builder-save.ts:33-34`); `og:image` wants a 1200×630 variant. Two paths: **Path A** — nullable `og_image_uri` column (migration) + `PUT /maps/{id}/og-image/` upload route + `GET /maps/{id}/og-image/` serve route + a second frontend `doCapture` at 1200×630 (~1 day); **Path B** — backend receives the native canvas capture (~1440×900) and resizes to both variants on upload (~1.5 days). Either path then wires `og_image_uri` into the shared-viewer `<meta property="og:image">` tag.
**Source:** v1030 Phase 1133 WALK-05 disposition (2026-05-27) → `milestones/v1030-REQUIREMENTS.md` §"Future Requirements (v1031+)"; `milestones/v1030-phases/1133-audit-first-builder-walkthrough/1133-BUILDER-WALKTHROUGH-AUDIT.md#share-08-disposition`
**Estimated effort:** ~1–1.5 days (pick Path A or B in a planning audit)
**Constraint:** Do NOT add `@vercel/og` / `satori` — both on the STACK do-NOT-add list.
**Status:** Promoted to v1031 Phase 1142.

Plans:

- [ ] TBD

---

### Phase 999.18: Builder v2 feature register — editor-control + layer-type expansion (BACKLOG — P3)

**Goal:** Map Builder feature-expansion items deferred from v1030. Three sub-groups — promote independently (effort varies from small editor controls to whole new layer subsystems):

- _Render-mode expansion:_ **EDITOR-FILL-01** fill-pattern (sprite upload + selection flow); **EDITOR-DEM-04** contour-line overlay control; **EDITOR-DEM-05** hypsometric tint color ramps for terrain; **EDITOR-RASTER-COLORMAP** single-band stretch/colormap UI (depends on backend colormap-render path scoping).
- _Editor convenience:_ **EDITOR-SYMBOL-04** categorical icon mapping with real distinct-value query (`useColumnDistinctValues` exists post-WALK-01); **EDITOR-BASEMAP-06** custom basemap style URL override (architecture-shaped).
- _Layer-type expansion:_ Text/Annotation layer ("Render as Text"); Draw/annotation layer (text + shapes); LiDAR support.

**Source:** `milestones/v1030-REQUIREMENTS.md` §"v2 Requirements"
**Estimated effort:** Split per sub-group at promotion — render-mode/convenience are polish-sized; layer-type expansion is feature-milestone work.
**Status:** Render-mode sub-group promoted to v1031 Phases 1140-1141. Editor-convenience and layer-type expansion remain parked.

Plans:

- [ ] TBD

---

### Phase 999.19: SharePanel font-weight hygiene (F2) (BACKLOG — P3)

**Goal:** SharePanel renders 3 distinct font weights across 5 sites vs the UI-SPEC max-2; reduce to ≤2 weights. Cosmetic only — fold into any future builder polish pass.
**Source:** v1030 milestone audit — `v1030-MILESTONE-AUDIT.md` (F2, P3)
**Estimated effort:** <0.5 day
**Status:** Promoted to v1031 Phase 1142.

Plans:

- [ ] TBD

---
*Roadmap updated: 2026-05-28 — v1031 Builder Render-Mode & Share Polish active (Phases 1140-1143, 9/9 reqs mapped). Backlog 999.17/18/19 render-mode + share items promoted to v1031; editor-convenience + layer-type expansion remain parked in 999.18.*

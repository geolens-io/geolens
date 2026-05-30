# Roadmap: GeoLens

## Historical Milestones

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

## Current Milestone: v1034 Raster Stretch & Colormap Completion

### Phases

- [x] **Phase 1152: Single-Band Raster Fixture** - Seed a uint8 non-DEM single-band COG via the seed script; hard gate for all subsequent stretch/colormap verification (completed 2026-05-29)
- [x] **Phase 1153: Backend — Multi-Band Stretch + Configurable Bounds** - Fix `n_bands=1` call site for per-band multi-band rescale; spike Titiler `p=` support then wire `pmin`/`pmax`/`sigma` params + compound cache key (completed 2026-05-29)
- [ ] **Phase 1154: Frontend Controls + Cleanup** - Widen stretch gate to multi-band; add pmin/pmax/sigma inputs; stretch-colormap hint copy; remove v1033 dead code
- [ ] **Phase 1155: Close-Gate** - Orchestrator Playwright MCP: multi-band stretch on RGB ortho + single-band stretch/colormap on TESTDATA-01 fixture; standard test gates

## Phase Details

### Phase 1152: Single-Band Raster Fixture
**Goal**: A real non-DEM single-band uint8 raster is available in the system so all subsequent colormap and stretch UI verification runs against actual data rather than a DEM that silently bypasses all stretch/colormap logic
**Depends on**: Nothing (first phase)
**Requirements**: TESTDATA-01
**Success Criteria** (what must be TRUE):
  1. Running the seed script ingests a small uint8 single-band GeoTIFF (e.g. Natural Earth `GRAY_50M_SR` or a GDAL-generated synthetic COG) and completes without error
  2. `SELECT is_dem FROM catalog.raster_assets WHERE dataset_id = '<fixture_id>'` returns `false` — the dataset is NOT routed through `algorithm=terrainrgb`
  3. Re-running the seed script skips the fixture (idempotent — no duplicate ingest)
  4. The fixture is acquired at seed time (downloaded or generated during script execution), never at pytest time
**Plans**: 1 plan
  - [x] 1152-01-singleband-raster-fixture-PLAN.md — seed an idempotent single-band uint8 GRAY_50M_SR raster fixture; verify band_count==1 + is_dem=false
**UI hint**: yes

### Phase 1153: Backend — Multi-Band Stretch + Configurable Bounds
**Goal**: The backend correctly computes an independent per-band rescale for multi-band rasters AND accepts configurable percentile/sigma bounds that are properly isolated in the stats cache — so a 3-band ortho produces 3 `rescale=` fragments and changing `pmin` from 2 to 5 actually changes the served tiles
**Depends on**: Phase 1152 (fixture required for backend smoke verification)
**Requirements**: RASTER-STRETCH-03 (backend), SPIKE-01, RASTER-STRETCH-UI-01 (backend)
**Success Criteria** (what must be TRUE):
  1. SPIKE result recorded: `curl http://localhost:8000/cog/statistics?url=<path>&p=5&p=95` against the running Titiler 2.0.2 container returns `percentile_5` and `percentile_95` keys (or the spike documents an alternative approach if not)
  2. A tile request for a 3-band raster with `stretch=percentile` produces a Titiler URL containing exactly 3 `rescale=` fragments — one per band — confirmed by a unit test asserting the fragment count
  3. Two requests for the same asset with different `pmin`/`pmax` values produce different cache entries in `_band_stats_cache` (key is `(open_path, pmin, pmax)`) and different `rescale=` values in the Titiler URL
  4. A request with invalid bounds (e.g. `pmin=95&pmax=5`, `sigma=-1`) is rejected with HTTP 422 before reaching Titiler
**Plans**: 1 plan
  - [x] 1153-01-multiband-configurable-bounds-PLAN.md — multi-band n_bands fix + pmin/pmax/sigma params + bounds-keyed stats cache + 422 validation; closes SPIKE-01

### Phase 1154: Frontend Controls + Cleanup
**Goal**: The RasterEditor exposes stretch controls for multi-band rasters, lets users configure percentile bounds and sigma, shows a coupling hint on single-band rasters, and the v1033 dead code is removed — without breaking any existing vitest or smoke tests
**Depends on**: Phase 1153 (backend must accept pmin/pmax/sigma before frontend sends them)
**Requirements**: RASTER-STRETCH-03 (frontend gate), RASTER-STRETCH-UI-01 (frontend), RASTER-STRETCH-UI-02, CLEANUP-01
**Success Criteria** (what must be TRUE):
  1. The stretch section (minmax/percentile/stddev selector) is visible in the RasterEditor for a multi-band raster layer; the colormap section remains hidden for multi-band
  2. When stretch is set to `percentile`, two numeric inputs for pmin and pmax appear; when stretch is `stddev`, a sigma control (1/2/3) appears; changing either causes the tile URL to update with the new params
  3. On a single-band raster with stretch not equal to `minmax` and colormap not equal to `gray`, the coupling hint ("Stretch sets the input range for the colormap") is visible below the stretch control
  4. The dead `onRenderModeChange` optional member is absent from `LayerStyleEditor/types.ts`; `demEditor.hillshadeTerrainNote` i18n key and its advisory display are removed or made reachable; `npm run typecheck` exits 0 and vitest is green
**Plans**: 2 plans
- [x] 1154-01-PLAN.md — buildColormapTileUrl forwards _pmin/_pmax/_sigma (non-default only) + unit tests
- [ ] 1154-02-PLAN.md — RasterEditor gate-split + percentile/sigma controls + stretch-colormap hint + i18n + CLEANUP-01 hillshade note removal
**UI hint**: yes

### Phase 1155: Close-Gate
**Goal**: The complete raster stretch/colormap feature is verified end-to-end against real data with Playwright MCP — tile URLs carry the expected params, tile output visibly differs across stretch modes, and all standard gates are green — so the milestone can be tagged
**Depends on**: Phases 1152, 1153, 1154
**Requirements**: VERIFY-01, QA-01
**Success Criteria** (what must be TRUE):
  1. On the TESTDATA-01 single-band fixture in the live builder: switching stretch mode (minmax/percentile/stddev) produces distinct tile response sizes OR visually distinct map output, and the emitted Titiler tile URL carries the expected `rescale=` and `colormap_name=` params — not merely HTTP 200
  2. On an existing RGB multi-band raster in the live builder: the stretch section is visible, the colormap section is hidden, and applying percentile stretch produces a Titiler URL with 3 `rescale=` fragments
  3. Configuring non-default pmin/pmax (e.g. 5/95) on the single-band fixture changes the emitted tile URL and the map re-renders — confirming configurable bounds reach Titiler
  4. `npm run typecheck` 0 errors, vitest green, `e2e:smoke:builder` green, focused backend raster/tile pytest green, i18n parity, `make openapi-check` no-drift (no API surface change expected); 0 console errors per surface in Playwright MCP
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1152. Single-Band Raster Fixture | 1/1 | Complete   | 2026-05-29 |
| 1153. Backend — Multi-Band Stretch + Configurable Bounds | 1/1 | Complete   | 2026-05-29 |
| 1154. Frontend Controls + Cleanup | 1/2 | In Progress|  |
| 1155. Close-Gate | 0/? | Not started | - |

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

### Phase 999.18: Builder v2 feature register — editor-control + layer-type expansion (BACKLOG — P3)

**Goal:** Map Builder feature-expansion items deferred from v1030. Three sub-groups — promote independently (effort varies from small editor controls to whole new layer subsystems):

- _Editor convenience:_ **EDITOR-SYMBOL-04** categorical icon mapping with real distinct-value query (`useColumnDistinctValues` exists post-WALK-01); **EDITOR-BASEMAP-06** custom basemap style URL override (architecture-shaped).
- _Layer-type expansion:_ Text/Annotation layer ("Render as Text"); Draw/annotation layer (text + shapes); LiDAR support.

**Source:** `milestones/v1030-REQUIREMENTS.md` §"v2 Requirements"
**Estimated effort:** Split per sub-group at promotion — editor-convenience are polish-sized; layer-type expansion is feature-milestone work.

Plans:

- [ ] TBD

---

*Roadmap updated: 2026-05-29 — v1034 roadmap created (phases 1152-1155).*

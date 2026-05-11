# GeoLens

## What This Is

An on-premises, PostGIS-native GIS data catalog that lets GIS analysts, data engineers, and non-technical staff search, preview, and export geospatial datasets — both vector and raster — through a fast, search-first web UI. Built on a "database-first" architecture using FastAPI for catalog, tile serving (ST_AsMVT for vector, Titiler for raster), feature serving, metadata, search, RBAC, and job orchestration.

Shipped 50 milestones (v1.0-v1.6, v1.8-v1.9, v2.0-v2.6, v3.0-v7.0, v7.2-v7.3, v8.0-v8.2, v9.0-v9.1, v10.0-v13.8; plus cross-repo marketing/docs milestones). Production-hardened with refresh token auth, non-root containers, Trivy CI scanning, Prometheus metrics, automated S3 backups, Redis circuit breaker, magic byte file validation, and route-based code splitting. Cloud-ready with provider-agnostic storage (S3), caching (Redis/Valkey), managed database support, and presigned uploads. Full-featured GIS catalog with faceted search (FTS + pgvector + keyword/org/CRS facets + ranking boosts), map preview, export, collections, layer creation/editing, AI-assisted map building, related dataset discovery, raster dataset support (COG ingest, tile serving, export), VRT mosaics with lifecycle management, STAC 1.1 export for raster interop, publication lifecycle (draft/ready/internal/published), declarative `geolens.yaml` catalog manifests, and internationalization (i18n). Map builder is a complete cartographic authoring surface: clean `style_config`/`paint` separation, incremental layer save with stable layer IDs, first-class raster/line/zoom-expression controls, DEM hillshade with map-level terrain, MapLibre style JSON export/import round-trip, sprite-backed symbol/icon layers, and durable map edit history with builder History panel. Accessible UI with 44px mobile touch targets, keyboard-focusable tables, WCAG AA badge contrast, semantic collection markup, responsive detail headers, and raster/VRT preview resilience with bounded retry. Deployable by other organizations via `docker compose up`, then automatable through `geolens init`, `geolens validate`, and `geolens apply`.

## Current State

51 milestones delivered (v1.0-v1.6, v1.8-v1.9, v2.0-v2.6, v3.0-v7.0, v7.2-v7.3, v8.0-v8.2, v9.0-v9.1, v10.0-v13.9; plus v14.0 marketing site shipped from `getgeolens.com` repo on 2026-04-13). v1.7 Marketplace & Distribution paused at Phase 40 (AWS AMI Build). Open-core architecture is **A-grade ship-ready** — Apache 2.0 licensed core, enterprise extensions register via `importlib.metadata` entry_points, auto-generated Python + TypeScript SDKs from `backend/openapi.json`, Apache-2.0 `geolens` CLI on PyPI (login/scan/publish/export-stac/init/validate/apply), SAML enterprise overlay with SP-initiated SSO + JIT provisioning + audited attribute→role mapping, documented + tested edition lifecycle (operator runbooks, admin SAML→local conversion endpoint, round-trip symmetry test), **fully extensible audit + billing + AI + governance seams** (`AuditSink`, `BillingExtension`, `AIProviderExtension`, `EmbeddingProviderExtension`, `PermissionExtension`, `WorkflowExtension`), bidirectional catalog/processing boundaries enforced through `ProcessingPort` + `CatalogPort` architecture guards, maps/search service facades protected by private-module import guards plus size-budget checks, declarative manifest automation for first-catalog adoption, and a complete map-builder cartographic authoring stack with full MapLibre line-gradient authoring + style JSON round-trip. Latest v13.9 milestone closed v13.8 inherited tech debt (architecture-guard regressions, Nyquist VALIDATION.md backfill, openapi-python-client warning) and shipped first-class line-gradient authoring deferred from Phase 247 — 19/19 requirements satisfied, audit passed.

The marketing and documentation web properties (v14.0 + v15.0 + 999.5 cross-repo style alignment) and their planning artifacts moved to the `getgeolens.com` repo on 2026-04-26 — see `~/Code/getgeolens.com/.planning/` for active docs-site work.

## Recent Shipped Milestone: v1001 Map Builder UI/UX Polish Sweep

**Shipped:** 2026-05-11

**Goal delivered:** Make the Map Builder feel coherent, efficient, and trustworthy across the full create/edit/style/preview/share workflow on desktop, tablet, and mobile.

**Delivered:**
- Broad workflow sweep across create/edit/style/preview/share paths, including empty/loading/error/saved/dirty states.
- Inspector and Map Stack polish that reduces density, clarifies hierarchy, and keeps layer/style/basemap/relief controls predictable.
- Save/share/public-output parity for stable layer identity and publication state.
- Auth shell, mobile sheet, touch target, copy, i18n, and basemap recovery hardening.
- Durable QA coverage for polished builder flows: focused Vitest, builder Playwright, builder/public accessibility, and builder smoke without the sidebar drag-handle flake.

**Functional reference:** Use Kepler.gl as a guide for how builder functionality should behave - especially layer workflow, filtering, interactions, map settings, and save/export semantics - but do not copy Kepler.gl's visual style. GeoLens keeps its own product design language and MapLibre-based architecture.

**Milestone close:** 38/38 requirements satisfied across Phases 1002-1007. Audit: passed. See `.planning/milestones/v1001-ROADMAP.md` and `.planning/milestones/v1001-MILESTONE-AUDIT.md`.

## Recent Backlog Completion: v1000 Map Stack (shipped 2026-05-11)

**Delivered:** Unified Map Stack UX, normalized Surface/Relief/Basemap/Data/Labels/Interactions model, persisted curated `basemap_config`, explicit z-order policy, relief/terrain presentation polish, Playwright MCP visual QA evidence, public-viewer basemap rendering parity, and authenticated public DEM metadata preservation.

- Public shared-token and authenticated map viewers now pass persisted `basemap_config` into `ViewerMap`.
- `ViewerMap` reuses the builder `applyBasemapConfigToMap` transform with the `viewer-source-` managed-source prefix after load, `style.load`, and runtime config/label changes.
- `PublicMapViewerPage.toSharedLayer` preserves `is_dem` and `dem_vertical_units` so authenticated public saved maps keep DEM relief semantics before `ViewerMap`.
- Focused verification passed: `PublicMapViewerPage`, `ViewerMap.basemap-config`, `map-stack`, and frontend lint.

## Last Milestone (this repo): v13.13 Backlog Sweep (shipped 2026-05-07)

**Delivered:** 9 phases (271-279), 130/130 requirements satisfied, ~106 source-file commits — see [milestones/v13.13-ROADMAP.md](milestones/v13.13-ROADMAP.md) and [milestones/v13.13-MILESTONE-AUDIT.md](milestones/v13.13-MILESTONE-AUDIT.md).

- **154 deferred M+L v13.12 findings reorganized into 130 REQ-IDs and cleared.** Phases were domain-grouped: DB → Docker → Security → Performance → API/Docs → Code Quality → i18n/Env → Tests → Admin/Close.
- **Hybrid-shape milestone via `/gsd-autonomous` orchestration:** ~30 parallel `gsd-executor` agent spawns; planner agents per phase via `gsd-planner`. Reused the v13.12 audit-shape but with finer-grained per-domain phases.
- **Frontend wins:** map-vendor 1052kB chunk now off-route, DatasetPage 217kB → 34kB (-84%), AttributeTable virtualized for 10k+ rows, store relocation to `src/stores/`, builder i18n complete (zoomExpression + symbol + raster + hillshade + uploadIcon translated to es/fr/de — 135 strings).
- **Backend wins:** chat_service.py 1013 LOC decomposed into 5 sub-modules behind a Phase-226-style facade. 113 broad-except sites annotated. Architecture-guard 1500-LOC cap on routers + size-budget rule for AI sub-modules. `WORKER_SHUTDOWN_TIMEOUT` and `ENV_ONLY_CONFIG` migrated from raw `os.environ.get` to Pydantic Settings. `PUBLIC_BASE_URL` soft-deprecated.
- **Security wins:** SVG sanitization (defusedxml + CSP isolation), download-scoped JWT, origin-allowlist enforcement, SSRF re-validation on COG redirect, 32-byte share-token entropy, OAuth Referrer-Policy: no-referrer, SessionMiddleware https_only (prod), structlog field redaction, embed-iframe sandbox tightened, PIL.Image.verify() thumbnail gate.
- **API wins:** `POST /maps/import` typed body (no more `additionalProperties: true`), CHANGELOG `[Unreleased]` populated for v1.1.0 readiness, README counts/badges/build-time corrected, `docs/api-style.md` documents conventions.
- **Test wins:** Backend coverage gate 58.5 → 60. Frontend coverage thresholds ratcheted up across all 4 dimensions. 6 raw `waitForTimeout` calls in E2E specs replaced with deterministic locator polling. 35 inline `pytest.skip` calls migrated to decorator form.
- **Admin wins:** ApiKey `max_length=255` lock, audit-log search rewritten to `lower(unaccent(...))` form (uses pg_trgm GIN indexes from v13.12 Alembic 0010), AdminAuditPage page-guard, server-driven enterprise-tabs registry, audit-export format dispatcher unified, MinIO image bumped + sha256-pinned, non-blocking license-checker CI job added.
- **Deferred at close (4 items):** SEC-14 (CI carve-out for pip CVE-2026-6357 — runner image still ships pip 26.0.1, retry after pip 26.1 base-image refresh); SEC-07 + CODE-05 + TEST-10 Playwright MCP UAT visual confirmations (DOM-level substitutes + reviewer commands documented).

**Known close caveats:**
- ~10 commit-message attribution orphans from parallel-agent staging races (functional state at HEAD is correct; same race pattern as v13.12 Phase 269).
- Pre-existing typecheck error in `frontend/src/components/builder/__tests__/preserve-drawing-buffer.test.ts` from v13.13 Phase 274-06 (uses `node:fs`/`node:path` without `@types/node`). Vitest at runtime works fine. Surfaced/confirmed out-of-scope by ~6 plans across the milestone.
- `test_no_catalog_imports_processing` regex false-positive on a comment line in `service_public.py:186` — pre-existing on clean main, surfaced repeatedly out-of-scope.

## Prior Shipped Milestone: v13.12 Pre-Public Security & Audit Hardening (shipped 2026-05-07)

**Delivered:** 8 phases (263-270), 32/32 requirements satisfied — see [milestones/v13.12-ROADMAP.md](milestones/v13.12-ROADMAP.md).

- **17-audit sweep dispatched and consolidated** — 193 findings (2C / 37H / 83M / 71L) classified across security, infra, API, docs, perf, code, i18n, OSS dimensions; all sourced under `.planning/audits/v13.12/`.
- **All 39 Critical+High findings remediated inline** — 2 Critical (README seed-natural-earth bug; tile SQL no per-tile LIMIT) + 37 High closed across 4 parallel remediation agents in Phases 268-269. 5 new Alembic revisions (`0008..0012`). Boundary integrity remained A+/A+/A/A throughout.
- **154 Medium+Low findings deferred to backlog** — `.planning/backlog/v13.12-medium-findings.md` (83 M) and `.planning/backlog/v13.12-low-findings.md` (71 L) with rationale + target follow-up.
- **PUBLIC-READINESS.md committed at repo root** (commit `39fcb22b`) — composite grade **A−**, recommendation **CONDITIONAL-GO** with 3 deployment-scope conditions: (1) operators regenerate `JWT_SECRET_KEY` (H-28); (2) public repo recreation per `2026-05-05-recreate-public-repo-before-launch.md` todo; (3) CHANGELOG `[Unreleased]` populated and tagged v1.1.0 (H-02 PUT thumbnail body change).
- **Hybrid-shape milestone validated** — 4 audit-dispatch phases (263-266) with 17 parallel investigation agents → 1 triage phase → 2 remediation phases with 6 parallel fix agents → 1 verification phase. Total agents-orchestrated: ~24. Pattern reusable for future audit-driven hardening milestones.
- **Race-condition notes** — 3 commit-message orphan attributions in Phase 269 (H-04, SDK regen, H-16); functional state at HEAD is correct.

**Known close caveats:**
- Distribution & supply chain (DIST-01..04: Helm + SBOM + signed images + AMI) explicitly OUT OF SCOPE for v13.12 — recommend follow-up milestone for procurement-driven adopters.
- OSS launch posture (OSS-01..04) tracked separately at `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`.
- 176 standing deferred items acknowledged at close (175 cross-milestone `quick_tasks` + 1 pending todo).

## Earlier Milestone (this repo): v13.11 Map Builder Polish & Quality Sweep (shipped 2026-05-07)

**Delivered:** 5 phases (258-262), 6 plans, 17/17 requirements satisfied — see [milestones/v13.11-ROADMAP.md](milestones/v13.11-ROADMAP.md).

- **Phase 256 UI audit closure (BUILDER-POLISH-01) shipped** — gradient preview swatch (POLISH-01 BLOCKER) lands as a `data-testid="line-gradient-preview-swatch"` div with inline `linear-gradient(to right, ...)` style, gated to canonical-gradient mode only; per-row "Color" label noise removed (POLISH-02 — `label=""` in gradient mode); Solid/Gradient toggle gains focus ring + `cursor-pointer` (POLISH-03); advanced-expression disclosure spans full panel width (POLISH-04); each stop row carries a visible `pos` prefix span (POLISH-05); stable per-stop React keys via optional `id?: string` field on builder JSONB shape (POLISH-06 — canonical paint expression byte-identity preserved per v13.9 GRAD-05/06); trash button wrapped in shadcn `<Tooltip>` (POLISH-07).
- **Copy + i18n shipped** — `advancedHint` rewritten to drop "interpolate-linear-line-progress" jargon (COPY-01); real es/fr/de translations of the 16-key `lineGradient` block (COPY-02) — no English fallbacks remain in those locales for this block.
- **Builder quality sweep shipped** — orange `bg-warning` unsaved-changes dot on the Save button when there are uncommitted edits (QUALITY-01); `cursor-pointer` added to the shadcn Button cva base (propagates everywhere) plus 17 builder file native-button updates (QUALITY-02); single unguarded `console.warn` in `map-sync.ts` wrapped in `import.meta.env.DEV` guard — runtime console clean in production (QUALITY-03); BuilderMap NavigationControl moved bottom-right → top-right matching ViewerMap convention across public/share/embed surfaces (QUALITY-04).
- **Layer visibility debug + audit shipped** — `LabelEditor.handleToggle` no longer silently no-ops when `columns[0]` is unavailable; the Switch now disables with a tooltip when no columns exist (LAYER-01). Full audit of visibility code paths across LayerItem Eye toggle, LabelEditor Switch, syncLayersToMap, ChatPanel AI tools, removeStaleSourcesAndLayers, reorderDataLayers, hillshade companion, render-mode swap, and filter-changes — no other regressions surfaced (LAYER-02).
- **Close hygiene shipped** — MEMORY.md updated for BUILDER-POLISH-01 closure with full v13.11 milestone entry (CLOSE-01); `2026-05-07-phase-256-ui-audit-blocker-backlog-gradient-preview-swatch.md` moved to `.planning/todos/done/` with frontmatter `status: closed, shipped_in: v13.11` (CLOSE-02).
- **Hybrid-shape milestone validated** — Phase 258 ran the full skill chain (smart discuss → minimal UI-SPEC → plan-phase → execute-phase → code-review with WR-01 + IN-02 fixed inline → 258-VERIFICATION.md). Phases 259-262 ran inline with focused executor agents and direct edits. Each path produced a SUMMARY with per-REQ landing notes; full CI gate (`tsc --noEmit` exit 0, `eslint` clean, `vitest run` 1183/1183) green at every commit. Mixed-shape milestones are a viable extension of the v13.10 hygiene-shape pattern.
- **Formal milestone audit passed** — [v13.11-MILESTONE-AUDIT.md](milestones/v13.11-MILESTONE-AUDIT.md) records 17/17 requirements satisfied, 5/5 phases complete, 4/4 user-facing flows verified, no orphaned requirements. Tech debt: 3 deferred items (Phase 261 visual-UAT smoke-check recommended post-deploy, Phase 258 IN-03 mode-switch edge case, Phase 258 WR-02 strict parser).

**Known close note:** Phase 261 fix addresses the most likely root cause matching the user's "Label-Layer toggle not working" symptom (silent-no-op when `dataset_column_info` is empty). If a different scenario surfaces post-deploy, capture exact reproducer + affected dataset's column info to drive a follow-up.

<details>
<summary>Earlier milestone — v13.10 GH Issues Hygiene (shipped 2026-05-07)</summary>

**Delivered:** 1 phase (257), 3 plans, 8/8 requirements satisfied — see [milestones/v13.10-ROADMAP.md](milestones/v13.10-ROADMAP.md).

- **GH issue tracker reflects shipped reality** — All 11 open issues in `geolens-io/geolens` (#50-#59 builder + #97 sequencing tracker) closed with REQ-ID-citing comments verified against v13.8 (27/27) + v13.9 (19/19) milestone audits. Tracker #97 closed last with a summary linking each child closure path.
- **CTRL-01 batch confirmation gate** — A single batch summary presented before any `gh issue close` ran; user replied `approved` and only then did the 11 mutations execute. Closure log records per-issue `gh exit` codes (all 0).
- **Spot-checks confirmed three non-obvious closures** — #51 (style export/import — v13.9 byte-for-byte round-trip E2E flow PASS), #56 (terrain — NEW-INT-01 closure trail via commit `e46b96c6` and two `TestImportStyleJsonTerrain` regression tests), #58 (line paint properties — split across v13.8 LINE-01..02 and v13.9 GRAD-01..06 with both halves explicitly cited).
- **PROJECT.md refreshed** — `Active` set to placeholder; v13.10 added to chronological shipped list; `BUILDER-POLISH-01` (Phase 256 UI polish, now this milestone) and `OPS-01` (server-side map thumbnails) explicitly named in `Out of Scope` so future planning sweeps see them.
- **Hygiene-milestone shape validated** — One phase, three plans, zero new feature code, single batch confirmation as the only user input. Single-phase milestones are a viable pattern when scope is tightly coupled audit + closure + tracker refresh.
- **Formal milestone audit passed** — [milestones/v13.10-MILESTONE-AUDIT.md](milestones/v13.10-MILESTONE-AUDIT.md) records 8/8 requirements satisfied, 11/11 GitHub issues closed, 0 LEFTOVER, 0 UNCLEAR.

</details>

<details>
<summary>Earlier milestone — v13.9 Map Builder Closeout (shipped 2026-05-06)</summary>

**Delivered:** 5 phases (252-256), 13 plans, 19/19 requirements satisfied — see [milestones/v13.9-ROADMAP.md](milestones/v13.9-ROADMAP.md).

- **Architecture-guard regressions closed** — `catalog/maps/style_json.py` tile signing now routes through `CatalogPort` (CATPORT-02/04, LAYERING-01); `catalog/maps/router.py` imports `apply_layer_diff` from the `service.py` facade (BOUND-01, LAYERING-02); `catalog/maps/service_crud.py` 651 → 423 LOC after extracting layer-diff cluster into `service_diff.py` (BOUND-02, LAYERING-03). Full 20/20 `test_layering.py` architecture-guard suite green (LAYERING-04).
- **Nyquist VALIDATION.md backfill shipped** — six new `VALIDATION.md` files cover v13.8 Phases 246-251 with executable pytest/vitest selectors + grep gates (VALID-01..06). Single reviewer-runnable command `make validate-v13-8` runs 63 checks across 6 phases with fail-fast semantics, three-tier exit codes, and pre-flight API container detection (VALID-07).
- **SDK regen warning closed** — `PUT /maps/{map_id}/thumbnail/` switched from `text/plain` to JSON body backed by `ThumbnailUploadRequest`; `make sdks` now produces zero `openapi-python-client` warnings and ships `upload_thumbnail_maps_map_id_thumbnail_put.py` for the first time (SDK-01). Hard warning gate added to `make sdks` (fails on `^WARNING parsing` line); AST-based architecture-guard test pins the route shape so CI catches regression on every pytest run (SDK-02).
- **First-class line-gradient authoring shipped** — source-side `lineMetrics: true` lazy emission via `lineGradientNeededFor()` helper with sticky lifecycle (GRAD-01); style adapter expression-identity preservation through `addLayers` + `syncPaint` regression-locked at the `===` level (GRAD-04); MapLibre style JSON export emits `lineMetrics: true` with allowlist guard for unsupported source types (GRAD-05); JSON import round-trips paint + builder intent end-to-end with byte-identical re-emission (GRAD-06).
- **Builder UI for line-gradient shipped** — `LineGradientControls` component with Solid/Gradient mode toggle, color picker per stop, position input bounded `[0,1]`, add/remove affordances, and canonical interpolate-linear-line-progress round-trip parser (GRAD-02). Raw expression editor disclosure with parse + structural validation, Apply/Cancel commit semantics, and round-trip via shared parser — canonical hydrates stops, non-canonical preserves customExpression hint (GRAD-03).
- **Visual UAT via Playwright MCP** — Phase 256 verified live against MapLibre canvas; caught a cross-component closure-capture regression in `commitStops`/`updateBuilderConfig` wiring (`6c7b5b04`), fixed inline + locked behind two regression tests. Stronger close than mechanical-only verification.
- **Formal milestone audit passed** — [milestones/v13.9-MILESTONE-AUDIT.md](milestones/v13.9-MILESTONE-AUDIT.md) records 19/19 requirements satisfied, 7/7 cross-phase integration checks WIRED, 4/4 end-to-end flows complete, Nyquist compliant.

**Known close note:** Phase 256 UI audit (18/24) surfaced 1 BLOCKER (gradient preview swatch missing from authoring panel) + 6 minor recommendations (focus rings, `w-full` disclosure button, stable React keys, repeated "Color" labels). Non-functional polish; carry into next milestone if/when builder UX is rescoped. Phase 256 SECURITY.md analyzed 4 threats (raw expression injection, XSS, persisted style, runaway expression DoS) — all closed (2 mitigated, 2 accepted). Phase 256 UI polish backlog promoted to v13.11 (BUILDER-POLISH-01).

</details>

<details>
<summary>Earlier milestone — v13.8 Map Builder Advanced Styling (shipped 2026-05-06)</summary>

**Delivered:** 6 phases (246-251), 22 plans, 27/27 requirements satisfied — see [milestones/v13.8-ROADMAP.md](milestones/v13.8-ROADMAP.md).

- **Style state foundation shipped** — `MapLayer.paint` is now MapLibre-only; builder UI flags moved to documented `style_config` with row migration. `PATCH /maps/{map_id}/layers` incremental layer diffs with stable IDs landed alongside the OpenAPI + Python/TypeScript SDK contracts.
- **Advanced styling controls shipped** — first-class raster paint controls (with reset), line gap/blur/offset (`line-gradient` deferred to v13.9), zoom expression editor for `step`/`interpolate` stops on line/circle/label/opacity, and adapter preservation of expression-valued paint.
- **DEM hillshade and terrain shipped** — raster-dem source + 6-key hillshade paint allowlist + illumination/exaggeration/color controls. Map-level terrain config persists across builder, public viewer, and shared/embed surfaces.
- **MapLibre style JSON interop shipped** — full export/import round-trip for raster, DEM hillshade, terrain block, and outline/extrusion/label companions. Sprite-backed symbol/icon layers with upload/storage/serving.
- **Map edit history shipped** — durable backend event capture for committed saves, builder right-rail History panel, OpenAPI + SDK contracts refreshed.
- **Formal re-audit passed** — [milestones/v13.8-MILESTONE-AUDIT.md](milestones/v13.8-MILESTONE-AUDIT.md) records 27/27 requirements satisfied. v13.9 closed the inherited tech debt (architecture-guard regressions, VALIDATION.md backfill, openapi-python-client warning) and the deferred `line-gradient` authoring.

</details>

<details>
<summary>Earlier milestone — v13.7 Manifest-Driven Catalog Automation (shipped 2026-05-04)</summary>

**Delivered:** 5 phases (241-245), 18 plans, 19/19 requirements satisfied — see [milestones/v13.7-ROADMAP.md](milestones/v13.7-ROADMAP.md).

- **Manifest v1 contract shipped** — `geolens.yaml` now covers stable dataset identity, vector/raster/VRT sources, metadata, and Community-safe publication intent with fixtures and compatibility tests.
- **Offline CLI workflow shipped** — `geolens init` and `geolens validate` create and validate manifests locally with deterministic exit codes, path-specific errors, and import-boundary guards.
- **Backend apply workflow shipped** — `POST /ingest/manifest/apply` reuses existing auth, upload permission, storage validation, ingest jobs, catalog metadata, search, and map-preview contracts.
- **CLI apply and adoption docs shipped** — `geolens apply` and `--dry-run` support configured API workflows, public examples, and a first-catalog Docker Compose walkthrough.
- **Formal milestone audit passed** — [milestones/v13.7-MILESTONE-AUDIT.md](milestones/v13.7-MILESTONE-AUDIT.md) records 19/19 requirements satisfied, 19/19 integration checks, 6/6 verified flows, no orphaned requirements, and no critical gaps.

**Known close note:** The v13.7 audit does not claim full backend/frontend/E2E suite success. Focused manifest gates, contract drift checks, architecture guards, and the adoption path passed; remaining third-party deprecation warnings and the CLI raw-transport follow-up are nonblocking residual risks.

</details>

<details>
<summary>Earlier milestone — v13.6 Catalog Maps/Search Service Decomposition (shipped 2026-05-04)</summary>

**Delivered:** 5 phases (236-240), 18 plans, 21/21 requirements satisfied — see [milestones/v13.6-ROADMAP.md](milestones/v13.6-ROADMAP.md).

- **Maps service facade stabilized** — `backend/app/modules/catalog/maps/service.py` is now a thin public re-export surface over focused shared, CRUD, layer, and public/share modules.
- **Search service facade stabilized** — `backend/app/modules/catalog/search/service.py` is now a thin public re-export surface over focused filter, facet, collection, semantic, dataset, and OGC record modules.
- **Boundary guards added** — private maps/search split modules cannot be imported directly by external production modules, and size-budget checks guard against facade or private-module regrowth.
- **Contract tests hardened** — brittle VRT/search source-introspection checks now assert helper/facade behavior instead of inline implementation blocks.
- **Formal milestone audit passed** — [milestones/v13.6-MILESTONE-AUDIT.md](milestones/v13.6-MILESTONE-AUDIT.md) records 21/21 requirements satisfied, 21/21 integration checks, 7/7 verified flows, no orphaned requirements, and no critical gaps.

**Known close note:** Full backend coverage and Playwright smoke are not fully green locally; Phase 240 records exact outcomes and blockers. The focused v13.6-owned maps/search backend suite and touched-module lint/format gates passed.

</details>

<details>
<summary>Earlier milestone — v13.5 Enterprise Governance Seams (shipped 2026-05-03)</summary>

**Delivered:** 4 phases (232-235), 13 plans, 16/16 requirements satisfied — see [milestones/v13.5-ROADMAP.md](milestones/v13.5-ROADMAP.md).

- **PermissionExtension** — permission checks, catalog visibility filtering, and dataset detail access now route through a first-class platform extension with overlay tests and an architecture guard.
- **WorkflowExtension** — publication status endpoints and metadata `record_status` writes now route through a workflow extension that supports custom transitions, hooks, and states.
- **Advanced-sharing contract verified** — Community keeps basic share/embed behavior while custom embed lifetimes, origin restrictions, and expiring share links are gated consistently across schema, service, UI, API/OpenAPI, and GTM docs.
- **Post-impl close gate passed** — `docs-internal/audits/post-impl-20260503-v13-5.md` records Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings.
- **Formal milestone audit passed** — [milestones/v13.5-MILESTONE-AUDIT.md](milestones/v13.5-MILESTONE-AUDIT.md) records 16/16 requirements satisfied, no orphaned requirements, and no critical gaps.

**Known close note:** Full-suite merge readiness still belongs to normal CI/full-suite validation; the close audit used focused governance and architecture checks.

</details>

<details>
<summary>Earlier milestone — v13.4 Boundary Closeout (shipped 2026-05-03)</summary>

**Delivered:** 7 phases (225, 226, 227, 228, 230, 231, 229), 23 plans, 30/30 requirements satisfied — see [milestones/v13.4-ROADMAP.md](milestones/v13.4-ROADMAP.md).

- **ProcessingPort + CatalogPort** — both directions of the catalog↔processing cycle now go through Protocol boundaries; `test_no_processing_imports_catalog` and `test_no_catalog_imports_processing` enforce the invariant.
- **AIProviderExtension + EmbeddingProviderExtension** — chat/completion and embeddings provider dispatch are extensible via platform registries, with module-level provider SDK import guards across `backend/app/processing/`.
- **SAML fixture tmp-path cleanup** — SAML overlay tests no longer dirty committed fixture files.
- **Cold publish workflows verified** — `geolens==1.0.0`, `geolens-cli==1.0.0`, and `@geolens/sdk==1.0.0` are visible from public registries.
- **Post-impl close gate passed** — `docs-internal/audits/post-impl-20260503-v13-4.md` records Boundary Integrity A+, Coupling Health A−, Seam Quality A−, no unresolved P1 findings.

**Known close note:** In-progress advanced-sharing controls were stashed before archival as `stash@{0}` and are not part of v13.4.

</details>

<details>
<summary>Earlier milestone — v13.3 Boundary A+ Cleanup (shipped 2026-05-01)</summary>

**Delivered:** 3 phases (222-224), 18 plans, 15/15 requirements satisfied — see [milestones/v13.3-ROADMAP.md](milestones/v13.3-ROADMAP.md).

- **AuditSink Protocol + 65-site chokepoint** — extensible audit-emission seam with per-sink failure isolation (`structlog.exception()` swallows + logs without breaking surrounding business operation). `audit_emit()` facade replaces 65 direct `log_action()` calls; only 7 references remain (definition site + DefaultAuditSink shim + docstrings). CI guard `test_no_log_action_calls_outside_audit_service` enforces invariant (Phase 222).
- **AWS Marketplace billing extracted** — `core/marketplace.py` deleted; `Settings.aws_marketplace_*` removed; generic `BillingExtension.on_startup()` dispatch loop in `api/main.py:184-209` with `asyncio.wait_for(timeout=10s)` + per-extension try/except. AWS Marketplace overlay subscribes via `geolens-enterprise/billing/` entry-point. Boundary Integrity grade A → **A+** (Phase 223).
- **Catalog god-module decomposed** — `backend/app/modules/catalog/datasets/domain/service.py` 1407 → 87 LOC thin re-export façade. Five cohesive sub-modules (create/query/lifecycle/metadata/relationships) each <500 LOC. 23 public symbols preserved across 47 consumer files via explicit named re-exports + `__all__`. DECOUPLE-04 architecture-guard test prevents future bypass (Phase 224).
- **SQL-safety single source of truth** — `_sql_safety.py` consolidates `SAFE_TABLE_NAME_RE` + `SAFE_COLUMN_NAME_RE` + `_safe_table_ref` (was redefined 6× pre-cleanup). Architecture guard extended to forbid external imports of the private module.
- **`IngestionResult` Pydantic model** — collapses `create_dataset` 17-kwarg signature to a single typed parameter object (with legacy-kwargs back-compat for existing test fixtures).
- **Three new architecture-guard Makefile targets** — `audit-sink-discipline`, `billing-extraction-discipline`, `catalog-domain-discipline`.

</details>

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
- ✓ `PermissionExtension` Protocol, Community default, typed accessor, overlay tests, and architecture guard cover action checks plus catalog visibility/detail access — v13.5
- ✓ `WorkflowExtension` Protocol, transition context, Community default, typed accessor, overlay tests, and architecture guard cover publication transitions and transition hooks — v13.5
- ✓ Dataset publication `/status/`, `/target-status/`, and metadata `record_status` writes consult `WorkflowExtension` instead of hardcoded-only state logic — v13.5
- ✓ Advanced sharing controls are gated consistently in Community vs Enterprise across schema validators, service guards, builder affordances, API/OpenAPI text, and GTM docs — v13.5
- ✓ Basic Community share/embed flows remain intact: non-expiring share links and default unrestricted 30-day embed tokens can still be created/revoked — v13.5
- ✓ v13.5 close audit records Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings — v13.5
- ✓ `catalog/maps/service.py` is split into focused service modules with a stable facade and no map-builder, layer, sharing, thumbnail, token, or public-viewer regressions — v13.6
- ✓ `catalog/search/service.py` is split into focused service modules with a stable facade and no search, facet, semantic/hybrid, OGC/STAC, AI, or collection regressions — v13.6
- ✓ Architecture guards prevent direct external imports of private maps/search split modules and keep facade/private service modules inside reviewed size budgets — v13.6
- ✓ Focused maps/search tests, lint, format checks, close-audit evidence, and formal milestone audit prove the decomposition preserved existing public behavior — v13.6
- ✓ Project-owned Pydantic deprecation warnings from the focused maps/search gate are fixed; remaining Alembic/Authlib warnings have explicit owner follow-up — v13.6
- ✓ Versioned `geolens.yaml` manifest schema covers stable dataset identity, source entries, metadata, and Community-safe publication intent with committed compatibility fixtures — v13.7
- ✓ `geolens init` and `geolens validate` provide an offline manifest workflow with deterministic exit codes, path-specific validation errors, and CLI import-boundary guards — v13.7
- ✓ Manifest apply API/service accepts typed payloads, preserves upload permission, storage/file safety, idempotency, and existing vector/raster/VRT ingest behavior — v13.7
- ✓ `geolens apply` and `--dry-run` publish or preview manifest-driven catalog changes through configured API credentials — v13.7
- ✓ Public examples and docs prove a Docker Compose to browsable catalog adoption path using local, HTTP/S3, and publication-state manifests — v13.7
- ✓ OpenAPI, generated Python/TypeScript SDKs, CI manifest gates, architecture guards, and formal close audit cover the manifest/apply surface — v13.7
- ✓ Map builders persist MapLibre-valid `paint` JSON only; private builder UI state lives in documented `style_config` with row migration — v13.8
- ✓ Map builders save only changed layers via `PATCH /maps/{map_id}/layers` with stable layer IDs preserving identity for history and future collaboration; full-replacement save retained as fallback — v13.8
- ✓ Map builders tune raster imagery (brightness/contrast/saturation/hue rotation/resampling/fade duration/opacity + reset), line styling (gap width/blur/offset, with `line-gradient` deferred), and zoom-dependent styling (`step`/`interpolate` editor for line/circle/label/opacity) through first-class controls — v13.8
- ✓ Map builders visualize DEM rasters as hillshade with illumination/exaggeration/color controls and apply persisted map-level terrain settings consistently in builder and public viewer surfaces with vertical-unit caveats — v13.8
- ✓ Map builders export/import MapLibre style documents (raster, DEM hillshade, terrain block, outline/extrusion/label companions, builder metadata round-trip) and author sprite-backed symbol/icon layers with upload/storage/serving and consolidated symbol+label adapter — v13.8
- ✓ Map builders review a durable edit history timeline in the right rail backed by committed-save event capture (actor, timestamp, target, action type, change summary) — v13.8
- ✓ Open GitHub issue tracker (`geolens-io/geolens`) reflects post-audit state — all 11 open issues (#50-#59 builder issues + #97 sequencing tracker) closed with REQ-ID-citing comments verified against v13.8 + v13.9 milestone audits; tracker #97 closed last with summary linking each child closure path — v13.10 (shipped 2026-05-07)
- ✓ Map builder line-gradient authoring panel renders a gradient preview swatch above the stop list when Gradient mode is active and the expression is canonical (POLISH-01) — v13.11 (shipped 2026-05-07)
- ✓ Map builder gradient stop rows do not render the per-row "Color" label noise (POLISH-02), Solid/Gradient toggle has visible focus ring + cursor-pointer affordances (POLISH-03), the advanced-expression disclosure button spans full panel width (POLISH-04), each stop row carries a visible `pos` prefix label (POLISH-05), stop rows use stable per-stop UUID React keys (POLISH-06 — `id` field stays in builder JSONB only, paint expression byte-identity preserved), and the trash button is wrapped in a shadcn Tooltip (POLISH-07) — v13.11
- ✓ Map builder `advancedHint` copy reads in builder-user vocabulary (no internal-implementation jargon) and the 16-key `lineGradient` i18n block is fully translated in es/fr/de — v13.11 (COPY-01..02)
- ✓ Map builder Save button shows a `bg-warning` (orange) unsaved-changes dot when there are uncommitted edits, every interactive element across builder surfaces uses `cursor-pointer`, the runtime console is clean (DEV-only diagnostics), and the zoom-control widget renders in the same screen position on builder and shared/public/embed map surfaces — v13.11 (QUALITY-01..04)
- ✓ Map builder Label-Layer toggle no longer silently no-ops when `dataset_column_info` is empty — Switch becomes disabled with a tooltip in that state; full layer-order-and-visibility audit found no other regressions across LayerItem Eye toggle, syncLayersToMap, ChatPanel AI tools, render-mode swap, hillshade companion, or filter-changes — v13.11 (LAYER-01..02)

### Active

v1001 Map Builder UI/UX Polish Sweep — broad workflow sweep selected by the user. Full REQ-ID list is archived in `.planning/milestones/v1001-REQUIREMENTS.md`.

- [ ] **Workflow audit and triage**: Review the builder from new map creation through adding data, editing layers, styling, previewing, saving, sharing, and public viewing; classify findings by severity and user-flow impact.
- [ ] **Inspector and Map Stack polish**: Tighten the recently shipped Map Stack and inspector experience for density, hierarchy, selected/disabled/empty states, mobile reachability, keyboard flow, and predictable editing.
- [ ] **Styling and data-expression polish**: Smooth high-friction layer styling surfaces, including categorical/graduated/zoom/line-gradient/raster/hillshade/symbol/label/popup controls and their validation states.
- [ ] **Preview, save, share, and public-output polish**: Make authored maps render consistently across builder preview, saved-map detail, shared-token, authenticated public, and embed surfaces.
- [ ] **Durable QA gate**: Convert visual, keyboard, accessibility, and smoke findings into repeatable Playwright/Vitest coverage where practical, with screenshot evidence only for the remaining genuinely visual checks.

### Out of Scope

- Persistent connector registry, scheduled mirroring, encrypted credential vault, and connector UI — still Phase 999.13 / Enterprise backlog
- Tenant scoping for the future Cloud tier — still Phase 999.6 and not needed for single-tenant self-hosted manifest apply
- Helm release / `geolens-helm` launch decision (#92) — deferred indefinitely per milestone kickoff; do not include in v13.8
- AMI distribution, SBOM/signed image pipeline, and `geolens-schemas` extraction — still separate P2 distribution/package milestones
- Enterprise-only publishing policies or approval workflows — manifests may declare Community-safe publication state, but advanced governance remains overlay scope

- New map authoring capabilities beyond this milestone, including live collaboration and time sliders — still separate future scope from advanced styling
- AI capability expansion — AI chat and map generation stay as-is until a dedicated AI milestone changes scope
- Phone-specific map-builder optimization — still separate from the tablet/desktop builder scope already shipped
- Power-user resizable/persisted sidebar widths — useful enhancement, but secondary to the default tablet/desktop shell already shipped
- New net capabilities that are not necessary for polish, including live collaboration, annotation layers, time sliders, and a full new map authoring paradigm — v1001 is a UI/UX refinement milestone over existing builder architecture.
- Server-side map thumbnails via Celery + Pillow tile compositing for API-created and multi-user maps — OPS-01 remains a separate operational milestone unless needed only for builder preview polish.
- Full STAC certification — STAC 1.1 endpoints implemented and tested, formal certification deferred
- STAC for vector datasets — STAC is raster-centric; vector records served via OGC Records
- STAC temporal model (per-asset timestamps) — awkward for vector catalogs
- Automatic VRT regeneration on source change — manual-first, webhook/auto deferred until usage patterns understood
- Cursor-based catalog pagination (GAP-STD-08) — offset pagination works for <100K records; breaking change deferred
- Real-time collaboration / editing features — catalog is read/browse/export focused
- Raster band math / custom color ramps — v13.8 adds MapLibre raster paint controls, not analytical raster processing
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

- **Current state**: v13.7 shipped. 49 milestones delivered. v13.8 is active and scoped to Map Builder Advanced Styling from GitHub milestone #1 / tracker #97. Full-featured GIS catalog supporting vector, raster, and VRT datasets with faceted search (FTS + pgvector + keyword/org/CRS facets + ranking boosts), map preview, export, collections, layer creation/editing, AI-assisted map building, related dataset discovery, STAC 1.1 export for raster/VRT interop, publication lifecycle, VRT lifecycle management, declarative `geolens.yaml` manifests, CLI init/validate/apply automation, and i18n (en/es/fr/de). Open-core extension seams now cover identity, audit, billing, AI providers, embeddings, permissions, workflows, catalog/processing boundaries, maps/search service facades, and manifest adoption workflows.
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
| Manifest schema lives in the CLI package, not backend internals | `geolens init` and `geolens validate` must work offline and stay Apache-2.0 Community-safe | ✓ Good — v13.7 schema/fixtures/validation helpers run without backend, SDK, DB, GDAL, rasterio, or Enterprise imports |
| Manifest apply reuses existing ingest/catalog contracts | Avoid a parallel ingestion stack while giving users a declarative first-catalog workflow | ✓ Good — v13.7 apply service preserves auth, upload permission, storage/file safety, idempotency, vector/raster/VRT ingest, search, and preview behavior |
| Manifest adoption is locked by examples plus generated contracts | First-catalog workflow must be both human-followable and API/SDK-visible | ✓ Good — v13.7 docs/examples, OpenAPI, Python SDK, TypeScript SDK, CI gates, and close audit cover the apply path |
| Maps/search service modules use thin public facades | Preserve stable imports for routers, AI, OGC/STAC, and tests while making implementation files small enough to maintain | ✓ Good — v13.6 facade export tests plus private-module import guards protect the contract |
| AST-based private-module guards over grep checks | Covers all Python import shapes without brittle line-pattern assumptions | ✓ Good — v13.6 guards catch direct external imports of private maps/search split modules |
| Explicit per-file size budgets for maps/search service modules | Prevents facade regrowth while allowing reviewed exceptions for known larger private modules | ✓ Good — v13.6 guard enforces thin facades and bounded private modules |
| Behavior-focused VRT/search tests over source introspection | Source checks became brittle after decomposition; helper/facade behavior is the real public contract | ✓ Good — v13.6 replaced search source-inspection assertions with contract tests |
| Record broader gate failures instead of expanding v13.6 scope | Full backend/Playwright failures were outside the owned maps/search decomposition surface | ✓ Good — Phase 240 documents exact blockers while focused v13.6-owned gates pass |
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
*Last updated: 2026-05-11 after closing v1001 Map Builder UI/UX Polish Sweep*

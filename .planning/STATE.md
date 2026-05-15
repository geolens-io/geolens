---
gsd_state_version: 1.0
milestone: v1009
milestone_name: Map Builder v1.5 (Polish)
status: Archived (`tech_debt`)
stopped_at: v1009 Map Builder v1.5 (Polish) roadmapped; Phase 1039 ready to plan.
last_updated: "2026-05-15T04:00:00.000Z"
last_activity: 2026-05-15 — Phase 1044 Plan 04 complete (final smoke gate; all 5 gates PASS; v1009 GO; POL-25 satisfied)
progress:
  total_phases: 11
  completed_phases: 11
  total_plans: 26
  completed_plans: 26
  percent: 100
---

# State

## Current Position

Phase: 1044
Plan: 04 complete
Status: v1009 milestone complete — all 25 POL requirements satisfied, smoke gate green
Last activity: 2026-05-15 — Phase 1044 Plan 04 complete (final smoke gate; all 5 gates PASS; v1009 GO; POL-25 satisfied)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-14 after shipping v1008)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Executing v1009 Map Builder v1.5 (Polish) — drag-from-catalog, multi-select bulk ops, UI/UX sweep, test debt closeout

## Active Milestone: v1009 Map Builder v1.5 (Polish)

**Started:** 2026-05-14
**Roadmapped:** 2026-05-14
**Phases:** 1039-1044 (6 phases)
**Requirements:** 25 (POL-01..25 across 5 categories)

**Goal:** Polish the v1008 unified-stack Map Builder — add drag-from-catalog-into-stack + multi-layer selection / bulk ops, sweep the entire builder surface for modern/sleek/intuitive presentation, and close out pre-existing builder test drift.

### Phase Sequence

| Phase | Name | Requirements | Plans | Status |
|-------|------|--------------|-------|--------|
| 1039 | ux-audit-and-test-debt-closeout | POL-12, POL-19, POL-20, POL-21 | 2 plans (1039-01 test debt, 1039-02 UX audit) | ✅ Shipped 2026-05-14 |
| 1040 | drag-from-catalog-into-stack | POL-01, POL-02, POL-03, POL-04, POL-05 | TBD | Not started |
| 1041 | multi-layer-selection-and-bulk-ops | POL-06, POL-07, POL-08, POL-09, POL-10, POL-11 | TBD | Not started |
| 1042 | spacing-density-states-polish | POL-13, POL-14, POL-15 | TBD | Not started |
| 1043 | error-empty-states-and-ia-cleanup | POL-16, POL-17, POL-18 | TBD | Not started |
| 1044 | cross-cutting-closeout | POL-22, POL-23, POL-24, POL-25 | TBD | Not started |

### Sequencing Rationale

**Why audit + test debt first (Phase 1039):** POL-12's `BUILDER-UX-AUDIT.md` produces the P0/P1 finding list that scopes Phase 1042 (spacing/density/states) and Phase 1043 (error/empty/IA). Running the audit before those phases is non-negotiable. The test debt closeout (POL-19/20/21) co-locates here because the failing test surfaces — `EmptyStackState.integration`, `StackRow`, `UnifiedStackPanel`, `use-builder-layers.add-dataset` — are exactly the files the audit touches; repair-while-you-read is cheaper than two separate passes over the same code.

**Why drag-from-catalog before multi-select (Phase 1040 → Phase 1041):** Both features are independent in capability terms but heavily overlap in file surface (`StackRow`, `UnifiedStackPanel`, `use-builder-layers`), so sequential ordering avoids merge conflicts. Drag-from-catalog goes first because it has fewer state-model implications (no persistent selection state, no atomic-rollback contract) and acts as a warm-up to the DnD primitives Phase 1041 will reuse.

**Why polish (Phases 1042, 1043) rides after the feature phases:** Spacing/density and empty-state polish must include the new bulk action bar surface (1041) and any drag-from-catalog affordance changes (1040). Running 1042/1043 last lets the polish pass sweep across the final v1.5 surface area, not a half-built one. Phase 1042 (visual tokens/states/loading) feeds Phase 1043 (error/empty/IA) because the empty-state copy lives inside the polished spacing scaffold.

**Why cross-cutting closeout (Phase 1044) is the final phase:** i18n needs the final set of strings, a11y needs the final keyboard surface, the Playwright UAT spec exercises the final composition, and the builder smoke gate verifies the entire milestone. All upstream phases must be merged before any of these gates can be authored authoritatively.

**Hard constraints carried from v1008:**

- No saved-map shape changes (Phase 1033 normalizer is locked).
- No public viewer / shared / embed surface changes (parity guarantee).
- All work uses the `sketch-findings-geolens` token set; no new tokens introduced.
- POL-09 bulk operations use existing per-layer PATCH endpoints — no backend API changes.

## Last Shipped Milestone

**Version:** v1008 Map Builder Sidebar Redesign
**Started:** 2026-05-13
**Shipped:** 2026-05-14
**Status:** Archived (`tech_debt`)
**Goal:** Re-architect the Map Builder sidebar from six fixed sections into one unified, drag-orderable layer stack — with basemap-as-group, DEM-as-raster-layer, compact rows, and a side-by-side LayerEditorPanel flyout — while normalizing legacy saved maps and aligning the Add Data modal to the new model.
**Phases:** 1033-1038 (6 phases, 16 plans, 27 requirements; 27/27 satisfied)
**UAT:** 9 pass / 1 skip / 0 fail (`e2e/builder-unified-stack.spec.ts`)
**Audit:** `tech_debt` / `COMPLETE_WITH_TECH_DEBT_REVIEW` — 1 warning (smoke-test sweep) + 7 info/deferred items recorded
**Archive:** `.planning/milestones/v1008-ROADMAP.md`, `.planning/milestones/v1008-REQUIREMENTS.md`, `.planning/milestones/v1008-MILESTONE-AUDIT.md`

## Prior Shipped Milestone

**Version:** v1007 Release Hygiene
**Started:** 2026-05-12
**Shipped:** 2026-05-12
**Status:** Executing Phase 1038
**Goal:** Close release hygiene after v1006 by proving dependency/security state, generated artifacts, stack health, smoke coverage, Playwright MCP browser health, and temporary data cleanup.
**Phases:** 1032 (1 phase, 10 requirements; 10 requirements complete)
**Audit:** passed / GO
**Archive:** `.planning/milestones/v1007-ROADMAP.md`, `.planning/milestones/v1007-REQUIREMENTS.md`, `.planning/milestones/v1007-MILESTONE-AUDIT.md`

## Prior Shipped Milestone

**Version:** v1006 Large Dataset Cluster Scaling
**Started:** 2026-05-12
**Shipped:** 2026-05-12
**Status:** Archived
**Goal:** Extend v1005 Point Cluster from bounded client-side GeoJSON datasets to large point datasets by adding a server-side clustered tile/source path, preserving the existing saved-map shape and renderer controls, and adding the expected cluster exploration interactions without regressing normal vector tiles.
**Phases:** 1027-1031 (5 phases, 25 requirements; 25 requirements complete)
**Audit:** passed / GO
**Archive:** `.planning/milestones/v1006-ROADMAP.md`, `.planning/milestones/v1006-REQUIREMENTS.md`, `.planning/milestones/v1006-MILESTONE-AUDIT.md`

## Prior Shipped Milestone

**Version:** v1005 Builder Point Cluster Foundation
**Started:** 2026-05-12
**Shipped:** 2026-05-12
**Status:** Archived
**Goal:** Ship Point Cluster safely for eligible point datasets by proving a bounded GeoJSON source path, preserving saved-map compatibility, and falling back cleanly when clustering is not supported.
**Phases:** 1023-1026 (4 phases, 20 requirements; 20 requirements complete)
**Audit:** passed / GO
**Archive:** `.planning/milestones/v1005-ROADMAP.md`, `.planning/milestones/v1005-REQUIREMENTS.md`, `.planning/milestones/v1005-MILESTONE-AUDIT.md`

## Prior Shipped Milestone

**Version:** v1004 Builder Renderer Expansion
**Started:** 2026-05-12
**Shipped:** 2026-05-12
**Status:** Archived
**Goal:** Add the next Map Builder render modes through a deliberate renderer capability layer, shipping MapLibre-native wins first and making any deck.gl/H3/trips dependency decision explicit before implementation.
**Phases:** 1019-1022 (4 phases, 20 requirements; 20 requirements complete)
**Audit:** passed / GO
**Archive:** `.planning/milestones/v1004-ROADMAP.md`, `.planning/milestones/v1004-REQUIREMENTS.md`, `.planning/milestones/v1004-MILESTONE-AUDIT.md`

## Prior Shipped Milestone

**Version:** v1003 Builder v1 Hardening
**Started:** 2026-05-12
**Shipped:** 2026-05-12
**Status:** Archived
**Goal:** Prove and harden the v1002 builder sidebar and Add Dataset redesign through durable browser, accessibility, and round-trip coverage without adding schema, renderer, or catalog capabilities.
**Phases:** 1014-1018 (5 phases, 24 requirements; 24 requirements complete)
**Audit:** passed / GO
**Archive:** `.planning/milestones/v1003-ROADMAP.md`, `.planning/milestones/v1003-REQUIREMENTS.md`, `.planning/milestones/v1003-MILESTONE-AUDIT.md`

## Prior Shipped Milestone

**Version:** v1002 Layer Sidebar + Add Dataset Redesign
**Shipped:** 2026-05-12
**Phases:** 1008-1013 (6 phases, 6 plans)
**Requirements:** 37/37 satisfied (ARCH-01..04, STACK-01..05, RENDER-01..08, BASE-01..04, TERRAIN-01..02, ADD-01..08, QA-01..06)
**Audit:** `tech_debt` / `COMPLETE_WITH_BROWSER_ENV_REVIEW`
**Archive:** `.planning/milestones/v1002-ROADMAP.md`, `.planning/milestones/v1002-REQUIREMENTS.md`, `.planning/milestones/v1002-MILESTONE-AUDIT.md`

## Earlier Shipped Milestone

**Version:** v1001 Map Builder UI/UX Polish Sweep
**Shipped:** 2026-05-11
**Phases:** 1002-1007 (6 phases, 8 plans)
**Requirements:** 38/38 satisfied (FLOW-01..06, STACK-01..06, STYLE-01..08, OUTPUT-01..06, A11Y-01..06, QA-01..06)
**Audit:** passed / GO
**Archive:** `.planning/milestones/v1001-ROADMAP.md`, `.planning/milestones/v1001-REQUIREMENTS.md`, `.planning/milestones/v1001-MILESTONE-AUDIT.md`

## Earlier Shipped Milestone

**Version:** v1000 Map Stack and Basemap Layer Controls
**Shipped:** 2026-05-11
**Phases:** 1000-1001 (2 phases, 7 plans, 27 tasks)
**Requirements:** 7/7 satisfied (MAPSTACK-01..07)
**Audit:** `tech_debt` / `COMPLETE_WITH_TECH_DEBT_REVIEW` — generated SDK drift, visual QA automation, seeded demo E2E gating, and full release gates not rerun
**Archive:** `.planning/milestones/v1000-ROADMAP.md`, `.planning/milestones/v1000-REQUIREMENTS.md`, `.planning/milestones/v1000-MILESTONE-AUDIT.md`

## Earlier Shipped Milestone

**Version:** v13.14 Smoke Stabilization
**Shipped:** 2026-05-08
**Phases:** 280-282 (3 phases, 3 plans, ~5 source-file commits)
**Requirements:** 13/13 satisfied (SLASH-01..04, SMOKE-281-01..04, SMOKE-282-01..06)
**Audit:** none — bugfix milestone, smoke regression coverage validated by `npm run e2e:smoke` final 50/1/2 result
**Source:** quick task `260508-d6i` (full smoke run after fresh stack reset + thematic-demo seed)

## Earlier Shipped Milestone

**Version:** v13.13 Backlog Sweep
**Shipped:** 2026-05-07
**Phases:** 271-279 (9 phases, 51 plans, ~106 source-file commits)
**Requirements:** 130/130 satisfied (DBM-01..09, INF-01..16, SEC-01..17, PERF-01..11, API-01..14, CODE-01..14, CONF-01..15, TEST-01..10, ADMIN-01..13, CLOSE-01..05)
**Audit:** **passed** — composite grade **A**, recommendation **GO**
**Archive:** `.planning/milestones/v13.13-ROADMAP.md`, `.planning/milestones/v13.13-REQUIREMENTS.md`, `.planning/milestones/v13.13-MILESTONE-AUDIT.md`

## Accumulated Context

- **v1009 roadmapped 2026-05-14** as a 6-phase frontend polish milestone on top of the v1008 unified-stack foundation. Phase 1039 leads with the `BUILDER-UX-AUDIT.md` + test debt because the audit drives Phase 1042/1043 priorities AND the failing test surfaces overlap the audit's file surface. Phases 1040 (drag-from-catalog) and 1041 (multi-select) ship sequentially to avoid merge conflicts on shared `StackRow`/`UnifiedStackPanel`/`use-builder-layers` files. Phases 1042/1043 ride after the feature phases so polish sweeps the final v1.5 surface. Phase 1044 closes with i18n + a11y + UAT + smoke.
- **v1008 roadmapped 2026-05-13** as a frontend-heavy milestone touching `frontend/src/components/builder/` and the saved-map JSON loader. Backend touches are minimal (loader normalizer; possibly a hand-curated suggestions surface). Sequenced foundational normalizer (Phase 1033) first because every other change must round-trip through it. Phase 1034 ships row anatomy + LayerEditorPanel flyout together as one vertical slice because they are co-dependent. Phases 1035-1037 extend the unified-stack model. Phase 1038 is sketch-fidelity + a11y + i18n + Playwright MCP UAT closeout.
- **v1008 visual decisions are locked** by the `sketch-findings-geolens` skill — row anatomy, palette, group glyphs (`⊞` basemap, `▸` folder), 380px flyout width between 340px sidebar and map. v1009 phases must reuse the skill, not redo the design work. No new tokens introduced in v1.5.
- **v1008 reference commits to revive:** `1d3cdc9a` (LayerEditorPanel flyout), `aeac195c` (z-index fix). **Commits to retire:** `383e1f55` (inline expansion regression), `6756149c` (six-section model), `fa5856ba` (inline basemap/terrain rows).
- **v1008 saved-map compat is non-optional:** legacy maps must continue to render in public/shared/embed viewers throughout v1.5. `d2c5c99c` compat fixtures are the regression gate.
- **v13.13 was a 9-phase autonomous backlog sweep** of v13.12's 154 deferred M+L findings, organized into 130 REQ-IDs by domain affinity (DB → Docker → Security → Performance → API/Docs → Code Quality → i18n/Env → Tests → Admin/Close). Same hybrid orchestration shape as v13.12 (parallel `gsd-executor` agents per phase) but with finer-grained per-domain phase boundaries instead of audit-dispatch boundaries.
- **30-agent autonomous orchestration** validated: per-phase planner agent (gsd-planner) generates 4-8 plans, then parallel executor agents (gsd-executor) ship plans wave-by-wave with file-overlap-driven sequencing. Closeout (CLOSE-01..05) handled inline by orchestrator since the planner agent timed out on the closeout plan.
- **Frontend headline metrics:** map-vendor 1052kB chunk lazy-loaded off non-map routes (PERF-06); DatasetPage bundle 217kB → 34kB (-84%) via lazy ReuploadDialog/VrtCreateDialog/DetailPanel (CODE-06); AttributeTable virtualized via @tanstack/react-virtual for 10k+ rows (PERF-07); Builder i18n complete — 135 strings translated to es/fr/de across zoomExpression + symbol + raster + hillshade + uploadIcon blocks.
- **Backend headline changes:** chat_service.py 1013 LOC decomposed into 5 sub-modules <400 LOC each behind a Phase-226-style facade (zero public API change — CODE-02); 113 broad-except sites annotated with `# broad: <reason>` + architecture-guard test forbids new unjustified ones (CODE-08); architecture-guard 1500-LOC cap on routers with allowlist for over-cap routers (`maps/router.py`=1610 capped at 1700, `search/router.py`=1515 capped at 1600); 35 inline `pytest.skip` migrated to `@pytest.mark.skipif` decorator form (TEST-09); 6 mock-call-count assertions converted to behavior assertions (TEST-06).
- **Security headline changes:** SVG icon CSP `default-src 'none'; sandbox` + defusedxml re-serialization (SEC-01, SEC-09); download-scoped JWT with `typ:download` + ≤2min TTL (SEC-04); 32-byte share-token entropy (SEC-10); `_request_origin` validates against `CORS_ALLOWED_ORIGINS` allowlist (SEC-05); COG redirect SSRF re-validation (SEC-06); SessionMiddleware https_only in non-dev (SEC-02); OAuth Referrer-Policy: no-referrer (SEC-13); structlog field redaction (SEC-03); GZip vs SecurityHeaders middleware order pinned by regression test (SEC-17). 15/17 SEC-* requirements satisfied at close; SEC-14 (CI pip CVE carve-out removal) deferred per safety caveat → **closed post-milestone 2026-05-08** (commit `b019f68b`: bumped lockfile pip 26.0.1→26.1.1, dropped both `--ignore-vuln` flags, GitHub Dependabot alert #35 resolved).
- **API & docs headline changes:** `POST /maps/import` typed `MapStyleImportRequest` Pydantic body (API-01) — OpenAPI no longer emits `additionalProperties: true`; CHANGELOG `[Unreleased]` populated with 10 new map-builder routes ready for v1.1.0 tag (API-02); `docs/api-style.md` documents trailing-slash + status-code conventions (API-03, API-07); README dataset count + signature-maps + cold first-build time corrected (API-04, API-13); demo cluster `getgeolens.io` → `getgeolens.com` (API-14); titiler/valkey/uv image pins bumped (API-08).
- **i18n & env headline changes:** `WORKER_SHUTDOWN_TIMEOUT` and `ENV_ONLY_CONFIG` migrated from raw `os.environ.get` to Pydantic Settings (CONF-03, CONF-04); `PUBLIC_BASE_URL` soft-deprecated with one-shot startup WARN (CONF-01); `VITE_API_PROXY_TARGET` legacy alias removed (CONF-14); 135 builder.json locale strings landed; admin/dataset i18n cleanup (CONF-10, CONF-11).
- **Admin headline changes:** ApiKey `max_length=255` (ADMIN-01); audit-log search rewritten to `lower(unaccent(...))` form so it uses the existing pg_trgm GIN indexes from v13.12 Alembic 0010 (ADMIN-02); AdminAuditPage page-guard (ADMIN-08); server-driven enterprise-tabs registry (ADMIN-03); audit-export format dispatcher unified (ADMIN-04); `register_user` audit event (ADMIN-05); delete_user FK SET NULL behavior locked by static-analysis test (ADMIN-06); MinIO image bumped to 2025-09-07 + sha256-pinned (ADMIN-10, ADMIN-12); non-blocking license-checker CI job (ADMIN-13); stale CVE-2026-4539 carve-out removed (ADMIN-11).
- **Test health changes:** Backend `--cov-fail-under` 58.5 → 60 (TEST-01, actual=77.02%); frontend coverage thresholds ratcheted (32/27/27/32 → 41/39/37/42, TEST-02); 6 raw `waitForTimeout` calls in E2E specs replaced with deterministic locator polling (TEST-04, TEST-05); LayerPanel + MapTitleBar new co-located tests (14 tests, TEST-03); 8 SourcesTab `it.todo` migrated to backlog file (TEST-07); H-33 dataset-detail L144 fixture stabilized via PATCH-seeded fixture, pending todo closed (TEST-10).

### Roadmap Evolution

- v1009 roadmapped 2026-05-14: Map Builder v1.5 (Polish) scopes drag-from-catalog-into-stack, multi-layer selection + bulk ops, UX audit + spacing/density/state polish, error/empty-state + IA cleanup, builder test debt closeout, and i18n + a11y + Playwright UAT closeout. Sequenced audit + test debt first (Phase 1039) because the audit drives Phase 1042/1043 priorities AND the failing test files overlap the audit's file surface.
- Phase 1039 added: ux-audit-and-test-debt-closeout (POL-12, POL-19..21).
- Phase 1040 added: drag-from-catalog-into-stack (POL-01..05).
- Phase 1041 added: multi-layer-selection-and-bulk-ops (POL-06..11).
- Phase 1042 added: spacing-density-states-polish (POL-13..15).
- Phase 1043 added: error-empty-states-and-ia-cleanup (POL-16..18).
- Phase 1044 added: cross-cutting-closeout (POL-22..25).
- v1008 roadmapped 2026-05-13: Map Builder Sidebar Redesign scopes a unified drag-orderable layer stack with basemap-as-group, DEM-as-raster-layer, compact row anatomy, side-by-side LayerEditorPanel flyout, `⚙ Settings` affordance, catalog-first empty state with hand-curated suggestions, Add Data modal alignment, and saved-map normalizer that preserves public/shared/embed viewer fidelity.
- Phase 1033 added: saved-map-normalizer-and-viewer-parity (BSR-20..23).
- Phase 1034 added: unified-stack-rows-and-layer-editor-flyout (BSR-01..04, BSR-10..13).
- Phase 1035 added: basemap-group-folder-groups-and-dem-raster (BSR-05..09).
- Phase 1036 added: settings-affordance (BSR-14..15).
- Phase 1037 added: empty-state-and-add-data-alignment (BSR-16..19).
- Phase 1038 added: a11y-i18n-sketch-fidelity-and-uat-closeout (BSR-24..27).
- v1007 shipped 2026-05-12: release hygiene verified scanner-clean `urllib3==2.7.0`, dismissed stale Dependabot #36/#37 with evidence so open GitHub alerts are zero, regenerated OpenAPI/SDK artifacts for the server-side cluster tile route, fixed frontend compose health, made collections smoke self-seeding, passed broad backend/frontend/security/browser gates, and confirmed a clean Playwright MCP search-page console after temporary data cleanup.
- v1006 shipped 2026-05-12: authenticated server-side cluster MVT tiles now scale Cluster beyond bounded GeoJSON point datasets, builder/public/shared/embed viewers route large point Cluster layers to `/tiles/clusters/...`, cluster interaction popups and zoom activation work across companion layers, style JSON export records cluster strategy metadata with standalone point fallback, and Playwright MCP verified a 6,001-feature live map with signed tile requests and zero current-page console warnings/errors.

## Recent Decisions

- **v1009 audit-first sequencing.** Phase 1039 leads the milestone with the `BUILDER-UX-AUDIT.md` document because POL-13/14/15/16/17/18 polish work explicitly depends on the audit's P0/P1 finding list to scope plans. Test debt (POL-19/20/21) was co-located with the audit because both touch the same files (`EmptyStackState`, `StackRow`, `UnifiedStackPanel`, `use-builder-layers`).
- **v1009 sequential feature delivery.** Phase 1040 (drag-from-catalog) precedes Phase 1041 (multi-select) sequentially rather than running them as parallel waves. Both features touch shared unified-stack surfaces (`StackRow`, `UnifiedStackPanel`, `use-builder-layers`) — sequential ordering trades parallelism for zero merge-conflict cost.
- **v1009 no-new-tokens constraint.** All visual polish in Phase 1042/1043 must reuse the `sketch-findings-geolens` token set from v1008. No new design tokens introduced in v1.5; the polish is normalization and unification, not new visual vocabulary.
- **v1008 sequencing puts the saved-map normalizer first.** Phase 1033 is foundational because every downstream phase (unified stack, basemap group, DEM render-mode, settings, empty state, closeout) must round-trip through the normalizer. Public/shared/embed viewer parity is the non-negotiable gate.
- **v1008 row + flyout ship together.** Phase 1034 bundles the unified stack row anatomy (BSR-01..04) and the LayerEditorPanel flyout (BSR-10..13) into one vertical slice because the compact row IS the entry surface that opens the flyout — splitting them would ship half a feature.
- **v1008 reuses locked design decisions.** Row anatomy, palette, group glyphs, and flyout layout are pinned in the `sketch-findings-geolens` skill. Implementation must load and reuse the skill, not redesign.
- **Autonomous milestone shape proven for backlog sweeps.** The same `/gsd-autonomous` orchestration that worked for v13.12's 17-audit dispatch+remediation also works for v13.13's 9-phase domain-grouped backlog sweep. Per-phase planner agent + parallel executor agents per wave; closeout inline. Reusable for any future milestone where requirements are pre-classified by domain.

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260508-bv1 | Sync v0.1.0 branding | 2026-05-08 | 659b9e61 | Needs Review | [260508-bv1-sync-v0-1-0-branding](./quick/260508-bv1-sync-v0-1-0-branding/) |
| 260508-d6i | Reset local env + thematic demo seed + full smoke (6 failures surfaced) | 2026-05-08 | 7bac058b | Needs Review | [260508-d6i-reset-local-environment-and-run-smoke-ch](./quick/260508-d6i-reset-local-environment-and-run-smoke-ch/) |
| 260508-lkz | Rebuild demo themes + fixtures with 5 visually arresting 3D + Map Builder showcase maps (code-only; seeder run + Playwright deferred) | 2026-05-08 | cb474308 | Verified | [260508-lkz-rebuild-geolens-demo-themes-and-fixtures](./quick/260508-lkz-rebuild-geolens-demo-themes-and-fixtures/) |
| 260508-nl9 | Live validation of 260508-lkz demo fixtures (seeder + Playwright MCP) — surfaced 5 bugs, fixed 2 inline (gdal-bin in seeder image; NIFC retry), 2 documented as follow-ups (worker MissingGreenlet on raster + clip_to_mercator_bounds; api /tmp tmpfs cap < UPLOAD_MAX_SIZE_MB) | 2026-05-08 |  | Incomplete | [260508-nl9-run-seeder-and-playwright-mcp-smoke-chec](./quick/260508-nl9-run-seeder-and-playwright-mcp-smoke-chec/) |
| 260508-rr5 | Fix /tmp tmpfs cap blocking large uploads (gh #101) — set tempfile.tempdir to /app/staging in app/api/main.py | 2026-05-08 | 220a2052 | Verified | [260508-rr5-fix-tmp-tmpfs-cap-blocking-large-uploads](./quick/260508-rr5-fix-tmp-tmpfs-cap-blocking-large-uploads/) |
| 260514-ajo | Smoke-test sweep deferred from v1008 close: fixed SidebarRail Add-data event bug + rewrote 8 stale tests and deleted 4 tests for removed features; full smoke 56/56 pass | 2026-05-14 | 91951aca |  | [260514-ajo-run-through-the-smoke-checks-and-fix-any](./quick/260514-ajo-run-through-the-smoke-checks-and-fix-any/) |

## Deferred Items

Items acknowledged and deferred at v13.13 milestone close (2026-05-07).

**v13.13-specific deferrals:**

- ~~**SEC-14 (CVE-2026-6357 carve-out removal):**~~ **CLOSED 2026-05-08** (post-milestone, commit `b019f68b`). Realization: pip-audit scans the lockfile pip (transitive of `pip-audit` → `pip-api`), not the runner-image pip. `uv lock --upgrade-package pip` bumped to 26.1.1, OSV.dev confirms zero known vulns, both `--ignore-vuln CVE-2026-3219` and `--ignore-vuln CVE-2026-6357` removed from `ci.yml`.
- **3 Playwright MCP UAT visual confirmations:**
  - SEC-07 (embed iframe sandbox visual confirmation) — DOM-level test pinned by Phase 273-07; visual UAT deferred to manual reviewer.
  - CODE-05 (4-flow store-relocation visual UAT) — 9 DOM-level smoke tests prove imports resolve and actions still work; 4-flow visual UAT deferred to manual reviewer.
  - TEST-10 (5-run flake-resilience verification) — Path A fixture stabilization committed; 5 consecutive Playwright runs deferred to manual reviewer.
- **Pre-existing test drift not fixed in v13.13:**
  - `preserve-drawing-buffer.test.ts` typecheck error (Phase 274-06 commit `e8d11728`, uses `node:fs`/`node:path` without `@types/node`). Surfaced/confirmed out-of-scope by ~6 plans across v13.13.
  - `test_no_catalog_imports_processing` regex false-positive on a comment in `service_public.py:186`. Pre-existing on clean main HEAD.
  - Backend `pytest --cov` collection import errors (`tests/test_tile_cache.py` missing `cachetools` in test env; `tests/test_phase_272_compose.py` setup errors).

**Standing carryforwards (cross-milestone):**

- 175+ cross-milestone `quick_tasks` carried forward since v13.1.
- `2026-05-05-recreate-public-repo-before-launch.md` — pre-public-launch repo strategy (still pending; OSS-01).
- **Distribution & supply chain** (DIST-01..04): Helm chart, SBOM, Cosign-signed images, AMI Packer pipeline — out of v13.13 scope; recommend follow-up milestone for procurement-driven adopters.
- **v13.12 PUBLIC-READINESS deployment conditions** (out-of-scope for codebase, in-scope for adopter):
  - JWT secret regeneration (H-28).
  - Public repo recreation (OSS-01).
  - Tag v1.1.0 + populate CHANGELOG (H-02 — CHANGELOG body now populated by API-02 in v13.13; tag is operator-led).
- Persistent connector registry (999.13) — Enterprise backlog.
- Future Cloud tenant scoping (999.6) — Cloud prerequisite.
- `geolens-schemas` extraction (999.16) — separate distribution/packaging milestone.
- Server-side map thumbnails (OPS-01) — separate operational milestone.

## Session Continuity

Last session: 2026-05-15T03:42:09.240Z
Stopped at: v1009 Map Builder v1.5 (Polish) roadmapped; Phase 1039 ready to plan.
Resume file: None

---
*Last updated: 2026-05-14 after creating v1009 roadmap*

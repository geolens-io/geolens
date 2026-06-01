# Roadmap: v1036 Widget → Plugin Platform Rename

**Milestone:** v1036
**Granularity:** standard
**Status:** Planning
**Type:** Breaking rename (1.0.0 → 2.0.0)

## Milestone Goal

Rename the map "widget" platform to "plugin" across the entire stack — DB, API, frontend, i18n, docs, and tooling — as a **hard breaking change** on shipped 1.0.0. No back-compat alias, no deprecation shim, no dual-read: the old `widgets`/`enabled_widgets` names are removed in the same change that introduces `plugins`/`enabled_plugins`. The plugin *identifier values* `measurement` and `legend` are preserved (they are stable IDs, not the word "widget"). Breaking DB + API contract change → CHANGELOG `[2.0.0]`. The rename gives the extensibility surface an honest name and unblocks the queued plugin-platform roadmap (swipe / pmtiles / COG / streetview IControls).

**Core invariant (applies to every phase):** the plugin ID strings `measurement` and `legend` are NEVER renamed. Only the platform/container noun (`widget*` → `plugin*`) changes. No `widgets` alias is accepted or emitted anywhere after the cut.

## Phases

- [x] **Phase 1161: Backend Rename & Contract** - Rename `maps.widgets`→`maps.plugins` (column, model, schemas, settings, tests) with a reversible migration; refresh OpenAPI + SDK.
- [x] **Phase 1162: Frontend Rename** - Rename `map-widgets/`→`map-plugins/` and all `Widget*`→`Plugin*` identifiers/API types; typecheck + vitest green.
- [x] **Phase 1163: i18n Key Rename** - Rename ~64 `widget*` i18n keys → `plugin*` across en/es/fr/de with full key parity. (completed 2026-05-31)
- [x] **Phase 1164: Tooling, Docs & Audit Fixes** - Rename slash command, skills, and e2e specs; fold in 3 deferred audit fixes; write plugin-development guide + CHANGELOG `[2.0.0]`. (completed 2026-05-31)
- [x] **Phase 1165: Live MCP Close-Gate** - Orchestrator-driven Playwright MCP proving the renamed `maps.plugins` column round-trips set→save→reload, plus the full deterministic gate.

## Phase Details

### Phase 1161: Backend Rename & Contract
**Goal**: The backend persists and serves the plugin platform under the `plugins` / `enabled_plugins` names end-to-end, with a reversible migration as the foundation for every downstream change.
**Depends on**: Nothing (foundation phase)
**Requirements**: BE-RENAME-01, BE-RENAME-02, BE-RENAME-03, BE-RENAME-04, BE-RENAME-05, BE-RENAME-06
**Success Criteria** (what must be TRUE):
  1. Running `alembic upgrade head` renames the `maps.widgets` JSONB column to `maps.plugins` and the `persistent_config` key `enabled_widgets` to `enabled_plugins`, preserving existing row values; the paired downgrade restores both original names exactly (round-trip test passes). The deployed `0001_baseline.py` is not edited.
  2. Creating or updating a map via the API accepts and returns a `plugins` field (not `widgets`) in the Map request/response schemas, and the settings feature-toggle API reads and writes `enabled_plugins`.
  3. The settings validator accepts `measurement` and `legend` as valid `enabled_plugins` values (ID values unchanged) and rejects non-list/empty-string input as before.
  4. The backend test suite passes with every reference updated to `plugins`/`enabled_plugins`, and no test (or app code) references the removed `widgets`/`enabled_widgets` names.
  5. `make openapi` regenerates a committed `backend/openapi.json` exposing the `plugins`/`enabled_plugins` fields (`make openapi-check` clean), and the regenerated TS/Python SDK reflects it.
**Plans**: 2 plans
  - [x] 1161-01-PLAN.md — Reversible `0025` migration (rename `catalog.maps.widgets`→`plugins` column + `enabled_widgets`→`enabled_plugins` config key) + `Map` model & `persistent_config` rename + upgrade/downgrade round-trip test (BE-RENAME-01/02/03)
  - [x] 1161-02-PLAN.md — Map & Settings API contract rename (schemas, settings validator+route+config object, maps router/service/helpers) + full backend test sweep + `make openapi` regen so `make openapi-check`/`sdks-check` are clean (BE-RENAME-04/05/06)

### Phase 1162: Frontend Rename
**Goal**: The frontend consumes the renamed plugin contract under `Plugin*` / `map-plugins` everywhere, with the build and unit suite fully green.
**Depends on**: Phase 1161 (renamed API contract + regenerated SDK)
**Requirements**: FE-RENAME-01, FE-RENAME-02, FE-RENAME-03, FE-RENAME-04, FE-RENAME-05
**Success Criteria** (what must be TRUE):
  1. The directory `frontend/src/components/map-widgets/` no longer exists and `frontend/src/components/map-plugins/` holds its contents (all entries incl. `__tests__/` and `builtin/`); every import across the app resolves to the new path.
  2. No `Widget*` platform identifier remains in `frontend/src` (`WidgetHost`/`WidgetPanel`/`WidgetErrorBoundary`/`WidgetDefinition`/`WidgetContext`/`registerWidget`/`register-widgets`/`map-widget-store`/`widget-availability`/`registry` exports → `Plugin*`); `types/api.ts`, the settings api client, and TanStack query keys use `plugins`/`enabled_plugins`.
  3. The plugin ID string values `measurement` and `legend` are unchanged throughout the frontend.
  4. `npm run typecheck` reports 0 errors and the renamed `vitest` suites are green.
**Plans**: 2 plans
  - [x] 1162-01-PLAN.md — `git mv` `map-widgets/`→`map-plugins/` (10 entries) + `map-widget-store`→`map-plugin-store`, rename all `Widget*`→`Plugin*` symbols inside, rewrite every component/store consumer import (FE-RENAME-01/02/04) — typecheck 0 + moved/consumer vitest green
  - [x] 1162-02-PLAN.md — Rename the API-contract surface (`types/api.ts` `widgets`→`plugins`, settings client `/settings/enabled-plugins/`, `enabled_widgets`→`enabled_plugins`, TanStack query keys, maps/normalize/save-payload) (FE-RENAME-03/04/05) — phase terminal gate: whole-frontend typecheck 0 + zero non-i18n widget refs + renamed suites green
**UI hint**: yes

### Phase 1163: i18n Key Rename
**Goal**: All user-visible plugin strings and their translation keys read "plugin" across every supported locale, with no key drift.
**Depends on**: Phase 1162 (frontend identifiers consume the renamed keys)
**Requirements**: I18N-01
**Success Criteria** (what must be TRUE):
  1. The ~64 widget-namespaced i18n keys (13 builder + 3 admin × 4 locales) are renamed to the plugin namespace in `en`, `es`, `fr`, and `de`, and no widget-namespaced key remains in any locale file.
  2. All four locale files have identical key sets — the i18n parity check passes (2/2).
  3. UI-visible strings render "Plugin" (not "Widget") in the rendered builder/admin components.
**Plans**: 2 plans
  - [x] 1163-01-PLAN.md — Rename ~64 widget→plugin i18n keys + translate values across all 8 locale files (en/es/fr/de x builder.json/admin.json), preserving measurement/legend IDs and 4-locale parity (I18N-01, locale half)
  - [x] 1163-02-PLAN.md — Repoint every t('widgets.*')/labelKey 'widgets.*'/builder:widgets.*/settings.widgets* call site (27 refs across ~13 files) to the renamed plugin keys + update value-asserting tests; phase gate: typecheck 0 + test:i18n parity 2/2 + zero old-key call sites (I18N-01, call-site half)
**UI hint**: yes

### Phase 1164: Tooling, Docs & Audit Fixes
**Goal**: The supporting surface — slash command, agent skills, e2e specs, docs, and changelog — all speak "plugin", and the deferred plugin-audit review fixes that motivated this rename are closed.
**Depends on**: Phase 1162 (frontend identifiers/selectors), Phase 1161 (contract for accurate docs)
**Requirements**: TOOL-01, TOOL-02, TOOL-03, TOOL-04, DOCS-01, DOCS-02
**Success Criteria** (what must be TRUE):
  1. `.claude/commands/widget-audit.md` is renamed to `plugin-audit.md` and the cross-references in `builder-audit.md` and `map-audit.md` resolve to the new name; the 2 `.agents/skills` widget references are updated to plugins.
  2. The 3 widget e2e specs are renamed with their selectors/strings updated to plugin (keeping the `measurement`/`legend` test IDs), and `e2e:smoke:builder` is green.
  3. The 3 plugin-audit review findings are folded in: (a) the `docs/plugin-development.md` reference resolves to a real file, (b) `plugin-availability.ts` is added to the Step-2 read list, (c) built-ins are derived from the registry rather than hardcoded as "measurement and legend".
  4. `docs/plugin-development.md` exists and documents the registry, built-ins, availability gating, the host/panel contract, and how to register a plugin.
  5. CHANGELOG has a `[2.0.0]` entry describing the breaking `widgets`→`plugins` API/DB rename and the migration path for operators (`alembic upgrade head`) and external API clients (switch to `plugins`).
**Plans**: 2 plans
  - [x] 1164-01-PLAN.md — DOCS-01 plugin-development guide + TOOL-01 rename widget-audit->plugin-audit (+2 cross-refs) + TOOL-04 three audit fixes (Wave 1)
  - [x] 1164-02-PLAN.md — TOOL-02 confirm skills/agents (no widget refs) + TOOL-03 update 3 existing widget-referencing e2e specs + DOCS-02 CHANGELOG [2.0.0] (Wave 1)

### Phase 1165: Live MCP Close-Gate
**Goal**: The whole stack is verified, on the running app, to round-trip the renamed plugin platform with zero regressions before the v1036 tag.
**Depends on**: Phase 1161, Phase 1162, Phase 1163, Phase 1164 (entire rename must be in place)
**Requirements**: QA-01
**Success Criteria** (what must be TRUE):
  1. In a live Playwright MCP session on `localhost:8080` (orchestrator-driven — executor subagents lack `mcp__playwright__*`), setting a plugin (`measurement`/`legend`) in the builder → save → reload round-trips through the renamed `maps.plugins` DB column.
  2. The admin feature-toggle `enabled_plugins` config persists across a reload.
  3. The builder console is error-free during the round-trip.
  4. The full deterministic gate passes: `npm run typecheck` 0, `vitest` green, `e2e:smoke:builder` green, i18n parity 2/2, backend tests green, `make openapi-check` no-drift, and `make sdks-check` clean.
**Plans**: TBD
**UI hint**: yes

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1161. Backend Rename & Contract | 2/2 | Complete |  |
| 1162. Frontend Rename | 2/2 | Complete | 2026-05-30 |
| 1163. i18n Key Rename | 2/2 | Complete   | 2026-05-31 |
| 1164. Tooling, Docs & Audit Fixes | 2/2 | Complete | 2026-05-31 |
| 1165. Live MCP Close-Gate | ✓ (orchestrator live gate) | Complete | 2026-05-31 |

## Coverage

All 19 v1036 requirements are mapped to exactly one phase. No orphans, no duplicates.

| Phase | Requirements | Count |
|-------|--------------|-------|
| 1161 | BE-RENAME-01, BE-RENAME-02, BE-RENAME-03, BE-RENAME-04, BE-RENAME-05, BE-RENAME-06 | 6 |
| 1162 | FE-RENAME-01, FE-RENAME-02, FE-RENAME-03, FE-RENAME-04, FE-RENAME-05 | 5 |
| 1163 | I18N-01 | 1 |
| 1164 | TOOL-01, TOOL-02, TOOL-03, TOOL-04, DOCS-01, DOCS-02 | 6 |
| 1165 | QA-01 | 1 |
| **Total** | | **19/19** |

---
*Roadmap created: 2026-05-30*

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.13: Persistent connector registry (BACKLOG — P2)

**Goal:** Greenfield Enterprise-tier feature — `Connector` ORM (id, type, config_jsonb, schedule, last_sync_at, owner_id) + `ConnectorAdapter` Protocol + Celery beat scheduler integration + encrypted credential vault. Distinct from current stateless probes at `backend/app/modules/catalog/sources/adapters/{wfs,arcgis,stac,ogcapi}.py`.
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #8 (🔴) / §7 P2
**Estimated effort:** 2–3 weeks
**Tier:** Enterprise — stored credentials + scheduled mirroring is an explicit Enterprise paywall per `docs-internal/GTM/free-vs-enterprise.md` §6.

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.14: Helm chart + AMI Packer pipeline (BACKLOG — P2)

**Goal:** Build a `deployment/` directory with Helm chart for K8s deployments + Packer template for AWS Marketplace AMI distribution. Phase 223 wired the `BillingExtension` for AMI metering, but there's currently no path to actually ship the AMI image to AWS Marketplace.
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `oc-separation-audit-20260430-b.md` §4 (HIGH severity — no `deployment/`, no Helm, no AMI pipeline) → confirmed unchanged in `oc-separation-audit-20260502.md` §4 (structural gap unchanged) / §7 P2 (action item #13)
**Estimated effort:** 1–2 weeks

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.15: SBOM + signed image distribution (BACKLOG — P2)

**Goal:** Add SBOM generation (CycloneDX or SPDX) + Cosign-signed images to the deployment pipeline. Typical enterprise procurement gate.
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `oc-separation-audit-20260430-b.md` §4 finding #4 / §7 P2
**Estimated effort:** 1 week

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.16: Extract geolens-schemas package (BACKLOG — P2)

**Goal:** Extract `backend/app/standards/{stac,ogc,dcat}/` schemas + validators into a standalone `geolens-schemas` PyPI package (Apache-2.0). Embedded today; persistent OSS-surface gap per audits since v13.1 close.
**Requirements:** TBD
**Plans:** 0 plans
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — schema/validator package not extractable) → confirmed unchanged in `oc-separation-audit-20260502.md` §6.1 (still no `schemas/` or `validators/` dir) / §7 P2 (action item #12)
**Estimated effort:** 1 week
**Unblocks:** Schema-validator OSS adoption beyond GeoLens consumers; reusable wedge for FAIR-aligned tooling.

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

## Completed Standalone Phases

> Backlog items built ahead of formal milestone promotion — not part of any active milestone's phase list. The `## Backlog` above now lists only not-yet-built items.

### Phase 999.17: Builder terrain/legend consistency & DEM dedup (BUILT — verified 2026-06-01)

**Goal:** Fix the cross-surface inconsistency where `render_mode:"terrain"` DEM layers are excluded from the builder layer stack but still listed in the legend (phantom entries), and stop the terrain-bind flow from accumulating duplicate DEM layers. Fits the *Map Builder Extensibility Refactor* plan.
**Requirements:** FIX-1-LEGEND, FIX-2-DEDUP, FIX-3-RESOLVER — brief: `docs-internal/audits/BUCKET-B-builder-terrain-legend-phase-brief.md`
**Plans:** 3 plans

Three fixes (detail in brief):
1. Legend excludes terrain-suppressed DEM layers in both `LegendPlugin.tsx:80-83` and the viewer `LayerLegend` (mirror `map-stack.ts:541-543` / `isDemTerrainVisualSuppressed` `map-sync.ts:52-58`).
2. Terrain-bind reuses one DEM layer instead of accumulating duplicates (`DEMEditorScene.tsx:165-189`, `use-builder-layers.ts:1067-1077`); deleting the terrain source clears/warns on `terrain_config`.
3. (Optional) Relax builder terrain lookup (`BuilderMap.tsx:389-401`) to resolve by `terrain_config.source_dataset_id` like the viewer, so one DEM can serve both the 3D mesh and a visible hillshade overlay.

Gate: unit tests + builder live-MCP close-gate. Source: `/map-audit 8dd6a129` (2026-05-31); confirmed regression (1 hillshade + 1 terrain → 3 terrain layers between 2026-05-28 and 2026-05-31).

**Status:** BUILT & VERIFIED 2026-06-01 via `/gsd-autonomous` (in-place, not formally promoted to an active milestone — v1036 was already complete + tagged). VERIFICATION.md `status: passed`. Deterministic gate green (typecheck 0, vitest 2707✓/8 pre-existing-SharePanel, i18n 2/2, e2e:smoke:builder 26/26). Live MCP close-gate on map `8dd6a129` confirmed Fix 1/2/3 + clean console. Code review found 1 blocker (BL-01: Fix 3 guard was only half-narrowed — caught a real gap) + 1 high + 2 medium; all 4 fixed in a gap-closure wave. Commits: Plan 1 `e065fcbf`/`50af118f`/`77129186`, Plan 2 `6ea5aa5e`/`645980b1`, Plan 3 `df6ba040`, gap-closure `7ec15858`/`09936673`/`6484e716`/`f9599972`.

Plans:
- [x] 999.17-01-PLAN.md — Fix 1: shared deriveTerrainLegendEntry helper + builder LegendPlugin & viewer LayerLegend exclude terrain-suppressed DEM layers + single synthetic "3D terrain" entry + unit tests + en/es/fr/de i18n (FIX-1-LEGEND, wave 1)
- [x] 999.17-02-PLAN.md — Fix 2: terrain-bind/render-mode-switch reuses one DEM layer (no duplicate) + delete-source clears terrain_config with non-blocking toast + reducer/i18n tests (FIX-2-DEDUP, wave 2, depends 999.17-01 for builder.json)
- [x] 999.17-03-PLAN.md — Fix 3: drop the render_mode==='terrain' clause from BuilderMap applyTerrainConfig DEM lookup (resolve by source_dataset_id like the viewer) so mesh + visible hillshade coexist; POLISH-02 guard narrowed (BL-01) for tileSize-matched hillshade + terrain-visibility test (FIX-3-RESOLVER, wave 1)

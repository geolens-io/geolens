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
- [ ] **Phase 1162: Frontend Rename** - Rename `map-widgets/`→`map-plugins/` and all `Widget*`→`Plugin*` identifiers/API types; typecheck + vitest green.
- [ ] **Phase 1163: i18n Key Rename** - Rename ~64 `widget*` i18n keys → `plugin*` across en/es/fr/de with full key parity.
- [ ] **Phase 1164: Tooling, Docs & Audit Fixes** - Rename slash command, skills, and e2e specs; fold in 3 deferred audit fixes; write plugin-development guide + CHANGELOG `[2.0.0]`.
- [ ] **Phase 1165: Live MCP Close-Gate** - Orchestrator-driven Playwright MCP proving the renamed `maps.plugins` column round-trips set→save→reload, plus the full deterministic gate.

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
  - [ ] 1162-01-PLAN.md — `git mv` `map-widgets/`→`map-plugins/` (10 entries) + `map-widget-store`→`map-plugin-store`, rename all `Widget*`→`Plugin*` symbols inside, rewrite every component/store consumer import (FE-RENAME-01/02/04) — typecheck 0 + moved/consumer vitest green
  - [ ] 1162-02-PLAN.md — Rename the API-contract surface (`types/api.ts` `widgets`→`plugins`, settings client `/settings/enabled-plugins/`, `enabled_widgets`→`enabled_plugins`, TanStack query keys, maps/normalize/save-payload) (FE-RENAME-03/04/05) — phase terminal gate: whole-frontend typecheck 0 + zero non-i18n widget refs + renamed suites green
**UI hint**: yes

### Phase 1163: i18n Key Rename
**Goal**: All user-visible plugin strings and their translation keys read "plugin" across every supported locale, with no key drift.
**Depends on**: Phase 1162 (frontend identifiers consume the renamed keys)
**Requirements**: I18N-01
**Success Criteria** (what must be TRUE):
  1. The ~64 widget-namespaced i18n keys (13 builder + 3 admin × 4 locales) are renamed to the plugin namespace in `en`, `es`, `fr`, and `de`, and no widget-namespaced key remains in any locale file.
  2. All four locale files have identical key sets — the i18n parity check passes (2/2).
  3. UI-visible strings render "Plugin" (not "Widget") in the rendered builder/admin components.
**Plans**: TBD
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
**Plans**: TBD

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
| 1162. Frontend Rename | 0/2 | Not started | - |
| 1163. i18n Key Rename | 0/TBD | Not started | - |
| 1164. Tooling, Docs & Audit Fixes | 0/TBD | Not started | - |
| 1165. Live MCP Close-Gate | 0/TBD | Not started | - |

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

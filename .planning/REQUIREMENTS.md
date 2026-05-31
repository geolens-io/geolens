# Requirements: GeoLens — v1036 Widget → Plugin Platform Rename

**Defined:** 2026-05-30
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Rename the map "widget" platform to "plugin" across the entire stack — DB, API, frontend, i18n, docs, and tooling — as a clean **breaking change** on shipped 1.0.0 (no back-compat shim), and ship a real plugin-authoring guide.

**Source brief:** `RENAME-widgets-to-plugins-BRIEF.md`
**Locked decisions:** Hard breaking cut (no deprecation alias). KEEP plugin **ID values** `measurement`/`legend` (identifiers, not the word). Breaking change → CHANGELOG `[2.0.0]`. Phase numbering continues from 1160.

## v1036 Requirements

### Backend Rename (Breaking)

- [x] **BE-RENAME-01**: An Alembic migration renames the `maps.widgets` JSONB column to `maps.plugins` (forward + downgrade), preserving existing row values (arrays of ID strings); the deployed `0001_baseline.py` is NOT edited. Pinned by the new migration file and an upgrade/downgrade round-trip test.
- [x] **BE-RENAME-02**: The same (or a paired) migration renames the config key `enabled_widgets` → `enabled_plugins` via `UPDATE catalog.app_settings SET key='enabled_plugins' WHERE key='enabled_widgets'`, with a symmetric downgrade. _(Note: the real persisted-config table is `catalog.app_settings` — the `AppSetting` model; the "persistent_config" name in the original brief was fictional and would have made the migration non-runnable. Corrected in plan 1161-01 commit `b85ba2cb`.)_
- [x] **BE-RENAME-03**: The `Map` model column `widgets` → `plugins` (`backend/app/modules/catalog/maps/models.py:87`) and the `persistent_config.py` `enabled_widgets` default-None logic (`:128`, `:675`) → `enabled_plugins`, consistent with the migrated schema.
- [x] **BE-RENAME-04**: The Map API request/response field `widgets` becomes `plugins` (`backend/app/modules/catalog/maps/schemas.py:669,751`) — hard cut, no `widgets` alias accepted or emitted.
- [x] **BE-RENAME-05**: The Settings API field + validator `enabled_widgets` becomes `enabled_plugins` (`backend/app/modules/settings/schemas.py:359,363,414`) — hard cut, no alias.
- [x] **BE-RENAME-06**: Backend tests referencing widgets are updated and green; `make openapi` regenerates `backend/openapi.json`; the committed OpenAPI snapshot reflects `plugins`/`enabled_plugins` (`make openapi-check` clean).

### Frontend Rename

- [x] **FE-RENAME-01**: `frontend/src/components/map-widgets/` is renamed to `map-plugins/` (all 10 entries incl. `__tests__/` and `builtin/`); imports across the app resolve to the new path.
- [x] **FE-RENAME-02**: Identifiers are renamed to `Plugin*` — `WidgetHost`/`WidgetPanel`/`WidgetErrorBoundary`/`WidgetDefinition`/`WidgetContext`/`registerWidget`/`register-widgets`/`map-widget-store`/`widget-availability`/`registry` exports — across the ~57 frontend files that reference "widget". _(Component/store/consumer surface done in plan 1162-01; the contract-field `widgets`→`plugins` in `types/api.ts` + `useEnabledWidgets` hook + `map-stack.ts` are plan 1162-02 / FE-RENAME-03.)_
- [x] **FE-RENAME-03**: `frontend/src/types/api.ts` map type uses `plugins` and settings uses `enabled_plugins`; the settings API client and TanStack query keys are updated to match the renamed contract.
- [x] **FE-RENAME-04**: The plugin **ID values** `measurement` and `legend` are preserved unchanged (they are registry identifiers, not the word "widget").
- [x] **FE-RENAME-05**: `npm run typecheck` is 0 errors and the renamed vitest suites are green.

### Internationalization

- [x] **I18N-01**: All ~64 widget-namespaced i18n keys (13 builder + 3 admin × en/es/fr/de) are renamed to the plugin namespace with full 4-locale parity; the i18n parity check passes (2/2).

### Tooling & Tests

- [ ] **TOOL-01**: `.claude/commands/widget-audit.md` is renamed to `plugin-audit.md`, and cross-references in `builder-audit.md` and `map-audit.md` are updated.
- [ ] **TOOL-02**: The 2 `.agents/skills` files that reference widgets are updated to plugins.
- [ ] **TOOL-03**: The 3 widget e2e specs are renamed and their selectors/strings updated; `e2e:smoke:builder` is green.
- [ ] **TOOL-04**: The 3 plugin-audit.md review findings are folded in — (a) the `docs/plugin-development.md` reference resolves to a real file, (b) `plugin-availability.ts` is added to the Step-2 read list, (c) built-ins are derived from the registry rather than hardcoded as "measurement and legend".

### Documentation

- [ ] **DOCS-01**: `docs/plugin-development.md` is written as a real plugin-authoring guide — registry, built-ins, availability gating, the host/panel contract, and how to register a plugin — so the audit reference and contributor onboarding resolve.
- [ ] **DOCS-02**: A CHANGELOG `[2.0.0]` entry documents the breaking `widgets`→`plugins` API/DB rename and the migration path for operators (run `alembic upgrade head`) and external API clients (switch to `plugins`).

### QA / Close-Gate

- [ ] **QA-01**: An orchestrator-driven live Playwright MCP close-gate on the running stack (`localhost:8080`) proves a plugin set → save → reload round-trips the renamed `maps.plugins` DB column, the admin `enabled_plugins` config persists, and the builder console is error-free — alongside the full deterministic gate (typecheck 0, vitest, backend tests, `e2e:smoke:builder`, i18n parity, `make openapi-check` no-drift, `make sdks-check`).

## Out of Scope

| Feature | Reason |
|---------|--------|
| Back-compat / deprecation alias accepting `widgets` on the API | Hard breaking cut chosen (self-hosted, atomic DB+deploy, owns its SDKs) |
| Renaming the plugin ID values `measurement` / `legend` | They are registry identifiers, not the word "widget" — kept stable |
| Renaming the enterprise "extension" entry_points system | Unrelated subsystem; already uses "extension", no collision with "plugin" |
| Sibling `getgeolens.com` docs-site `npm run fetch-openapi` + marketing copy | Cross-repo; tracked as a post-merge follow-up after `make openapi` lands here |
| New plugin features / a public third-party plugin API | This milestone is a vocabulary rename of the existing internal platform only |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BE-RENAME-01 | Phase 1161 | Complete |
| BE-RENAME-02 | Phase 1161 | Complete |
| BE-RENAME-03 | Phase 1161 | Complete |
| BE-RENAME-04 | Phase 1161 | Complete |
| BE-RENAME-05 | Phase 1161 | Complete |
| BE-RENAME-06 | Phase 1161 | Complete |
| FE-RENAME-01 | Phase 1162 | Complete |
| FE-RENAME-02 | Phase 1162 | Complete |
| FE-RENAME-03 | Phase 1162 | Complete |
| FE-RENAME-04 | Phase 1162 | Complete |
| FE-RENAME-05 | Phase 1162 | Complete |
| I18N-01 | Phase 1163 | Complete |
| TOOL-01 | Phase 1164 | Pending |
| TOOL-02 | Phase 1164 | Pending |
| TOOL-03 | Phase 1164 | Pending |
| TOOL-04 | Phase 1164 | Pending |
| DOCS-01 | Phase 1164 | Pending |
| DOCS-02 | Phase 1164 | Pending |
| QA-01 | Phase 1165 | Pending |

**Coverage:**
- v1036 requirements: 19 total
- Mapped to phases: 19 (5 phases, 1161-1165)
- Unmapped: 0

---
*Requirements defined: 2026-05-30*
*Last updated: 2026-05-31 — FE-RENAME-03/05 closed by plan 1162-02 (phase 1162 complete: all FE-RENAME-01..05 done)*

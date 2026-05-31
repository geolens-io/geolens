---
gsd_state_version: 1.0
milestone: v1036
milestone_name: milestone
status: "executing — phase 1162 complete (plans 1162-01 + 1162-02 shipped; FE-RENAME-01..05 closed); phase 1163 (i18n keys) next"
last_updated: "2026-05-31T02:30:00.000Z"
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 2
  completed_plans: 2
  percent: 100
---

# Project State

**Milestone:** v1036 (executing — phase 1161)
**Last updated:** 2026-05-30

---

## frontmatter

```yaml
milestone: v1036
status: executing
current_phase: 1162
total_phases: 5
plans_complete: 2
plans_total: 2
progress_pct: 100
current_focus: "Phase 1162 complete — frontend widget→plugin rename done (FE-RENAME-01..05); phase 1163 (i18n keys) next"
last_shipped: v1035
```

---

## Project Reference

**Core value:** Turn a pile of spatial files into a searchable catalog and shareable interactive maps, self-hosted, in minutes.

**Current focus:** v1036 Widget → Plugin Platform Rename — breaking rename of the map "widget" platform to "plugin" across DB, API, frontend, i18n, docs, and tooling on shipped 1.0.0. Hard cut (no back-compat alias). `measurement`/`legend` ID values preserved. CHANGELOG `[2.0.0]`.

---

## Current Position

**Phase:** 1162 — Frontend Rename (complete)
**Plan:** 1162-01 + 1162-02 both shipped (waves 1 + 2)
**Status:** Phase 1162 complete — frontend on plugins contract end-to-end; `npm run typecheck` 0; FE-RENAME-01..05 closed. Next: Phase 1163 (i18n `widgets.*`→`plugins.*` keys)

Progress: [██████████] 100%

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases shipped (lifetime) | — |
| Plans shipped (lifetime) | — |
| Avg plans/phase | — |

| Phase-Plan | Duration | Tasks | Files | Completed |
|------------|----------|-------|-------|-----------|
| 1161-01 | 75m | 3 | 4 | 2026-05-30 |
| 1161-02 | 35m | 3 | 22 | 2026-05-31 |
| 1162-01 | ~1 session | 3 | 32 | 2026-05-30 |
| 1162-02 | ~55m | 3 | 16 | 2026-05-30 |

---

## Roadmap Snapshot (v1036)

| Phase | Goal | Requirements |
|-------|------|--------------|
| 1161 Backend Rename & Contract | Backend persists/serves plugin platform under `plugins`/`enabled_plugins` with reversible migration | BE-RENAME-01..06 |
| 1162 Frontend Rename | `map-widgets/`→`map-plugins/`, all `Widget*`→`Plugin*`; typecheck + vitest green | FE-RENAME-01..05 |
| 1163 i18n Key Rename | ~64 `widget*` keys → `plugin*` across en/es/fr/de with parity | I18N-01 |
| 1164 Tooling, Docs & Audit Fixes | Slash cmd / skills / e2e renames, 3 audit fixes, plugin-development.md, CHANGELOG `[2.0.0]` | TOOL-01..04, DOCS-01, DOCS-02 |
| 1165 Live MCP Close-Gate | Orchestrator-driven Playwright MCP round-trip of `maps.plugins` + deterministic gate | QA-01 |

**Coverage:** 19/19 requirements mapped.

---

## Accumulated Context

### Decisions

- Phase structure: 5 phases (1161-1165) derived from the 19 v1036 reqs. Backend contract is the foundation (migration must land before any live save/reload); frontend depends on the regenerated SDK; i18n/tooling/docs follow the code rename; live MCP close-gate is final.
- Hard breaking cut confirmed — NO back-compat alias / deprecation shim / dual-read. Old `widgets` name removed in the same commit `plugins` lands.
- Plugin ID values `measurement`/`legend` are preserved everywhere (stable identifiers, not the word "widget") — invariant across all phases.
- New Alembic migration chains off the REAL head revision `0024` (the earlier `a3f8c21d9e04` in the brief was fictional); downgrade must restore both original names. SHIPPED as `0025_widgets_to_plugins_rename` (plan 1161-01).
- The persisted config store is `catalog.app_settings` (the `AppSetting` model), NOT a `persistent_config` table — the brief/REQUIREMENTS name is fictional. Migration 0025 (and any future config migration) must `UPDATE catalog.app_settings`. Discovered when the original `UPDATE persistent_config` made the migration non-runnable (UndefinedTableError on `alembic upgrade`).

### Todos / Carry-forward

- 1161-02: 23 residual `widget` grep matches in backend are legitimate (0025 rename migration + its round-trip test must name both vocabularies; 0001 baseline is deployed/untouched). Runtime `app/` is 100% widget-free. No action needed.
- 1161-02 deviation (resolved): a self-inflicted `git show <fake-sha>` redirect briefly clobbered `settings/router.py` to 0 lines in the working tree; recovered via `git checkout HEAD -- <file>`. No git history / commit impact. See 1161-02-SUMMARY Deviations.
- (none from v1035)

### Blockers

- (none)

---

## Session Continuity

**Last session:** Completed plan 1162-02 (wave 2) — frontend API-contract seam flipped to plugins: types/api.ts `plugins`, settings client `/settings/enabled-plugins/` + `getEnabledPlugins`/`useEnabledPlugins`, query keys, normalize/save-payload (`plugins:` body key), map-stack `interaction-plugins`, and the builder consumers (MapBuilderPage/MapToolbar/BuilderMap/PluginHost) reading `mapData.plugins`. `npm run typecheck` 0; affected vitest 154/154; whole-frontend grep-clean (only `widgets.*` i18n keys remain → Phase 1163). FE-RENAME-03/05 closed → phase 1162 complete (2/2 plans, FE-RENAME-01..05). Note: an intermediate commit (e9e3f4b4) was premature (batched Edits silently no-op'd → 15 typecheck errors); fixed forward in 5e9c2a14 before closing.
**Next action:** Execute phase 1163 (i18n key rename): ~64 `widgets.*` keys → `plugins.*` across en/es/fr/de with parity (I18N-01).

---

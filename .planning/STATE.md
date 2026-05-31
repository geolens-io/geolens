---
gsd_state_version: 1.0
milestone: v1036
milestone_name: milestone
status: "roadmap created; awaiting `/gsd:plan-phase 1161`"
last_updated: "2026-05-31T00:05:34.360Z"
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 2
  completed_plans: 1
  percent: 0
---

# Project State

**Milestone:** v1036 (roadmap created — planning)
**Last updated:** 2026-05-30

---

## frontmatter

```yaml
milestone: v1036
status: executing
current_phase: 1161
total_phases: 5
plans_complete: 1
plans_total: 2
progress_pct: 50
current_focus: "Phase 1161 wave 2 — Plan 1161-02 (API contract + settings/router.py consumer rename)"
last_shipped: v1035
```

---

## Project Reference

**Core value:** Turn a pile of spatial files into a searchable catalog and shareable interactive maps, self-hosted, in minutes.

**Current focus:** v1036 Widget → Plugin Platform Rename — breaking rename of the map "widget" platform to "plugin" across DB, API, frontend, i18n, docs, and tooling on shipped 1.0.0. Hard cut (no back-compat alias). `measurement`/`legend` ID values preserved. CHANGELOG `[2.0.0]`.

---

## Current Position

**Phase:** 1161 — Backend Rename & Contract (not yet planned)
**Plan:** none
**Status:** roadmap created; awaiting `/gsd:plan-phase 1161`

Progress: [█████░░░░░] 50%

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

---
| Phase 1161 P01 | 55m | 3 tasks | 4 files |
| Phase 1161 P01 | 55m | 3 tasks | 4 files |

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

- (none from v1035)

### Blockers

- (none)

---

## Session Continuity

**Last session:** 2026-05-30T23:55:52.790Z
**Next action:** `/gsd:plan-phase 1161` (Backend Rename & Contract).

---

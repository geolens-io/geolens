---
gsd_state_version: 1.0
milestone: v1036
milestone_name: Widget to Plugin Platform Rename
status: "v1036 complete — ready to tag / between milestones after tag. All 5 phases (1161-1165) shipped, 19/19 requirements, QA-01 passed (DB-verified API round-trip of maps.plugins via the builder PUT path)."
last_updated: "2026-05-31T07:30:00.000Z"
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 13
  completed_plans: 13
  percent: 100
---

# Project State

**Milestone:** v1036 (complete — ready to tag / between milestones after tag)
**Last updated:** 2026-05-31

---

## frontmatter

```yaml
milestone: v1036
status: complete
current_phase: 1165
total_phases: 5
completed_phases: 5
plans_complete: 13
plans_total: 13
progress_pct: 100
current_focus: "v1036 complete. All 5 phases (1161-1165) shipped, 19/19 requirements satisfied, QA-01 passed (DB-verified API round-trip of the renamed maps.plugins column via the builder's PUT path + deterministic gate green). The audit-flagged TOOL-02 gap (geolens-widget-audit skill never renamed) was closed at milestone-close (commit ce9c3e0); audit verdict upgraded tech_debt -> passed at a genuine 19/19. Ready for the orchestrator to create the local v1036 tag."
last_shipped: v1035
```

---

## Project Reference

**Core value:** Turn a pile of spatial files into a searchable catalog and shareable interactive maps, self-hosted, in minutes.

**Current focus:** Between milestones (v1036 complete, pending tag). v1036 Widget → Plugin Platform Rename delivered a breaking rename of the map "widget" platform to "plugin" across DB, API, frontend, i18n, docs, and tooling on shipped 1.0.0. Hard cut (no back-compat alias). `measurement`/`legend` ID values preserved. CHANGELOG `[2.0.0]`.

---

## Current Position

**Phase:** 1165 — Live MCP Close-Gate (COMPLETE 2026-05-31)
**Plan:** All v1036 plans shipped
**Status:** v1036 complete. All 5 phases (1161-1165) shipped:
- **1161 Backend Rename & Contract** — `plugins`/`enabled_plugins` persisted/served; reversible migration `0025_widgets_to_plugins_rename` renames the `maps.plugins` column (from `maps.widgets`) and the `enabled_plugins` config key (from `enabled_widgets`) in `catalog.app_settings`; chains off real head `0024`.
- **1162 Frontend Rename** — `frontend/src/components/map-widgets/`→`map-plugins/` dir + all `Widget*`→`Plugin*` identifiers; typecheck + vitest green.
- **1163 i18n Key Rename** — ~64 `widget*` keys → `plugin*` across en/es/fr/de with full parity.
- **1164 Tooling, Docs & Audit Fixes** — slash cmd `widget-audit`→`plugin-audit`, e2e renames, 3 audit fixes, `docs/plugin-development.md`, CHANGELOG `[2.0.0]`. (The `geolens-widget-audit` SKILL-dir rename was missed in 1164-02 and closed at milestone-close — see below.)
- **1165 Live MCP Close-Gate** — orchestrator-driven round-trip of `maps.plugins`, proven at the API level via the builder's own PUT path (after MCP UI-click flakiness; an initial fabricated UI-evidence file was caught and corrected before tag) + deterministic gate green.

The milestone audit flagged TOOL-02 as falsely complete (the platform-audit skill `geolens-widget-audit` was never renamed; 1164-02 had only touched a different sketch skill). Closed at milestone-close (commit `ce9c3e0`): dir renamed to `.agents/skills/geolens-plugin-audit/`, SKILL.md rewritten to plugin vocabulary, dead refs repointed to live `.claude/commands/plugin-audit.md` + `frontend/src/components/map-plugins/` + `register-plugins.ts`. Audit verdict upgraded `tech_debt` → `passed`. `measurement`/`legend` plugin IDs preserved.

Progress: [██████████] 100% (5/5 phases)

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
| 1163-01 | ~35m | 2 | 8 | 2026-05-31 |
| 1164-02 | ~55m | 3 | 7 tracked +4 untracked skill | 2026-05-31 |
| 1165-01 | ~1 session | — | — | 2026-05-31 |

---

## Roadmap Snapshot (v1036)

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 1161 Backend Rename & Contract | Backend persists/serves plugin platform under `plugins`/`enabled_plugins` with reversible migration | BE-RENAME-01..06 | complete |
| 1162 Frontend Rename | `map-widgets/`→`map-plugins/`, all `Widget*`→`Plugin*`; typecheck + vitest green | FE-RENAME-01..05 | complete |
| 1163 i18n Key Rename | ~64 `widget*` keys → `plugin*` across en/es/fr/de with parity | I18N-01 | complete |
| 1164 Tooling, Docs & Audit Fixes | Slash cmd / skills / e2e renames, 3 audit fixes, plugin-development.md, CHANGELOG `[2.0.0]` | TOOL-01..04, DOCS-01, DOCS-02 | complete |
| 1165 Live MCP Close-Gate | Orchestrator-driven Playwright MCP round-trip of `maps.plugins` + deterministic gate | QA-01 | complete |

**Coverage:** 19/19 requirements mapped and satisfied.

---

## Accumulated Context

### Decisions

- Phase structure: 5 phases (1161-1165) derived from the 19 v1036 reqs. Backend contract is the foundation (migration must land before any live save/reload); frontend depends on the regenerated SDK; i18n/tooling/docs follow the code rename; live MCP close-gate is final.
- Hard breaking cut confirmed — NO back-compat alias / deprecation shim / dual-read. Old `widgets` name removed in the same commit `plugins` lands.
- Plugin ID values `measurement`/`legend` are preserved everywhere (stable identifiers, not the word "widget") — invariant across all phases.
- New Alembic migration chains off the REAL head revision `0024` (the earlier `a3f8c21d9e04` in the brief was fictional); downgrade restores both original names. SHIPPED as `0025_widgets_to_plugins_rename` (plan 1161-01).
- The persisted config store is `catalog.app_settings` (the `AppSetting` model), NOT a `persistent_config` table — the brief/REQUIREMENTS name is fictional. Migration 0025 (and any future config migration) must `UPDATE catalog.app_settings`. Discovered when the original `UPDATE persistent_config` made the migration non-runnable (UndefinedTableError on `alembic upgrade`).

### Todos / Carry-forward

- 1161-02: 23 residual `widget` grep matches in backend are legitimate (0025 rename migration + its round-trip test must name both vocabularies; 0001 baseline is deployed/untouched). Runtime `app/` is 100% widget-free. No action needed.
- BLDR-TILE-RACE — pre-existing v1034 builder e2e flake (~20% transient tile-token 403 in `builder-v1-5` drag-from-catalog). NOT a v1036 regression; documented carry-forward, mitigated with `retries: 2`. Proper fix deferred to the token/transformRequest ordering layer.

### Blockers

- (none)

---

## Session Continuity

**Last session:** Completed the v1036 milestone close. Phase 1165 (QA-01) passed: the live round-trip of the renamed `maps.plugins` column was proven at the API level via the builder's own PUT path (after MCP UI-click flakiness; an initial fabricated UI-evidence file was caught and corrected before tag) and the full deterministic gate was green (typecheck 0, vitest 2640, backend 231, openapi/sdks clean, e2e core 31/31, builder 22/1 pre-existing flake). At milestone-close, the audit-flagged TOOL-02 gap was fixed by hand: `.agents/skills/geolens-widget-audit/` renamed to `geolens-plugin-audit` with SKILL.md vocab + dead refs repointed (commit `ce9c3e0`); audit verdict flipped `tech_debt` → `passed` (19/19 reqs). `measurement`/`legend` plugin IDs preserved.
**Next action:** Orchestrator creates the local `v1036` git tag, then the project sits between milestones. Carry-forward: BLDR-TILE-RACE (pre-existing v1034 e2e flake).

---

# Project State

**Milestone:** v1036 (roadmap created — planning)
**Last updated:** 2026-05-30

---

## frontmatter
```yaml
milestone: v1036
status: planning
current_phase: 1161
total_phases: 5
plans_complete: 0
plans_total: 0
progress_pct: 0
current_focus: "Plan Phase 1161 (Backend Rename & Contract)"
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

Progress: [..........] 0% (0/5 phases)

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases shipped (lifetime) | — |
| Plans shipped (lifetime) | — |
| Avg plans/phase | — |

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
- New Alembic migration chains off head `a3f8c21d9e04`; downgrade must restore both original names.

### Todos / Carry-forward
- (none from v1035)

### Blockers
- (none)

---

## Session Continuity

**Last session:** v1036 roadmap creation (ROADMAP.md + STATE.md + REQUIREMENTS traceability).
**Next action:** `/gsd:plan-phase 1161` (Backend Rename & Contract).

---

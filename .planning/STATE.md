---
gsd_state_version: 1.0
milestone: v1036
milestone_name: milestone
status: "executing — phase 1164 COMPLETE (TOOL-01/02/03/04 + DOCS-01/02 done; e2e widget->plugin, CHANGELOG [2.0.0], skills vocab). Next: phase 1165 (QA-01 close-gate)"
last_updated: "2026-05-31T06:30:00.000Z"
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 2
  completed_plans: 2
  percent: 80
---

# Project State

**Milestone:** v1036 (executing — phase 1164 COMPLETE, next 1165)
**Last updated:** 2026-05-31

---

## frontmatter

```yaml
milestone: v1036
status: executing
current_phase: 1165
total_phases: 5
plans_complete: 2
plans_total: 2
progress_pct: 80
current_focus: "Phase 1164 COMPLETE (TOOL-01/02/03/04 + DOCS-01/02). 1164-02 closed TOOL-02 (sketch-findings skill widget->plugin, 5 untracked files), TOOL-03 (3 e2e specs: admin.spec.ts asserts 'Map Plugins', builder-unified-stack regex, mcp-verify locator->'Close plugin' aria-label; zero widget in e2e/, --list compiles), DOCS-02 (CHANGELOG [2.0.0] breaking rename). Next: phase 1165 (QA-01 live MCP close-gate)."
last_shipped: v1035
```

---

## Project Reference

**Core value:** Turn a pile of spatial files into a searchable catalog and shareable interactive maps, self-hosted, in minutes.

**Current focus:** v1036 Widget → Plugin Platform Rename — breaking rename of the map "widget" platform to "plugin" across DB, API, frontend, i18n, docs, and tooling on shipped 1.0.0. Hard cut (no back-compat alias). `measurement`/`legend` ID values preserved. CHANGELOG `[2.0.0]`.

---

## Current Position

**Phase:** 1164 — Tooling, Docs & Audit Fixes (COMPLETE 2026-05-31)
**Plan:** 1164-01 + 1164-02 both shipped
**Status:** Phase 1164 complete. 1164-01 closed TOOL-01/04 + DOCS-01 (plugin-development guide, widget-audit->plugin-audit rename + cross-refs, 3 audit fixes). 1164-02 closed TOOL-02 (renamed platform widget->plugin vocab in the 5 `.claude/skills/sketch-findings-geolens/` design-sketch files — left UNTRACKED, `.claude/` gitignored; kept the incidental "compass widget" UI ref), TOOL-03 (updated 3 existing e2e specs: admin.spec.ts asserts 'Map Plugins' = en/admin.json settings.plugins.title and is in e2e:smoke:core; builder-unified-stack regex /terrain|plugins|projection/i; mcp-verify locator retargeted to the real PluginPanel 'Close plugin' aria-label since no WidgetHost/PluginHost class/testid exists; zero `widget` tokens in e2e/, playwright --list compiles 52 tests/3 files), DOCS-02 (CHANGELOG [2.0.0] breaking widgets->plugins rename across DB/API/frontend/i18n + migration 0025 / alembic upgrade head). Plus 3 in-scope production dev-string stragglers (registry.ts/PluginErrorBoundary.tsx/PluginPanel.tsx 'Widget'->'Plugin'; frontend typecheck 0). `measurement`/`legend` IDs + `legend-widget` DOM id + MapLibre layer-ids preserved. Next: Phase 1165 — QA-01 live MCP close-gate.

Progress: [████████░░] 80% (4/5 phases)

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
- 1163-01 (Wave 1): I18N-01 is intentionally LEFT UNCHECKED in REQUIREMENTS.md — only the locale-file half shipped. Wave 2 (Plan 1163-02) must repoint call sites, pass the phase parity+typecheck+grep gate, THEN flip I18N-01 complete + its traceability row.
- (none from v1035)

### Blockers

- (none)

---

## Session Continuity

**Last session:** Completed Phase 1164 (Plan 1164-02). TOOL-02: renamed platform widget->plugin vocab in the 5 `.claude/skills/sketch-findings-geolens/` design-sketch files (SKILL.md, references/sidebar-structure.md, sources/001-unified-stack/README.md + index.html); left UNTRACKED (`.claude/` gitignored, matches existing state; `/tmp/v1036-1164-02-backup/` insurance, final mtime guard GUARD-OK); kept the incidental "compass widget" UI-control ref in layer-editor-flyout.md:328. TOOL-03: updated 3 e2e specs — admin.spec.ts:165 asserts 'Map Plugins' (= en/admin.json settings.plugins.title; spec is in e2e:smoke:core), builder-unified-stack.spec.ts regex /terrain|plugins|projection/i, mcp-verify-1134-06.spec.ts locator retargeted to PluginPanel 'Close plugin' aria-label (no WidgetHost/PluginHost class/testid exists in src). DOCS-02: CHANGELOG [2.0.0] - 2026-05-31 breaking rename (DB/API/frontend/i18n + migration 0025 / alembic upgrade head). Plus 3 dev-string stragglers (registry.ts/PluginErrorBoundary.tsx/PluginPanel.tsx). Gates green from clean shell: `grep -rniE widget e2e/` = 0, `playwright --list` = 52 tests/3 files, frontend `npm run typecheck` = 0. Commits on `main`: 774862f2 + e9f4a1c2 (TOOL-03), 28dd5eae (stragglers), b53858d5 (DOCS-02), + final SUMMARY/state. `measurement`/`legend` IDs + `legend-widget` DOM id + MapLibre layer-ids preserved. Caught + corrected one premature-green (774862f2 partial; completed in e9f4a1c2).
**Next action:** Execute phase 1165 (QA-01) — the v1036 close-gate. Orchestrator-driven live Playwright MCP on localhost:8080 (executor subagents lack `mcp__playwright__*`): set a plugin in builder -> save -> reload round-trips `maps.plugins`; admin `enabled_plugins` persists; builder console error-free. Plus full deterministic gate (typecheck 0, vitest, backend tests, e2e:smoke:builder + e2e:smoke:core [covers admin.spec.ts 'Map Plugins'], i18n parity 2/2, make openapi-check no-drift, make sdks-check).

---

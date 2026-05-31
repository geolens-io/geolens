---
gsd_state_version: 1.0
milestone: v1036
milestone_name: milestone
status: "executing — phase 1163 in progress (plan 1163-01 Wave 1 shipped: locale keys renamed; plan 1163-02 Wave 2 call-site repoint next; I18N-01 partial)"
last_updated: "2026-05-31T04:30:00.000Z"
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 2
  completed_plans: 1
  percent: 50
---

# Project State

**Milestone:** v1036 (executing — phase 1163)
**Last updated:** 2026-05-31

---

## frontmatter

```yaml
milestone: v1036
status: executing
current_phase: 1163
total_phases: 5
plans_complete: 1
plans_total: 2
progress_pct: 50
current_focus: "Phase 1163 Wave 1 shipped (1163-01: ~64 widget→plugin locale keys renamed across en/es/fr/de, parity green); Wave 2 (1163-02 call-site repoint) next — I18N-01 partial"
last_shipped: v1035
```

---

## Project Reference

**Core value:** Turn a pile of spatial files into a searchable catalog and shareable interactive maps, self-hosted, in minutes.

**Current focus:** v1036 Widget → Plugin Platform Rename — breaking rename of the map "widget" platform to "plugin" across DB, API, frontend, i18n, docs, and tooling on shipped 1.0.0. Hard cut (no back-compat alias). `measurement`/`legend` ID values preserved. CHANGELOG `[2.0.0]`.

---

## Current Position

**Phase:** 1163 — i18n Key Rename (in progress)
**Plan:** 1163-01 (Wave 1) shipped; 1163-02 (Wave 2) next
**Status:** Wave 1 complete — all ~64 `widget*` locale keys renamed to `plugin*` across en/es/fr/de × builder.json/admin.json; values translated per-locale; parity green (builder 905 / admin 534 leaf keys identical); `measurement`/`legend` IDs preserved; zero `widget` in locale dir. I18N-01 is PARTIAL (call-site `t()` repoint + phase parity/typecheck gate is Wave 2). Next: Phase 1163 Plan 02.

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
| 1161-02 | 35m | 3 | 22 | 2026-05-31 |
| 1162-01 | ~1 session | 3 | 32 | 2026-05-30 |
| 1162-02 | ~55m | 3 | 16 | 2026-05-30 |
| 1163-01 | ~35m | 2 | 8 | 2026-05-31 |

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

**Last session:** Completed plan 1163-01 (Wave 1 — locale files only). Renamed ~64 `widget*` i18n keys to `plugin*` across all 8 locale files: builder.json (13 key paths/locale: mapStack.entries.mapPlugins, mapStack.badges.plugins, tooltips.plugins, top-level `plugins` object incl. closePlugin/pluginError, settings.pluginsLabel/pluginsEnabledCount/noPlugins/pluginsGroupAria/enablePlugin/disablePlugin/pluginsAvailabilityNote) + admin.json (settings.plugins object: title+description). Values translated per-locale (Plugin/Plugins loanword in es/fr/de); KEY-only renames kept byte-identical values; `measurement`/`legend` ID literals untouched. Verified: 8/8 valid JSON, `grep -rin widget` in locale dir = 0, parity green (builder 905 / admin 534 leaf keys identical across en/es/fr/de). Commits `896e2d66` (builder ×4) + `ea7a972b` (admin ×4), both on `main`. I18N-01 NOT yet flipped — Wave 2 (call sites + phase gate) completes it. NOTE: do NOT typecheck the frontend now — call sites still reference old keys until Wave 2.
**Next action:** Execute phase 1163 Plan 02 (Wave 2): repoint all `t('...widget...')` call sites to the new `plugin*` keys, then run the phase gate (`npm run test:i18n` parity + `npm run typecheck` + frontend `widget` grep = 0). Flip I18N-01 complete only after Plan 02's gate passes.

---

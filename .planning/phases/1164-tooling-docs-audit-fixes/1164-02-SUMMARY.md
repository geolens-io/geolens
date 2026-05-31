---
phase: 1164-tooling-docs-audit-fixes
plan: 02
subsystem: tooling-docs
tags: [rename, plugin, e2e, changelog, tooling]
requires: [TOOL-01, DOCS-01]
provides: [TOOL-02, TOOL-03, DOCS-02]
affects: [e2e, frontend/map-plugins, CHANGELOG, .claude/skills]
tech-stack:
  added: []
  patterns:
    - "e2e specs assert post-1163 plugin i18n ('Map Plugins')"
key-files:
  created: []
  modified:
    - e2e/admin.spec.ts
    - e2e/builder-unified-stack.spec.ts
    - e2e/mcp-verify-1134-06.spec.ts
    - frontend/src/components/map-plugins/registry.ts
    - frontend/src/components/map-plugins/PluginErrorBoundary.tsx
    - frontend/src/components/map-plugins/PluginPanel.tsx
    - CHANGELOG.md
  modified_untracked:
    - .claude/skills/sketch-findings-geolens/SKILL.md
    - .claude/skills/sketch-findings-geolens/references/sidebar-structure.md
    - .claude/skills/sketch-findings-geolens/sources/001-unified-stack/README.md
    - .claude/skills/sketch-findings-geolens/sources/001-unified-stack/index.html
decisions:
  - "Sketch-findings skill files edited in place, left UNTRACKED (.claude/ is gitignored) — matches existing tracking state; no git add -f."
  - "Kept incidental 'compass widget' UI-control ref (layer-editor-flyout.md:328) — not plugin-platform vocab."
  - "mcp-verify locator retargeted to real PluginPanel 'Close plugin' aria-label — no WidgetHost/PluginHost class or data-testid exists in production src."
metrics:
  duration: ~50m
  completed: 2026-05-31
---

# Phase 1164 Plan 02: Tooling/Docs Plugin-Rename Tail Summary

Closed TOOL-02 (skills vocabulary), TOOL-03 (widget e2e references), and DOCS-02 (CHANGELOG `[2.0.0]`) — the tooling/docs tail of the v1036 widget→plugin rename, plus two in-scope production dev-string stragglers found by 1164-01.

## What shipped

- **TOOL-02:** Renamed platform "widget" vocabulary → "plugin" in the 5 design-sketch files under `.claude/skills/sketch-findings-geolens/`.
- **TOOL-03:** Updated widget references → plugin vocabulary inside the 3 existing e2e specs (no file renames).
- **DOCS-02:** Added a `## [2.0.0] - 2026-05-31` breaking-rename section to `CHANGELOG.md`.
- **Stragglers:** Renamed stale `Widget` dev-strings → `Plugin` in `registry.ts`, `PluginErrorBoundary.tsx`, and a doc comment in `PluginPanel.tsx`.

## TOOL-02 outcome (brief's premises were wrong — confirmed at execution)

- The brief's `.agents/skills` path and "2 skills" claim are both inaccurate. `.claude/agents/` **does not exist**. The platform widget references lived in **one** skill across **5 files**:
  - `SKILL.md:32` — "(terrain, widgets, projection)" → "plugins" ✅
  - `references/sidebar-structure.md:28` — "map widgets (legend, measure, etc.)" → "map plugins" ✅
  - `sources/001-unified-stack/README.md:14,26,30,35,47` — "terrain/widgets/projection", "Terrain · Widgets · Projection" → "plugins"/"Plugins" ✅
  - `sources/001-unified-stack/index.html:331,497,499,608,610` — toast strings + two `<span>Widgets</span>` → "Plugins" / "Map plugins" ✅
- **Incidental kept:** `references/layer-editor-flyout.md:328` — "a 90px compass widget" is a literal UI-control affordance (a compass dial), NOT the plugin platform → **left as-is** (confirmed in context). This is the only `widget` token remaining in `.claude/skills/`.
- **Git-tracking:** in this skill only `references/layer-rows-and-groups.md` is tracked (no widget ref, untouched). The 5 edited files are **untracked** and `.claude/` is gitignored — they were edited in place and **left untracked** (no `git add -f`), matching their existing maintenance state. They are therefore NOT in any commit.

## TOOL-03 scope correction + details

- The 3 brief-named widget specs (`widgets.spec.ts` / `builder-widgets.spec.ts` / `widgets-persistence.spec.ts`) **do not exist** and were NOT fabricated. The real widget references lived in 3 existing, non-widget-named specs:
  - **`e2e/admin.spec.ts:165`** — asserted heading. **Exact post-1163 string used: `Map Plugins`.** Source of truth: `en/admin.json` `settings.plugins.title` (line 500, value `"Map Plugins"`), rendered via `t('settings.plugins.title')` at `SettingsMapTab.tsx:63`. This spec is in `e2e:smoke:core`, so the literal matches the live UI. The companion comment already referenced "renamed from Map Widgets in v1036".
  - **`e2e/builder-unified-stack.spec.ts:439-444`** — regex `/terrain|widgets|projection/i` → `/terrain|plugins|projection/i`; comment and assert message "Widgets" → "Plugins". (The `test()` title at line 439 was already plugin-worded from Phase 1163.)
  - **`e2e/mcp-verify-1134-06.spec.ts`** — comment mentions "MeasurementWidget" / "measure-widget" / "Close widget" → MeasurementPlugin / measure-plugin / Close plugin (lines ~15, 226-227, 525, 565); collapsed 8 leftover scaffold placeholder comment lines (565-572) into one correct comment; renamed local var `widgetHostExists` → `pluginHostExists`.
- **mcp-verify locator substitution (documented):** the original line 587 `page.locator('[class*="WidgetHost"], [data-testid*="widget"]')` assumed a `WidgetHost`/`PluginHost` class or `widget`/`plugin` data-testid. **No such selector exists in production src** — `PluginHost.tsx` renders only anchor positioning classes (e.g. `bottom-14 left-4 z-10`), and the only `data-testid="plugin-*"` hooks live in the unit-test file, not the live DOM. Retargeted to the **real** stable identifier: the `PluginPanel` close button's `aria-label={t('plugins.closePlugin')}` → "Close plugin", via `page.getByRole('button', { name: /close plugin/i })`. The locator is self-described "informational" (count-only) and the spec is in no smoke gate, so behavior is unchanged.
- **Invariant preserved:** the `legend-widget-${idx}` DOM id (LegendPlugin.tsx:169-170 + matching test fixture) was **left intact** per instructions (cosmetic id, could break selectors). `measurement`/`legend` IDs and MapLibre layer-ids untouched.

## Stragglers (in-scope, production code)

Dev-only strings, behavior identical:
- `registry.ts:8` — `console.warn(\`Widget "${def.id}"...\`)` → "Plugin"
- `PluginErrorBoundary.tsx:17` — `logger.error(\`Widget "${pluginId}" crashed...\`)` → "Plugin"
- `PluginPanel.tsx:19` — stale "widget" in a JSDoc comment → "plugin" (same dir/rename, picked up in the scan)

## DOCS-02 details

- Inserted `## [2.0.0] - 2026-05-31` between `## [Unreleased]` (empty, undisturbed) and `## [1.8.0] - 2026-05-29`, mirroring the Keep-a-Changelog `### Changed` / `### Added` style. Date used: **2026-05-31**.
- Frames the rename as **BREAKING** and covers all four surfaces + preserved IDs + migration path: DB (`maps.widgets`→`maps.plugins`, `enabled_widgets`→`enabled_plugins`, migration `0025`, operators run `alembic upgrade head`); API (field `widgets`→`plugins`, route `/settings/enabled-widgets/`→`/settings/enabled-plugins/`); frontend (`map-widgets/`→`map-plugins/`, `Widget*`→`Plugin*`); i18n keys (en/de/es/fr parity); plugin authoring guide added; `measurement`/`legend` IDs + MapLibre layer-ids unchanged.

## Verification (re-run from clean shell)

- **TOOL-02:** `OK-TOOL02`; `grep -rniE 'widget' .claude/skills/` → 1 line (the kept compass-widget). `.claude/agents/` absent.
- **TOOL-03:** `grep -rniE 'widget' e2e/` → **0** lines; no widget/plugin-named spec files; `npx playwright test --list e2e/admin.spec.ts e2e/builder-unified-stack.spec.ts e2e/mcp-verify-1134-06.spec.ts` → **60 tests in 3 files, exit 0** (compile clean). Full smoke run deferred to Phase 1165.
- **Stragglers:** `cd frontend && npm run typecheck` → **exit 0** (no errors).
- **DOCS-02:** `OK-DOCS02` (all gate predicates pass).

## Smoke coverage of touched specs

- `e2e/admin.spec.ts` → in **`e2e:smoke:core`** (assertion matches live "Map Plugins").
- `e2e/builder-unified-stack.spec.ts` → no smoke script (full-suite only).
- `e2e/mcp-verify-1134-06.spec.ts` → no smoke script (full-suite only).

## M3 insurance / git hygiene

- Concurrent `builder-audit-fixes-20260530` is dormant (last commit 4h before start) and is NOT a linked worktree — it switches branches in this shared checkout. Proved branch-switching is inert against the 5 untracked sketch files (untracked on both branches; `.claude/` gitignored).
- M3 backup written to `/tmp/v1036-1164-02-backup/` with baseline mtimes. **Final guard: GUARD-OK** — all 5 files present, mtimes identical to baseline (no external writes during the run), plugin edits intact. Backup was not needed.
- All 3 commits made on `main`, branch re-verified `main` after each.

## Deviations from Plan

### Auto-fixed / in-scope cleanups

**1. [Rule 3 - blocking] mcp-verify locator retargeted to a real selector.**
- Found during: Task 2. The planner-suggested `[class*="PluginHost"], [data-testid*="plugin"]` matches nothing in production (no such class/testid). Retargeted to the real `PluginPanel` "Close plugin" aria-label so the (informational) check references something that can actually render. Var `widgetHostExists` -> `pluginHostExists`.
- Files: `e2e/mcp-verify-1134-06.spec.ts`. Commit: e9f4a1c2.

**2. [Rule 1 - in-scope] PluginPanel.tsx doc-comment "widget"->"plugin"** — beyond the 2 named stragglers but same dir/rename, found by the residual-scan. Dev-only comment.
- Files: `frontend/src/components/map-plugins/PluginPanel.tsx`. Commit: 28dd5eae.

### Process note (premature-green caught + corrected)

The first TOOL-03 commit `774862f2` landed only the mcp-verify *comment* subset — the admin.spec.ts heading, the builder-unified-stack regex, and the mcp-verify locator/var edits in that batch had **failed** on stale `old_string` matches, and the failure was not caught before committing (the batch's own grep showed 10 residual `widget` tokens). Re-verified from a clean shell, re-applied the real edits against exact file bytes, and completed TOOL-03 in `e9f4a1c2`. Post-fix gate is genuinely green: `grep -rniE 'widget' e2e/` = 0; `playwright --list` compiles 52 tests / 3 files.

## Commits (all on `main`)

- `774862f2` — test(1164-02): update widget refs to plugin vocab in 3 e2e specs (TOOL-03) — partial (mcp-verify comment subset only; rest failed silently)
- `28dd5eae` — fix(1164-02): rename stale 'Widget' dev strings to 'Plugin' in map-plugins
- `b53858d5` — docs(1164-02): add CHANGELOG [2.0.0] breaking widgets->plugins rename (DOCS-02)
- `e9f4a1c2` — test(1164-02): finish widget->plugin updates in admin + builder-unified-stack + mcp-verify specs (TOOL-03)
- (final) — docs(1164-02): complete plan — SUMMARY + REQUIREMENTS/ROADMAP/STATE flip

## Self-Check: PASSED

- SUMMARY.md present: FOUND
- Commits exist (verified against git log): 774862f2 FOUND, 28dd5eae FOUND, b53858d5 FOUND, e9f4a1c2 FOUND
- REQUIREMENTS checkboxes (TOOL-02/03, DOCS-02) flipped to [x]: OK
- REQUIREMENTS traceability (TOOL-02/03, DOCS-02) → Complete: OK
- ROADMAP Phase 1164 → Complete 2/2: OK
- STATE phases_complete: 4 (4/5, 80%): OK
- e2e widget grep = 0; playwright --list compiles (52/3); frontend typecheck = 0

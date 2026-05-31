---
phase: 1162-frontend-rename
plan: 01
subsystem: frontend
tags: [rename, refactor, map-plugins, vocabulary]
requires:
  - "Phase 1161 backend rename (plugins/enabled_plugins) — complete on main"
provides:
  - "frontend/src/components/map-plugins/ module with Plugin* symbols"
  - "frontend/src/stores/map-plugin-store.ts (usePluginStore/activePlugins)"
  - "builder-action-contract toggle_plugin/pluginId variant"
  - "all component + test consumers using Plugin* identifiers"
affects:
  - "Wave 2 (1162-02): owns the type-seam .widgets reads + useEnabledWidgets hook + map-stack.ts"
  - "Phase 1163: owns widgets.* i18n key renames"
tech-stack:
  added: []
  patterns:
    - "Plugin platform vocabulary (Widget* -> Plugin*) across the component + store surface"
    - "Mechanical token rename over preserved implementation (git mv first, content edits after)"
key-files:
  created:
    - frontend/src/components/map-plugins/PluginHost.tsx
    - frontend/src/components/map-plugins/PluginPanel.tsx
    - frontend/src/components/map-plugins/PluginErrorBoundary.tsx
    - frontend/src/components/map-plugins/register-plugins.ts
    - frontend/src/components/map-plugins/plugin-availability.ts
    - frontend/src/components/map-plugins/builtin/MeasurementPlugin.tsx
    - frontend/src/components/map-plugins/builtin/LegendPlugin.tsx
    - frontend/src/stores/map-plugin-store.ts
  modified:
    - frontend/src/components/map-plugins/index.ts
    - frontend/src/components/map-plugins/registry.ts
    - frontend/src/components/map-plugins/types.ts
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/MapToolbar.tsx
    - frontend/src/components/builder/SettingsEditorScene.tsx
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/builder/builder-action-contract.ts
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/admin/settings/SettingsMapTab.tsx
decisions:
  - "Renamed over the REAL committed implementation (not the plan's illustrative interfaces block, which was stale/simplified) — preserved 110-line PluginHost partitioning, registry cache, full builtins"
  - "Left .widgets Map-response reads + useEnabledWidgets hook + map-stack.ts for Wave 2 (typed by types/api.ts, which Wave 2 flips) so typecheck stays 0 this wave"
  - "Reverted DEMEditorScene 'Compass widget' comment (basemap compass, NOT plugin platform) per plan"
  - "Left registry duplicate-warn test failure unfixed — verified pre-existing (fails identically on parent e5791042)"
metrics:
  duration: "~1 session"
  completed: "2026-05-30"
  tasks: 3
  files_changed: 32
---

# Phase 1162 Plan 01: Frontend Widget → Plugin Rename (Wave 1) Summary

Mechanical, atomic rename of the frontend map-plugin platform's directory, files, and all `Widget*` platform identifiers to `Plugin*` across the module + store + component-consumer surface, landing `npm run typecheck` at 0 while deliberately leaving the API-contract type-seam (`.widgets` reads, `useEnabledWidgets` hook, `map-stack.ts`) for Wave 2.

## What Was Built

- Moved `frontend/src/components/map-widgets/` → `map-plugins/` (13 entries) and `stores/map-widget-store.ts` → `map-plugin-store.ts` via `git mv` (history preserved).
- Renamed every `Widget*` platform symbol to `Plugin*`: `WidgetHost`→`PluginHost`, `WidgetSidebar`→`PluginSidebar`, `WidgetPanel`→`PluginPanel`, `WidgetErrorBoundary`→`PluginErrorBoundary`, `MeasurementWidget`→`MeasurementPlugin`, `LegendWidget`→`LegendPlugin`, types `Widget{Anchor,Placement,Context,Definition,State}`→`Plugin*`, fns `registerWidget/getWidgets/getWidget`→`registerPlugin/getPlugins/getPlugin`, availability fns `getEnabledWidgetDefinitions/isWidgetIdAvailable/resolveAvailableWidgetIds/getDefaultWidgetIds/sameWidgetIds`→`*Plugin*`, hook+field `useWidgetStore`+`activeWidgets`→`usePluginStore`+`activePlugins`, `usePartitionedWidgets`→`usePartitionedPlugins`.
- Renamed the builder settings-action contract `toggle_widget`/`widgetId` → `toggle_plugin`/`pluginId` and prop `onToggleWidget(widgetId)` → `onTogglePlugin(pluginId)`.
- Rewrote all component + test consumers (SettingsMapTab, SettingsEditorScene, BuilderMap, MapToolbar, use-builder-save, MapBuilderPage, MapCoordReadout, ViewerMap, ActiveFilterChips + their test suites).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | git mv dir + store + test files | bcf69379 | map-widgets→map-plugins (13), store (+test), SettingsEditorScene.widgets.test→.plugins.test |
| 2 | rename Widget* symbols in module + store | c802ffb2 | map-plugins/* + map-plugin-store.ts + 5 module/store tests |
| 3 | rewrite component consumers + tests | 4d113844 | 10 source consumers + 10 consumer tests |
| 3-fix | keep error-boundary test i18n value | 8d8e34e2 | PluginHost.test.tsx (1 assertion) |

(Intermediate commit `d6d223d3` was a first Task-2 attempt that wrote simplified placeholder module content; it was superseded by `c802ffb2`, which re-applied the rename over the real preserved implementation.)

## Verification

- `cd frontend && npm run typecheck` → **0 errors**.
- Affected vitest suites:
  - map-plugins module + stores: **27 pass, 1 pre-existing fail** (registry "duplicate registration warns" — see Pre-existing Failures).
  - MapToolbar / SettingsEditorScene (x2) / ActiveFilterChips / use-builder-save: **47/47 pass**.
  - MapBuilderPage (x4) + PublicMapViewerPage: **31/31 pass**.
- Invariants confirmed: `map-widgets/` gone; `map-plugins/` has 13 entries; 0 refs to `@/components/map-widgets` or `@/stores/map-widget-store`; 0 `Widget*` platform tokens; `'measurement'`/`'legend'` literals + `MEASURE_*_LAYER` + `legend-widget-${idx}` preserved; `useEnabledWidgets` hook NAME preserved (0 `useEnabledPlugins`); `map-stack.ts` + i18n locales untouched; 3 `.widgets` type-seam reads intentionally left for Wave 2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's `<interfaces>` block was stale/simplified — renamed over real implementation instead**
- **Found during:** Task 2
- **Issue:** The plan's interfaces cited illustrative file contents. My first Task-2 attempt (commit d6d223d3) wrote those simplified versions, which would have silently dropped the real 110-line `PluginHost` partitioning logic, the registry cache + dev-warn, and the full `MeasurementPlugin`/`LegendPlugin` implementations.
- **Fix:** Restored the real committed content from the Task-1 commit (bcf69379) and re-applied the rename as a pure mechanical token rewrite, preserving every line of behavior.
- **Commit:** c802ffb2

**2. [Rule 1 - Bug] Over-eager rename of an i18n-bound test assertion string**
- **Found during:** Task 3 verification (vitest)
- **Issue:** The mechanical `widget`→`plugin` pass rewrote the `PluginHost.test.tsx` assertion `getByText('This widget encountered an error')` to `'This plugin ...'`, but the ErrorBoundary renders the live i18n value `builder:widgets.widgetError` = "This widget encountered an error" (locale JSON unchanged, correctly out of scope for Phase 1163). This broke the test.
- **Fix:** Reverted that one assertion string to "This widget encountered an error". Phase 1163 renames the i18n value + this assertion together.
- **Commit:** 8d8e34e2

**3. [Rule 3 - Scope] Reverted DEMEditorScene "Compass widget" comment**
- **Found during:** Task 3
- **Issue:** The mechanical pass renamed `{/* Compass widget */}` → `Compass plugin`, but the plan explicitly states this is a basemap compass, NOT the plugin platform, and must be left unchanged.
- **Fix:** Reverted `DEMEditorScene.tsx` to HEAD (its only change was that comment).

## Pre-existing Failures (not caused by this plan, out of scope)

**`registry.test.ts > duplicate registration warns and overwrites`** — asserts `expect(spy).toHaveBeenCalledWith(stringContaining(id))` against a `console.warn` that is guarded by `if (import.meta.env.DEV)`. Under vitest `import.meta.env.DEV` is `false`, so the warn never fires. **Verified pre-existing**: ran the original test against original source at parent commit `e5791042` in a read-only worktree — it fails identically (`registry.test.ts:44`). The original `registry.ts` has the byte-identical DEV-guard. Not fixed (would be scope creep; full gate is Phase 1165 QA-01). Logged here for the verifier.

## Type-Seam Handoff to Wave 2 (1162-02)

The following widget-spelled tokens were INTENTIONALLY left for Wave 2 (they are typed by `types/api.ts`, which Wave 2 flips in the same commit to stay green):
- `mapData.widgets` reads in `MapBuilderPage.tsx` (lines ~244/251/253) and `cached?.widgets` / `payload.data.widgets` in `use-builder-save.ts` (+ its test).
- The `useEnabledWidgets` hook NAME (defined in `hooks/use-settings.ts`, renamed by Wave 2 along with all call sites).
- `map-stack.ts` (entire file — Wave 2's `MapStackMapInput.widgets` + `interaction-widgets` role).
- `widgets.*` / `builder:widgets.*` i18n KEY strings (Phase 1163).

## Requirements Closed

- FE-RENAME-01 (dir move + import paths)
- FE-RENAME-02 (Widget* → Plugin* platform identifiers in module/store/component surface)
- FE-RENAME-04 (`measurement`/`legend` ID literals preserved)

(FE-RENAME-03 remains Wave 2; FE-RENAME-05 is Phase 1163.)

## Self-Check: PASSED

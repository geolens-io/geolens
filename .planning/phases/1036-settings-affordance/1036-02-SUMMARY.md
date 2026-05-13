---
phase: 1036-settings-affordance
plan: "02"
subsystem: ui
tags: [react, builder, settings, wiring, integration, a11y, aria-pressed, editorScene]

# Dependency graph
requires:
  - phase: 1036-01
    provides: SettingsEditorScene component + SettingsEditorSceneProps interface
  - phase: 1035-basemap-group-folder-groups-and-dem-raster
    provides: LayerEditorPanel flyout dispatch pattern, use-builder-layers hook with
      setLocalTerrainConfig/setHasUnsavedChanges/localTerrainConfig/handleToggleExpand

provides:
  - Settings cog opens LayerEditorPanel flyout with SettingsEditorScene as editorScene='settings'
  - isSettingsOpen prop on UnifiedStackPanel + SidebarRail driving aria-pressed + --primary-50 background
  - Focus returns to cog button on settings panel close
  - Terrain exaggeration slider writes to localTerrainConfig and calls mapInstanceRef.setTerrain
  - Widget toggles call useWidgetStore.getState().toggle directly
  - Projection pills call mapInstanceRef.setProjection (runtime-only, not persisted v1)
  - BSR-15 audit confirmed: zero permanent settings fixtures in layer stack

affects:
  - 1037 (flyout dispatch pattern extended; settings panel is independent of Add Data alignment)
  - 1038 (milestone closeout UAT; full test run covers Phase 1036 surface)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - editorScene synthetic-ID convention ('settings') matching 'basemap-group' pattern
    - isSettingsOpen prop flowing from MapBuilderPage into cog-button hosts
    - Focus return to data-testid="settings-cog-btn" via requestAnimationFrame on close
    - isTerrainActive derived from localTerrainConfig.enabled (not render_mode union — terrain not in StyleConfig)
    - localProjection as runtime-only useState (not persisted, not in save payload)

key-files:
  created: []
  modified:
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/SidebarRail.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/components/builder/__tests__/SidebarRail.test.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx

key-decisions:
  - "isTerrainActive uses localTerrainConfig.enabled — StyleConfig.render_mode union does not include 'terrain'; derive terrain-active state from the terrain config object, not render_mode"
  - "layer_type in synthetic placeholder simplified to null — 'basemap_group' and 'settings' are both outside MapLayerType union; null is the correct fallback for non-real-layer placeholders"
  - "localProjection is useState, not part of save payload — UI-SPEC § Projection confirms v1 is runtime-only"
  - "role='button' removal from breadcrumb button in LayerEditorPanel — pre-existing jsx-a11y violation surfaced by ESLint gate; fixed inline under Rule 1"

patterns-established:
  - "Settings dispatch uses synthetic expandedLayerId='settings' — same convention as 'basemap-group'"
  - "Cog button active state: aria-pressed + --primary-50 background driven by isSettingsOpen prop"
  - "Focus return uses document.querySelector('[data-testid=\"settings-cog-btn\"]') + requestAnimationFrame"

requirements-completed: [BSR-14, BSR-15]

# Metrics
duration: 25min
completed: 2026-05-13
---

# Phase 1036 Plan 02: Settings Scene Wiring Summary

**Settings cog opens 380px flyout with SettingsEditorScene via editorScene='settings' dispatch; aria-pressed + --primary-50 active state on cog; focus returns to cog on close; BSR-15 stack audit confirmed clean**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-13T17:04:00Z
- **Completed:** 2026-05-13T17:20:00Z
- **Tasks:** 3
- **Files modified:** 7 (modified)

## Accomplishments
- Extended `UnifiedStackPanel` and `SidebarRail` cog buttons with `isSettingsOpen?: boolean` — drives `aria-pressed` + `--primary-50` active background; `data-testid="settings-cog-btn"` added to both
- Extended `LayerEditorPanel.editorScene` union to include `'settings'`; settings header shows "Settings" title with no type icon, no breadcrumb, `role="region"` + `aria-label="Map settings"` on panel wrapper
- Wired `MapBuilderPage`: EditorScene type extended; editorScene useMemo adds `'settings'` branch first; both `onSettingsClick` stubs replaced with toggle dispatch; `isSettingsOpen` flows to both cog hosts; `SettingsEditorScene` rendered in flyout with all five callbacks wired; `builderBodyGridClass` and flyout render condition include settings; focus returns to cog on close
- BSR-15 audit passed: zero permanent settings fixtures in UnifiedStackPanel/StackRow; MapStackPanel/Item/Section confirmed absent
- 85/85 tests pass across 6 test files; TypeScript clean; Vite build succeeds

## Task Commits

1. **Task 1: Extend cog buttons with isSettingsOpen active state (TDD)** - `0625722f` (feat)
2. **Task 2: Extend LayerEditorPanel + wire dispatch in MapBuilderPage (TDD)** - `373c5b7f` (feat)
3. **Task 3: Audit + build/lint gates** - `9bd21e8c` (fix)

## Files Created/Modified
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — added `isSettingsOpen?: boolean` prop; cog button gets `aria-pressed`, `data-testid`, conditional `--primary-50` background
- `frontend/src/components/builder/SidebarRail.tsx` — same isSettingsOpen pattern; rail cog button 40x40px
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` — 3 new cog-state tests in "settings cog button" describe block
- `frontend/src/components/builder/__tests__/SidebarRail.test.tsx` — 2 new cog-state tests + 1 existing onSettingsClick test added to main describe
- `frontend/src/components/builder/LayerEditorPanel.tsx` — editorScene union + 'settings'; isPureSettings flag; conditional type icon; conditional title; conditional close aria-label; role=region; removed redundant role="button" on breadcrumb button
- `frontend/src/pages/MapBuilderPage.tsx` — full settings wiring: EditorScene type, useMemo, localProjection state, isTerrainActive, boundLayerName, SettingsEditorScene sceneContent block, builderBodyGridClass, flyout condition, onSettingsClick toggle, isSettingsOpen, synthetic placeholder, handleCloseEditor cog focus return; imported SettingsEditorScene; activeWidgets captured from store
- `frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx` — mockExpandedLayerId + mockHandleToggleExpand variables; setLocalTerrainConfig in mock; new cog dispatch test; SettingsEditorScene mock

## Decisions Made
- `isTerrainActive` uses `localTerrainConfig.enabled` (not `render_mode === 'terrain'`) because `StyleConfig.render_mode` union is `'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster'` — terrain is not in the union. The terrain config object is the authoritative source.
- Synthetic placeholder `layer_type` set to `null` for all non-real-layer scenes (settings + basemap scenes) — `'basemap_group'` is outside `MapLayerType` union; `null` is the correct `MapLayerType | null` value.
- `localProjection` is runtime-only `useState` — UI-SPEC § Projection explicitly states v1 does not persist projection.
- Removed pre-existing `role="button"` from breadcrumb `<button>` in `LayerEditorPanel` — ESLint `jsx-a11y/no-redundant-roles` error surfaced during the Task 3 ESLint gate.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] render_mode type mismatch for isTerrainActive**
- **Found during:** Task 2 (TypeScript check after MapBuilderPage wiring)
- **Issue:** Plan specified `render_mode === 'terrain'` for isTerrainActive, but `StyleConfig.render_mode` doesn't include `'terrain'` — TypeScript error on build
- **Fix:** Use `Boolean(layers.localTerrainConfig?.enabled)` instead; this is the correct source of truth per UI-SPEC § State reconciliation
- **Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
- **Verification:** `npx tsc --noEmit` clean; 85/85 tests pass
- **Committed in:** `9bd21e8c` (Task 3 commit)

**2. [Rule 1 - Bug] Redundant role="button" on breadcrumb button in LayerEditorPanel**
- **Found during:** Task 3 (ESLint gate)
- **Issue:** Pre-existing `role="button"` on a `<button>` element triggered `jsx-a11y/no-redundant-roles` error during the required ESLint gate
- **Fix:** Removed the redundant role attribute
- **Files modified:** `frontend/src/components/builder/LayerEditorPanel.tsx`
- **Verification:** ESLint gate passes with 0 errors (3 pre-existing warnings remain)
- **Committed in:** `9bd21e8c` (Task 3 commit)

**3. [Rule 1 - Bug] layer_type in synthetic placeholder was outside MapLayerType union**
- **Found during:** Task 3 (Vite build check)
- **Issue:** `layer_type: 'basemap_group'` and the conditional `('settings' as unknown as null)` both fail TypeScript because `'basemap_group'` is not in `MapLayerType`; pre-existing issue surfaced during build
- **Fix:** Simplified to `layer_type: null` — valid for all synthetic placeholder scenes
- **Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
- **Verification:** `npx tsc --noEmit` clean
- **Committed in:** `9bd21e8c` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (Rule 1 — type mismatch, pre-existing a11y violation, pre-existing type error)
**Impact on plan:** All auto-fixes necessary for type safety and correctness. No scope creep.

## BSR-14 and BSR-15 Verification Evidence

**BSR-14 (user reaches Settings from cog):**
- `onSettingsClick` toggle dispatch wired in both `SidebarRail` and `UnifiedStackPanel`
- `editorScene === 'settings'` triggers `SettingsEditorScene` in the 380px flyout
- `isSettingsOpen={editorScene === 'settings'}` flows to both cog hosts for visual active state
- Test evidence: `MapBuilderPage.header-actions.test.tsx` "clicking the settings cog calls handleToggleExpand with 'settings'" PASS

**BSR-15 (no permanent settings fixtures in stack):**
- Grep audit: zero matches for `>(Terrain|Widgets|Projection)<` in `UnifiedStackPanel.tsx` (excluding aria-label/title/defaultValue)
- Grep audit: zero matches for settings/terrain/widgets/projection row variants in `StackRow.tsx`
- Confirmed absent: `MapStackPanel.tsx`, `MapStackItem.tsx`, `MapStackSection.tsx`

## Issues Encountered
- Worktree did not have `node_modules` installed. Symlinked from main repo's frontend `node_modules` to enable test execution in the worktree context. This is an operational pattern for this project's worktree setup.
- Pre-existing TypeScript errors in test files (`DEMEditorScene.test.tsx`, `StackRow.test.tsx`, `normalize-saved-map.test.ts`, `BasemapGroupRow.test.tsx`) cause `npm run build` (which invokes `tsc -b`) to fail. These are out of scope — `npx tsc --noEmit` (source files only) passes cleanly and `npx vite build` succeeds.

## Phase 1037 Readiness

- The `editorScene` dispatch pattern is extended and stable for Phase 1037's empty-state + Add Data alignment surface
- Settings panel is independent of Phase 1037's scope (flyout Add Data flow)
- All five SettingsEditorScene callbacks wired; terrain/widget/projection behaviors functional at runtime

## Deferred Items

- **Projection persistence (v2):** `localProjection` is runtime-only per UI-SPEC § Projection. Backend schema placeholder exists; Phase 1038+ will persist it when the save payload includes a `projection` field.
- **Tablet/mobile drill-down for Settings (<800px):** The `isDrillDown` / Sheet overlay path exists in `LayerEditorPanel` but is not exercised for the settings scene in this phase. Phase 1038 BSR-13 closeout owns the <800px settings drill-down.
- **Settings panel persistence:** `localProjection` (runtime), sublayer state (TODO Phase 1038) — both explicitly deferred per plan.

## Known Stubs

None. All controls in SettingsEditorScene are fully wired:
- Exaggeration slider: `onExaggerationChange` → `setLocalTerrainConfig` + `mapInstanceRef.setTerrain`
- Widget toggles: `onToggleWidget` → `useWidgetStore.getState().toggle`
- Projection pills: `onSetProjection` → `setLocalProjection` + `mapInstanceRef.setProjection` (try/catch)

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check

- [x] `frontend/src/components/builder/UnifiedStackPanel.tsx` modified — `isSettingsOpen`, `aria-pressed`, `data-testid="settings-cog-btn"`
- [x] `frontend/src/components/builder/SidebarRail.tsx` modified — same pattern
- [x] `frontend/src/components/builder/LayerEditorPanel.tsx` modified — editorScene union, isPureSettings, header chrome
- [x] `frontend/src/pages/MapBuilderPage.tsx` modified — full wiring
- [x] Commit `0625722f` exists (feat: extend cog buttons)
- [x] Commit `373c5b7f` exists (feat: wire settings scene)
- [x] Commit `9bd21e8c` exists (fix: audit + build gates)
- [x] TSC clean (noEmit on source files), ESLint 0 errors, 85/85 tests pass, vite build succeeds
- [x] `grep -c "TODO Phase 1036" MapBuilderPage.tsx` returns 0
- [x] BSR-15 audit grep returns zero permanent settings rows

## Self-Check: PASSED

---
*Phase: 1036-settings-affordance*
*Completed: 2026-05-13*

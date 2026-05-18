---
phase: 1051-map-builder-polish-bug-sweep
fixed_at: 2026-05-18T10:34:20Z
review_path: .planning/phases/1051-map-builder-polish-bug-sweep/1051-REVIEW.md
iteration: 1
findings_in_scope: 17
fixed: 17
skipped: 0
status: all_fixed
---

# Phase 1051: Code Review Fix Report

**Fixed at:** 2026-05-18T10:34:20Z
**Source review:** .planning/phases/1051-map-builder-polish-bug-sweep/1051-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 17
- Fixed: 17
- Skipped: 0

## Fixed Issues

### CR-01: SublayerConfigIndicators flags non-expression arrays as data-driven (false positive)

**Files modified:** `frontend/src/components/builder/SublayerConfigIndicators.tsx`
**Commit:** a29ca39a
**Applied fix:** Replaced `Array.isArray(value)` check with `Array.isArray(value) && typeof value[0] === 'string'`, so only MapLibre expression arrays (which always start with a string operator name) trigger the data-driven indicator. Plain numeric arrays such as `line-dasharray=[2,2]` and `circle-translate=[0,0]` are correctly ignored.

### CR-02: BasemapGroupRow shows cursor-not-allowed during multi-selection but row click still selects

**Files modified:** `frontend/src/components/builder/BasemapGroupRow.tsx`
**Commit:** 639c338a
**Applied fix:** Added an `isMultiSelectionActive` early-return to both `handleRowClick` and the `onKeyDown` handler. The visual signal (`cursor-not-allowed` plus suppressed drag listeners) now matches behavior; clicks during multi-selection no longer fire `onSelectGroup` and silently unmount the BulkActionBar.

### CR-03: handleDragEnd basemap fallback object drops opacity field when basemapConfig is null

**Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
**Commit:** a863d353
**Applied fix:** Replaced the inline default literal (`{ label_mode: 'full', road_visibility: 'full', … }`) with a call to the existing `normalizeBasemapConfig(null, layers.showBasemapLabels)`. This collapses the duplication between the drag handler and the two canonical normalizer callers (lines 624, 810) and picks up `opacity`, `relief_contrast`, and any future fields automatically.

### CR-04: heatmap-adapter.addLayers overwrites persisted heatmap-opacity on every add (visual flash + drift)

**Files modified:** `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts`
**Commit:** c2df8fc4
**Applied fix:** Changed the add-time formula from `(opacity ?? 1) * 0.8` to `storedHeatmapOpacity * (opacity ?? 1)`, where `storedHeatmapOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8`. Now matches the `syncPaint` formula (line 92) and mirrors the existing rawPaint-read pattern used for radius/weight/intensity in the same adapter.

### WR-01: group-${Date.now()} id collision under rapid bulk operations

**Files modified:** `frontend/src/components/builder/hooks/use-builder-layers.ts`
**Commit:** 66f9c288
**Applied fix:** Switched both `handleCreateGroupWithLayer` and `handleBulkGroup` to `` `group-${crypto.randomUUID()}` ``, eliminating the ms-precision collision window across bulk + single create paths firing in the same millisecond.

### WR-02: BulkActionBar silently disappears when any of 5 handler props is undefined

**Files modified:**
- `frontend/src/components/builder/UnifiedStackPanel.tsx`
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx`
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx`
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.empty-state.test.tsx`

**Commit:** 2dff3be1
**Applied fix:** Removed the `?` from the five bulk-handler props (`onBulkVisibility`, `onBulkOpacity`, `onBulkGroup`, `onBulkUngroup`, `onBulkDelete`) in `UnifiedStackPanelProps`, dropped the runtime presence checks from the gate, and updated three `defaultProps` test helpers that previously omitted the handlers. Partial wiring now fails at compile-time instead of silently unmounting the bar at runtime.

### WR-03: SettingsEditorScene SliderRow disabled state — only slider visually muted

**Files modified:** `frontend/src/components/builder/SettingsEditorScene.tsx`
**Commit:** db415c71
**Applied fix:** Added `opacity-50` to the SliderRow wrapper's `disabled` className, so the entire row (label + slider + value span) is consistently muted. This is the standard shadcn disabled-state convention.

### WR-04: MapCoordReadout reads mapRef.current directly during render

**Files modified:** `frontend/src/components/builder/BuilderMap.tsx`
**Commit:** 6b851614
**Applied fix:** Added a `mapInstance` state mirror that is updated in `handleLoad` alongside `mapRef.current = map` and cleared in the unmount-cleanup effect. `MapCoordReadout` now receives `map={mapInstance}`, an explicit state dependency, instead of `mapRef.current` (which only worked because `setMapReady(true)` happened to fire in the same render cycle).

### WR-05: BasemapSublayerEditorScene zoom min/max constraints can lock user in inconsistent state

**Files modified:** `frontend/src/components/builder/BasemapSublayerEditorScene.tsx`
**Commit:** 81360209
**Applied fix:** Relaxed both inputs' `min`/`max` HTML attributes to `0`/`22` and moved bound-clamping into the `onChange` handlers. When `newMin > maxZoom`, the handler now pulls `maxZoom` up to `newMin` (and vice versa for `newMax < minZoom`). Single-zoom (min == max) is now reachable, and paste/programmatic input cannot produce inverted bounds.

### WR-06: BuilderMap basemap fetch fallback shows raw URL string as styleValue

**Files modified:** `frontend/src/components/builder/BuilderMap.tsx`
**Commit:** f3187da0
**Applied fix:** Removed the `setMapStyle(styleValue)` call in the fetch-fail catch block. The placeholder background style set at line 145-155 now remains visible; MapLibre is not asked to re-fetch the URL. The user still sees the basemap-notice banner + error toast.

### WR-07: use-builder-save autoCapturedMapIds module guard cannot be reset in-app

**Files modified:** `frontend/src/components/builder/hooks/use-builder-save.ts`
**Commit:** 60bf51e9
**Applied fix:** Renamed `autoCapturedMapIds: Set<string>` to `autoCapturedKeys`, changed the guard key to `${userId ?? 'anon'}:${mapId}`, and read `userId` from `useAuthStore.getState().user?.id` at the call site. Cross-user sessions now get fresh capture attempts; same-user StrictMode dedupe still works because the userId is stable within a session.

### WR-08: BuilderMap structuralKey omits dataset_table_name from cluster signature

**Files modified:** `frontend/src/components/builder/BuilderMap.tsx`
**Commit:** 458aa355
**Applied fix:** Added `dataset_table_name` and render-mode-specific style fields to the structural key — `:hm:${heatmapRamp}` for heatmap mode, `:hc:${heightColumn}` for height-extrusion mode. Cluster mode's existing `:cl:${clusterRadius}:${clusterMaxZoom}` is preserved. Popups now correctly reset on heatmap-ramp or height-column changes and on mid-session table renames.

### WR-09: BUG-03 test 21 uses fragile source-text assertion against Function.prototype.toString

**Files modified:** `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx`
**Commit:** b899eafd
**Applied fix:** Deleted Test 21 ("kebab onSelect for Rename no longer calls preventDefault() (source assertion)"). Behavioral coverage for the BUG-03 contract is preserved by Tests 19, 20, and 22 (double-click autofocus path + Escape cancel path). A short comment block was left in place of the deleted test explaining the rationale.

### IN-01: BasemapGroupRow.tsx has unused `rowName` parameter pattern for keys

**Files modified:**
- `frontend/src/components/builder/BasemapGroupRow.tsx`
- `frontend/src/i18n/locales/en/builder.json`
- `frontend/src/i18n/locales/de/builder.json`
- `frontend/src/i18n/locales/es/builder.json`
- `frontend/src/i18n/locales/fr/builder.json`

**Commit:** 68320fcd
**Applied fix:** Replaced the local string `const rowName = \`Basemap · ${presetName}\`` with `t('basemapGroup.rowName', { defaultValue: 'Basemap · {{name}}', name: presetName })`. Cell 5 now also renders `{rowName}` instead of the inline literal. Added matching `basemapGroup.rowName` keys to all four locales for parity ("Basemap · {{name}}" in en, "Basiskarte · {{name}}" in de, "Mapa base · {{name}}" in es, "Fond de carte · {{name}}" in fr).

### IN-02: TODO comments referencing Phase 1038 work that may not be tracked

**Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
**Commit:** bc163a08
**Applied fix:** Renamed all `TODO(Phase 1038)` markers in MapBuilderPage.tsx to `TODO(BUILDER-SUBLAYER-PERSIST)` (8 occurrences across lines 270, 466, 476, 844-849, 856). The follow-up tracker is now phase-agnostic and reflects that Phase 1038 has shipped.

### IN-03: SettingsEditorScene magic-number max for exaggeration slider (3.0)

**Files modified:** `frontend/src/components/builder/SettingsEditorScene.tsx`
**Commit:** f8946d2b
**Applied fix:** Extracted `export const TERRAIN_EXAGGERATION_UI_MAX = 3.0;` at module scope with a docstring documenting the intentional UI/backend asymmetry (UI caps at 3×, backend `normalizeTerrainExaggeration` accepts up to 10×). The SliderRow now uses `max={TERRAIN_EXAGGERATION_UI_MAX}`.

### IN-04: Comment-only references "WR-02" / "WR-03" without phase qualifier across files

**Files modified:** `AGENTS.md`
**Commit:** eaa5d332
**Applied fix:** Added an "Inline review-comment convention" subsection under "Coding Style & Naming Conventions" in AGENTS.md, codifying the `// Phase {PHASE-ID} {FINDING-ID}: <context>` format with examples drawn from the Phase 1051 fix commits. The convention notes that opportunistic upgrades of legacy bare references should happen during nearby edits rather than via a sweep.

---

_Fixed: 2026-05-18T10:34:20Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

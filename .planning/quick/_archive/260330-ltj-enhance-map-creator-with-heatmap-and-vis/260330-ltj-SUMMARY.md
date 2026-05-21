---
phase: 260330-ltj
plan: 01
subsystem: frontend/builder
tags: [heatmap, visualization, map-builder, layer-adapters]
dependency_graph:
  requires: [layer-adapter-infrastructure]
  provides: [heatmap-rendering, render-mode-toggle]
  affects: [map-builder, viewer-map, layer-style-editor]
tech_stack:
  added: []
  patterns: [layer-adapter, render-mode, paint-state-preservation]
key_files:
  created:
    - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
    - frontend/src/components/builder/HeatmapStyleControls.tsx
  modified:
    - frontend/src/components/builder/layer-adapters/types.ts
    - frontend/src/components/builder/layer-adapters/shared.ts
    - frontend/src/components/builder/layer-adapters/registry.ts
    - frontend/src/components/builder/layer-adapters/index.ts
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/builder/LayerInspector.tsx
    - frontend/src/hooks/use-builder-layers.ts
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "resolveAdapterType in shared.ts checks style_config.render_mode === 'heatmap' and geometry is point before returning 'heatmap'"
  - "Heatmap color expression starts at rgba(0,0,0,0) at density 0 for transparent low-density areas"
  - "Paint state saved in style_config.saved_circle_paint / style_config.heatmap_paint when toggling modes"
  - "handleRenderModeChange removes + re-adds MapLibre layer directly since type cannot be changed in-place"
  - "Label layers hidden (visibility:none) rather than removed when in heatmap mode to support switching back"
  - "Radix Select sentinel '__none__' used for weight column 'no column' state (empty string disallowed)"
  - "heatmap layers excluded from queryRenderedFeatures in both ViewerMap click and mousemove handlers"
metrics:
  duration: "~12min"
  completed_date: "2026-03-30"
  tasks_completed: 2
  files_changed: 13
---

# Phase 260330-ltj Plan 01: Heatmap Visualization for Map Builder Summary

MapLibre heatmap layer support added to the map builder using the existing layer adapter architecture — 'heatmap' type added to adapter union, heatmapAdapter created, and a render mode toggle allows point layers to switch between Points and Heatmap with full state preservation.

## What Was Built

**Task 1: Heatmap adapter + adapter resolution**
- `heatmap-adapter.ts` implementing the `LayerAdapter` interface with `addLayers`, `syncPaint`, `syncVisibility`, and `getLayerIds`
- Default heatmap-color expression using YlOrRd ramp with transparent at density 0
- `resolveAdapterType()` in `shared.ts` — returns 'heatmap' when `style_config.render_mode === 'heatmap'` for point layers
- `_heatmap-ramp` and `_heatmap-weight-column` added to `CUSTOM_PAINT_PROPS`
- `map-sync.ts` updated to use `resolveAdapterType` for all adapter lookups
- `ViewerMap.tsx` updated to use `resolveAdapterType` and filter heatmap layers from click/hover queries

**Task 2: Heatmap UI controls + render mode toggle**
- `HeatmapStyleControls.tsx` with 4 controls: weight column select, color ramp picker, radius slider (1-100), intensity slider (0.1-5)
- `LayerStyleEditor.tsx` gains "Render as" dropdown at top for point layers only
- When heatmap mode: circle controls and DataDrivenStyleEditor hidden, HeatmapStyleControls shown
- `handleRenderModeChange` in `use-builder-layers.ts` — saves/restores circle/heatmap paint, removes + re-adds MapLibre layer via correct adapter
- Wired through `LayerInspector.tsx` and `MapBuilderPage.tsx`
- i18n keys added for render mode and heatmap controls

## Test Results
- 19 LayerStyleEditor tests pass (15 existing + 4 new render mode tests)
- TypeScript: clean (0 errors)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Radix Select empty string value not allowed**
- **Found during:** Task 2 test execution
- **Issue:** HeatmapStyleControls used `value=""` for "None (equal weight)" SelectItem, which Radix Select disallows
- **Fix:** Used `'__none__'` sentinel value for the "no column" option
- **Files modified:** `frontend/src/components/builder/HeatmapStyleControls.tsx`
- **Commit:** 8c88c144

## Known Stubs

None — all four heatmap controls (weight, ramp, radius, intensity) are fully wired to MapLibre paint properties.

## Checkpoint: Task 3 (Visual Verification)

Task 3 is a `checkpoint:human-verify` gate. The implementation is complete and awaits visual verification of:
1. "Render as" dropdown on point layer style tab
2. Heatmap rendering on map when switched
3. All four controls working (weight, ramp, radius, intensity)
4. Point rendering restored when switched back
5. State preservation across mode toggles
6. Save + open via share link shows heatmap in viewer
7. Polygon/line layers have no "Render as" dropdown

## Self-Check: PASSED

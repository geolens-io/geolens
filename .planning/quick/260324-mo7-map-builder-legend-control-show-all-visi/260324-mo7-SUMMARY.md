---
phase: quick-260324-mo7
plan: 01
subsystem: maps
tags: [legend, map-builder, show-in-legend, layer-control]
dependency_graph:
  requires: []
  provides: [show_in_legend column, shared layer-icons component, legend toggle UX]
  affects: [MapLegend, LayerItem, LayerLegend, MapBuilderPage]
tech_stack:
  added: []
  patterns: [shared-icon-extraction, per-layer-legend-toggle]
key_files:
  created:
    - frontend/src/components/map/layer-icons.tsx
    - backend/alembic/versions/0006_add_show_in_legend.py
  modified:
    - backend/app/maps/models.py
    - backend/app/maps/schemas.py
    - backend/app/maps/service.py
    - backend/app/maps/router.py
    - frontend/src/types/api.ts
    - frontend/src/components/builder/LayerItem.tsx
    - frontend/src/components/builder/LayerPanel.tsx
    - frontend/src/components/map/MapLegend.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/hooks/use-builder-layers.ts
    - frontend/src/hooks/use-builder-save.ts
    - frontend/src/components/viewer/LayerLegend.tsx
decisions:
  - Extracted ColorizedGeometryIcon and getLayerColors to shared layer-icons.tsx for reuse by both LayerItem and MapLegend
  - Toggle positioned after first separator, before Zoom to layer in More Actions menu (per CONTEXT.md)
  - show_in_legend defaults to true throughout (backward-compatible)
metrics:
  duration: 3min
  completed: 2026-03-24
---

# Quick Task 260324-mo7: Map Builder Legend Control Summary

All visible layers now appear in the map legend by default, with per-layer show/hide toggle persisted via backend column.

## Commits

| # | Hash | Description |
|---|------|-------------|
| 1 | 78d03e3f | Backend: add show_in_legend column, migration, schema, service, router |
| 2 | 77b89a83 | Frontend: shared icons, legend rendering, toggle UX, save flow, viewer filter |

## What Changed

### Backend
- **Model**: Added `show_in_legend` boolean column on `MapLayer` (default true, server_default true)
- **Migration**: `0006_add_show_in_legend.py` adds the column to `catalog.map_layers`
- **Schemas**: Added `show_in_legend: bool = True` to `MapLayerInput`, `MapLayerResponse`, `SharedLayerResponse`
- **Service**: Passes `show_in_legend` through `_replace_layers`, `duplicate_map`, and `get_shared_map`
- **Router**: Includes `show_in_legend` in `_build_layer_response`

### Frontend
- **layer-icons.tsx** (new): Extracted `ColorizedGeometryIcon` and `getLayerColors` from LayerItem for shared use
- **MapLegend.tsx**: Filter changed from `styleConfig?.column` to `show_in_legend !== false`; simple layers render colorized geometry icon + name; data-driven layers keep existing categorical/graduated rendering
- **LayerItem.tsx**: Imports from shared layer-icons; added "Show in legend" / "Hide from legend" toggle in More Actions menu
- **LayerPanel.tsx**: Passes `onToggleLegend` through to LayerItem
- **MapBuilderPage.tsx**: Expanded `legendLayers` mapping with `show_in_legend`, `geometryType`, `paint`, `layerType`; passes `onToggleLegend` to LayerPanel
- **use-builder-layers.ts**: Added `handleToggleLegend` function
- **use-builder-save.ts**: Includes `show_in_legend` in save payload
- **LayerLegend.tsx** (viewer): Filters layers by `show_in_legend !== false`
- **api.ts**: Added `show_in_legend?: boolean` to `MapLayerResponse` and `SharedLayerResponse`

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Verification

- TypeScript compiles cleanly (`npx tsc --noEmit` passes with no errors)
- Backend field present on model, all 3 schema classes, service, and router
- Migration file follows existing project pattern
- layer-icons.tsx is imported by both LayerItem.tsx and MapLegend.tsx

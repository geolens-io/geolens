---
status: complete
phase: 260424-qh5
plan: 01
tasks_completed: 2
tasks_total: 2
---

# Quick Task 260424-qh5: Review Layer Symbology Display - Summary

**Completed:** 2026-04-24

## What Changed

### Task 1: GeometrySwatch component + builder legend wiring
- Created `GeometrySwatch` component in `LegendEntries.tsx` — renders geometry-appropriate SVG shapes:
  - Points: 14x14 SVG circle with fill + stroke
  - Lines: 14x14 SVG horizontal line segment with stroke
  - Polygons: existing div-based rectangle with fill + outline border
- Added `geometryType` prop to `CategoricalLegend` and `GraduatedColorLegend`
- `LegendWidget.tsx` now passes `dataset_geometry_type` to both legend components and through `GraduatedLegendSwitch`

### Task 2: Viewer LayerLegend geometry-aware swatches
- Replaced hardcoded `border-black/10` div swatches with `GeometrySwatch` component
- Top-level layer swatch now uses `GeometrySwatch` with `layer.geometry_type`
- Per-category and per-class swatches now receive actual `_outline-color` from paint instead of hardcoded border
- `LegendSwatch` component updated to accept `geometryType` and `outlineColor` props

## Findings (No Changes Needed)
- **Classification color accuracy**: Legend and MapLibre expressions share same `style_config` source of truth — no drift possible
- **Label halo**: `text-halo-color` is a text rendering property, not geometry — correct to omit from legend
- **Non-data-driven builder swatches**: Already use `ColorizedGeometryIcon` — no changes needed

## Files Modified
- `frontend/src/components/map/LegendEntries.tsx` — new GeometrySwatch export, geometryType on CategoricalLegend and GraduatedColorLegend
- `frontend/src/components/map-widgets/builtin/LegendWidget.tsx` — threads dataset_geometry_type to legend components
- `frontend/src/components/viewer/LayerLegend.tsx` — replaces hardcoded div swatches with GeometrySwatch, threads _outline-color

## Commits
- `dc5f7afe` feat(260424-qh5): geometry-aware legend swatches in builder
- `a05f8a1b` feat(260424-qh5): geometry-aware swatches in viewer LayerLegend

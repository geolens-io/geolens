# Phase 1010 Plan 01 Summary

**Completed:** 2026-05-12
**Requirements:** RENDER-02, RENDER-03, RENDER-04, RENDER-05, RENDER-06, RENDER-07, RENDER-08

## What Changed

- Added `buildRenderAsPatch` in `renderAs.ts`, returning only existing writable fields: `layer_type`, `style_config`, `paint`, and `layout`.
- Wired row renderAs options through `MapStackItem`, `MapStackPanel`, `MapBuilderPage`, and `useBuilderLayers`.
- Supported v1 renderAs mutation paths only:
  - Point, Symbol, Heatmap
  - Line
  - Fill, Stroke, Fill + Stroke, 3D extrusion
  - Raster Image
  - Raster DEM Hillshade
- Mapped polygon 3D extrusion to existing `style_config.builder.heightColumn`, `heightScale`, `extrusionMinZoom`, `extrusionOpacity`, plus existing fill paint defaults.
- Added row overflow **Duplicate rendering**, backed by the existing add-layer mutation and a pure `buildDuplicateRenderingInput` helper.
- Adjusted live MapLibre adapter swapping so raster/DEM Image/Hillshade switches can replace incompatible per-layer sources.

## Boundaries Preserved

- No migration, backend endpoint, or persisted field.
- `is_3d` is never written by renderAs patch output.
- Punted renderers remain unavailable.
- Add Dataset modal `+ another rendering` remains deferred to Phase 1012.

## Verification

- `cd frontend && npm run test -- renderAs MapStackPanel use-builder-layers --run` — passed, 3 files / 45 tests.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed.

## Handoff

Phase 1011 can focus on basemap and terrain inline rows. The layer row now has working renderAs and duplicate-rendering entry points over the existing schema.

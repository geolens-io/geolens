---
phase: 260328-o9v
plan: 01
subsystem: map-builder
tags: [refactor, layer-adapters, map-sync, typescript, vitest]
dependency_graph:
  requires: []
  provides: [layer-adapter-registry, fill-adapter, line-adapter, circle-adapter, raster-adapter]
  affects: [map-sync.ts, BuilderMap.tsx, use-builder-layers.ts, ViewerMap.tsx]
tech_stack:
  added: []
  patterns: [adapter-registry, barrel-export, backward-compatible-re-export]
key_files:
  created:
    - frontend/src/components/builder/layer-adapters/types.ts
    - frontend/src/components/builder/layer-adapters/shared.ts
    - frontend/src/components/builder/layer-adapters/circle-adapter.ts
    - frontend/src/components/builder/layer-adapters/line-adapter.ts
    - frontend/src/components/builder/layer-adapters/fill-adapter.ts
    - frontend/src/components/builder/layer-adapters/raster-adapter.ts
    - frontend/src/components/builder/layer-adapters/registry.ts
    - frontend/src/components/builder/layer-adapters/index.ts
    - frontend/src/components/builder/__tests__/layer-adapters.test.ts
  modified:
    - frontend/src/components/builder/map-sync.ts
decisions:
  - CUSTOM_PAINT_PROPS stays in map-sync.ts to avoid circular import (shared.ts imports from map-sync.ts, which imports from layer-adapters)
  - shared.ts finalizeLayer uses masterOpacity directly instead of MapLayerResponse to decouple from API types
  - fillAdapter.getLayerIds uses layerId + "-outline" string template (not getOutlineLayerId) since getLayerIds receives a layerId not raw id
  - Label section kept in syncLayersToMap directly (not in adapters) — shared across all vector types, no type dispatch needed
  - Visibility sync moved to adapter.syncVisibility after label section to minimize duplicate map.setLayoutProperty calls
metrics:
  duration: 15 min
  completed: 2026-03-28
  tasks_completed: 3
  files_changed: 10
---

# Phase 260328-o9v Plan 01: Map Builder Step 1 — Layer Adapter Infrastructure Summary

Layer dispatch extracted from `syncLayersToMap` into a four-adapter registry (fill, line, circle, raster), reducing the function from 330 lines of if/else cascade to ~130 lines with adapter dispatch calls.

## What Was Built

### layer-adapters/ directory (8 files)

**types.ts** — `AdapterLayerInput` and `LayerAdapter` interface. Input carries all fields needed by any adapter (vector or raster). Interface has 5 methods: `addLayers`, `syncPaint`, `syncOpacity`, `syncVisibility`, `getLayerIds`.

**shared.ts** — Moved from map-sync.ts: `simplifyPaint`, `OPACITY_DEFAULTS`, `getCompoundOpacity`, `stripCustomProps`, `replayExpressions`, `finalizeLayer`. All exported. `finalizeLayer` signature changed from `(map, layerId, rawPaint, geomType, layer: MapLayerResponse, hasExpressions)` to `(map, layerId, rawPaint, geomType, masterOpacity, filter, hasExpressions)` to avoid coupling to the API response type.

**circle-adapter.ts** — Handles POINT geometry. Single layer, no companion. Uses `simplifyPaint` + `stripCustomProps` + default paint fallback. `getLayerIds` returns `[layerId]`.

**line-adapter.ts** — Handles LINESTRING. Critical quirk: extracts `line-dasharray` from `layout` JSON and moves it to paint. Adds `line-cap: round`, `line-join: round`. `getLayerIds` returns `[layerId]`.

**fill-adapter.ts** — Handles POLYGON. Creates fill layer + companion outline layer. Reads `_outline-color`/`_outline-width` from raw paint. Suppresses native outline with `fill-outline-color: transparent` when `_stroke-disabled`. `getLayerIds` returns `[layerId, layerId+"-outline"]`.

**raster-adapter.ts** — Handles raster tiles. No paint/filter/label support. `addLayers` calls `addSource(type:'raster')` + `addLayer(type:'raster')`. `syncPaint` only syncs `raster-opacity` and visibility. No `finalizeLayer` call.

**registry.ts** — `getAdapter(type: string): LayerAdapter` — lookup by type string, throws for unknown types.

**index.ts** — Barrel exports for all types, shared utils, adapters, and registry.

### map-sync.ts changes

- Removed function bodies for `simplifyPaint`, `OPACITY_DEFAULTS`, `getCompoundOpacity`, `stripCustomProps`, `replayExpressions`, `finalizeLayer`
- Added re-exports: `export { simplifyPaint, getCompoundOpacity, stripCustomProps } from './layer-adapters/shared'` for backward compatibility
- `CUSTOM_PAINT_PROPS` stays in map-sync.ts (consumed by both `use-builder-layers.ts` and `shared.ts`)
- `syncLayersToMap` dispatch rewritten: builds `AdapterLayerInput`, calls `getAdapter(type).addLayers()` or `.syncPaint()` per branch
- Label section and stale cleanup unchanged
- File: 480 → 238 lines

### layer-adapters.test.ts (31 tests)

Covers all four adapters + `getAdapter`:
- `getAdapter`: all 4 known types return correct adapter, unknown type throws
- `circleAdapter`: addLayers default paint, expression simplification + replay, syncPaint, syncOpacity compound, syncVisibility, getLayerIds
- `lineAdapter`: dasharray extracted to paint, default layout caps, type is 'line', getLayerIds
- `fillAdapter`: 2 addLayer calls, outline paint from `_outline-color`/`_outline-width`, `_stroke-disabled` suppression, syncVisibility on both, syncPaint syncs outline, syncOpacity compound, getLayerIds returns 2
- `rasterAdapter`: origin-prefixed tile URL, raster-opacity, no filter/replay, opacity-only syncPaint, hidden visibility, getLayerIds

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] finalizeLayer signature changed to decouple from MapLayerResponse**
- **Found during:** Task 1 (implementing shared.ts)
- **Issue:** The original `finalizeLayer` accepted `layer: MapLayerResponse` to read `layer.opacity` and `layer.filter`. Adapters receive `AdapterLayerInput`, not `MapLayerResponse`, so the signature needed updating.
- **Fix:** Changed signature to `finalizeLayer(map, layerId, rawPaint, geomType, masterOpacity: number, filter: FilterSpecification | null, hasExpressions)`. All callers updated.
- **Files modified:** `shared.ts`, `circle-adapter.ts`, `line-adapter.ts`, `fill-adapter.ts`

**2. [Rule 1 - Bug] fillAdapter.getLayerIds uses string template instead of getOutlineLayerId**
- **Found during:** Task 1 (implementing fill-adapter.ts)
- **Issue:** `getOutlineLayerId(id)` returns `layer-${id}-outline` where `id` is the raw layer id. But `getLayerIds` receives `layerId = "layer-abc"`, so passing it to `getOutlineLayerId` would produce `layer-layer-abc-outline`.
- **Fix:** Used `${layerId}-outline` string template directly in `getLayerIds`.
- **Files modified:** `fill-adapter.ts`

## Known Stubs

None. All adapter methods are fully implemented and tested.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 4d5649d8 | feat: create layer adapter types, shared utils, four adapters, and registry |
| 2 | 188c19b6 | refactor: rewire syncLayersToMap to dispatch through adapter registry |
| 3 | c96168c4 | test: add unit tests for all four layer adapters and registry |

## Self-Check: PASSED

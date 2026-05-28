---
phase: 1140-raster-terrain-editor-controls
reviewed: 2026-05-28T00:00:00Z
depth: deep
files_reviewed: 26
files_reviewed_list:
  - backend/app/processing/tiles/router.py
  - backend/app/modules/catalog/maps/schemas.py
  - backend/app/modules/catalog/maps/service_shared.py
  - backend/app/modules/catalog/maps/router.py
  - backend/tests/test_raster_colormap_proxy.py
  - frontend/nginx.conf
  - frontend/src/types/api.ts
  - frontend/src/components/builder/contour-sync.ts
  - frontend/src/components/builder/color-relief-sync.ts
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/DEMEditorScene.tsx
  - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
  - frontend/src/components/builder/layer-adapters/raster-adapter.ts
  - frontend/src/components/builder/__tests__/contour-sync.test.ts
  - frontend/src/components/builder/__tests__/color-relief-sync.test.ts
  - frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx
  - frontend/src/components/builder/__tests__/map-sync.raster.test.ts
  - frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts
  - frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/vite.config.ts
  - frontend/package.json
  - frontend/package-lock.json
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: findings
---

# Phase 1140: Code Review Report

**Reviewed:** 2026-05-28
**Depth:** deep
**Files Reviewed:** 26
**Status:** findings

## Summary

Phase 1140 delivers three DEM/raster editor controls — contour overlay, hypsometric tint, and single-band colormap — plus the backend allowlist validation and nginx cache-key change that the RESEARCH identified as pre-conditions.

The security requirement (T-1140-01: colormap_name allowlist) and the Pitfall 6 protection (builder-private keys never reaching `setPaintProperty`) are both correctly implemented and tested. The backend, schemas, nginx, and i18n are clean. The `color-relief` companion layer handles mode-switch and toggle-off transitions correctly.

Two behavioral bugs were found via deep trace: one affects the contour interval control at runtime (source tiles URL never updated on interval change — the primary DEM-04 knob stops working after the initial layer add), and one is a lifecycle gap (color-relief companion layer is not removed when the DEM layer is deleted from the map). Both are correctness issues, not style concerns.

---

## Critical Issues

### CR-01: Contour interval change has no effect after initial layer add

**File:** `frontend/src/components/builder/contour-sync.ts:167-198`

**Issue:** `syncContourLayer` constructs a new `contourProtocolUrl` (which encodes the current `thresholds` values derived from `_contour-interval`) on every call, but it only uses that URL when the vector source does not yet exist. Once the contour source is on the map, `map.getSource(contourSourceId)` returns truthy and the `addSource` block is skipped entirely. The existing source continues serving tiles generated from the original threshold parameters. Only `line-color` and `line-width` are updated via `setPaintProperty`. The interval slider — the primary DEM-04 control — silently has no visual effect after the first add.

The `maplibre-contour` library encodes the threshold configuration into the protocol URL via `actor.e(options)`, so URL1 (interval=100) and URL2 (interval=200) are distinct strings. The fix is to call `setTiles()` on the existing source when the desired URL has changed.

**Fix:**
```typescript
// After the existing source check block (line 167), replace with:
const existingSource = map.getSource(contourSourceId) as { setTiles?: (tiles: string[]) => void } | undefined;
if (!existingSource) {
  map.addSource(contourSourceId, {
    type: 'vector',
    tiles: [contourProtocolUrl],
  });
} else {
  // Update the tiles URL so interval/threshold changes re-fetch with new params.
  existingSource.setTiles?.([contourProtocolUrl]);
}
```

`VectorTileSource.setTiles()` exists in MapLibre GL JS 5.x (confirmed in `node_modules/maplibre-gl/dist/maplibre-gl.d.ts:2615`).

---

## Warnings

### WR-01: color-relief companion layer orphaned when DEM layer is deleted

**File:** `frontend/src/components/builder/map-sync.ts:824-851` (removeStaleSourcesAndLayers)

**Issue:** When a DEM layer is deleted from the map stack, `syncLayersToMap` no longer includes it in `renderableLayers`, so `syncColorReliefLayer` is never called for the deleted layer. The cleanup path `removeStaleSourcesAndLayers` iterates `currentSources` keyed by source ID. The `color-relief` companion layer has **no own source** — it reuses the existing `raster-dem` source. The stale-source loop removes `layer-<id>` (the hillshade layer) when `source-<id>` falls out of `desiredSources`, but the derived `layer-<id>-colorrelief` ID is not in the list of companion layer IDs checked (label/arrow/extrusion/outline/clusterCount/clusterCircle — see lines 842-848). The MapLibre instance is left with an orphaned `color-relief` layer referencing a now-removed source, which can emit errors and corrupt z-order until the map is re-created.

Note: The contour companion layer is **not** affected by this bug because its source ID (`source-<id>-contour`) is tracked in `managedSourcesRef` and `removeStaleSourcesAndLayers` correctly derives and removes `layer-<id>-contour` from it.

The misleading comment on `map-sync.ts:916-917` ("syncColorReliefLayer never calls addSource; the companion layer is auto-removed by syncColorReliefLayer when disabled...") is only true for toggle-off and mode-switch; it is false for the layer-deletion path.

**Fix:** Add `colorrelief` to the stale-source cleanup list in `removeStaleSourcesAndLayers`:
```typescript
// In removeStaleSourcesAndLayers, after line 838:
const colorReliefId = `${layerId}-colorrelief`;
// existing companions...
if (map.getLayer(colorReliefId)) map.removeLayer(colorReliefId);
// existing: if (map.getLayer(layerId)) map.removeLayer(layerId);
```

### WR-02: `_demSources` module-level registry is never pruned

**File:** `frontend/src/components/builder/contour-sync.ts:74`

**Issue:** `_demSources` is a module-level `Map<string, DemSource>` that accumulates one entry per unique `sourceId` seen. When a DEM layer is removed from the map, its `DemSource` instance (and any associated Web Worker resources it holds) is never released from the registry. In sessions where users add and remove many DEM layers, the registry grows without bound.

Additionally, if the same `sourceId` is reused after deletion (e.g., the same dataset re-added), `ensureDemSource` returns the stale `DemSource` bound to the old `tileUrl` — meaning if the tile URL changed (auth token rotation), the contour tiles would continue using the expired URL until the page is refreshed.

**Fix:** In `syncContourLayer`'s disabled branch, remove the entry from `_demSources` when the source is removed:
```typescript
if (!enabled) {
  if (map.getLayer(contourLayerId)) map.removeLayer(contourLayerId);
  if (map.getSource(contourSourceId)) map.removeSource(contourSourceId);
  _demSources.delete(input.sourceId);  // release DemSource + worker
  return;
}
```

---

## Info

### IN-01: No test coverage for contour interval change or color-relief DEM-deletion scenarios

**File:** `frontend/src/components/builder/__tests__/contour-sync.test.ts` and `color-relief-sync.test.ts`

**Issue:** There is no test asserting that changing `_contour-interval` when the contour source already exists calls `setTiles()` on the source (or causes a source recreate). This would have caught CR-01 before merge. There is also no test for the path where a DEM layer disappears from the sync loop while the color-relief layer is active — the test suite only exercises `syncColorReliefLayer` in isolation, not the `removeStaleSourcesAndLayers` path.

**Fix:** Add two regression tests:

1. In `contour-sync.test.ts`: Simulate `syncContourLayer` called twice with the same source ID, first with `interval=100`, then with `interval=200`. Assert that `setTiles` (or equivalent) is called on the second invocation with the new URL.

2. In `map-sync.raster.test.ts`: Test that after a DEM layer with active hypsometric tint is removed from the layers list and `syncLayersToMap` is re-called, the `layer-<id>-colorrelief` layer is removed from the map.

---

_Reviewed: 2026-05-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

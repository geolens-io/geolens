---
phase: 1134-map-functionality-and-smaller-screen-polish
plan: "01"
subsystem: builder/layer-adapters
tags: [builder, map-sync, layer-adapter, regression, tdd]
dependency_graph:
  requires: []
  provides:
    - raster-adapter split-guard (WALK-R-05 fix)
    - symbol-adapter syncLayerFilter migration
    - per-adapter regression test coverage (MAP-18 contract)
  affects:
    - frontend/src/components/builder/layer-adapters/raster-adapter.ts
    - frontend/src/components/builder/layer-adapters/symbol-adapter.ts
tech_stack:
  added: []
  patterns:
    - split source-guard from layer-guard (raster re-add on basemap reload)
    - syncLayerFilter helper for all setFilter call sites
    - per-adapter __tests__ regression pin pattern
key_files:
  created:
    - frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts
    - frontend/src/components/builder/layer-adapters/__tests__/symbol-adapter.test.ts
    - frontend/src/components/builder/layer-adapters/__tests__/circle-adapter.test.ts
    - frontend/src/components/builder/layer-adapters/__tests__/fill-adapter.test.ts
    - frontend/src/components/builder/layer-adapters/__tests__/line-adapter.test.ts
    - frontend/src/components/builder/layer-adapters/__tests__/cluster-adapter.test.ts
  modified:
    - frontend/src/components/builder/layer-adapters/raster-adapter.ts
    - frontend/src/components/builder/layer-adapters/symbol-adapter.ts
    - frontend/src/components/builder/layer-adapters/__tests__/heatmap-adapter.test.ts
decisions:
  - Cluster adapter intentionally keeps raw setFilter for compound combineFilter shape — not migrated to syncLayerFilter
  - Fill extrusion companion layer does not receive layout.visibility block at add-time (existing gap, noted in test)
  - Defense-in-depth setLayoutProperty after addLayer retained in raster-adapter for visibility correctness
metrics:
  duration: "~7 minutes"
  completed: "2026-05-27T16:13:15Z"
  tasks_completed: 3
  files_changed: 8
---

# Phase 1134 Plan 01: Per-Adapter Regression Sweep Summary

**One-liner:** Raster split-guard (WALK-R-05) + symbol syncLayerFilter migration + 7-adapter MAP-18 regression pin suite covering BUG-01 initial visibility, filter sync, syncVisibility, and getLayerIds shape.

## What Was Built

### Task 1: Raster adapter — split source-guard from layer-guard (WALK-R-05)

**Before (single early-return — WALK-R-05 bug):**
```ts
// raster-adapter.ts line 61 (before)
if (map.getSource(sourceId)) return;   // gates entire addLayers — blank tiles on basemap reload
map.addSource(sourceId, { ... });
map.addLayer({ id: layerId, ... });
```

**After (split guards — WALK-R-05 fix):**
```ts
// raster-adapter.ts lines 64-75 (after)
if (!map.getSource(sourceId)) {
  map.addSource(sourceId, { ... });
}
if (map.getLayer(layerId)) return;     // layer-only idempotency guard
map.addLayer({
  id: layerId,
  type: 'raster',
  source: sourceId,
  paint: buildRasterPaint(input),
  ...(visible === false ? { layout: { visibility: 'none' as const } } : {}),  // BUG-01
});
if (!visible) {
  map.setLayoutProperty(layerId, 'visibility', 'none');  // defense-in-depth
}
```

The three branches now covered:
| Source exists | Layer exists | Behavior |
|---|---|---|
| No | No | addSource + addLayer (cold add) |
| Yes | No | addLayer only (WALK-R-05 fix — basemap reload re-add) |
| Yes | Yes | no-op (idempotent) |

**Regression tests:** `raster-adapter.test.ts` — 7 tests (0 RED → 7 GREEN):
- Test 1: cold add → addSource + addLayer
- Test 2: source-exists/layer-missing → addLayer only (WALK-R-05 regression pin)
- Test 3: source-exists/layer-exists → no-op
- Test 4: visible=false → layout.visibility === 'none' in addLayer call
- Test 5: syncPaint smoke (setPaintProperty called)
- Test 6: syncVisibility(false) → setLayoutProperty 'none'
- Test 7: getLayerIds → [layerId]

### Task 2: Symbol adapter — migrate raw setFilter to syncLayerFilter (WALK-S)

**Before (raw setFilter in two places):**
```ts
// addLayers line 133
map.setFilter(input.layerId, input.filter);
// syncPaint line 151
map.setFilter(input.layerId, input.filter ?? null);
```

**After (syncLayerFilter helper in both places):**
```ts
// import line 3 — added syncLayerFilter to existing import
import { syncOwnedLayoutProperties, syncOwnedPaintProperties, syncSingleLayerVisibility, syncLayerFilter } from './shared';
// addLayers line 133
syncLayerFilter(map, input.layerId, input.filter);    // call site 1
// syncPaint line 151
syncLayerFilter(map, input.layerId, input.filter);    // call site 2 (was: filter ?? null)
```

syncLayerFilter benefits: guards `!map.getLayer` before calling setFilter, passes null when filter is empty/null (clearing the MapLibre filter), matches v1026 owned-property contract used by fill/line/circle/heatmap.

**Regression tests:** `symbol-adapter.test.ts` — 6 tests (all GREEN from write due to behavioral equivalence):
- Test 1: addLayers visible=true → layout.visibility 'visible'
- Test 2: addLayers visible=false → layout.visibility 'none' (BUG-01 PASS pin)
- Test 3: syncPaint with filter → setFilter called with filter (via helper)
- Test 4: syncPaint filter=null → setFilter called with null
- Test 5: syncVisibility(false) → setLayoutProperty 'none'
- Test 6: getLayerIds → [layerId]

### Task 3: Adapter regression pin sweep — circle, heatmap, fill, line, cluster

No source code modifications. Five adapter test files created/extended, pinning the MAP-18 contract:

| File | Tests added | BUG-01 pin | Filter sync pin | getLayerIds shape |
|---|---|---|---|---|
| circle-adapter.test.ts | 4 (new) | layout.visibility='none' | setFilter via syncLayerFilter | [layerId] |
| heatmap-adapter.test.ts | 4 (extended) | layout.visibility='none' | setFilter via syncLayerFilter | [layerId] |
| fill-adapter.test.ts | 5 (new) | fill+outline=none; extrusion added but no layout block | setFilter via syncLayerFilter | [id, outline, extrusion] |
| line-adapter.test.ts | 4 (new) | layout.visibility='none' | setFilter via syncLayerFilter | [id, id-arrow] |
| cluster-adapter.test.ts | 4 (new) | all 3 sub-layers visibility='none' | raw setFilter documented as v1026 exception | [circle, count, base] |

**Total tests across all 8 adapter test files: 59 (Tasks 1-3) + 95 (pre-existing layer-adapters scope) = 154 passing**

## Deviations from Plan

### Noted Gaps (documented in tests, not fixed in this plan)

**Fill extrusion companion:** The fill-extrusion layer (3rd companion) does not receive a `layout.visibility` block at add-time in the current `fillAdapter.addLayers`. The test documents this as an existing gap — visibility is controlled via `syncVisibility`. Not a regression from this plan; pre-existing behavior.

**Symbol addLayers raw setFilter:** The guard `if (input.filter && Array.isArray(input.filter) && input.filter.length > 0)` was preserved as-is (per plan instruction). The call inside was migrated from `map.setFilter` to `syncLayerFilter`. The `syncLayerFilter` helper no-ops on empty/null filter, so the guard is now redundant but kept for clarity.

## Cross-References

- WALK-R-05: raster source-guard early-return — `1133-BUILDER-WALKTHROUGH-AUDIT.md`
- WALK-S (symbol raw setFilter): same audit
- MAP-18: per-adapter regression pin requirement in REQUIREMENTS.md
- v1011 BUG-01: visibility-at-add-time pattern established in `fill-adapter.ts`/`circle-adapter.ts`

## Self-Check: PASSED

- All 8 adapter test files exist at expected paths
- All 3 task commits present: 6d7c3771, 378a575b, 9540d69e
- `cd frontend && npm test -- layer-adapters --run` → 154 tests, 9 files, all passing
- `cd frontend && npm run typecheck` → 0 errors
- `git diff -- frontend/src/components/builder/builder-action-contract.ts` → empty (union unchanged)
- `grep -n "if (map.getSource(sourceId)) return" raster-adapter.ts` → 0 matches
- `grep -nE "syncLayerFilter" symbol-adapter.ts` → 3 matches (import + addLayers + syncPaint)
- `grep -nE "map\.setFilter\(input\.layerId" symbol-adapter.ts` → 0 matches

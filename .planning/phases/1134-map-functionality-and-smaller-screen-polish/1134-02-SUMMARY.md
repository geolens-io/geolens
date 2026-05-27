---
phase: 1134-map-functionality-and-smaller-screen-polish
plan: "02"
subsystem: builder/layer-adapters
tags:
  - builder
  - delete
  - map-sync
  - adapter
dependency_graph:
  requires:
    - builder-layer-mutations.ts (modified)
    - layer-adapters/registry.ts (getAdapter — existing)
    - layer-adapters/fill-adapter.ts (getLayerIds — existing)
    - layer-adapters/cluster-adapter.ts (getLayerIds — existing)
  provides:
    - removePerLayerCompanions with optional renderModeByLayerId arg
    - builder-layer-mutations.test.ts (12 per-render-mode regression cases)
    - use-builder-layers.delete.test.ts extended with 5 MAP-17 pin cases
  affects:
    - handleRemove in use-builder-layers.ts (call-site unchanged; back-compat via optional arg)
    - handleBulkDelete in use-builder-layers.ts (call-site unchanged)
tech_stack:
  added: []
  patterns:
    - adapter-registry lookup via getAdapter() + adapter.type === renderMode guard
    - optional-arg back-compat: callers without renderModeByLayerId use 7-suffix fallback
key_files:
  created:
    - frontend/src/components/builder/hooks/__tests__/builder-layer-mutations.test.ts
  modified:
    - frontend/src/components/builder/hooks/builder-layer-mutations.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts
decisions:
  - "Used getAdapter(type).getLayerIds(prefixedId) — registry already exported from layer-adapters/registry.ts; no new registry needed"
  - "Optional renderModeByLayerId arg preserves all 3 existing call sites in use-builder-layers.ts without modification"
  - "Fallback suffix list kept for legacy callers; label suffix (-label) preserved because no adapter declares it in getLayerIds"
  - "line adapter deviation: returns [layerId, arrowLayerId] not [layerId] alone — Test 3b added to pin this correctly (plan interfaces section was inaccurate)"
metrics:
  duration: "4m 21s"
  completed: "2026-05-27T16:20:46Z"
  tasks_completed: 2
  files_changed: 3
---

# Phase 1134 Plan 02: Adapter-driven removePerLayerCompanions (MAP-17) Summary

Adapter-driven `removePerLayerCompanions` via `getLayerIds`; 7-suffix fallback preserved for all legacy callers.

## What Was Built

### `deriveCompanionIds` helper (builder-layer-mutations.ts)

New private helper that looks up the registered `LayerAdapter` for a given render mode and returns `adapter.getLayerIds(prefixedLayerId)`. When no adapter is registered or the render mode is unknown, it falls back to the static 7-suffix list identical to the pre-existing behavior.

```typescript
function deriveCompanionIds(prefixedLayerId: string, renderMode: string | null | undefined): string[]
```

The guard `adapter.type === renderMode` prevents the `getAdapter()` registry fallback (which returns `circleAdapter` for unknown types) from silently using a wrong adapter's id list.

### `removePerLayerCompanions` signature change

Added optional third argument:

```typescript
export function removePerLayerCompanions(
  map: MaplibreMap | null,
  layerIds: Iterable<string>,
  renderModeByLayerId?: Map<string, string>,  // NEW — optional
): void
```

- When `renderModeByLayerId` is provided: derives companion ids via `deriveCompanionIds` (adapter path).
- When omitted: uses 7-suffix fallback (identical to pre-existing behavior).

**All 3 existing call sites in `use-builder-layers.ts` (lines 310, 629, 805) are unchanged** — they omit the argument and fall through to the fallback path.

### Test counts

| File | New tests | Total |
|------|-----------|-------|
| `builder-layer-mutations.test.ts` | 12 (new file) | 12 |
| `use-builder-layers.delete.test.ts` | 5 (MAP-17 block appended) | 10 |

`builder-layer-mutations.test.ts` covers:
- Test 1: fill → 3 ids (base, outline, extrusion)
- Test 2: cluster → 3 ids (cluster-circle, cluster-count, base)
- Test 3 (x4): circle/symbol/heatmap/raster → 1 id each
- Test 3b: line → 2 ids (base + arrow companion)
- Test 4: legacy no-renderMode → 7-suffix fallback, 7 calls
- Test 5: null companion skipped without error
- Test 6: null map → no-op
- Test 7: isStyleLoaded()=false → no calls
- Test 8: multiple layer ids → each swept independently (fill 3 + cluster 3 = 6)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] line adapter returns 2 ids, not 1**
- **Found during:** Task 2 GREEN phase — `line` render mode test failed with 2 removeLayer calls
- **Issue:** Plan's `<interfaces>` section stated "From all other adapters (circle/symbol/heatmap/line/raster): `getLayerIds(layerId) { return [layerId]; }`" — but `line-adapter.ts:228` returns `[layerId, arrowLayerId(layerId)]` (base + arrow companion)
- **Fix:** Split Test 3 into Test 3 (circle/symbol/heatmap/raster = 1 id) and Test 3b (line = 2 ids: base + arrow). Both tests document correct adapter behavior.
- **Files modified:** `builder-layer-mutations.test.ts` (test file only)
- **Commit:** `69f3e4e7`

## Confirmation: use-builder-layers.ts NOT Modified

`git diff -- frontend/src/components/builder/hooks/use-builder-layers.ts` returns empty. The 3 call-sites continue to use the 7-suffix fallback path via the optional-arg back-compat design.

## Self-Check: PASSED

- `builder-layer-mutations.test.ts`: FOUND
- `1134-02-SUMMARY.md`: FOUND
- Commit `05e71a4b` (Task 1 tests): FOUND
- Commit `69f3e4e7` (Task 2 impl+tests): FOUND
- `deriveCompanionIds` in builder-layer-mutations.ts: 2 occurrences (definition + call site)
- `getLayerIds` in builder-layer-mutations.ts: 3 occurrences (docstring + impl + adapter call)

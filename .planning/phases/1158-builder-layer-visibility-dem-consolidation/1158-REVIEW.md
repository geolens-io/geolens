---
phase: 1158-builder-layer-visibility-dem-consolidation
reviewed: 2026-05-30T00:00:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/color-relief-sync.ts
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx
  - frontend/src/components/builder/__tests__/color-relief-sync.test.ts
  - frontend/src/components/builder/__tests__/BuilderMap.terrain-visibility.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.dem-rows.test.tsx
findings:
  critical: 1
  warning: 1
  info: 1
  total: 3
status: issues_found
---

# Phase 1158: Code Review Report

**Reviewed:** 2026-05-30
**Depth:** deep
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Four targeted bug fixes for builder rendering/visibility (BLDR-01 through BLDR-04). The BLDR-01 raster-basemap guard, BLDR-02 terrain attach/detach, and BLDR-04 color-relief companion visibility are all correct and well-tested. One cross-file consistency defect was found in BLDR-03: `selectableRowIds` in `MapBuilderPage.tsx` is built from the raw `layers.localLayers` list (including terrain-mode DEM layers that are now suppressed from the stack UI), while `visibleStackLayers` filters them out of every rendered row. A shift-click range-select spanning a suppressed terrain layer can silently include that layer's ID in `selectedIds`, which `handleBulkDelete` will then act on — deleting the terrain configuration record from the backend without any user intent to select or delete it.

## Critical Issues

### CR-01: `selectableRowIds` includes suppressed terrain-DEM IDs, enabling accidental bulk-delete

**File:** `frontend/src/pages/MapBuilderPage.tsx:500-506`

**Issue:** `selectableRowIds` is derived from `layers.localLayers` (the full layer list), but BLDR-03 now filters terrain-mode DEM layers out of `visibleStackLayers`, so those layers have no `[data-row-id]` DOM element and no rendered row. When a user shift-clicks from a visible layer above a terrain DEM to a visible layer below it, `computeNextSelection` (`selection-utils.ts`) receives the full `selectableRowIds` list and returns a range that includes the suppressed terrain DEM ID. That ID ends up in `selectedIds`. Two concrete consequences:

1. **Accidental bulk-delete:** `handleBulkDelete` in `use-builder-layers.ts:598-610` filters only `layer_type === 'group:folder'` rows. A terrain-mode DEM layer has `layer_type: null`, so it passes through and is sent to the backend bulk-delete endpoint. The terrain configuration record is deleted.

2. **BulkActionBar count confusion:** The bar shows "N selected" where N counts the invisible terrain ID. The user sees a selection count that doesn't match the visible rows — and selecting all visible rows between two points can silently select a row they cannot see.

The shift-arrow keyboard handler in `UnifiedStackPanel.tsx:778` also tries `querySelector('[data-row-id="${adjacentId}"]')` when the adjacentId is a suppressed terrain row — it returns null and focus skips, creating dead navigation steps.

**Fix:** Filter suppressed terrain IDs out of `selectableRowIds` at construction time. Import `isDemTerrainVisualSuppressed` from `./map-sync` in `MapBuilderPage.tsx` and add the filter:

```typescript
// frontend/src/pages/MapBuilderPage.tsx
import { isDemTerrainVisualSuppressed } from '@/components/builder/map-sync';

const selectableRowIds = useMemo((): string[] => {
  return layers.localLayers
    .filter((l) => !isDemTerrainVisualSuppressed(l))
    .map((l) => l.id);
}, [layers.localLayers]);
```

This mirrors the `visibleStackLayers` filter in `UnifiedStackPanel.tsx:790-793` and ensures `selectableRowIds`, rendered rows, and shift-click ranges are consistent.

## Warnings

### WR-01: `isEmpty` false-positive when all layers are terrain-mode DEM records

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx:837`

**Issue:** `isEmpty = visibleStackLayers.length === 0`. If a user has added a map layer configured in terrain mode (and no other layers), `isEmpty` is `true` and `EmptyStackState` is rendered, even though `layers.length > 0`. The user sees "Add data" empty-state UI while the map is actively displaying a DEM terrain layer. The terrain record exists on the backend; the stack just doesn't show it. This is surprising and could lead users to think their layer was deleted.

Whether this is intentional (terrain is map-level config, not a layer row) needs to be documented. If it's accepted as intentional, a comment should say so explicitly; if not, add a fallback guard:

```typescript
// Use raw layers.length to gate the true empty state,
// so a map with only a terrain DEM still shows "populated" state.
const isEmpty = layers.length === 0;
```

Or, if the intent is that `isEmpty` means "no stackable rows," add a comment explaining why a terrain-only map showing "Add data" state is correct.

## Info

### IN-01: BLDR-02 Test A has a loose assertion that could survive a no-op

**File:** `frontend/src/components/builder/__tests__/BuilderMap.terrain-visibility.test.tsx:380-384`

**Issue:** Test A asserts `setTerrainCalls.length > 0` and checks the last call is `{ source: TERRAIN_SOURCE_ID }`. Because `applyTerrainConfig` is called once on mount (isStyleLoaded returns true immediately), a single attach call is expected. However, if the component were ever changed to call `setTerrain(null)` first and then `setTerrain(source)` (e.g. to reset before re-attaching), the `length > 0` check would still pass and the last-call assertion would still pass — a "detach then attach" sequence produces the same assertion results as a single "attach". Consider tightening to assert `setTerrainCalls.length === 1` or specifically assert that `setTerrain(null)` is never called:

```typescript
// Stricter: ensure setTerrain was called exactly once with the source
expect(setTerrainCalls).toHaveLength(1);
expect(setTerrainCalls[0][0]).toMatchObject({ source: TERRAIN_SOURCE_ID });
```

This is low severity since the test still proves the correct attach path runs; the loose form does not create a false negative for the current implementation.

---

_Reviewed: 2026-05-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

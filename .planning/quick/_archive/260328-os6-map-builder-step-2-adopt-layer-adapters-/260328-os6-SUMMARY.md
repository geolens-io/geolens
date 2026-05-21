---
phase: 260328-os6
plan: 01
subsystem: frontend/viewer
tags: [refactor, map-builder, viewer, layer-adapters]
dependency_graph:
  requires: [260328-o9v]
  provides: [unified-layer-rendering-builder-viewer]
  affects: [frontend/src/components/viewer/ViewerMap.tsx, frontend/src/components/builder/layer-adapters/fill-adapter.ts]
tech_stack:
  added: []
  patterns: [layer-adapter pattern extended to viewer, prefix-agnostic outline ID derivation]
key_files:
  created: []
  modified:
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/components/builder/layer-adapters/fill-adapter.ts
decisions:
  - "fill-adapter derives outlineId from input.layerId (${input.layerId}-outline) instead of getOutlineLayerId(input.id) — prefix-agnostic, works for both builder (layer-{uuid}-outline) and viewer (viewer-layer-{sort}-outline)"
  - "ViewerMap retains local reorderBasemapLabels — map-sync version uses source- prefix filter which would incorrectly match viewer-source- prefixed data layers as basemap symbols"
metrics:
  duration: 15 min
  completed: 2026-03-28
  tasks_completed: 3
  files_changed: 2
---

# Phase 260328-os6 Plan 01: Map Builder Step 2 — Adopt Layer Adapters Summary

**One-liner:** ViewerMap refactored to use layer adapter system (fill/line/circle), gaining expression replay, _stroke-disabled, line-dasharray, and compound opacity; fill-adapter made prefix-agnostic for outline ID derivation.

## What Was Built

Replaced the ~120-line inline circle/line/fill dispatch in `ViewerMap.tsx` with calls to the layer adapter system introduced in Step 1 (260328-o9v). Both the map builder and viewer now share identical rendering logic through a single adapter dispatch path.

**Changes:**

1. **fill-adapter.ts** — Changed all four outline ID derivations (`addLayers`, `syncPaint`, `syncOpacity`, `syncVisibility`) from `getOutlineLayerId(input.id)` to `` `${input.layerId}-outline` ``. Removed the `getOutlineLayerId` import from map-sync. This makes the fill adapter work with any layer ID prefix, enabling reuse in both builder (`layer-{uuid}-outline`) and viewer (`viewer-layer-{sort}-outline`) contexts without hardcoding the `layer-` prefix.

2. **ViewerMap.tsx** — Added `toAdapterInput()` helper that maps `SharedLayerResponse` + `visibleLayers` + `tileUrl` to the `AdapterLayerInput` contract. Replaced the three geometry-type dispatch branches (circle/line/fill) in the sync-layers useEffect with `getAdapter(type).addLayers/syncPaint`. Replaced the manual three-layer visibility loop with `adapter.syncVisibility()` plus explicit label handling. Removed local `getOutlineLayerId` function (adapter manages outline IDs). Added imports for `getAdapter`, `AdapterLayerInput`, and `getLayerType`.

**What the viewer gains for free:**
- Expression replay (match/step/interpolate expressions render correctly on initial add)
- `_stroke-disabled` flag suppresses polygon outline in viewer
- `line-dasharray` stored in layout JSON renders as dashed lines
- Compound opacity (property opacity × master opacity, not naive multiplication)
- `simplifyPaint` fallback prevents addLayer failures on complex expressions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Kept local reorderBasemapLabels in ViewerMap**

- **Found during:** Task 1 implementation
- **Issue:** The plan proposed importing `reorderBasemapLabels` from `map-sync` to remove the local copy. However, map-sync's implementation filters basemap symbol layers using `!String(l.source ?? '').startsWith('source-')`. Viewer data layers use `viewer-source-{sort}` as their source ID. `'viewer-source-5'.startsWith('source-')` is FALSE, so viewer data symbol layers (label layers) would be incorrectly classified as basemap symbol layers by map-sync's function and moved/hidden. The local version correctly filters on `!startsWith('viewer-source-')`, keeping viewer data labels intact.
- **Fix:** Retained the local `reorderBasemapLabels` function with the correct `viewer-source-` prefix check.
- **Files modified:** `frontend/src/components/viewer/ViewerMap.tsx`
- **Commit:** 55b05f54

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 2 (fill-adapter) | 05b7006a | feat(260328-os6-02): update fill-adapter outline ID to use layerId prefix |
| Task 1 (ViewerMap) | 55b05f54 | refactor(260328-os6-01): replace inline layer dispatch in ViewerMap with adapter calls |

## Verification

- TypeScript: zero errors (`tsc --noEmit`)
- Builder tests: 103 tests pass (all 8 test files)
- Adapter tests: 56 tests pass (layer-adapters.test.ts, map-sync.raster.test.ts, BuilderMap.unit.test.ts)
- fill-adapter backward compatibility: `fillAdapter > syncVisibility sets visibility on both main and outline layers` PASSED

## Self-Check: PASSED

- `frontend/src/components/viewer/ViewerMap.tsx` — FOUND (modified, uses getAdapter)
- `frontend/src/components/builder/layer-adapters/fill-adapter.ts` — FOUND (modified, uses layerId-outline)
- Commit 55b05f54 — FOUND
- Commit 05b7006a — FOUND

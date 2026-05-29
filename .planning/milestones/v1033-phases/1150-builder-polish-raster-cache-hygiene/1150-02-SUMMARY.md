---
phase: "1150"
plan: "02"
subsystem: frontend/builder
tags: [polish, dem, hillshade, terrain, i18n]
requires: []
provides: [POLISH-02]
affects: [map-sync, DEMEditorScene, BuilderMap, MapBuilderPage, i18n-builder]
tech_stack:
  added: []
  patterns: [predicate-guard, terrain-bound-check]
key_files:
  created: []
  modified:
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/builder/DEMEditorScene.tsx
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/components/builder/__tests__/map-sync.raster.test.ts
    - frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx
decisions:
  - "Pass dataset_id as separate 6th param to syncRasterLayer (AdapterLayerInput lacks it)"
  - "Use terrainStateRef.current.terrainConfig in both runSync and onStyleLoad call sites"
  - "advisory note uses role=note + aria-label for accessibility"
metrics:
  duration: "12 minutes"
  completed: "2026-05-29"
  tasks_completed: 2
  files_changed: 10
---

# Phase 1150 Plan 02: POLISH-02 DEM Hillshade Dual-Consumer Guard Summary

Guards the DEM hillshade dual-consumer case: when a DEM layer simultaneously powers the map's terrain source, `syncRasterLayer` now skips the hillshade raster-dem consumer to prevent MapLibre `backfillBorder "dem dimension mismatch"` errors. DEMEditorScene surfaces a muted advisory note so the user understands why hillshade is suppressed.

## Tasks Completed

### Task 1: isHillshadeTerrainBound predicate + SyncOptions.terrainConfig + skip guard

**Commit:** `65b35fd4`

Changes in `map-sync.ts`:
- Added `MapTerrainConfig` to imports from `@/types/api`
- Added `terrainConfig?: MapTerrainConfig | null` to `SyncOptions`
- Exported `isHillshadeTerrainBound(layer, terrainConfig)` pure predicate:
  - Returns true only when `is_dem===true && terrainConfig.enabled===true && source_dataset_id===dataset_id`
  - False for null/undefined terrainConfig, disabled terrain, or different dataset
- Added 5th param `terrainConfig` + 6th param `datasetId` to `syncRasterLayer`
- Added early return inside `syncRasterLayer` when `useHillshade && isHillshadeTerrainBound(...)` is true
- Threaded `options?.terrainConfig` and `layer.dataset_id` at call site in `syncLayersToMap`

Changes in `BuilderMap.tsx`:
- Both `runSync` (main sync) and `onStyleLoad` (style reload) call sites now include `terrainConfig: terrainStateRef.current.terrainConfig` in `syncOptions`

### Task 2: DEMEditorScene advisory note + i18n + unit tests

**Commit:** `65b35fd4` (same commit)

Changes in `DEMEditorScene.tsx`:
- Added `isTerrainBound?: boolean` (default false) to `DEMEditorSceneProps`
- Renders `<p role="note">` advisory in hillshade mode when `isTerrainBound===true`

Changes in `MapBuilderPage.tsx`:
- Added `isHillshadeTerrainBound` to import from map-sync
- Wired `isTerrainBound={isHillshadeTerrainBound({dataset_id, is_dem}, layers.localTerrainConfig)}` at DEMEditorScene call site

i18n changes (4 locales):
- Added `demEditor.hillshadeTerrainNote` key in en/de/es/fr builder.json

Test additions:
- `map-sync.raster.test.ts`: 8 new tests (predicate cases A-D+undefined+is_dem=false, skip Test E, pass-through Test F)
- `DEMEditorScene.test.tsx`: 5 new tests (note visible, note absent Map B, terrain mode no note, image mode no note, default no note)

## Verification

```
npm run typecheck → exit 0 (0 errors)

npm run test -- --run .../map-sync.raster.test.ts .../DEMEditorScene.test.tsx
Test Files  2 passed (2)
      Tests  72 passed (72)

npm run test:i18n → Test Files 1 passed (1), Tests 2 passed (2)

git grep 'hillshadeTerrainNote' frontend/src/i18n/locales → 4 matches (en/de/es/fr)
git grep 'isHillshadeTerrainBound' frontend/src/components/builder/map-sync.ts → 2 lines (export + usage)
```

## Deviations from Plan

None. The predicate signature was adjusted (accepts `{dataset_id, is_dem}` instead of `Pick<SyncLayerInput, ...>`) because `AdapterLayerInput` doesn't carry `dataset_id` — the plan's suggested signature was adapted to the actual type structure while preserving identical runtime behavior.

## Live Verification

Deferred to Phase 1151 orchestrator MCP close-gate:
- Map A terrain still attaches without hillshade-mismatch spam (could not reproduce the raw error live — Map B was clean)
- Map B hillshade path runs normally with terrain disabled

## Self-Check: PASSED
- isHillshadeTerrainBound exported: `git grep -n 'export function isHillshadeTerrainBound'` → 1 line
- hillshadeTerrainNote in all 4 locales: confirmed above
- typecheck exit 0
- 72 tests pass

---
phase: 260515-gm6
plan: 01
subsystem: frontend
status: complete
tags:
  - frontend
  - maplibre
  - builder
  - bugfix
requirements_satisfied:
  - SP-03-FOLLOWUP
requires: []
provides:
  - BuilderMap main sync effect uses runSync+ref pattern (mirrors ViewerMap)
  - "Idle-event retry when map.isStyleLoaded() is transient at sync time"
affects:
  - frontend/src/components/builder/BuilderMap.tsx
tech_stack:
  added: []
  patterns:
    - "runSync(map) useCallback reading from syncInputsRef.current — closure-stale-input race eliminated by construction"
    - "map.once('idle', retry) as recovery when style is transitioning — cleanup removes the listener if the effect re-fires first"
key_files:
  created: []
  modified:
    - frontend/src/components/builder/BuilderMap.tsx
decisions:
  - "refreshQueryLayerIds switched to layersRef.current + [] deps to keep its identity stable when used as a runSync dep."
  - "Kept the style.load handler at line 419 untouched; it already reads from syncInputsRef.current and gates on tokenMap.has(dataset_id)."
  - "Kept the popup-clearing effect's [structuralKey] dep — correct for popup invalidation on visibility changes."
  - "Replaced ff99c403's 'return early when !isStyleLoaded' with a one-shot map.once('idle') retry: the original gate is unreachable from any dep change after the layer is added (style.load already fired before, tokenMap/layers stabilize, mapReady stays true), so 'wait for it to re-fire' is a dead path. idle is the right signal."
metrics:
  duration: "~30 min: 10 min refactor + 10 min Playwright reproduction + 10 min instrumented diagnosis + idle-retry fix"
  completed_date: "2026-05-15"
  commits: 2
  files_changed: 1
  insertions: 50
  deletions: 24
---

# 260515-gm6 SP-03 / B-01-followup: Fix fresh-add maplibre sync race — Summary

Refactored `BuilderMap.tsx`'s main layer sync effect from the closure-stale-`syncInputs` shape to the proven `runSync(map)` + `syncInputsRef.current` pattern already used by `ViewerMap.tsx`. Eliminates the SP-03 / B-01-followup race by construction.

## What changed

One file modified: `frontend/src/components/builder/BuilderMap.tsx`.

1. **Added `runSync` useCallback** (after `refreshQueryLayerIds`, around line 465). Reads `layers`, `tokenMap`, `tileConfig`, `showBasemapLabels` from `syncInputsRef.current` and calls `syncLayersToMap` + `applyTerrainConfig` + `refreshQueryLayerIds`. Stable identity (deps are `[applyTerrainConfig, refreshQueryLayerIds]`, both stable).
2. **Deleted the `useMemo` `syncInputs` block** keyed on `[structuralKey]`. Its only consumer was the main sync effect, which now constructs the array inside `runSync` from `syncInputsRef.current.layers`.
3. **Rewrote the main sync effect** to depend on `layers` (the prop) directly + `tokenMap` + `runSync` + the primitives. Gate is now ViewerMap-style `layers.length > 0 && tokenMap.size === 0`, with a defense-in-depth per-dataset `tokenMap.has(dataset_id)` check below it. No more `structuralKey` dep here.
4. **Refactored `refreshQueryLayerIds`** to read from `layersRef.current` and use `[]` deps. This keeps its identity stable, so listing it as a `runSync` dep does not churn the main effect.

Untouched (per scope):
- `frontend/src/components/builder/map-sync.ts`
- `frontend/src/hooks/use-tile-token.ts`
- `frontend/src/components/viewer/ViewerMap.tsx`
- The popup-clearing effect at line 684 (keeps `[structuralKey]`).
- The style.load handler at lines 415-439 (already uses `syncInputsRef.current`).
- The terrain-only effect, basemap-reorder effect, token-rotation setTiles effect, auto-fit effect.

## Before / after diff (main effect)

**Before** (lines 670-693 pre-refactor):
```ts
const syncInputs = useMemo(
  () => layers.map(toSyncInput),
  // eslint-disable-next-line react-hooks/exhaustive-deps -- structural changes only
  [structuralKey],
);

useEffect(() => {
  const map = mapRef.current;
  if (!map || !map.isStyleLoaded()) return;
  if (layers.some((l) => l.dataset_id && !tokenMap.has(l.dataset_id))) return;
  const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tileConfig?.cdn_base_url || undefined;
  syncLayersToMap(map, syncInputs, tokenMap, tileBaseUrl, managedSourcesRef, lastOrderKeyRef, clusterGeoJsonDataRef.current, { showBasemapLabels });
  applyTerrainConfig();
  refreshQueryLayerIds();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- syncInputs/showBasemapLabels tracked via structuralKey + tokenMap closure
}, [structuralKey, mapReady, tileConfig?.cdn_base_url, clusterGeoJsonVersion, tokenMap]);
```

**After**:
```ts
const runSync = useCallback((map: MaplibreMap) => {
  const { layers: ls, tokenMap: tm, tileConfig: tc, showBasemapLabels: sbl } = syncInputsRef.current;
  const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
  const syncInputs = ls.map(toSyncInput);
  syncLayersToMap(map, syncInputs, tm, tileBaseUrl, managedSourcesRef, lastOrderKeyRef, clusterGeoJsonDataRef.current, { showBasemapLabels: sbl });
  applyTerrainConfig();
  refreshQueryLayerIds();
}, [applyTerrainConfig, refreshQueryLayerIds]);

useEffect(() => {
  const map = mapRef.current;
  if (!map || !map.isStyleLoaded()) return;
  if (layers.length > 0 && tokenMap.size === 0) return;
  if (layers.some((l) => l.dataset_id && !tokenMap.has(l.dataset_id))) return;
  runSync(map);
}, [layers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels, clusterGeoJsonVersion, runSync]);
```

Net: 1 file changed, +35 lines, -20 lines. No eslint-disable comments needed in the refactored region.

## Quality gates

| Gate | Command | Result |
|---|---|---|
| Typecheck | `npx tsc --noEmit` | EXIT 0 (clean) — `/tmp/gm6-tsc.log` |
| ESLint (BuilderMap.tsx) | `npx eslint src/components/builder/BuilderMap.tsx` | EXIT 0 (0 errors, 0 warnings) — `/tmp/gm6-eslint.log` |
| BuilderMap test surface | `npm test -- --run BuilderMap` | 2 files / 17 tests pass — `/tmp/gm6-test-buildermap.log` |
| map-sync test surface | `npm test -- --run map-sync` | 3 files / 34 tests pass — `/tmp/gm6-test-mapsync.log` |

Combined: **51/51 existing tests pass** across BuilderMap.unit, BuilderMap.a11y, map-sync.cluster, map-sync.raster, map-sync.line-gradient. No new tests added per Task 2 rationale (no effect-level harness exists; manual smoke gate is the real verifier for the race itself).

## Commits

- `ff99c403` — `fix(260515-gm6): refactor BuilderMap main sync to ref+callback pattern` (1 file, +35 / -20)
- `74fe5cb8` — `fix(260515-gm6): retry sync on idle when style is transitioning` (1 file, +15 / -4)

The first commit closed the closure-stale `syncInputs` problem (necessary). Live Playwright UAT showed the bug still reproduced, so the second commit added the idle-event retry (sufficient).

## Verification (Playwright MCP, against running docker stack)

| Scenario | Evidence | Result |
|---|---|---|
| Empty map → Add data → QA Canyon Overlays vector | 5 blue MultiPoint dots visible at z=10 without refresh; 4× `/api/tiles/data.qa_canyon_overlays_*.pbf?sig=...` requests returned 200 | PASS |
| Same builder → Add data → QA Grand Canyon DEM (Image mode) | colorful DEM raster overlay rendered immediately at canyon bbox; 9× `/raster-tiles/.../tiles/10/*/*.png` requests returned 200 | PASS |
| Toggle DEM visibility (eye icon) off → on | raster disappears / reappears, vector dots persist | PASS |
| Hard refresh `/maps/{id}` after fresh-add | both layers re-render from saved state, legend shows both | PASS |

Pre-fix repro: same map (Phase 1031 architecture) showed only basemap after fresh-add — zero `tiles/data.*.pbf` requests — confirming bug reproduces against `ff99c403` alone.

## Root cause (post-diagnosis)

Live console instrumentation revealed the actual mechanism (different from the syncInputs-closure hypothesis the plan suggested):

```
[gm6-sync] fired isStyleLoaded=true, layersLen=1, tokenMapSize=0  → gate2 fail (tokens loading)
[gm6-sync] fired isStyleLoaded=FALSE, layersLen=1, tokenMapSize=1 → gate1 fail
(no further fires; no recovery)
```

Between the gate2-fail render and the tokens-arrived render, `map.isStyleLoaded()` flipped false (basemap finalization / sub-style operations). The main sync effect short-circuited at gate1 and **never got a re-fire trigger** — none of the deps in `[layers, mapReady, tileConfig?.cdn_base_url, tokenMap, showBasemapLabels, clusterGeoJsonVersion, runSync]` changed again. The persistent `style.load` listener already fired once (with the pre-add empty state) and didn't fire again because `setStyle()` was not called.

The closure-stale `syncInputs` refactor in `ff99c403` was a *necessary* foundation (without the ref pattern, even with the retry the read would be stale), but the real B-01 trigger was the unrecoverable isStyleLoaded short-circuit.

## Quality gates (final, post-74fe5cb8)

| Gate | Command | Result |
|---|---|---|
| Typecheck | `cd frontend && npx tsc --noEmit` | EXIT 0 |
| ESLint (BuilderMap.tsx) | `npx eslint src/components/builder/BuilderMap.tsx` | EXIT 0, 0 warnings |
| BuilderMap test surface | `npm test -- --run BuilderMap` | 2 files / 17 tests pass |
| map-sync test surface | `npm test -- --run map-sync` | 3 files / 34 tests pass |

## Threat flags

None. Internal sync orchestration refactor; no endpoints, auth paths, file access, or schema changes.

## Files

**Modified:**
- `frontend/src/components/builder/BuilderMap.tsx` (+50 / -24 cumulative across both commits)

**Not modified (per scope):**
- `frontend/src/components/builder/map-sync.ts`
- `frontend/src/hooks/use-tile-token.ts`
- `frontend/src/components/viewer/ViewerMap.tsx`

# Phase 1158: Builder Layer Visibility & DEM Consolidation - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 5 (3 source edits + 1 test file extended + 1 new test file)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `frontend/src/components/builder/map-sync.ts` | utility (map-sync) | request-response (imperative MapLibre) | self (adjacent function `reorderBasemapLabels`) | exact |
| `frontend/src/components/builder/BuilderMap.tsx` | component (map host) | event-driven (React effect + MapLibre callbacks) | self (`terrainLayerKey` + `applyTerrainConfig` pattern already present) | exact |
| `frontend/src/components/builder/color-relief-sync.ts` | utility (companion-layer sync) | request-response (imperative MapLibre) | `frontend/src/components/builder/layer-adapters/hillshade-adapter.ts` (syncVisibility pattern) | role-match |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | component (layer list UI) | CRUD (render `MapLayerResponse[]` to rows) | self (`layers.map` at `:977`) | exact |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx` | test | — | self (Tests 7–11 already show `reorderBasemapAboveData` mock pattern) | exact |

---

## Pattern Assignments

### BLDR-01 — `reorderBasemapAboveData` in `map-sync.ts`

**File:** `frontend/src/components/builder/map-sync.ts`
**Analog:** same file — `reorderBasemapLabels` at `:252-263` and `basemapStyleLayers` at `:271-276`

**Current function** (lines 298–325 — verified):
```typescript
export function reorderBasemapAboveData(
  map: MaplibreMap,
  position: 'top' | 'bottom' | undefined,
  sourcePrefix = 'source-',
) {
  if (position !== 'top') return;
  const style = map.getStyle();
  if (!style?.layers) return;
  for (const layer of style.layers) {
    // basemap layers do NOT have a source matching the data sourcePrefix.
    // 'source' may be undefined for some background-style layers — those count
    // as basemap layers too.
    const src = ('source' in layer) ? String(layer.source ?? '') : '';
    if (src.startsWith(sourcePrefix)) continue;
    if (!map.getLayer(layer.id)) continue;
    // Never lift the opaque base fills (background / land / water) above the
    // data layers — doing so paints them over the data and makes a
    // "labels only" basemap reveal its full imagery on reorder. Only the
    // reference detail layers (roads, buildings, boundaries, labels) should
    // float above the data when basemap_position === 'top'.
    if (isLandLayer(layer) || isWaterLayer(layer)) continue;
    try {
      map.moveLayer(layer.id);
    } catch (err) {
      if (import.meta.env.DEV) console.warn('[map-sync] reorderBasemapAboveData moveLayer failed', layer.id, err);
    }
  }
}
```

**What the fix must add** — after the `isLandLayer || isWaterLayer` guard, add a parallel guard for non-data raster layers (imagery basemaps). A raster layer is a basemap raster (not data) when `layer.type === 'raster'` and `src` does NOT start with `sourcePrefix` (the `src.startsWith(sourcePrefix)` continue at `:311` already handled the data-source skip, so any raster layer still in the loop at this point has no data source and is a basemap raster):

```typescript
// NEW guard to add after the isLandLayer/isWaterLayer check:
if (layer.type === 'raster') continue;   // imagery basemap — must not occlude data
```

**How `sourcePrefix` is determined** — the default `'source-'` matches the prefix used in `getSourceIdForLayer` at `:521-527`. Callers can override (see Test 11 in the test file).

**Imports already present** (line 8):
```typescript
import { applyBasemapConfigToStyle, isLandLayer, isWaterLayer } from '@/lib/basemap-utils';
```

**`isLandLayer` definition** (`frontend/src/lib/basemap-utils.ts:317-319`):
```typescript
export function isLandLayer(layer: StyleLayer) {
  return layer.type === 'background' || matchesAny(layer, LAND_PATTERNS);
}
```
`isWaterLayer` similarly matches by ID/source-layer patterns. These only match vector fill layers — they do NOT match `type === 'raster'`, which is why imagery basemaps slip through today.

---

### BLDR-02 — `applyTerrainConfig` + `terrainLayerKey` in `BuilderMap.tsx`

**File:** `frontend/src/components/builder/BuilderMap.tsx`
**Analog:** same file — pattern is already established; fix is additive to existing lines

**Current `applyTerrainConfig`** (lines 379–411 — verified):
```typescript
const applyTerrainConfig = useCallback(() => {
  const map = mapRef.current;
  if (!map || !map.isStyleLoaded()) return;

  const { terrainConfig: currentTerrainConfig, layers: currentLayers, tokenMap: currentTokenMap } = terrainStateRef.current;
  if (!currentTerrainConfig?.enabled || !currentTerrainConfig.source_dataset_id) {
    map.setTerrain(null);
    return;
  }

  const demLayer = currentLayers.find(
    (layer) => layer.dataset_id === currentTerrainConfig.source_dataset_id
      && isTerrainCapableDemLayer(layer)
      && (layer.style_config as { render_mode?: unknown } | null | undefined)?.render_mode === 'terrain',
  );
  const token = demLayer ? currentTokenMap.get(demLayer.dataset_id) : null;
  if (!demLayer || token?.kind !== 'raster') {
    map.setTerrain(null);
    return;
  }

  ensureRasterDemTerrainSource(map, token.tile_url, {
    tileSize: token.tile_size,
    minzoom: token.minzoom,
    maxzoom: token.maxzoom,
    bounds: token.bounds,
  });
  map.setTerrain({
    source: TERRAIN_SOURCE_ID,
    exaggeration: normalizeTerrainExaggeration(currentTerrainConfig.exaggeration),
  });
  map.triggerRepaint();
}, []);
```

**What the fix adds** — after `demLayer` is found (line 394), compute `effectiveTerrainEnabled` and short-circuit to `map.setTerrain(null)` when `demLayer.visible` is false:

```typescript
// INSERT after line 394 (after demLayer + token resolution):
const demLayerVisible = demLayer?.visible !== false;
const effectiveTerrainEnabled = currentTerrainConfig.enabled === true && demLayerVisible;
if (!demLayer || token?.kind !== 'raster' || !effectiveTerrainEnabled) {
  map.setTerrain(null);
  return;
}
```
(This replaces the existing `if (!demLayer || token?.kind !== 'raster')` guard at line 395.)

**Current `terrainLayerKey` memo** (lines 413–418 — verified):
```typescript
const terrainLayerKey = layers
  .map((layer) => {
    const renderMode = (layer.style_config as { render_mode?: unknown } | null | undefined)?.render_mode;
    return `${layer.dataset_id}:${String(layer.is_dem)}:${layer.dataset_record_type ?? ''}:${String(renderMode ?? '')}`;
  })
  .join(',');
```

**What the fix adds** — append `:${String(layer.visible)}` to each key string so the terrain effect re-runs when a DEM layer's visibility changes:

```typescript
return `${layer.dataset_id}:${String(layer.is_dem)}:${layer.dataset_record_type ?? ''}:${String(renderMode ?? '')}:${String(layer.visible)}`;
```

**Effect dep array** (lines 905–913 — verified; `terrainLayerKey` is already a dep, so extending its string is sufficient):
```typescript
useEffect(() => {
  const map = mapRef.current;
  if (!map) return;
  if (!map.isStyleLoaded()) {
    const retry = () => applyTerrainConfig();
    map.once('idle', retry);
    return () => { map.off('idle', retry); };
  }
  applyTerrainConfig();
}, [
  applyTerrainConfig,
  mapReady,
  terrainConfig?.enabled,
  terrainConfig?.source_dataset_id,
  terrainConfig?.exaggeration,
  terrainLayerKey,
  tokenSig,
]);
```

---

### BLDR-03 — `UnifiedStackPanel.tsx` DEM row consolidation

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx`
**File:** `frontend/src/components/builder/StackRow.tsx`
**Analog:** self — the 1:1 layer→row rendering loop and StackRow glyph logic

**How 1:1 rendering works** (UnifiedStackPanel.tsx lines 977–1053 — verified):
```typescript
{layers.map((layer) => {
  // Skip child rows — they render inside their group container
  if (getParentGroupId(layer)) return null;

  if (isFolderGroupLayer(layer)) {
    // ... folder group + children
  }

  // Loose layer — one SortableStackRow per MapLayerResponse, no synthesis
  return (
    <SortableStackRow
      key={layer.id}
      layer={layer}
      ...
    />
  );
})}
```

**Why three rows appear** — `isDemTerrainVisualSuppressed` (`map-sync.ts:52-58`) only suppresses the terrain layer from MapLibre rendering; it does NOT suppress the terrain-mode DEM layer from the `layers.map` render in `UnifiedStackPanel`. All three `MapLayerResponse` records (two hillshade + one terrain-mode) appear in `layers` and get a `SortableStackRow`.

**StackRow glyph logic for DEM** (StackRow.tsx lines 70–77 — verified):
```typescript
const isDEM = layer.is_dem === true;
const renderMode = (layer.style_config as Record<string, unknown> | null | undefined)?.render_mode;
let glyph = '▦';
if (isDEM) {
  if (renderMode === 'hillshade') glyph = '⛰';
  else if (renderMode === 'terrain') glyph = '◬';
  // else image → ▦ (default)
}
```

**`isDemTerrainVisualSuppressed` function** (`map-sync.ts:52-58` — verified):
```typescript
export function isDemTerrainVisualSuppressed(layer: {
  is_dem?: boolean | null;
  style_config?: Pick<StyleConfig, 'render_mode'> | null;
}) {
  return layer.is_dem === true
    && (layer.style_config as { render_mode?: unknown } | null | undefined)?.render_mode === 'terrain';
}
```
This is exported from `map-sync.ts` and can be imported by `UnifiedStackPanel.tsx` to filter terrain-mode rows from the stack, matching the approach in `map-sync.ts:919-921`.

**`MapStackDuplicateMetadata` logic** — dead in live UI path but usable for row labeling (`map-stack.ts:299-337`). The `duplicateIndex` function returns `disambiguationLabel: 'Copy N of M'` when `Math.max(datasetCount, nameCount) > 1`. If the planner wants to surface "Copy N of M" badges directly in `UnifiedStackPanel`, the `duplicateIndex` function can be extracted and called on `layers` to build a `Map<layerId, MapStackDuplicateMetadata>`, then passed into `SortableStackRow`/`StackRow` as a prop. The badge value is `metadata.duplicate.disambiguationLabel`.

**Confirmed: `buildMapStack` is dead in live UI** — only referenced in comments of `normalize-saved-map.ts` and in `__tests__/map-stack.test.ts`. Do NOT wire fixes through it.

---

### BLDR-04 — `syncColorReliefLayer` in `color-relief-sync.ts`

**File:** `frontend/src/components/builder/color-relief-sync.ts`
**Analog (visibility pattern):** `frontend/src/components/builder/layer-adapters/hillshade-adapter.ts` — passes `input.visible` to `addLayers` and asserts it in `syncPaint`

**Current `syncColorReliefLayer`** (lines 66–113 — verified, full file is 113 lines):
```typescript
export function syncColorReliefLayer(
  map: MaplibreMap,
  input: AdapterLayerInput,
): void {
  const reliefLayerId = `${input.layerId}-colorrelief`;

  const renderMode = (input.style_config as Record<string, unknown> | null | undefined)?.render_mode;
  const isHillshade = renderMode === 'hillshade';
  const enabled = input.paint['_hypso-enabled'] === true && isHillshade;

  if (!enabled) {
    if (map.getLayer(reliefLayerId)) {
      map.removeLayer(reliefLayerId);
    }
    return;
  }

  if (!map.getSource(input.sourceId)) return;

  const rampName =
    typeof input.paint['_hypso-ramp'] === 'string'
      ? (input.paint['_hypso-ramp'] as string)
      : 'Viridis';

  // Always recreate (remove then add) — color-relief-color is a ColorRampProperty
  if (map.getLayer(reliefLayerId)) {
    map.removeLayer(reliefLayerId);
  }

  map.addLayer(
    {
      id: reliefLayerId,
      type: 'color-relief' as unknown as 'hillshade',
      source: input.sourceId,
      paint: {
        'color-relief-color': buildElevationExpression(rampName),
        'color-relief-opacity': 0.7,
      },
    } as unknown as import('maplibre-gl').AddLayerObject,
    input.layerId,   // Insert BELOW hillshade
  );
}
```

**Bug:** `addLayer` call has no `layout` field → visibility defaults to `'visible'` regardless of `input.visible`. No sync path re-asserts visibility on subsequent calls either (`syncColorReliefLayer` is always remove+add, but even on add it ignores `visible`).

**`AdapterLayerInput.visible`** (`types.ts:23` — verified):
```typescript
export interface AdapterLayerInput {
  id: string;
  ...
  visible: boolean;   // line 23
  ...
}
```

**Call site** (`map-sync.ts:931-958` — verified):
```typescript
const adapterInput: AdapterLayerInput & { style_config?: StyleConfig | null } = {
  ...
  visible: layer.visible,   // line 936 — already populated
  ...
};
...
if (adapterInput.is_dem === true) {
  syncColorReliefLayer(map, adapterInput);   // passes full adapterInput
}
```

**No signature change needed** — `input.visible` is already in scope inside `syncColorReliefLayer`. The fix is to add `layout: { visibility: input.visible ? 'visible' : 'none' }` to the `addLayer` call:

```typescript
// MODIFIED addLayer block in syncColorReliefLayer:
map.addLayer(
  {
    id: reliefLayerId,
    type: 'color-relief' as unknown as 'hillshade',
    source: input.sourceId,
    layout: { visibility: input.visible ? 'visible' : 'none' },   // ADD THIS
    paint: {
      'color-relief-color': buildElevationExpression(rampName),
      'color-relief-opacity': 0.7,
    },
  } as unknown as import('maplibre-gl').AddLayerObject,
  input.layerId,
);
```

Because `syncColorReliefLayer` always does remove+add (Pitfall 1), this single change covers both the initial add and all subsequent syncs.

---

## Shared Patterns

### MapLibre mock recipe for unit tests
**Source:** `frontend/src/components/builder/__tests__/color-relief-sync.test.ts:8-27`
**Apply to:** new BLDR-02 terrain test + new BLDR-04 visibility extension test

```typescript
function createMockMap() {
  const layers = new Map<string, { id: string }>();
  const sources = new Set<string>();

  return {
    _layers: layers,
    _sources: sources,
    getLayer: vi.fn((id: string) => layers.get(id) ?? null),
    addLayer: vi.fn((layer: { id: string }) => { layers.set(layer.id, layer); }),
    removeLayer: vi.fn((id: string) => { layers.delete(id); }),
    getSource: vi.fn((id: string) => (sources.has(id) ? { type: 'raster-dem' } : null)),
    setTerrain: vi.fn(),
    setLayoutProperty: vi.fn(),
    getTerrain: vi.fn(() => null),
  };
}
```

Variant for `reorderBasemapAboveData` (already in `UnifiedStackPanel.basemap-drag.test.tsx:268-277`):
```typescript
function makeMockMap(
  layers: Array<{ id: string; source?: string; type?: string; layout?: Record<string, unknown> }>,
): MaplibreMap {
  const moveLayer = vi.fn();
  return {
    moveLayer,
    getLayer: (id: string) => layers.some((l) => l.id === id) ? { id } : undefined,
    getStyle: () => ({ layers }),
  } as unknown as MaplibreMap;
}
```

### `AdapterLayerInput` test fixture shape
**Source:** `frontend/src/components/builder/__tests__/color-relief-sync.test.ts:29-52`
**Apply to:** BLDR-04 visibility test extension

```typescript
function makeInput(
  overrides: Partial<AdapterLayerInput> & {
    paint?: Record<string, unknown>;
    style_config?: Record<string, unknown> | null;
  } = {},
): AdapterLayerInput {
  return {
    id: 'dem-1',
    dataset_table_name: 'dem_table',
    dataset_geometry_type: null,
    opacity: 1,
    visible: true,     // <-- toggle this to test BLDR-04
    paint: {},
    layout: {},
    filter: null,
    is_dem: true,
    sourceId: 'source-dem-1',
    layerId: 'layer-dem-1',
    sourceLayer: '',
    tileUrl: '',
    style_config: { render_mode: 'hillshade' },
    ...overrides,
  } as AdapterLayerInput;
}
```

### React component map mock (for BLDR-02 terrain test)
**Source:** `frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx:89-147`
**Apply to:** any new BuilderMap integration test for `applyTerrainConfig`

The `vi.hoisted` + `fakeMap` + `handlers.emit` pattern is the established way to drive `map.once('idle', ...)` callbacks in BuilderMap tests. The mock includes `setTerrain: vi.fn()` (line 112) and `isStyleLoaded: vi.fn(() => true)` (line 110). `@vis.gl/react-maplibre` is mocked to fire `onLoad({ target: fakeMap })` synchronously in a `useEffect`.

### `terrainLayerKey` extend pattern
**Source:** `frontend/src/components/builder/BuilderMap.tsx:413-418`
The key already computes per-layer identity as `dataset_id:is_dem:dataset_record_type:render_mode`. Extending it with `:visible` is additive and does not affect the existing terrain-enable/disable re-trigger behavior (those deps are still governed by `terrainConfig?.enabled` at line 908).

---

## Test Pin Locations

| Bug | Test file | Existing tests present | New test to add |
|---|---|---|---|
| BLDR-01 | `UnifiedStackPanel.basemap-drag.test.tsx` | Tests 7–14 cover vector basemap `moveLayer` skip and position DOM order | Add Test 15: raster basemap layer (`type: 'raster'`, non-data source) is NOT lifted by `reorderBasemapAboveData` at `position='top'` |
| BLDR-02 | `BuilderMap.unit.test.ts` or `BuilderMap.a11y.test.tsx` | `BuilderMap.unit.test.ts` tests `ensureRasterDemTerrainSource`/`setTerrain(null)` (helper level); `a11y.test.tsx` tests `setTerrain` being called with correct args | Add tests: (a) `setTerrain(null)` when `demLayer.visible === false`; (b) terrain re-attaches when `demLayer.visible` flips back to `true` |
| BLDR-03 | `UnifiedStackPanel.test.tsx` or a new `UnifiedStackPanel.dem-rows.test.tsx` | No existing DEM-row count test | Add test: terrain-mode DEM layer (`is_dem: true`, `render_mode: 'terrain'`) is suppressed from the stack render; only hillshade DEM layers render rows |
| BLDR-04 | `color-relief-sync.test.ts` | Tests 1–13 cover add/remove/ramp — none assert `layout.visibility` | Add test: `addLayer` call includes `layout.visibility: 'none'` when `input.visible === false`; `layout.visibility: 'visible'` when `input.visible === true` |

---

## Build & Test Recipe

From `frontend/`:
1. `npm run typecheck` — must reach 0 errors before any commit
2. `npm test` (vitest) — runs all unit specs including the four test files above
3. `npm run test:e2e -- e2e/builder*.spec.ts` — `e2e:smoke:builder` subset for regression gate
4. Live verification is the Phase 1160 Playwright MCP close-gate (orchestrator-only, not executor)

---

## No Analog Found

None — all four fixes have clear analogs in the existing codebase.

---

## Metadata

**Analog search scope:** `frontend/src/components/builder/`, `frontend/src/components/builder/__tests__/`, `frontend/src/lib/basemap-utils.ts`, `frontend/src/components/builder/layer-adapters/types.ts`
**Files scanned:** 12
**Pattern extraction date:** 2026-05-30

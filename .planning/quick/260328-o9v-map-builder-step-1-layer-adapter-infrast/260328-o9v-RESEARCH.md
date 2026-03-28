# Map Builder Step 1: Layer Adapter Infrastructure - Research

**Researched:** 2026-03-28
**Domain:** MapLibre GL layer dispatch refactor (fill, line, circle, raster)
**Confidence:** HIGH

## Summary

The `syncLayersToMap` function in `map-sync.ts` (lines 133-459) contains a large if/else-if/else cascade that dispatches on geometry type to produce different MapLibre `addLayer` calls for circle, line, fill, and raster layers. Six handler functions in `use-builder-layers.ts` duplicate portions of this dispatch by making direct MapLibre imperative calls with hardcoded companion layer IDs (`-outline`, `-label`). A parallel classifier already exists in `layer-capabilities.ts` that maps the same inputs to a `LayerCapabilities` object.

The refactor extracts the per-type `addLayer` + `syncPaint` logic into adapter objects keyed by `'fill' | 'line' | 'circle' | 'raster'`, each implementing a common interface. The dispatch in `syncLayersToMap` becomes a single `adapter.addLayers(map, input)` call, and the handlers in `use-builder-layers.ts` call `adapter.syncPaint(map, input)` instead of branching manually.

**Primary recommendation:** Create `frontend/src/components/builder/layer-adapters/` with one adapter per type plus a shared interface, then rewire `syncLayersToMap` and the six `use-builder-layers.ts` handlers to dispatch through adapters.

## Architecture: Current Code Map

### map-sync.ts -- Function Catalog

| Function | Lines | Purpose | Stays / Moves |
|----------|-------|---------|---------------|
| `CUSTOM_PAINT_PROPS` | 9-14 | Set of non-MapLibre custom paint keys | STAYS (shared constant) |
| `reorderBasemapLabels` | 17-33 | Move/hide basemap symbols above data | STAYS |
| `getSourceId` | 35-37 | `source-${id}` | STAYS |
| `getLayerId` | 39-41 | `layer-${id}` | STAYS |
| `getOutlineLayerId` | 43-45 | `layer-${id}-outline` | STAYS |
| `getLabelLayerId` | 47-49 | `layer-${id}-label` | STAYS |
| `getLayerType` | 51-56 | Geometry string -> `circle\|line\|fill` | STAYS (or re-export from adapters) |
| `simplifyPaint` | 64-83 | Strip expression arrays to scalar fallbacks | MOVES to shared adapter util |
| `OPACITY_DEFAULTS` | 85-89 | fill=0.3, line=1, circle=1 | MOVES to shared adapter util |
| `getCompoundOpacity` | 91-99 | `propOpacity * masterOpacity` | MOVES to shared adapter util |
| `stripCustomProps` | 102-104 | Remove `CUSTOM_PAINT_PROPS` from paint dict | MOVES to shared adapter util |
| `replayExpressions` | 107-114 | Re-apply array expressions via `setPaintProperty` | MOVES to shared adapter util |
| `finalizeLayer` | 117-130 | Replay + opacity + filter after addLayer | MOVES to shared adapter util |
| `syncLayersToMap` | 133-459 | Main dispatch -- **the big function** | STAYS but dispatch body replaced by adapter calls |
| `reorderDataLayers` | 465-479 | z-order sync | STAYS |

### syncLayersToMap -- Dispatch Branches (Lines 144-371)

**Raster branch** (lines 152-185): Completely self-contained. Reads `token.tile_url`, `token.tile_size`, `token.minzoom`, `token.maxzoom`, `layer.opacity`, `layer.visible`. No paint/layout/filter/label handling. Update path syncs `raster-opacity` and `visibility`.

**Vector branches** (lines 187-371): All share:
1. `buildSignedTileUrl` for source URL (line 187)
2. Source creation with `type: 'vector'` (lines 192-198)
3. `getLayerType()` dispatch (line 200)
4. `rawPaint` extraction and `hasExpressions` check (lines 201-207)

Then diverge into:

**Circle** (lines 209-229): `simplifyPaint` -> `stripCustomProps` -> `addLayer(type: 'circle')` with default paint `{circle-radius: 5, circle-color, circle-stroke-color, circle-stroke-width}` -> `finalizeLayer`.

**Line** (lines 230-259): Same prep, plus extracts `line-dasharray` from layout (it's a paint property stored in layout JSON). Default paint: `{line-color, line-width: 2}`. Layout adds `line-cap: round, line-join: round`. -> `finalizeLayer`.

**Fill** (lines 260-309): Same prep, plus: reads `_stroke-disabled` custom prop, suppresses native outline with `fill-outline-color: transparent`. Default paint: `{fill-color, fill-opacity: 0.3}`. **Creates companion outline layer** (`outlineId`, type: 'line') with `_outline-color` / `_outline-width` custom props applied as `line-color` / `line-width`. Outline gets its own opacity and filter.

**Sync-existing path** (lines 311-371): When source already exists, iterates paint props via `setPaintProperty`, syncs compound opacity, syncs filter. Fill layers also sync outline layer's `line-color`, `line-width`, `line-opacity`, `fill-outline-color`, and filter.

**Label path** (lines 373-426): Shared across all vector types. Adds/updates/removes symbol layer based on `label_config`. Uses `getLayerType()` for `symbol-placement` (line vs point) and point offset.

**Visibility path** (lines 429-438): Sets `visibility` on main layer, outline layer, label layer.

### use-builder-layers.ts -- Six Handlers with Direct MapLibre Calls

| Handler | Lines | MapLibre Calls | Companion Layers Touched |
|---------|-------|----------------|--------------------------|
| `handleFilterChange` | 243-266 | `setFilter` on main, outline, label | `layer-{id}-outline`, `layer-{id}-label` |
| `handleLabelChange` | 268-340 | `addLayer` symbol, `setLayoutProperty`, `setPaintProperty`, `removeLayer` | `layer-{id}-label` (full add/update/remove) |
| `handleStyleConfigChange` | 342-387 | `setPaintProperty` per prop, custom props to outline | `layer-{id}-outline` |
| `handlePaintChange` | 389-436 | `setPaintProperty` per prop, `getCompoundOpacity`, custom props to outline | `layer-{id}-outline` |
| `handleOpacityChange` | 438-472 | `setPaintProperty` opacity (raster branch vs vector branch), outline `line-opacity` | `layer-{id}-outline` |
| `handleLayoutChange` | 555-594 | `setLayoutProperty`/`setPaintProperty` (line-dasharray quirk), clear removed props | none |

### layer-capabilities.ts -- Parallel Classifier

Already maps `(layer_type, dataset_record_type, dataset_geometry_type)` -> `LayerCapabilities { kind, mapLayerType, supportsStyleEditor, ... }`. This is used by UI components but NOT by `map-sync.ts` or `use-builder-layers.ts`. The adapter registry should align with `mapLayerType` from this classifier.

## Architecture: Target Adapter Interface

### Recommended File Structure

```
frontend/src/components/builder/layer-adapters/
  types.ts          # AdapterLayerInput, LayerAdapter interface
  fill-adapter.ts   # fill + outline companion
  line-adapter.ts   # line (with dasharray quirk)
  circle-adapter.ts # circle (point data)
  raster-adapter.ts # raster tiles (no paint/filter/label)
  registry.ts       # Record<string, LayerAdapter> lookup
  shared.ts         # simplifyPaint, stripCustomProps, replayExpressions, finalizeLayer, getCompoundOpacity, OPACITY_DEFAULTS
  index.ts          # barrel export
```

### AdapterLayerInput Type

Cross-referencing every field read by `syncLayersToMap` from `MapLayerResponse` and `TileToken`:

```typescript
export interface AdapterLayerInput {
  // From MapLayerResponse
  id: string;                            // used for source/layer/outline/label IDs
  dataset_table_name: string;            // used for source-layer = `data.${table}`
  dataset_geometry_type: string | null;  // used by getLayerType (fill adapter needs it for label placement)
  opacity: number;                       // master opacity
  visible: boolean;                      // visibility toggle
  paint: Record<string, unknown>;        // raw paint JSON from API
  layout: Record<string, unknown>;       // raw layout JSON from API
  filter: FilterSpecification | null;    // filter expression
  label_config?: LabelConfig | null;     // label settings

  // Computed/derived
  sourceId: string;                      // `source-${id}`
  layerId: string;                       // `layer-${id}`
  sourceLayer: string;                   // `data.${dataset_table_name}`

  // For raster only (from TileToken)
  tileUrl: string;                       // resolved tile URL (vector) or token.tile_url (raster)
  tileSize?: number;                     // raster tile_size
  minzoom?: number;                      // raster source minzoom
  maxzoom?: number;                      // raster source maxzoom
}
```

### LayerAdapter Interface

```typescript
export interface LayerAdapter {
  /** Geometry/layer type this adapter handles */
  type: 'fill' | 'line' | 'circle' | 'raster';

  /** Add source + layer(s) to a fresh map. Called when source doesn't exist yet. */
  addLayers(map: MaplibreMap, input: AdapterLayerInput): void;

  /** Sync paint/filter/opacity to an existing layer. Called when source already exists. */
  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void;

  /** Set opacity (may differ for raster vs vector compound opacity). */
  syncOpacity(map: MaplibreMap, input: AdapterLayerInput): void;

  /** Set visibility on all owned layers (main + companions). */
  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void;

  /** Return all MapLibre layer IDs this adapter manages (for cleanup). */
  getLayerIds(layerId: string): string[];
}
```

Key design points:
- Fill adapter's `getLayerIds` returns `[layerId, outlineId]` -- two layers
- Circle and line return `[layerId]` -- one layer
- Raster returns `[layerId]` -- one layer, no filter/label support
- Label layer is handled separately (shared across all vector types) or as a mixin

### Extraction Boundaries

**Code that MOVES into adapters:**

| From | To | What |
|------|----|------|
| `syncLayersToMap` lines 152-185 | `raster-adapter.ts` | Raster addLayer + sync existing |
| `syncLayersToMap` lines 209-229 | `circle-adapter.ts` | Circle addLayer |
| `syncLayersToMap` lines 230-259 | `line-adapter.ts` | Line addLayer (with dasharray) |
| `syncLayersToMap` lines 260-309 | `fill-adapter.ts` | Fill addLayer + outline companion |
| `syncLayersToMap` lines 311-371 | Each adapter's `syncPaint` | Existing-source sync path |
| `simplifyPaint`, `stripCustomProps`, `replayExpressions`, `finalizeLayer`, `getCompoundOpacity`, `OPACITY_DEFAULTS` | `shared.ts` | Shared utility functions |

**Code that STAYS in map-sync.ts:**

| Lines | What | Why |
|-------|------|-----|
| 9-14 | `CUSTOM_PAINT_PROPS` | Referenced by use-builder-layers.ts handlers (import unchanged) |
| 17-56 | ID helpers + `reorderBasemapLabels` + `getLayerType` | Used by BuilderMap.tsx, ViewerMap.tsx |
| 133-143, 440-459 | Source set management + stale cleanup loop | Orchestration logic, not type-specific |
| 373-426 | Label layer management | Shared across all vector types (not type-dispatched) |
| 429-438 | Visibility sync | Calls adapter's `syncVisibility` or stays inline |
| 465-479 | `reorderDataLayers` | Not type-specific |

**Code that changes in use-builder-layers.ts:**

The six handlers currently duplicate type-dispatch logic. After refactor, they import the adapter registry and call:
```typescript
const adapter = getAdapter(getLayerType(layer.dataset_geometry_type));
adapter.syncPaint(map, buildInput(layer));
```

## Common Pitfalls

### Pitfall 1: Fill Outline as Companion Layer
**What goes wrong:** Fill layers create a companion `-outline` line layer. Forgetting to propagate filter, opacity, and visibility to the outline breaks the visual.
**How to avoid:** The fill adapter's `getLayerIds` must return both IDs. Every `syncPaint`, `syncOpacity`, `syncVisibility` call must operate on both.

### Pitfall 2: line-dasharray Stored in layout JSON
**What goes wrong:** `line-dasharray` is a MapLibre paint property but the codebase stores it in the `layout` JSON field. The line adapter must extract it from layout and apply via `setPaintProperty`, not `setLayoutProperty`.
**Where:** map-sync.ts line 233-241, use-builder-layers.ts lines 570-575.

### Pitfall 3: Custom Paint Props Leaking to MapLibre
**What goes wrong:** `_outline-color`, `_outline-width`, `_fill-disabled`, `_stroke-disabled` etc. are stored in the paint JSON but are NOT valid MapLibre properties. Passing them to `addLayer` crashes.
**How to avoid:** `stripCustomProps` must be called before every `addLayer`. Adapters must handle custom props explicitly in their own logic.

### Pitfall 4: Expression Replay Pattern
**What goes wrong:** MapLibre's `addLayer` sometimes fails with data-driven style expressions on certain versions. The codebase works around this by adding layers with simplified scalar paint, then replaying expressions via `setPaintProperty`.
**How to avoid:** Keep `simplifyPaint` + `replayExpressions` + `finalizeLayer` in `shared.ts` and call them from each vector adapter's `addLayers`.

### Pitfall 5: Raster Branch Has No Paint/Filter/Label
**What goes wrong:** Raster layers do not support paint customization, filter expressions, or labels. If the adapter interface requires these, raster adapter must no-op gracefully.
**How to avoid:** `syncPaint` for raster is a no-op (or only handles `raster-opacity`). Label handling remains in the shared vector-only label path.

### Pitfall 6: ViewerMap.tsx Has Parallel Duplication
**What goes wrong:** `ViewerMap.tsx` (lines 260-340+) has its own copy of the same dispatch logic with slightly different ID schemes (`getSourceId(sort_order)` vs `getSourceId(id)`). This refactor targets map-sync.ts only; ViewerMap consolidation is a separate step.
**How to avoid:** Design adapters generically enough that ViewerMap can adopt them later, but do NOT refactor ViewerMap in this step.

## Test Patterns

### Existing Test Infrastructure

- **Framework:** Vitest with jsdom environment
- **Config:** `frontend/vite.config.ts` test section (globals: true, setupFiles: `./src/test/setup.ts`)
- **Run command:** `cd frontend && npx vitest run src/components/builder/__tests__/map-sync.raster.test.ts`
- **Mock factory:** `createMockMap()` in test file returns typed mock of MaplibreMap with all needed methods
- **Layer factory:** `makeLayer()` returns full `MapLayerResponse` with overrides pattern
- **Token factories:** `makeRasterToken()`, `makeVectorToken()` for tile token mocks
- **Mock pattern:** `vi.mock('@/lib/tile-utils')` for buildSignedTileUrl

### New Tests Needed

For each adapter, test:
1. `addLayers` produces correct `addSource` + `addLayer` calls with expected type and paint
2. `addLayers` handles expression replay (hasExpressions = true path)
3. `syncPaint` updates paint properties on existing layer
4. `syncOpacity` calculates compound opacity correctly
5. `getLayerIds` returns the right set of companion IDs
6. Fill-specific: outline companion creation, `_outline-color`/`_outline-width` propagation, `_stroke-disabled` suppression
7. Line-specific: `line-dasharray` extraction from layout
8. Raster-specific: no-op on paint/filter/label, opacity-only sync

Recommended test file: `frontend/src/components/builder/__tests__/layer-adapters.test.ts`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Layer type classification | New branching in adapters | `getLayerType()` already exists, `getLayerCapabilities()` for UI |
| Mock MapLibre map | Custom mock object | Existing `createMockMap()` factory from tests |
| Paint prop filtering | Manual key checks | Existing `CUSTOM_PAINT_PROPS` Set + `stripCustomProps()` |

## External Consumers to Verify

After refactor, these files must still work (they import from `map-sync.ts`):

| File | Imports Used |
|------|-------------|
| `BuilderMap.tsx` | `syncLayersToMap`, `reorderDataLayers`, `reorderBasemapLabels`, `getSourceId`, `getLayerId`, `getOutlineLayerId`, `getLabelLayerId` |
| `use-builder-layers.ts` | `getLayerType`, `getCompoundOpacity`, `CUSTOM_PAINT_PROPS` |
| `ViewerMap.tsx` | `getLayerType`, `stripCustomProps` |
| `LayerStyleEditor.tsx` | `getLayerType` |

All existing exports from `map-sync.ts` must remain available. Functions moved to `shared.ts` should be re-exported from `map-sync.ts` for backward compatibility, or imports updated in consuming files.

## Sources

### Primary (HIGH confidence)
- Direct code reading of `frontend/src/components/builder/map-sync.ts` (480 lines)
- Direct code reading of `frontend/src/hooks/use-builder-layers.ts` (635 lines)
- Direct code reading of `frontend/src/lib/layer-capabilities.ts` (64 lines)
- Direct code reading of `frontend/src/components/builder/__tests__/map-sync.raster.test.ts` (411 lines)
- Direct code reading of `frontend/src/components/builder/BuilderMap.tsx` (260 lines examined)
- Direct code reading of `frontend/src/components/viewer/ViewerMap.tsx` (260-340 lines examined)

## Metadata

**Confidence breakdown:**
- Architecture patterns: HIGH - based entirely on reading the actual source code
- Extraction boundaries: HIGH - line-by-line analysis of dispatch branches
- Pitfalls: HIGH - identified from actual code quirks (dasharray, custom props, expression replay)

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (code-level analysis, stable as long as map-sync.ts unchanged)

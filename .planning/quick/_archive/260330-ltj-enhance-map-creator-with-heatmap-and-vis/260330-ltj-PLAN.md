---
phase: 260330-ltj
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/layer-adapters/types.ts
  - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
  - frontend/src/components/builder/layer-adapters/registry.ts
  - frontend/src/components/builder/layer-adapters/index.ts
  - frontend/src/components/builder/layer-adapters/shared.ts
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/viewer/ViewerMap.tsx
  - frontend/src/components/builder/HeatmapStyleControls.tsx
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/hooks/use-builder-layers.ts
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
autonomous: false
requirements: []

must_haves:
  truths:
    - "Point layers show a 'Render as' dropdown with Points and Heatmap options"
    - "Selecting Heatmap renders the layer as a MapLibre heatmap layer on the map"
    - "Heatmap controls (weight column, color ramp, radius, intensity) are shown when in heatmap mode"
    - "Switching back to Points restores point style controls and previous circle paint"
    - "Heatmaps render correctly in the shared/public ViewerMap"
    - "Non-point layers (line, polygon) do not show the Render as dropdown"
  artifacts:
    - path: "frontend/src/components/builder/layer-adapters/heatmap-adapter.ts"
      provides: "Heatmap layer adapter following LayerAdapter interface"
      exports: ["heatmapAdapter"]
    - path: "frontend/src/components/builder/HeatmapStyleControls.tsx"
      provides: "Heatmap-specific UI controls (weight, ramp, radius, intensity)"
      exports: ["HeatmapStyleControls"]
    - path: "frontend/src/components/builder/layer-adapters/types.ts"
      provides: "LayerAdapter type union extended with 'heatmap'"
      contains: "'heatmap'"
  key_links:
    - from: "frontend/src/components/builder/LayerStyleEditor.tsx"
      to: "frontend/src/components/builder/HeatmapStyleControls.tsx"
      via: "conditional render when render_mode === 'heatmap'"
      pattern: "render_mode.*heatmap"
    - from: "frontend/src/components/builder/map-sync.ts"
      to: "frontend/src/components/builder/layer-adapters/heatmap-adapter.ts"
      via: "resolveAdapterType checks style_config.render_mode"
      pattern: "resolveAdapterType"
    - from: "frontend/src/components/viewer/ViewerMap.tsx"
      to: "frontend/src/components/builder/layer-adapters/heatmap-adapter.ts"
      via: "resolveAdapterType used in viewer sync loop"
      pattern: "resolveAdapterType"
    - from: "frontend/src/hooks/use-builder-layers.ts"
      to: "frontend/src/components/builder/map-sync.ts"
      via: "handleRenderModeChange triggers layer remove + re-add"
      pattern: "handleRenderModeChange"
---

<objective>
Add heatmap visualization to the map builder, enabling point layers to render as MapLibre heatmap layers with configurable weight column, color ramp, radius, and intensity controls.

Purpose: Users need to visualize point density patterns (e.g., incident clusters, population density) without leaving the map builder. Heatmaps are a standard GIS visualization that the builder currently lacks.

Output: Heatmap adapter, style controls, render mode toggle, and viewer support -- all integrated into existing layer adapter architecture.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/builder/layer-adapters/types.ts
@frontend/src/components/builder/layer-adapters/registry.ts
@frontend/src/components/builder/layer-adapters/circle-adapter.ts
@frontend/src/components/builder/layer-adapters/shared.ts
@frontend/src/components/builder/layer-adapters/index.ts
@frontend/src/components/builder/map-sync.ts
@frontend/src/components/viewer/ViewerMap.tsx
@frontend/src/components/builder/LayerStyleEditor.tsx
@frontend/src/components/builder/DataDrivenStyleEditor.tsx
@frontend/src/components/builder/ColorRampPicker.tsx
@frontend/src/hooks/use-builder-layers.ts
@frontend/src/lib/color-ramps.ts
@frontend/src/types/api.ts

<interfaces>
<!-- Key types and contracts the executor needs. -->

From frontend/src/components/builder/layer-adapters/types.ts:
```typescript
export interface AdapterLayerInput {
  id: string;
  dataset_table_name: string;
  dataset_geometry_type: string | null;
  opacity: number;
  visible: boolean;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  filter: FilterSpecification | null;
  label_config?: LabelConfig | null;
  sourceId: string;
  layerId: string;
  sourceLayer: string;
  tileUrl: string;
  tileSize?: number;
  minzoom?: number;
  maxzoom?: number;
}

export interface LayerAdapter {
  type: 'fill' | 'line' | 'circle' | 'raster';  // Add 'heatmap' to this union
  addLayers(map: MaplibreMap, input: AdapterLayerInput): void;
  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void;
  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void;
  getLayerIds(layerId: string): string[];
}
```

From frontend/src/types/api.ts:
```typescript
export interface StyleConfig {
  mode: 'categorical' | 'graduated';
  column: string;
  ramp: string;
  classCount?: number;
  method?: 'equal_interval' | 'quantile';
  categories?: { value: string; color: string }[];
  breaks?: number[];
  colors?: string[];
  target?: 'color' | 'radius' | 'width';
  sizes?: number[];
  sizeRange?: [number, number];
}

export interface MapLayerResponse {
  // ... (style_config?: StyleConfig | null is the key field)
  // render_mode will be stored inside style_config as: style_config.render_mode
  dataset_column_info: { name: string; type: string }[] | null;
}
```

From frontend/src/lib/color-ramps.ts:
```typescript
export function getRampColors(rampName: string, count: number): string[];
export const SEQUENTIAL_RAMPS: readonly { name: string; label: string }[];
export const DIVERGING_RAMPS: readonly { name: string; label: string }[];
```

From frontend/src/components/builder/ColorRampPicker.tsx:
```typescript
interface ColorRampPickerProps {
  rampName: string;
  onChange: (name: string) => void;
  mode: 'categorical' | 'graduated';  // Use 'graduated' for heatmap
}
```

From frontend/src/components/builder/map-sync.ts:
```typescript
export function getLayerType(geometryType: string | null): 'circle' | 'line' | 'fill';
// Lines 103-104 resolve adapter: const type = getLayerType(...); const adapter = getAdapter(type);
// This is where resolveAdapterType() must be inserted.
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Heatmap adapter + adapter resolution with render_mode</name>
  <files>
    frontend/src/components/builder/layer-adapters/types.ts,
    frontend/src/components/builder/layer-adapters/heatmap-adapter.ts,
    frontend/src/components/builder/layer-adapters/registry.ts,
    frontend/src/components/builder/layer-adapters/index.ts,
    frontend/src/components/builder/layer-adapters/shared.ts,
    frontend/src/components/builder/map-sync.ts,
    frontend/src/components/viewer/ViewerMap.tsx
  </files>
  <action>
    **1. Extend LayerAdapter type union** in `types.ts`:
    Add `'heatmap'` to the `type` field union: `type: 'fill' | 'line' | 'circle' | 'raster' | 'heatmap'`.

    **2. Create `heatmap-adapter.ts`** following the `circle-adapter.ts` pattern exactly:

    ```typescript
    export const heatmapAdapter: LayerAdapter = {
      type: 'heatmap',
      addLayers(map, input) {
        // Extract heatmap-* props from input.paint, with sensible defaults:
        // - heatmap-radius: default 30 (or zoom interpolation expression)
        // - heatmap-weight: default 1
        // - heatmap-intensity: default 1
        // - heatmap-color: default YlOrRd ramp expression with transparent at density 0
        // - heatmap-opacity: default 0.8
        // Apply filter if present.
        // Do NOT call finalizeLayer (heatmap has no circle/fill/line opacity prop).
      },
      syncPaint(map, input) {
        // Use syncVectorPaint from shared.ts for heatmap-* properties.
        // Apply filter.
        // Skip CUSTOM_PAINT_PROPS (they don't apply to heatmap).
      },
      syncVisibility(map, input) {
        // Same pattern as circle-adapter: set 'visibility' layout property.
      },
      getLayerIds(layerId) {
        return [layerId]; // No companion layers
      },
    };
    ```

    Default heatmap-color expression (MUST have transparent at density 0):
    ```
    ['interpolate', ['linear'], ['heatmap-density'],
      0,   'rgba(0,0,0,0)',
      0.2, colors[1],  // from getRampColors('YlOrRd', 6)
      0.4, colors[2],
      0.6, colors[3],
      0.8, colors[4],
      1.0, colors[5],
    ]
    ```

    **3. Register in `registry.ts`**: Import `heatmapAdapter` and add `heatmap: heatmapAdapter` entry.

    **4. Re-export in `index.ts`**: Add `export { heatmapAdapter } from './heatmap-adapter';`

    **5. Add `resolveAdapterType` function** in `shared.ts`:
    ```typescript
    export function resolveAdapterType(
      geometryType: string | null,
      styleConfig?: { render_mode?: string } | null,
    ): string {
      if (
        styleConfig?.render_mode === 'heatmap' &&
        getLayerType(geometryType) === 'circle'
      ) {
        return 'heatmap';
      }
      return getLayerType(geometryType);
    }
    ```
    Export it from `shared.ts` and re-export from `map-sync.ts`.

    **6. Update `map-sync.ts` `syncLayersToMap`**:
    - Replace `const type = getLayerType(layer.dataset_geometry_type)` on line 103 with `const type = resolveAdapterType(layer.dataset_geometry_type, layer.style_config)`.
    - Do the same for the `syncPaint` branch (line 115 area).
    - Also for visibility sync (line 158): use `resolveAdapterType` instead of `getLayerType`.
    - When `render_mode === 'heatmap'`, hide any label layer for this layer (labels don't make sense on heatmaps). If `map.getLayer(labelId)` exists and render_mode is heatmap, set visibility to 'none'.

    **7. Update `ViewerMap.tsx`**:
    - Import `resolveAdapterType` from `map-sync`.
    - In the layer sync effect (~line 312-313), replace both `getLayerType(layer.geometry_type)` calls with `resolveAdapterType(layer.geometry_type, layer.style_config)`.
    - In the visibility toggle effect (~line 413), same replacement.
    - When `render_mode === 'heatmap'`, skip click/hover query for that layer (heatmap layers don't support queryRenderedFeatures in a meaningful way). Filter heatmap layers out of `queryLayers` in both click and mousemove handlers by checking `layers.find(l => l.sort_order === ...)?.style_config?.render_mode !== 'heatmap'`.

    **CRITICAL**: Do NOT attempt to change a MapLibre layer's type in-place. The render mode toggle (Task 2) handles remove+re-add. This task only ensures the correct adapter is selected based on `style_config.render_mode`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - heatmap-adapter.ts exists and follows LayerAdapter interface
    - LayerAdapter type union includes 'heatmap'
    - heatmapAdapter registered in registry
    - resolveAdapterType function exported from shared.ts and map-sync.ts
    - map-sync.ts uses resolveAdapterType for adapter selection
    - ViewerMap.tsx uses resolveAdapterType for adapter selection
    - TypeScript compiles without errors
  </done>
</task>

<task type="auto">
  <name>Task 2: Heatmap UI controls + render mode toggle with layer re-add</name>
  <files>
    frontend/src/components/builder/HeatmapStyleControls.tsx,
    frontend/src/components/builder/LayerStyleEditor.tsx,
    frontend/src/hooks/use-builder-layers.ts,
    frontend/src/i18n/locales/en/builder.json,
    frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
  </files>
  <action>
    **1. Create `HeatmapStyleControls.tsx`** -- a new component for heatmap-specific controls:

    Props:
    ```typescript
    interface HeatmapStyleControlsProps {
      layer: MapLayerResponse;
      onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
    }
    ```

    The component renders 4 controls (all read/write from `layer.paint`):

    a) **Weight column select**: Dropdown populated from `layer.dataset_column_info`, filtered to numeric types (`integer`, `numeric`, `real`, `double`, `float`, `bigint`, `smallint`, `int4`, `int8`, `int2`, `float4`, `float8`). "None" option = constant weight 1. When a column is selected, set `paint['heatmap-weight']` to `['get', columnName]` (simple get expression -- no min/max normalization needed for basic heatmaps). Store selected column name in a custom paint prop `paint['_heatmap-weight-column']` for UI state restoration.

    b) **Color ramp picker**: Reuse `ColorRampPicker` with `mode="graduated"`. On ramp change, build the `heatmap-color` interpolation expression using `getRampColors(rampName, 6)`:
    ```
    ['interpolate', ['linear'], ['heatmap-density'],
      0,   'rgba(0,0,0,0)',
      0.2, colors[1],
      0.4, colors[2],
      0.6, colors[3],
      0.8, colors[4],
      1.0, colors[5],
    ]
    ```
    Store ramp name in `paint['_heatmap-ramp']` for UI restoration. Default ramp: `'YlOrRd'`.

    c) **Radius slider**: Range 1-100, step 1, default 30. Maps to `paint['heatmap-radius']`. Use a simple scalar value (no zoom interpolation on the slider -- the adapter will apply zoom interpolation in addLayers when the value is a plain number).

    d) **Intensity slider**: Range 0.1-5.0, step 0.1, default 1. Maps to `paint['heatmap-intensity']`.

    Use the existing `SliderRow` helper pattern from LayerStyleEditor (copy the internal component or extract it). Use `useTranslation('builder')` with keys under `style.heatmap.*`.

    Add `_heatmap-ramp` and `_heatmap-weight-column` to `CUSTOM_PAINT_PROPS` set in `shared.ts` so they are stripped before MapLibre paint application.

    **2. Update `LayerStyleEditor.tsx`**:

    a) Add a "Render as" `<Select>` at the TOP of the component (before the `<DataDrivenStyleEditor>`), visible ONLY when `geomType === 'circle'`:
    ```tsx
    {geomType === 'circle' && (
      <div className="space-y-1">
        <div className="text-xs font-medium">{t('style.renderAs')}</div>
        <Select value={renderMode} onValueChange={handleRenderModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="points">{t('style.renderPoints')}</SelectItem>
            <SelectItem value="heatmap">{t('style.renderHeatmap')}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    )}
    ```

    Derive `renderMode` from: `(layer.style_config as any)?.render_mode || 'points'`.

    b) The `handleRenderModeChange` callback must be a NEW prop added to `LayerStyleEditorProps`:
    ```typescript
    onRenderModeChange: (layerId: string, mode: 'points' | 'heatmap') => void;
    ```

    c) When `renderMode === 'heatmap'`:
    - HIDE the `<DataDrivenStyleEditor>` (data-driven circle styles conflict with heatmap)
    - HIDE the circle point controls section (`geomType === 'circle'` block)
    - SHOW `<HeatmapStyleControls layer={layer} onPaintChange={onPaintChange} />`
    - Keep the master opacity slider and zoom range controls visible

    When `renderMode === 'points'`:
    - Show everything as before (existing behavior unchanged)

    **3. Add `handleRenderModeChange` to `use-builder-layers.ts`**:

    This is the critical function that handles the layer type switch. It must:
    1. Save current circle paint into `style_config.saved_circle_paint` when switching TO heatmap
    2. Build default heatmap paint (using `getRampColors('YlOrRd', 6)` for heatmap-color expression) when switching TO heatmap for the first time, or restore `style_config.heatmap_paint` if previously set
    3. Restore `style_config.saved_circle_paint` to `layer.paint` when switching BACK to points
    4. Update `style_config.render_mode` to the new mode
    5. **Remove the MapLibre layer and re-add** via the correct adapter (MapLibre does not support changing layer type in-place):
       ```typescript
       const map = mapInstanceRef.current;
       const mapLayerId = `layer-${layerId}`;
       const labelId = `layer-${layerId}-label`;
       // Remove old layer (keep source intact)
       if (map.getLayer(labelId)) map.removeLayer(labelId);
       if (map.getLayer(mapLayerId)) map.removeLayer(mapLayerId);
       // Re-add via adapter
       const newType = resolveAdapterType(layer.dataset_geometry_type, updatedStyleConfig);
       const adapter = getAdapter(newType);
       adapter.addLayers(map, adapterInput);
       // Re-add label layer if switching back to points and label_config exists
       if (mode === 'points' && layer.label_config?.column) { ... }
       ```
    6. Set `hasUnsavedChanges = true`

    Export `handleRenderModeChange` from the hook and wire it through `LayerInspector` -> `LayerStyleEditor`.

    **4. Wire `onRenderModeChange` through the component tree**:
    - `LayerInspector.tsx` receives `handleRenderModeChange` from the builder hook and passes it as `onRenderModeChange` to `LayerStyleEditor`.

    **5. Add i18n keys** to `frontend/src/i18n/locales/en/builder.json` under `"style"`:
    ```json
    "renderAs": "Render as",
    "renderPoints": "Points",
    "renderHeatmap": "Heatmap",
    "heatmap": {
      "weight": "Weight column",
      "weightNone": "None (equal weight)",
      "colorRamp": "Color ramp",
      "radius": "Radius",
      "intensity": "Intensity"
    }
    ```

    **6. Update tests** in `LayerStyleEditor.test.tsx`:
    - Add `onRenderModeChange` prop to all existing test renders (pass `vi.fn()`).
    - Add test: point layer renders "Render as" dropdown.
    - Add test: polygon layer does NOT render "Render as" dropdown.
    - Add test: when render mode is heatmap, heatmap controls are shown (mock `style_config` with `render_mode: 'heatmap'`).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30 && npx vitest run src/components/builder/__tests__/LayerStyleEditor.test.tsx --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>
    - "Render as" dropdown appears on point layers with Points/Heatmap options
    - Selecting Heatmap shows HeatmapStyleControls (weight, ramp, radius, intensity)
    - Selecting Heatmap hides circle controls and DataDrivenStyleEditor
    - Selecting Points restores circle controls
    - handleRenderModeChange removes MapLibre layer and re-adds via correct adapter
    - Paint state preserved when toggling between modes
    - All existing tests still pass
    - New tests pass for render mode dropdown visibility
    - TypeScript compiles without errors
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Visual verification of heatmap feature</name>
  <files>none</files>
  <action>
    Human verifies the complete heatmap feature. What was built: Heatmap visualization in the map builder with render mode toggle, heatmap rendering, style controls (weight, ramp, radius, intensity), state preservation across toggles, and viewer support.

    Steps to verify:
    1. Start the app: `docker compose up -d --build frontend`
    2. Open the map builder at http://localhost:8080 and add a point dataset as a layer
    3. In the Style tab, verify a "Render as" dropdown appears at the top with "Points" selected
    4. Switch to "Heatmap" -- verify:
       a. The map renders a heatmap (colored density blobs instead of individual points)
       b. Circle style controls disappear, replaced by: Weight column dropdown, Color ramp picker, Radius slider, Intensity slider
       c. Adjust radius slider (1-100) -- heatmap blobs grow/shrink
       d. Adjust intensity slider (0.1-5) -- heatmap density changes
       e. Change color ramp -- heatmap colors update
       f. Select a numeric weight column -- heatmap density shifts based on column values
    5. Switch back to "Points" -- verify:
       a. Circle/point rendering returns
       b. Original circle style controls reappear with previous values intact
    6. Switch back to "Heatmap" -- verify heatmap settings are preserved
    7. Save the map, then open it via a share link -- verify heatmap renders correctly in the viewer
    8. Verify: add a polygon or line layer -- no "Render as" dropdown should appear

    Resume signal: Type "approved" or describe issues to fix.
  </action>
  <verify>User visually confirms all 8 verification steps pass</verify>
  <done>User approves the heatmap feature as working correctly in both builder and viewer</done>
</task>

</tasks>

<verification>
- TypeScript compiles: `cd frontend && npx tsc --noEmit`
- Existing tests pass: `cd frontend && npx vitest run --reporter=verbose 2>&1 | tail -20`
- Heatmap adapter registered: `grep -n 'heatmap' frontend/src/components/builder/layer-adapters/registry.ts`
- resolveAdapterType used in both map-sync and ViewerMap: `grep -rn 'resolveAdapterType' frontend/src/components/builder/map-sync.ts frontend/src/components/viewer/ViewerMap.tsx`
</verification>

<success_criteria>
- Point layers can toggle between Points and Heatmap rendering via dropdown
- Heatmap renders using MapLibre native heatmap layer type with correct paint properties
- Four heatmap controls (weight, ramp, radius, intensity) function correctly
- State is preserved when toggling between render modes
- Heatmaps work in both builder and shared/public viewer
- Non-point layers are unaffected (no render mode dropdown)
- Zero backend changes required (render_mode stored in existing JSONB style_config)
</success_criteria>

<output>
After completion, create `.planning/quick/260330-ltj-enhance-map-creator-with-heatmap-and-vis/260330-ltj-SUMMARY.md`
</output>

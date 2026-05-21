---
phase: 260328-pax
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/widgets/builtin/MeasurementWidget.tsx
  - frontend/src/components/widgets/builtin/LegendWidget.tsx
  - frontend/src/components/widgets/register-widgets.ts
  - frontend/src/components/widgets/WidgetPanel.tsx
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/package.json
autonomous: true
requirements: [WIDGET-MEASURE, WIDGET-LEGEND]

must_haves:
  truths:
    - "User can activate measurement widget from toolbar, click on map to measure distance or area, and see results with unit toggle"
    - "User can activate legend widget from toolbar and see layer swatches reflecting current layer styles"
    - "Legend widget respects show_in_legend flag and shows categorical/graduated legends correctly"
    - "Measurement widget cleans up GeoJSON overlay and click listeners on close/unmount"
    - "Both widgets render inside WidgetPanel chrome with proper icons and labels"
  artifacts:
    - path: "frontend/src/components/widgets/builtin/MeasurementWidget.tsx"
      provides: "Distance/area measurement with map click interaction"
      min_lines: 80
    - path: "frontend/src/components/widgets/builtin/LegendWidget.tsx"
      provides: "Layer legend reading ctx.layers with categorical/graduated support"
      min_lines: 50
    - path: "frontend/src/components/widgets/register-widgets.ts"
      provides: "Registration of measurement (defaultVisible:false) and legend (defaultVisible:true)"
  key_links:
    - from: "frontend/src/components/widgets/builtin/MeasurementWidget.tsx"
      to: "ctx.mapInstance"
      via: "maplibre click handler + GeoJSON source/layer"
      pattern: "ctx\\.mapInstance"
    - from: "frontend/src/components/widgets/builtin/LegendWidget.tsx"
      to: "ctx.layers"
      via: "reads MapLayerResponse[] to render swatches"
      pattern: "ctx\\.layers"
    - from: "frontend/src/components/widgets/register-widgets.ts"
      to: "registry"
      via: "registerWidget calls for measurement + legend"
      pattern: "registerWidget.*measurement|registerWidget.*legend"
---

<objective>
Implement two real widgets for the map builder: Measurement (distance/area via @turf) and Legend (layer swatches from ctx.layers). Both use the existing widget infrastructure (registry, WidgetHost, WidgetPanel, WidgetToolbar). Remove the existing standalone MapLegend from MapBuilderPage since the Legend widget replaces it.

Purpose: Deliver the first two functional widgets that demonstrate the widget system's value. Measurement adds new map interaction capability; Legend consolidates existing legend rendering into the widget framework.
Output: Two widget components, updated registrations, i18n keys, @turf dependency installed.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/widgets/types.ts
@frontend/src/components/widgets/registry.ts
@frontend/src/components/widgets/register-widgets.ts
@frontend/src/components/widgets/WidgetHost.tsx
@frontend/src/components/widgets/WidgetPanel.tsx
@frontend/src/components/widgets/builtin/PlaceholderWidget.tsx
@frontend/src/components/map/MapLegend.tsx
@frontend/src/types/api.ts
@frontend/src/pages/MapBuilderPage.tsx
@frontend/src/i18n/locales/en/builder.json

<interfaces>
<!-- Key types the executor needs -->

From frontend/src/components/widgets/types.ts:
```typescript
export type WidgetSlot = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'sidebar-bottom' | 'map-overlay';

export interface WidgetContext {
  mapInstance: MaplibreMap | null;
  layers: MapLayerResponse[];
  mapId: string;
}

export interface WidgetDefinition {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  slot: WidgetSlot;
  component: React.ComponentType<{ ctx: WidgetContext }>;
  defaultVisible?: boolean;
}
```

From frontend/src/types/api.ts:
```typescript
export interface MapLayerResponse {
  id: string;
  dataset_name: string;
  dataset_geometry_type: string | null;
  display_name: string | null;
  visible: boolean;
  opacity: number;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
  style_config?: StyleConfig | null;
  layer_type?: string | null;
  show_in_legend?: boolean;
}

export interface StyleConfig {
  mode: 'categorical' | 'graduated';
  column: string;
  ramp: string;
  categories?: { value: string; color: string }[];
  breaks?: number[];
  colors?: string[];
}
```

From frontend/src/components/widgets/registry.ts:
```typescript
export function registerWidget(def: WidgetDefinition): void;
```

WidgetHost passes `ctx` to each widget component. Widgets render inside WidgetPanel chrome (header with icon/label/close button, scrollable body with max-h-64).

ctx is built in MapBuilderPage line 450:
```typescript
<WidgetHost ctx={{ mapInstance, layers: layers.localLayers, mapId: id! }} />
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Install @turf, create MeasurementWidget with distance/area modes</name>
  <files>
    frontend/package.json,
    frontend/src/components/widgets/builtin/MeasurementWidget.tsx,
    frontend/src/i18n/locales/en/builder.json,
    frontend/src/i18n/locales/es/builder.json,
    frontend/src/i18n/locales/fr/builder.json,
    frontend/src/i18n/locales/de/builder.json
  </files>
  <action>
    1. Install turf packages from `frontend/` directory:
       ```
       npm install @turf/distance @turf/area @turf/helpers
       ```

    2. Create `frontend/src/components/widgets/builtin/MeasurementWidget.tsx`:

       State:
       - `mode`: 'distance' | 'area' (toggle buttons)
       - `points`: LngLat[] (accumulated click coords)
       - `result`: number | null (computed measurement)
       - `unit`: 'metric' | 'imperial' (toggle)

       Behavior:
       - On mount (when ctx.mapInstance is available), add a GeoJSON source `_measure-src` and two layers:
         - `_measure-line` (line-string for distance, polygon outline for area) — `line-color: #3b82f6`, `line-width: 2`, `line-dasharray: [2, 1]`
         - `_measure-points` (circle layer for vertices) — `circle-radius: 5`, `circle-color: #3b82f6`, `circle-stroke-width: 2`, `circle-stroke-color: #fff`
       - Register a `click` handler on the map that appends point to `points[]`
       - On each click update:
         - For distance mode: compute cumulative distance using `@turf/distance` between consecutive pairs, summing segments. Display total.
         - For area mode: if >= 3 points, compute area using `@turf/area` on a polygon formed by closing the point ring. Display result.
       - Update the GeoJSON source data on every click to show the line/polygon and point markers.
       - Unit toggle: metric (m/km for distance, m2/km2 for area) vs imperial (ft/mi, ft2/mi2). Use 1000m threshold for km, 5280ft for mi; 1e6 m2 for km2, 27878400 ft2 for mi2.
       - "Clear" button resets points and result.
       - Change cursor to `crosshair` while widget is active.

       Cleanup (critical):
       - On unmount (useEffect cleanup) OR when widget is closed: remove the GeoJSON source and layers from the map, remove the click handler, restore cursor to default. Guard all removal with `map.getSource('_measure-src')` checks.

       UI layout (inside WidgetPanel body):
       - Mode toggle: two small buttons side by side (Ruler icon / Pentagon icon) with active highlight
       - Result display: large text showing measurement value + unit
       - Unit toggle: small "m/ft" text button
       - Clear button: text button "Clear" or trash icon
       - Instruction text when no points: "Click on map to measure"
       - All text via i18n `builder:widgets.measurement.*`

    3. Add i18n keys to all four locale files under a new `"widgets"` section at root level of builder.json:
       ```json
       "widgets": {
         "measurement": {
           "label": "Measure",
           "distance": "Distance",
           "area": "Area",
           "clear": "Clear",
           "clickToMeasure": "Click on map to measure",
           "metric": "Metric",
           "imperial": "Imperial"
         },
         "legend": {
           "label": "Legend",
           "noLayers": "No visible layers"
         },
         "closeWidget": "Close widget",
         "widgetError": "This widget encountered an error"
       }
       ```
       For es/fr/de files: translate the values appropriately. Keep keys identical.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>MeasurementWidget.tsx compiles, @turf packages in package.json, i18n keys present in all four locales</done>
</task>

<task type="auto">
  <name>Task 2: Create LegendWidget, register both widgets, remove standalone MapLegend</name>
  <files>
    frontend/src/components/widgets/builtin/LegendWidget.tsx,
    frontend/src/components/widgets/register-widgets.ts,
    frontend/src/pages/MapBuilderPage.tsx,
    frontend/src/components/widgets/WidgetPanel.tsx
  </files>
  <action>
    1. Create `frontend/src/components/widgets/builtin/LegendWidget.tsx`:

       Model the rendering logic on the existing `MapLegend.tsx` component (at `frontend/src/components/map/MapLegend.tsx`), but adapted to read from `ctx.layers` (which are `MapLayerResponse[]`).

       Behavior:
       - Filter `ctx.layers` to only visible layers where `show_in_legend !== false`
       - For each layer, determine display:
         a. If `style_config?.column` exists AND `style_config.mode === 'categorical'` AND `style_config.categories` exist:
            Show layer name as header, then list each category as a colored swatch (3x3 rounded-sm) + value label.
         b. If `style_config?.column` exists AND `style_config.mode === 'graduated'` AND `style_config.breaks` + `style_config.colors` exist:
            Show layer name as header, then list graduated stops: `< break[0]`, `break[i-1] - break[i]`, `>= break[last]` with corresponding color swatches.
         c. Otherwise (flat color): Use `ColorizedGeometryIcon` from `@/components/map/layer-icons` (import `ColorizedGeometryIcon`, `getLayerColors`, `extractStyleHints`) with the layer name beside it — same pattern as MapLegend.tsx lines 90-108.
       - Show empty state message when no eligible layers: `t('builder:widgets.legend.noLayers')`
       - Respect `opacity` on swatches via inline `style={{ opacity }}` when opacity < 1.
       - Respect stroke: read `paint['_outline-color']` and `paint['_stroke-disabled']` for swatch borders, same as existing MapLegend.

       Style: Use `text-xs` throughout, `space-y-0.5` for category lists, `truncate` on labels. Dividers between layers.

    2. Update `frontend/src/components/widgets/register-widgets.ts`:
       - Remove the placeholder widget registration entirely
       - Import and register MeasurementWidget:
         ```typescript
         import { Ruler } from 'lucide-react';
         import { MeasurementWidget } from './builtin/MeasurementWidget';
         registerWidget({
           id: 'measurement',
           label: 'Measure',
           icon: Ruler,
           slot: 'top-left',
           component: MeasurementWidget,
           defaultVisible: false,
         });
         ```
       - Import and register LegendWidget:
         ```typescript
         import { Layers } from 'lucide-react';
         import { LegendWidget } from './builtin/LegendWidget';
         registerWidget({
           id: 'legend',
           label: 'Legend',
           icon: Layers,
           slot: 'bottom-left',
           component: LegendWidget,
           defaultVisible: true,
         });
         ```

    3. Update `frontend/src/pages/MapBuilderPage.tsx`:
       - Remove the `import { MapLegend } from '@/components/map/MapLegend'` import
       - Remove the `legendLayers` const (lines ~213-223 that maps localLayers to legend format)
       - Remove the `<MapLegend layers={legendLayers} />` JSX (line ~448)
       The legend is now provided by the LegendWidget inside WidgetHost.

    4. Update `frontend/src/components/widgets/WidgetPanel.tsx`:
       - Increase `max-h-64` to `max-h-80` on the content div to give legend/measurement widgets more vertical room
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>LegendWidget renders layer swatches from ctx.layers; both widgets registered (measurement defaultVisible:false, legend defaultVisible:true); standalone MapLegend removed from MapBuilderPage; PlaceholderWidget registration removed; TypeScript compiles clean</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Measurement and Legend widgets integrated into the map builder widget system. Measurement provides distance/area calculation with map click interaction, GeoJSON overlay, and unit toggle. Legend displays layer swatches with categorical/graduated support, replacing the standalone MapLegend component.</what-built>
  <how-to-verify>
    1. Open http://localhost:8080 and navigate to a map with multiple styled layers
    2. Click the widget toolbar button (grid icon, top-right of map)
    3. Verify "Measure" and "Legend" appear in the widget picker (placeholder gone)
    4. Toggle Legend ON — verify it appears bottom-left with correct layer swatches
       - Layers with show_in_legend=false should be absent
       - Categorical layers show colored category swatches
       - Graduated layers show break range swatches
       - Flat-color layers show geometry icon + name
    5. Toggle Measurement ON — verify it appears top-left
       - Switch to "Distance" mode, click 2+ points on map — verify line overlay + distance result
       - Switch to "Area" mode, click 3+ points — verify polygon overlay + area result
       - Toggle metric/imperial — verify units change
       - Click "Clear" — verify overlay removed, result reset
    6. Close Measurement widget — verify GeoJSON overlay and crosshair cursor are cleaned up
    7. Verify Legend is visible by default on a new/fresh map load
    8. Verify Measurement is NOT visible by default
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<verification>
- `cd frontend && npx tsc --noEmit` — zero errors
- Both widget files exist in `frontend/src/components/widgets/builtin/`
- `register-widgets.ts` has two registrations (measurement + legend), no placeholder
- `MapBuilderPage.tsx` has no `MapLegend` import or usage
- i18n keys for `widgets.measurement.*` and `widgets.legend.*` present in all 4 locales
- `@turf/distance`, `@turf/area`, `@turf/helpers` in package.json dependencies
</verification>

<success_criteria>
- Measurement widget: click-to-measure with distance and area modes, GeoJSON overlay on map, unit toggle, full cleanup on unmount
- Legend widget: renders correct swatches for all layer style types (flat, categorical, graduated), respects show_in_legend and opacity
- Both widgets work through existing WidgetHost/WidgetPanel/WidgetToolbar infrastructure with no changes to those systems beyond max-height tweak
- Standalone MapLegend removed from MapBuilderPage (legend now provided by widget)
</success_criteria>

<output>
After completion, create `.planning/quick/260328-pax-map-builder-step-4-measurement-and-legen/260328-pax-SUMMARY.md`
</output>

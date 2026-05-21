---
phase: quick-260325-hrk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/map/layer-icons.tsx
  - frontend/src/components/map/MapLegend.tsx
  - frontend/src/components/builder/LayerItem.tsx
  - frontend/src/pages/MapBuilderPage.tsx
autonomous: true
requirements: [LEGEND-ICONS]

must_haves:
  truths:
    - "Line layers with dash patterns show dashed/dotted/dash-dot strokes in both layer list and legend icons"
    - "Line layers reflect relative width (thin/medium/thick) in legend icon"
    - "Polygon layers show two-tone fill+outline color in layer list and legend icons"
    - "Circle layers show border/stroke color ring in layer list and legend icons"
    - "Circle layers reflect relative radius (small/medium/large) in legend icon"
    - "Layer opacity is visually applied to icon colors in both layer list and legend"
  artifacts:
    - path: "frontend/src/components/map/layer-icons.tsx"
      provides: "Extended ColorizedGeometryIcon with style-aware rendering"
      exports: ["ColorizedGeometryIcon", "getLayerColors", "extractStyleHints"]
    - path: "frontend/src/components/map/MapLegend.tsx"
      provides: "Legend passing style hints to icon component"
    - path: "frontend/src/components/builder/LayerItem.tsx"
      provides: "Layer list item passing style hints to icon component"
    - path: "frontend/src/pages/MapBuilderPage.tsx"
      provides: "legendLayers mapping includes layout data"
  key_links:
    - from: "frontend/src/components/map/layer-icons.tsx"
      to: "ColorizedGeometryIcon callers"
      via: "extended props interface"
      pattern: "strokeColor|dashPattern|opacity|strokeWidth|radius"
    - from: "frontend/src/pages/MapBuilderPage.tsx"
      to: "frontend/src/components/map/MapLegend.tsx"
      via: "legendLayers with layout field"
      pattern: "layout.*l\\.layout"
---

<objective>
Enhance ColorizedGeometryIcon to reflect configured layer styles — dash patterns, line width, polygon outline color, circle stroke color, circle radius, and opacity — in both the layer list sidebar and the map legend.

Purpose: Layer icons currently show only the primary color. Users cannot visually distinguish a dashed red line from a solid red line, or a circle with a thick border from one without, by looking at the icon alone.

Output: Updated layer-icons.tsx with style-aware SVG rendering, plus wiring in LayerItem, MapLegend, and MapBuilderPage to pass the necessary style props through.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/map/layer-icons.tsx
@frontend/src/components/map/MapLegend.tsx
@frontend/src/components/builder/LayerItem.tsx
@frontend/src/pages/MapBuilderPage.tsx
@frontend/src/components/builder/LayerStyleEditor.tsx (for paint property names and defaults)
@frontend/src/components/builder/map-sync.ts (for _outline-* custom prop conventions)

<interfaces>
From layer-icons.tsx (current):
```typescript
export function ColorizedGeometryIcon({
  geometryType, colors, layerId, layerType
}: {
  geometryType: string | null;
  colors: string[];
  layerId: string;
  layerType?: string;
}) // renders Circle/Minus/Pentagon with color or gradient

export function getLayerColors(layer: Pick<MapLayerResponse, 'dataset_geometry_type' | 'paint' | 'style_config'>): string[]
```

From MapLegend.tsx:
```typescript
interface MapLegendLayer {
  name: string;
  styleConfig?: StyleConfig | null;
  visible: boolean;
  show_in_legend?: boolean;
  geometryType?: string | null;
  paint?: Record<string, unknown>;
  layerType?: string;
}
```

Paint property conventions (from LayerStyleEditor defaults):
- Polygon: fill-color, fill-opacity, _outline-color, _outline-width
- Line: line-color, line-width (layout: line-dasharray)
- Circle: circle-color, circle-radius, circle-stroke-color, circle-stroke-width

LINE_DASH_PRESETS: solid=undefined, dashed=[4,2], dotted=[1,2], dashDot=[4,2,1,2]
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Extend ColorizedGeometryIcon with style-aware rendering</name>
  <files>frontend/src/components/map/layer-icons.tsx</files>
  <action>
Add an optional `styleHints` prop to ColorizedGeometryIcon alongside existing props. The type:

```typescript
interface StyleHints {
  strokeColor?: string;      // polygon _outline-color or circle-stroke-color
  dashPattern?: number[];    // line-dasharray from layout (e.g., [4,2])
  opacity?: number;          // layer opacity (0-1)
  strokeWidth?: number;      // line-width raw value — map to SVG strokeWidth
  radius?: number;           // circle-radius raw value — map to SVG size hint
}
```

Also export a helper `extractStyleHints(paint, layout, geometryType): StyleHints` that reads from paint/layout objects:
- For lines: reads `line-width`, reads `line-dasharray` from layout (NOT paint — it is stored in layout in this codebase per map-sync.ts), maps raw dasharray values to SVG-friendly strokeDasharray (scale: multiply each value by 2 for the 14px icon)
- For polygons: reads `_outline-color` (custom prop per quick-260325-ff5 decision)
- For circles: reads `circle-stroke-color`, `circle-radius`
- For all: reads opacity from the layer (passed in directly, not from paint)

Rendering changes inside ColorizedGeometryIcon (all additive, do not break existing color/gradient logic):

1. **Line dash pattern**: When `styleHints.dashPattern` is set, render a custom SVG line element instead of the Lucide Minus icon. Draw a horizontal line with strokeDasharray. Scale dash values for the 14px icon space (multiply each by 1.5). Use the existing color/gradient fill logic for stroke color.

2. **Line width**: Map `styleHints.strokeWidth` to 3 tiers: <=1.5 thin (strokeWidth=2), 1.5-4 medium (strokeWidth=3, current default), >4 thick (strokeWidth=4.5).

3. **Polygon outline color**: When `styleHints.strokeColor` is set on a polygon, render the Pentagon with both fill (existing color) and stroke set to strokeColor with strokeWidth=1.5. For gradient fills, keep the gradient fill and add the stroke.

4. **Circle stroke color**: When `styleHints.strokeColor` is set on a point, render Circle with fill (existing color) and stroke set to strokeColor with strokeWidth=1.5.

5. **Circle radius**: Map `styleHints.radius` to icon size: <=3 use h-2.5 w-2.5 (small), 3-7 use h-3.5 w-3.5 (default), >7 use h-4.5 w-4.5 (large).

6. **Opacity**: Apply `style={{ opacity: styleHints.opacity }}` on the outermost element when opacity is defined and < 1.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>ColorizedGeometryIcon accepts optional styleHints and renders dash patterns, width hints, outline/stroke colors, radius hints, and opacity. extractStyleHints helper exported. No breaking changes to existing callers (styleHints is optional).</done>
</task>

<task type="auto">
  <name>Task 2: Wire style hints through LayerItem, MapLegend, and MapBuilderPage</name>
  <files>
    frontend/src/components/builder/LayerItem.tsx
    frontend/src/components/map/MapLegend.tsx
    frontend/src/pages/MapBuilderPage.tsx
  </files>
  <action>
**MapBuilderPage.tsx** — Add `layout` to the legendLayers mapping (line ~180):
```typescript
const legendLayers = layers.localLayers.map((l) => ({
  ...existing fields...,
  layout: l.layout,          // needed for line-dasharray
  opacity: l.opacity ?? 1,   // needed for opacity hint
}));
```

**MapLegend.tsx** — Update MapLegendLayer interface to include `layout` and `opacity`:
```typescript
interface MapLegendLayer {
  ...existing fields...
  layout?: Record<string, unknown>;
  opacity?: number;
}
```

In the flat-layer rendering path (the else branch at ~line 73 that renders ColorizedGeometryIcon), call extractStyleHints and pass result:
```typescript
import { ColorizedGeometryIcon, getLayerColors, extractStyleHints } from './layer-icons';

// In the flat-layer else branch:
const hints = extractStyleHints(
  layer.paint ?? {},
  layer.layout ?? {},
  layer.geometryType ?? null,
  layer.opacity,
);
<ColorizedGeometryIcon
  geometryType={layer.geometryType ?? null}
  colors={...existing...}
  layerId={`legend-${idx}`}
  layerType={layer.layerType}
  styleHints={hints}
/>
```

Also apply opacity to the categorical/graduated color squares: add `style={{ opacity: layer.opacity }}` on each color swatch div when opacity < 1.

**LayerItem.tsx** — After existing `const layerColors = getLayerColors(layer);` (line ~117), add:
```typescript
import { extractStyleHints } from '@/components/map/layer-icons';

const styleHints = extractStyleHints(
  layer.paint ?? {},
  (layer.layout as Record<string, unknown>) ?? {},
  layer.dataset_geometry_type,
  layer.opacity,
);
```

Pass `styleHints={styleHints}` to ColorizedGeometryIcon at ~line 151.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30 && npx vitest run --reporter=verbose frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx 2>&1 | tail -20</automated>
  </verify>
  <done>Style hints flow from layer data through MapBuilderPage legendLayers, into MapLegend and LayerItem, and reach ColorizedGeometryIcon. Existing tests still pass. Dash patterns, outline colors, stroke colors, radius, width, and opacity all visually reflected in both sidebar icons and legend icons.</done>
</task>

</tasks>

<verification>
- TypeScript compiles without errors: `npx tsc --noEmit --project frontend/tsconfig.json`
- Existing LayerStyleEditor tests pass: `npx vitest run frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx`
- Visual spot-check: build dev server shows icons reflecting configured styles in both layer list and legend
</verification>

<success_criteria>
- Line layers with dash patterns show dashed/dotted/dash-dot strokes in icons
- Line width reflected as thin/medium/thick stroke in icons
- Polygon icons show two-tone fill + outline color
- Circle icons show fill + stroke border color
- Circle radius reflected as small/medium/large icon size
- Opacity applied to all icon colors
- No regressions in existing color/gradient icon rendering
- TypeScript compiles cleanly
</success_criteria>

<output>
After completion, create `.planning/quick/260325-hrk-enhance-legend-and-layer-icons-to-reflec/260325-hrk-SUMMARY.md`
</output>

---
phase: quick-260324-kte
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/LayerItem.tsx
autonomous: false
requirements: [MERGE-INDICATORS]

must_haves:
  truths:
    - "Vector layer rows show a single colorized geometry icon instead of separate icon + color swatch"
    - "Single-color layers display a filled geometry icon in the layer paint color"
    - "Multi-color (categorical/graduated) layers display a gradient-filled geometry icon"
    - "Raster and VRT layers show their existing icons in muted gray with no color tinting"
  artifacts:
    - path: "frontend/src/components/builder/LayerItem.tsx"
      provides: "ColorizedGeometryIcon component and updated LayerItem layout"
      contains: "ColorizedGeometryIcon"
  key_links:
    - from: "ColorizedGeometryIcon"
      to: "getLayerColors()"
      via: "colors prop passed from LayerItem render"
      pattern: "getLayerColors.*layer"
---

<objective>
Merge the two separate layer list indicators (geometry type icon + color swatch) into a single colorized geometry icon in the map builder's LayerItem component.

Purpose: Reduce visual clutter in the layer list by combining redundant information into one compact indicator.
Output: Updated LayerItem.tsx with ColorizedGeometryIcon replacing both the geometry icon div and color swatch div.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260324-kte-inspect-the-map-creator-layer-list-item-/260324-kte-CONTEXT.md
@.planning/quick/260324-kte-inspect-the-map-creator-layer-list-item-/260324-kte-RESEARCH.md
@frontend/src/components/builder/LayerItem.tsx

<interfaces>
<!-- Existing functions to preserve/modify -->

From frontend/src/components/builder/LayerItem.tsx:
```typescript
// Lines 49-54 — will be replaced by ColorizedGeometryIcon
function GeometryIcon({ geometryType }: { geometryType: string | null }) {
  const gt = (geometryType ?? '').toUpperCase();
  if (gt.includes('POINT')) return <Circle className="h-3 w-3" />;
  if (gt.includes('LINE')) return <Minus className="h-3 w-3" />;
  return <Pentagon className="h-3 w-3" />;
}

// Lines 56-65 — keep as-is, provides color data
function getLayerColors(layer: MapLayerResponse): string[] { ... }

// Lines 169-185 — the two elements being merged:
// div.shrink-0.text-muted-foreground (geometry icon)
// div.flex.h-3.w-3.rounded-sm (color swatch, vector only)
```

From frontend/src/lib/layer-capabilities.ts:
```typescript
function getLayerCapabilities(layer): { kind: 'vector' | 'raster' | 'vrt'; ... }
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create ColorizedGeometryIcon and merge indicators</name>
  <files>frontend/src/components/builder/LayerItem.tsx</files>
  <action>
1. Create a new `ColorizedGeometryIcon` component (above `LayerItem`, replacing `GeometryIcon`) that accepts `{ geometryType: string | null; colors: string[]; layerId: string }`:

   a. Determine the icon component from geometryType (same logic as current GeometryIcon — POINT->Circle, LINE->Minus, default->Pentagon).

   b. **Single color** (colors.length <= 1): Render the icon with `fill={colors[0] ?? '#6366f1'}` and `strokeWidth={0}` at `className="h-3.5 w-3.5"`. Use fill (not stroke) for better color visibility at small sizes per research pitfall #3.

   c. **Multi-color** (colors.length > 1): Render a wrapper `<span className="relative inline-flex h-3.5 w-3.5">` containing:
      - A hidden SVG (`width="0" height="0" className="absolute"`) with `<defs>` containing a `<linearGradient id={\`layer-grad-${layerId}\`}>` with `<stop>` elements for each color at evenly distributed offsets.
      - The icon component with `fill={\`url(#layer-grad-${layerId})\`}` and `strokeWidth={0}` at `className="h-3.5 w-3.5"`.
      Use `width="0" height="0"` with `absolute` positioning (NOT `display: none` or `hidden`) to avoid browser rendering issues per research pitfall #2.

2. In the LayerItem render, replace the two indicator elements (lines 169-185) with a single block:
   - For `caps.kind === 'vrt'`: `<Layers className="h-3.5 w-3.5 text-muted-foreground" />`
   - For `caps.kind === 'raster'`: `<Grid3x3 className="h-3.5 w-3.5 text-muted-foreground" />`
   - For vector: `<ColorizedGeometryIcon geometryType={layer.dataset_geometry_type} colors={layerColors} layerId={layer.id} />`
   Wrap in a `<div className="shrink-0">` (remove `text-muted-foreground` from the wrapper since vector icons now get their own color; raster/VRT icons carry their own muted class).

3. Remove the color swatch div entirely (lines 179-185, the `{!isRaster && (...)}` block).

4. Remove the old `GeometryIcon` component (lines 49-54) since `ColorizedGeometryIcon` replaces it.

5. Bump icon sizes from `h-3 w-3` to `h-3.5 w-3.5` for the merged indicator to give slightly better color visibility (matching the eye icon size).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - LayerItem renders a single colorized geometry icon for vector layers (no separate color swatch)
    - Single-color vector layers show a filled icon in the paint color
    - Multi-color vector layers show a gradient-filled icon
    - Raster/VRT layers show muted gray icons unchanged
    - TypeScript compiles without errors
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: Verify colorized geometry icons in map builder</name>
  <files>frontend/src/components/builder/LayerItem.tsx</files>
  <action>
    Human verifies the merged indicator visually in the running application.
  </action>
  <verify>
    1. Open http://localhost:8080 and navigate to the map builder
    2. Add a vector layer (point, line, or polygon) — verify the layer row shows a single filled geometry icon tinted with the layer color (no separate color swatch bar)
    3. Change the layer to a categorical or graduated style — verify the icon shows a gradient of the category/ramp colors
    4. Add a raster or VRT layer — verify it shows the muted gray Grid3x3/Layers icon (no color)
    5. Confirm the overall row layout is clean: [Grip] [Eye] [ColorizedIcon] [Name] [Expand] [Menu]
  </verify>
  <done>User approves the visual appearance of the merged indicator</done>
</task>

</tasks>

<verification>
- TypeScript compilation passes
- Layer list items render one indicator instead of two for vector layers
- Raster/VRT layers unchanged
- No visual regression in layer row layout
</verification>

<success_criteria>
The map builder layer list shows a single colorized geometry icon per vector layer, with the color swatch removed. Raster/VRT layers retain their muted icons. Multi-color styles display as gradients on the icon.
</success_criteria>

<output>
After completion, create `.planning/quick/260324-kte-inspect-the-map-creator-layer-list-item-/260324-kte-01-SUMMARY.md`
</output>

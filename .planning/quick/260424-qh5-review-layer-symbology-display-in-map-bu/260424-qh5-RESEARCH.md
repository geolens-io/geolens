# Quick Task 260424-qh5: Review Layer Symbology Display - Research

**Researched:** 2026-04-24
**Domain:** Map builder legend rendering, symbology accuracy
**Confidence:** HIGH

## Summary

The codebase has **three distinct legend rendering contexts** with varying levels of symbology accuracy:

1. **Builder LayerItem** (`components/builder/LayerItem.tsx`) -- Uses `ColorizedGeometryIcon` from `components/map/layer-icons.tsx`. This is **well-implemented**: geometry-aware SVG shapes (circles for points, pentagons for polygons, line segments for lines), outline/stroke rendering, dash patterns, opacity, gradient fills for data-driven layers.

2. **Builder LegendWidget** (`components/map-widgets/builtin/LegendWidget.tsx`) -- For data-driven layers, uses `LegendEntries.tsx` which renders **all swatches as uniform `rounded-sm` divs** regardless of geometry type. For simple (non-data-driven) layers, falls through to `ColorizedGeometryIcon` which IS geometry-aware. This is the **primary gap**: categorical and graduated color legends show rectangular swatches even for point and line layers.

3. **Viewer LayerLegend** (`components/viewer/LayerLegend.tsx`) -- Renders all swatches (simple and data-driven) as **uniform rectangular divs** with no geometry differentiation at all. Does pass outline/stroke info for the top-level swatch but not for per-category/per-class swatches.

**Primary recommendation:** The `CategoricalLegend` and `GraduatedColorLegend` components in `LegendEntries.tsx` need geometry-type awareness to render circles for points and line segments for lines instead of uniform rectangles. The viewer `LayerLegend` also needs the same treatment for its `LegendSwatch` component.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Implementation Decisions
- Legend swatches should visually match geometry type: Points -> circle swatch, Lines -> short line segment, Polygons -> filled rectangle with visible outline
- Each swatch should reflect the actual fill + outline style applied to the layer
- Priority is legend-to-map consistency: verify that legend colors/breaks exactly match what MapLibre renders
- Fix any drift between the expression built for MapLibre and the legend display
- Use composite swatches: legend swatch shows fill color with outline border visible -- single swatch that captures the compound style
- No separate entries for fill vs outline; combine into one visual element
- Use Playwright MCP to visually inspect current behavior before and after changes
</user_constraints>

## Findings

### Finding 1: LegendEntries.tsx Swatches Are Geometry-Blind (for color legends)

**Confidence:** HIGH [VERIFIED: codebase]

`CategoricalLegend` and `GraduatedColorLegend` in `frontend/src/components/map/LegendEntries.tsx` render swatches as:

```tsx
<div className={swatchClass(s)} style={swatchStyle(color, s)} />
// swatchClass = 'w-3.5 h-3.5 rounded-sm shrink-0 border'
```

This produces a 14x14px rounded rectangle for every entry regardless of whether the layer is points, lines, or polygons. There is no `geometryType` prop passed to these components.

**Contrast with graduated SIZE legends:** `GraduatedRadiusLegend` correctly renders SVG circles, and `GraduatedWidthLegend` correctly renders SVG line segments. Only the COLOR-based legends are geometry-blind.

**Gap:** These components need a `geometryType` prop so they can render:
- Points: small SVG circle with fill + optional stroke
- Lines: short SVG line segment with stroke color
- Polygons: rectangle with fill + border (current behavior, already correct for this case)

### Finding 2: Viewer LayerLegend Is Entirely Geometry-Blind

**Confidence:** HIGH [VERIFIED: codebase]

`frontend/src/components/viewer/LayerLegend.tsx` has two swatch rendering paths:

**Top-level layer swatch (line 117-121):** A plain `div` with `backgroundColor` and no geometry differentiation:
```tsx
<div className="w-4 h-4 rounded-sm flex-shrink-0 border border-black/10"
     style={{ backgroundColor: color }} />
```

**Per-category/per-class swatches (LegendSwatch component, line 33-47):** Same plain div approach.

The `getSwatchColor()` function does geometry-aware color extraction (reads `circle-color` for points, `line-color` for lines, `fill-color` for fills) but the resulting color is always rendered as the same rectangular swatch. Geometry type information is available on the `layer` object (`layer.geometry_type`) but never flows to the swatch rendering.

**Additional gap:** The viewer legend's per-category swatches don't pass outline/stroke info at all -- they use a hardcoded `border-black/10` instead of the actual `_outline-color`.

### Finding 3: Classification Color Consistency is CORRECT

**Confidence:** HIGH [VERIFIED: codebase]

The data flow for classification colors does NOT have drift issues:

**Categorical path:**
1. `DataDrivenStyleEditor.tsx` calls `buildCategoricalExpression(column, valueColorMap, fallback)` 
2. Stores `categories: [{value, color}, ...]` in `style_config`
3. Stores the match expression in `paint[colorProp]`
4. Legend reads `style_config.categories` directly -- same source array that generated the expression

**Graduated path:**
1. `DataDrivenStyleEditor.tsx` calls `buildGraduatedExpression(column, breaks, colors)`
2. Stores `breaks` and `colors` arrays in `style_config`
3. Stores the step expression in `paint[colorProp]`
4. Legend reads `style_config.colors` and `style_config.breaks` -- same source arrays

**Per-color editing also stays in sync:** When a user edits an individual category/class color, `handleCategoryColorChange` and `handleGraduatedColorChange` rebuild both the expression AND the `style_config` atomically in the same `onStyleConfigChange` call.

**Conclusion:** Legend colors and MapLibre expression colors cannot drift because they are derived from the same `style_config` source of truth. No fix needed here.

### Finding 4: Fill+Outline Composite Rendering in Legend

**Confidence:** HIGH [VERIFIED: codebase]

**LegendWidget (builder):** The `swatchStyle` in `LegendEntries.tsx` DOES support outline rendering:
```tsx
function swatchStyle(color: string, s?: SwatchStyle): React.CSSProperties {
  return {
    backgroundColor: color,
    ...(!s?.strokeDisabled ? { borderColor: s?.outlineColor ?? MAP_COLORS.legendOutline } : {}),
  };
}
```

And `LegendWidget.tsx` passes `outlineColor`, `strokeDisabled`, and `opacity` through:
```tsx
const swatchStyle = { outlineColor, strokeDisabled, opacity };
```

So in the builder's LegendWidget, polygon fill+outline composite rendering **works correctly** -- the swatch shows the fill color with the actual outline color as its border.

**Viewer LayerLegend:** Does NOT pass outline info to per-category swatches. The `LegendSwatch` uses hardcoded `border-black/10`. The top-level swatch also uses `border-black/10`. The actual `_outline-color` from paint is not read at all in this component.

### Finding 5: Label Halo Is Not Represented in Any Legend

**Confidence:** HIGH [VERIFIED: codebase]

Label configuration (`label_config`) with halo properties (`haloColor`, `haloWidth`) is managed in `LabelEditor.tsx` but is not rendered in any legend component. This is likely by design -- label styling is a secondary visual property and showing it in the legend would add clutter. The CONTEXT.md mentions "fill + outline + halo" but the `haloColor/haloWidth` in this codebase are text-label halos (MapLibre `text-halo-color`/`text-halo-width`), not geometry halos. The existing compound style concern is fill + outline, which is handled in the builder widget but not the viewer.

### Finding 6: Builder LegendWidget Non-Data-Driven Path Is Already Good

**Confidence:** HIGH [VERIFIED: codebase]

For layers WITHOUT data-driven styling (no `style_config.column`), the `LegendWidget` renders:
```tsx
<ColorizedGeometryIcon
  geometryType={layer.dataset_geometry_type ?? null}
  colors={getLayerColors({...})}
  layerId={...}
  layerType={layer.layer_type ?? undefined}
  styleHints={extractStyleHints(...)}
/>
```

This path produces geometry-correct SVG icons with full style fidelity (outline color, stroke disabled, dash patterns, opacity, gradient fills). No changes needed here.

## Specific Gaps Summary

| Area | Builder LegendWidget | Viewer LayerLegend | Status |
|------|---------------------|-------------------|--------|
| Simple layer swatch | Geometry-aware (ColorizedGeometryIcon) | Geometry-blind (plain div) | Viewer needs fix |
| Categorical legend swatches | Geometry-blind (plain div) | Geometry-blind (plain div) | Both need fix |
| Graduated color legend swatches | Geometry-blind (plain div) | Geometry-blind (plain div) | Both need fix |
| Graduated radius legend swatches | Geometry-aware (SVG circles) | N/A (viewer has no radius legend) | OK |
| Graduated width legend swatches | Geometry-aware (SVG line segments) | N/A (viewer has no width legend) | OK |
| Heatmap legend | Gradient bar (correct) | Gradient bar (correct) | OK |
| Fill+outline composite | Correct (reads _outline-color) | Missing (hardcoded border) | Viewer needs fix |
| Classification color accuracy | Correct (same source) | Correct (same source) | OK |
| Label halo in legend | Not shown | Not shown | By design |

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/map/LegendEntries.tsx` | Add `geometryType` prop to `CategoricalLegend` and `GraduatedColorLegend`; render SVG circles for points, SVG lines for lines, keep divs for polygons |
| `frontend/src/components/map-widgets/builtin/LegendWidget.tsx` | Pass `geometryType` to CategoricalLegend and GraduatedColorLegend |
| `frontend/src/components/viewer/LayerLegend.tsx` | Replace plain-div swatches with geometry-aware rendering; pass actual `_outline-color` to per-category swatches |

## Implementation Notes

The `LegendEntries.tsx` shared swatch function is the right place to add geometry awareness. A single `GeometrySwatch` component that takes `geometryType`, `color`, and `SwatchStyle` could replace the current plain-div approach, reusing the same SVG patterns already proven in `GraduatedRadiusLegend` (circles) and `GraduatedWidthLegend` (lines).

For the viewer's `LayerLegend.tsx`, the `geometry_type` field is already available on `SharedLayerResponse` and can be threaded through to `LegendSwatch`.

## Sources

### Primary (HIGH confidence)
- `frontend/src/components/map/LegendEntries.tsx` -- swatch rendering for all legend types
- `frontend/src/components/map-widgets/builtin/LegendWidget.tsx` -- builder legend widget orchestration
- `frontend/src/components/viewer/LayerLegend.tsx` -- viewer legend rendering
- `frontend/src/components/map/layer-icons.tsx` -- ColorizedGeometryIcon (geometry-aware reference)
- `frontend/src/lib/color-ramps.ts` -- expression builders (categorical, graduated)
- `frontend/src/components/builder/DataDrivenStyleEditor.tsx` -- style_config population
- `frontend/src/components/builder/LayerStyleEditor.tsx` -- fill/outline/halo controls
- `frontend/src/components/builder/layer-adapters/fill-adapter.ts` -- polygon outline companion layer
- `frontend/src/lib/legend-utils.ts` -- break label formatting
- `frontend/src/lib/map-colors.ts` -- centralized color constants

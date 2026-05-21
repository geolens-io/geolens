# Quick Task: Map Creator Layer Styling Review - Research

**Researched:** 2026-03-25
**Domain:** MapLibre GL style spec compliance, builder layer styling architecture
**Confidence:** HIGH

## Summary

The layer styling system is well-structured for an MVP. It covers all three vector geometry types (point/line/polygon) plus raster opacity, uses a clean separation between UI components and map sync logic, and correctly implements data-driven styling with categorical and graduated expressions. The architecture flows from `LayerStyleEditor` -> `useBuilderLayers` hook (local state + imperative map updates) -> `map-sync.ts` (full reconciliation on mount/basemap change).

There are several concrete issues ranging from spec violations to duplicated logic and missing MVP-level properties. The most impactful are: (1) a non-spec `outline-width` paint property used as a workaround for MapLibre's 1px fill-outline limitation, (2) duplicated opacity multiplication logic across three files, and (3) missing `line-dasharray` support which is a very common styling need.

**Primary recommendation:** Fix the spec issues and reduce duplication. The outline workaround is clever and correct in approach but the naming should be clearer. Extract the opacity multiplication into a shared helper. Add dash-array support for lines.

## Architecture Overview

### Component Flow
```
LayerStyleEditor.tsx          -- UI controls per geometry type
  -> StyleColorPicker.tsx     -- color picker popover with presets
  -> DataDrivenStyleEditor.tsx -- categorical/graduated styling
    -> ColorRampPicker.tsx    -- chroma-js ramp selection
    -> color-ramps.ts         -- expression builders
LayerItem.tsx                 -- tabs (style/filter/labels), wires to LayerPanel
LayerPanel.tsx                -- DnD list, passes callbacks through
RasterLayerControls.tsx       -- opacity-only for raster/VRT layers

useBuilderLayers.ts           -- local state management + live imperative map updates
map-sync.ts                   -- full layer reconciliation (mount, basemap swap)
BuilderMap.tsx                -- MapLibre instance, calls syncLayersToMap on changes
layer-capabilities.ts         -- classifies layers into vector/raster/vrt capability sets
```

### Data Flow for Style Changes
1. User adjusts slider/color in `LayerStyleEditor`
2. Calls `onPaintChange(layerId, newPaint)` up to `useBuilderLayers.handlePaintChange`
3. `handlePaintChange` updates `localLayers` state AND imperatively calls `map.setPaintProperty()`
4. On save, `localLayers` are sent to the API
5. On mount/basemap change, `map-sync.syncLayersToMap` rebuilds all layers from scratch

## Findings

### Issue 1: Non-spec `outline-width` property (MEDIUM severity)

**File:** `LayerStyleEditor.tsx` line 21, `map-sync.ts` line 9

The polygon fill defaults include `outline-width: 1` which is not a MapLibre style spec property. This is intentionally a custom property used to drive a separate line layer that acts as the polygon outline (because MapLibre's native `fill-outline-color` is hardcoded to 1px width).

**The approach is correct** -- using a companion `line` layer for polygon outlines is the standard way to get variable-width polygon borders in MapLibre. However:

- The name `outline-width` is confusingly generic. Consider renaming to `_outline-width` or `gl-outline-width` to make it obviously non-spec (prefixed convention).
- Similarly, `fill-outline-color` IS a real MapLibre property but it's being stored in the custom props set alongside `outline-width` and applied to the line layer instead. This dual use is confusing -- the same key name means different things depending on context. The `CUSTOM_PAINT_PROPS` set in `map-sync.ts` strips it from the fill layer and applies it to the outline line layer, which is correct behavior, but the naming collision with the real spec property is a maintenance trap.

**Recommendation:** Rename to `_outline-width` and `_outline-color` (or similar prefix) to distinguish from spec properties. Update `CUSTOM_PAINT_PROPS`, `LayerStyleEditor`, `map-sync.ts`, and `use-builder-layers.ts` accordingly.

### Issue 2: Opacity multiplication duplicated in 3 places (MEDIUM severity)

The compound opacity logic (`propertyOpacity * masterOpacity`) is implemented separately in:

1. **`map-sync.ts`** lines 182-183, 211-213, 244-246 (initial layer creation)
2. **`map-sync.ts`** lines 293-301 (existing layer sync)
3. **`use-builder-layers.ts`** lines 413-419, 435-438, 449-452 (handlePaintChange)
4. **`use-builder-layers.ts`** lines 490-508 (handleOpacityChange)

Each reimplements the same pattern: `(paint['{type}-opacity'] as number) ?? defaultOpacity) * masterOpacity`. Different default values are used inconsistently (0.3 for fill, 1 for line/circle).

**Recommendation:** Extract a helper function:
```typescript
function getCompoundOpacity(
  paint: Record<string, unknown>,
  geomType: 'fill' | 'line' | 'circle',
  masterOpacity: number,
): number {
  const propKey = `${geomType}-opacity`;
  const defaults = { fill: 0.3, line: 1, circle: 1 };
  const propOpacity = (paint[propKey] as number) ?? defaults[geomType];
  return propOpacity * masterOpacity;
}
```

### Issue 3: Missing `line-dasharray` support (LOW severity, MVP gap)

Dashed lines are one of the most common styling needs for lines (roads, boundaries, planned routes). The `line` type controls expose color, opacity, and width but not `line-dasharray`. This is a layout property (not paint), so it would need different handling.

**Recommendation for MVP:** Add a simple preset dropdown (solid, dashed, dotted, dash-dot) that maps to common dasharray values:
- Solid: no dasharray
- Dashed: `[4, 2]`
- Dotted: `[1, 2]`
- Dash-dot: `[4, 2, 1, 2]`

This requires storing it in `layout` (not `paint`) and syncing via `setLayoutProperty`.

### Issue 4: `fill-opacity` serves double duty (LOW severity, correctness)

In `LayerStyleEditor`, the fill-opacity slider directly controls `fill-opacity` in paint. But in `map-sync.ts` and `use-builder-layers.ts`, the actual MapLibre `fill-opacity` is set to `fillOpacity * masterOpacity`. This means:

- The stored paint value is the "per-property" opacity (e.g., 0.3)
- The master opacity slider controls a separate `layer.opacity` field
- The MapLibre runtime value is the product of both

This is **correct behavior** but could confuse future developers. The `fill-opacity` slider label says "Opacity" and the master slider also says "Opacity". The UI separation (per-type section vs. bottom "Layer" section) helps, but the two opacity concepts could use clearer labeling.

**Minor fix:** Consider labeling the per-type slider "Fill opacity" and the master slider "Layer opacity" to disambiguate.

### Issue 5: `handlePaintChange` stale closure risk (LOW severity)

In `use-builder-layers.ts` line 402:
```typescript
const layer = resolvedLayer ?? localLayers.find((l) => l.id === layerId);
```

The `resolvedLayer` pattern works around the React state batching issue, but `localLayers` in the fallback branch captures the value from the current render, not the latest state. Since `setLocalLayers` uses a functional updater, `resolvedLayer` should always be populated, making the fallback dead code. Remove the `?? localLayers.find(...)` fallback to avoid confusion.

### Issue 6: `handlePaintChange` only syncs known properties (LOW severity)

`handlePaintChange` in `use-builder-layers.ts` has explicit `if` blocks for each known paint property (`fill-color`, `fill-opacity`, `line-color`, etc.). If a new paint property is added to the UI (e.g., `line-dasharray`, `circle-blur`), the live sync will silently skip it. The `handleStyleConfigChange` function uses a generic loop approach that is more resilient.

**Recommendation:** Refactor `handlePaintChange` to use the same generic loop pattern as `handleStyleConfigChange`:
```typescript
for (const [prop, value] of Object.entries(newPaint)) {
  if (CUSTOM_PROPS.has(prop)) { /* sync to outline layer */ continue; }
  if (value !== undefined) {
    map.setPaintProperty(mapLayerId, prop, value);
  }
}
// Then handle compound opacity separately
```

### Issue 7: Raster layers have no style controls beyond opacity (Acceptable for MVP)

Raster and VRT layers only expose an opacity slider. This is appropriate for MVP -- raster styling (contrast, saturation, brightness, hue-rotate) via MapLibre's `raster-contrast`, `raster-saturation`, `raster-brightness-min/max`, and `raster-hue-rotate` are nice-to-have but not essential.

### Issue 8: GEOMETRYCOLLECTION not handled (LOW severity, edge case)

`getLayerType()` in `map-sync.ts` defaults everything that isn't POINT or LINE to `fill`. A GEOMETRYCOLLECTION would be treated as fill, which is wrong. This is acceptable for MVP since PostGIS datasets rarely have mixed geometry types, but worth noting.

## Spec Compliance Summary

| Geometry | Paint Props Exposed | Spec Compliance | Missing Common Props |
|----------|-------------------|-----------------|---------------------|
| Fill (polygon) | fill-color, fill-opacity, fill-outline-color*, outline-width* | GOOD (outline via line layer workaround) | fill-pattern |
| Line | line-color, line-opacity, line-width | GOOD | line-dasharray (layout), line-blur, line-gap-width |
| Circle (point) | circle-color, circle-opacity, circle-radius, circle-stroke-color, circle-stroke-width | GOOD | circle-blur, circle-pitch-alignment |
| Raster | raster-opacity | GOOD | raster-contrast, raster-saturation, raster-brightness-min/max |
| Symbol (labels) | text-color, text-halo-color, text-halo-width | GOOD | text-opacity |

*Non-spec custom properties applied via companion line layer.

All exposed properties use correct MapLibre spec names (except the intentional custom props for polygon outlines). Expression builders for data-driven styles correctly produce `match` and `step` expressions per spec.

## Prioritized Action Items

1. **Refactor `handlePaintChange` to use generic loop** -- eliminates the need to update sync logic every time a new paint property is added. Aligns it with `handleStyleConfigChange` pattern. (Reduces ~55 lines to ~15)

2. **Extract compound opacity helper** -- single function used by map-sync.ts and use-builder-layers.ts. Eliminates 4 duplicated implementations.

3. **Rename custom outline props** -- prefix with `_` to distinguish from spec properties. Prevents future confusion.

4. **Add `line-dasharray` preset selector** -- single most impactful missing style control for MVP users.

5. **Clean up stale fallback in handlePaintChange** -- remove dead `?? localLayers.find()` branch.

## Sources

- MapLibre GL Style Spec: paint properties verified against https://maplibre.org/maplibre-style-spec/layers/
- Code review: All files listed in Architecture Overview section
- Confidence: HIGH -- all findings are from direct code reading, no external source ambiguity

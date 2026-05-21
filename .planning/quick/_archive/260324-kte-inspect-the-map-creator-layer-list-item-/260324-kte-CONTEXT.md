# Quick Task 260324-kte: Merge layer list item symbology/geometry into one indicator - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Task Boundary

Inspect the map creator layer list item symbology/geometry - can these 2 items be merged into one?

Currently the LayerItem.tsx component renders two separate side-by-side indicators between the visibility toggle and layer name:
1. **Geometry icon** (h-3 w-3) — Circle/Minus/Pentagon/Grid/Layers icon showing feature type
2. **Color swatch** (h-3 w-3) — Colored bar segments showing layer paint colors

These should be merged into a single unified indicator.

</domain>

<decisions>
## Implementation Decisions

### Merge Approach
- **Colorized icon**: Tint the geometry shape icon (circle/line/pentagon) with the layer's primary color. Single element replaces both current indicators.
- For simple styles: icon color = layer paint color (circle-color, line-color, fill-color)
- For data-driven styles: see multi-color decision below

### Raster Handling
- **Keep icon-only, muted**: Raster/VRT layers retain their Grid3x3/Layers icon in muted gray (text-muted-foreground). No color tinting — rasters don't have a single paint color. No change in behavior from current.

### Data-Driven Multi-Color Styles
- **Gradient fill on icon**: Apply a CSS gradient across the geometry icon using the category/graduated colors. Shows color variety in a single indicator.
- Categorical styles: gradient from category colors
- Graduated styles: gradient from color ramp

</decisions>

<specifics>
## Specific Ideas

- Current layout: `[Grip] [Eye] [GeomIcon] [ColorSwatch] [LayerName] [Expand] [Menu]`
- Target layout: `[Grip] [Eye] [ColorizedGeomIcon] [LayerName] [Expand] [Menu]`
- GeometryIcon function at lines 49-54 of LayerItem.tsx
- getLayerColors function at lines 56-65 of LayerItem.tsx
- Color swatch rendered at lines 179-185 of LayerItem.tsx

</specifics>

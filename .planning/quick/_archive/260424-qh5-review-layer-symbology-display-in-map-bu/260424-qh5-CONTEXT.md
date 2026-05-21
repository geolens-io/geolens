# Quick Task 260424-qh5: Review Layer Symbology Display in Map Builder - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Task Boundary

Review the map builder's layer symbology display for accuracy. Assess whether symbology accurately represents geometry type, whether classification (categorical/graduated) legend entries match the map rendering, and whether compound styles (fill + outline + halo) are properly displayed in both the style editor and the legend.

</domain>

<decisions>
## Implementation Decisions

### Legend Geometry Symbols
- Legend swatches should visually match geometry type: Points -> circle swatch, Lines -> short line segment, Polygons -> filled rectangle with visible outline
- Each swatch should reflect the actual fill + outline style applied to the layer

### Classification Accuracy
- Priority is legend-to-map consistency: verify that legend colors/breaks exactly match what MapLibre renders
- Fix any drift between the expression built for MapLibre and the legend display

### Fill/Outline/Halo Rendering
- Use composite swatches: legend swatch shows fill color with outline border visible -- single swatch that captures the compound style
- No separate entries for fill vs outline; combine into one visual element

### QA Approach
- Use Playwright MCP to visually inspect current behavior before and after changes

</decisions>

<specifics>
## Specific Ideas

- Check LegendEntries.tsx for how swatches are currently rendered per geometry type
- Verify color-ramps.ts expression builders produce values that match legend display
- Check fill-adapter.ts outline companion layer vs legend swatch rendering
- Inspect label halo rendering in legend context

</specifics>

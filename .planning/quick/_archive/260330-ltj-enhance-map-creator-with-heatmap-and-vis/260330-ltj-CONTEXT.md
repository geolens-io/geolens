# Quick Task 260330-ltj: Enhance map creator with heatmap and visualization capabilities - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Task Boundary

Add heatmap visualization to the map builder, allowing users to render point layers as heatmaps with configurable weight, color ramp, radius, and intensity controls.

</domain>

<decisions>
## Implementation Decisions

### Visualization Types
- Heatmap only for this task. No clusters, 3D extrusions, or other viz types.
- Use MapLibre's native `heatmap` layer type for point data.

### Heatmap Controls
- Simple control set: weight column picker, color ramp selector, radius slider, intensity slider.
- Auto-tune sensible defaults so heatmaps look good out of the box.
- No advanced controls (kernel type, per-zoom interpolation curves, custom opacity stops).

### Layer Type Switching
- Add a "Render as" dropdown (Points / Heatmap) at the top of the style tab.
- Same layer object, different rendering mode — not a separate layer type.
- When switched to heatmap, existing point style controls are replaced with heatmap-specific controls.
- Paint/style state for each mode should be preserved when toggling back and forth.

### Claude's Discretion
- Heatmap color ramp selection — reuse existing sequential/diverging ramps from the graduated style editor.
- Default radius/intensity values — pick sensible defaults based on MapLibre conventions.
- Zoom-based interpolation for radius — use standard MapLibre zoom interpolation to scale radius appropriately.

</decisions>

<specifics>
## Specific Ideas

- Reuse `ColorRampPicker` component and `SEQUENTIAL_RAMPS` / `DIVERGING_RAMPS` from existing data-driven style system.
- New `heatmap-adapter.ts` in `layer-adapters/` following the existing adapter pattern.
- `StyleConfig` type may need a `renderMode` field or similar to track points vs heatmap.
- The "Render as" dropdown should only appear for point geometry layers.

</specifics>

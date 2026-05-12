# Phase 1010: RenderAs actions and duplicate renderings - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1002 requirements, Phase 1008 renderAs foundation, Phase 1009 row UI

<domain>
## Phase Boundary

Phase 1010 turns the Phase 1009 row renderAs controls into real mutations and adds duplicate-rendering actions. It must stay within existing `MapLayer` fields and the existing add-layer/patch/save behavior.

The phase owns RENDER-02..08:
- Point supports Point, Symbol, Heatmap only.
- Line supports Line only.
- Polygon supports Fill, Stroke, Fill + Stroke, and 3D extrusion.
- Raster supports Image; raster DEM supports Image and Hillshade.
- RenderAs changes write only `layer_type`, `style_config`, `paint`, and `layout`.
- Polygon 3D extrusion writes existing `style_config.builder.*` extrusion fields and paint defaults.
- Duplicate rendering creates a sibling layer with the same `dataset_id`, independent style fields, and correct sort order.
</domain>

<decisions>
## Implementation Decisions

### Mutation Boundary
- Add a pure renderAs patch builder next to the Phase 1008 utility.
- Return only existing writable fields and prove `is_3d` is absent.
- Keep renderAs UI options limited by `getRenderAsOptions`.

### Builder Hook
- Extend `useBuilderLayers` with `handleRenderAsChange` and `handleDuplicateRendering`.
- Existing `handleRenderModeChange` can remain for older editor code, but row UI should use the new renderAs handler.
- For MapLibre immediacy, reuse the existing adapter-swap path and remove incompatible raster sources when switching DEM Image/Hillshade.

### Duplicate Rendering
- Use the existing `useAddLayer` mutation and `MapLayerInput`.
- Copy the source layer's dataset/style fields into the new layer input, assign `sort_order = current_max + 1`, and use a distinct display name.
- Do not introduce a new backend endpoint.
</decisions>

<specifics>
## Specific Ideas

- `buildRenderAsPatch(layer, renderAs)` returns a small patch plus an adapter type for immediate map swapping.
- Polygon extrusion chooses an existing builder height column, the first numeric dataset column, or a conservative fallback key if no metadata is available.
- Row overflow menu gets "Duplicate rendering"; the Add Dataset modal hook-up is deferred to Phase 1012 where the modal is edited.
</specifics>

<deferred>
## Deferred Ideas

- Add Dataset modal `+ another rendering` belongs to Phase 1012.
- Basemap and terrain rows belong to Phase 1011.
- New renderers remain punted: Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion.
</deferred>

---

*Phase: 1010-renderas-actions-and-duplicate-renderings*
*Context gathered: 2026-05-12 from current code and scoped handoff*

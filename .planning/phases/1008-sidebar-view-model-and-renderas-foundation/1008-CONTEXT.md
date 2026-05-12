# Phase 1008: Sidebar view-model and renderAs foundation - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1002 handoff and milestone requirements

<domain>
## Phase Boundary

Phase 1008 establishes the safe foundation for the Layer Sidebar + Add Dataset redesign. It should not rewrite rows, modal chrome, basemap controls, terrain controls, or mutation handlers yet. It should add the pure model/utility surface that later phases consume.

The phase owns ARCH-01..04 and RENDER-01:
- Preserve current persisted shapes and API payloads.
- Keep sidebar groups as derived frontend state.
- Use existing GeoLens UI vocabulary.
- Expose only currently supported renderer options.
- Provide a pure renderAs mapping utility with tests.
</domain>

<decisions>
## Implementation Decisions

### Persistence Boundary
- No migration work.
- No new `Map`, `MapLayer`, `Dataset`, or `Record` fields.
- No persisted group, recipe, preset, connector, timeline, or scene-graph entity.
- `is_3d` is read-only response/dataset metadata and must not appear in generated mutation patches.

### Renderer Boundary
- Supported v1 renderAs values are limited to current adapters:
  - Point: Point, Symbol, Heatmap
  - Line: Line
  - Polygon: Fill, Stroke, Fill + Stroke, 3D extrusion
  - Raster: Image
  - Raster DEM: Image, Hillshade
- Explicitly excluded from v1002: Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion, timeline playback, recipes, cross-layer filters, and blend mode.

### Code Shape
- Prefer a pure TypeScript utility near the builder surface, e.g. `frontend/src/components/builder/renderAs.ts`.
- Keep it free of React state and network side effects.
- Tests should prove both supported options and unsupported omissions.
- Later phases can import the utility into rows/modal/mutation handlers.
</decisions>

<specifics>
## Specific Ideas

- Reuse existing `MapLayerResponse` and `StyleConfig` types.
- Identify source class from `layer_type`, `dataset_record_type`, `dataset_geometry_type`, `is_dem`, and `style_config.render_mode`.
- Treat DEM as a raster subtype, not a separate modal tab or persisted layer type.
- Use a stable option id union so downstream UI can render a chip/select without inventing new strings.
- Include a helper for current renderAs label/id from an existing layer.
</specifics>

<deferred>
## Deferred Ideas

- Mutation dispatch for renderAs changes belongs to Phase 1010.
- Sidebar row rendering belongs to Phase 1009.
- Basemap and terrain rows belong to Phase 1011.
- Add Dataset modal use of renderAs belongs to Phase 1012.
- Full Playwright verification belongs to Phase 1013.
</deferred>

---

*Phase: 1008-sidebar-view-model-and-renderas-foundation*
*Context gathered: 2026-05-12 via scoped handoff*

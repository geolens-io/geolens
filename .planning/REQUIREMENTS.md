# Requirements: v1002 Layer Sidebar + Add Dataset Redesign

## Milestone Goal

Redesign the Map Builder layer sidebar and Add Dataset workflow over the existing renderer and persisted shapes. v1002 ships zero migrations, no new tables, no new renderers, and no persisted group model.

## Frozen Constraints

- `Map`, `MapLayer`, `Record`, and `Dataset` schemas remain unchanged.
- Existing catalog/import surfaces remain in place; the Add Dataset modal links to `ImportPage` instead of rebuilding import.
- Existing component vocabulary remains shadcn/Radix/Tailwind/CVA/lucide from `frontend/src/components/ui/*`.
- `is_3d` is read-only response/dataset metadata and must not be written from sidebar or modal code.
- Kepler.gl remains a conceptual reference for dataset/layer separation, not an implementation dependency.

## Requirements

### Schema And Architecture

- [x] **ARCH-01**: Existing saved maps round-trip through builder load/save without adding, removing, or renaming any persisted `Map`, `MapLayer`, `Dataset`, or `Record` fields.
- [x] **ARCH-02**: Sidebar groups remain a frontend view-model derived from `Map`, `MapLayer[]`, `basemap_*`, `terrain_config`, and `widgets`; no persisted group entity is introduced.
- [x] **ARCH-03**: New sidebar/modal components compose existing `frontend/src/components/ui/*` primitives and lucide icons; no Carbon dependency or new primitive library is introduced.
- [x] **ARCH-04**: v1002 code does not introduce renderer support for Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion, timeline playback, recipes, cross-layer filters, or blend mode.

### Sidebar And Stack

- [x] **STACK-01**: The builder sidebar keeps the existing system groups: `surface`, `relief`, `basemap`, `data`, `labels`, and `interactions`.
- [x] **STACK-02**: Layer rows render the v1 anatomy: drag handle, visibility toggle, type swatch, display name, `as <renderAs>` control, opacity control, and overflow actions.
- [x] **STACK-03**: The `data` group renders a collapsible dataset-rendering header when two or more layers share `dataset_id`, showing dataset name, source/type metadata, feature count when available, and `N renderings`.
- [x] **STACK-04**: Dataset-rendering headers omit unsupported metadata such as LIVE status unless an existing API response field can support it without backend changes.
- [x] **STACK-05**: Per-row visibility-at-zoom controls write only `layout._minzoom` and `layout._maxzoom`, preserving existing zoom-range behavior and validation.

### RenderAs And Duplicate Renderings

- [x] **RENDER-01**: A pure `renderAs` mapping utility resolves supported options from existing layer metadata without side effects.
- [x] **RENDER-02**: Point vector/GeoJSON layers support only Point, Symbol, and Heatmap `renderAs` options.
- [x] **RENDER-03**: Line vector/GeoJSON layers support only Line `renderAs`.
- [x] **RENDER-04**: Polygon vector/GeoJSON layers support Fill, Stroke, Fill + Stroke, and 3D extrusion `renderAs`.
- [x] **RENDER-05**: Raster layers support Image; raster DEM layers support Image and Hillshade.
- [x] **RENDER-06**: Changing `renderAs` writes only existing writable fields: `layer_type`, `style_config`, `paint`, and `layout`; it never writes `is_3d`.
- [x] **RENDER-07**: Polygon 3D extrusion writes `style_config.builder.heightColumn`, `heightScale`, `extrusionMinZoom`, `extrusionOpacity`, and paint defaults required by the existing extrusion companion layer.
- [x] **RENDER-08**: Users can create a duplicate rendering from a layer row overflow action, producing a sibling `MapLayer` with the same `dataset_id`, independent style config, and correct sort order.

### Basemap And Terrain

- [x] **BASE-01**: The `basemap` group renders one primary row named from the current `BasemapEntry.label`, with no basemap `MapLayer` rows created.
- [x] **BASE-02**: Basemap sublayer controls write existing `basemap_style`, `show_basemap_labels`, and `basemap_config` keys only.
- [x] **BASE-03**: Basemap swap lists enabled entries from the existing `BasemapEntry` registry and writes `basemap_style` plus normalized supported `basemap_config` keys.
- [x] **BASE-04**: Basemap reset restores default basemap appearance through existing basemap config normalization without adding persisted presets.
- [x] **TERRAIN-01**: The `relief` group surfaces map-level terrain source, enabled state, and exaggeration controls backed by `terrain_config`.
- [x] **TERRAIN-02**: Raster DEM layer rows expose `Use as terrain`, setting `terrain_config.source_dataset_id` to that layer's `dataset_id` without changing the layer's persisted fields.

### Add Dataset Modal

- [x] **ADD-01**: The Add Dataset modal remains search-first and reuses the existing dataset search API rather than introducing a new catalog endpoint.
- [x] **ADD-02**: Modal tabs are `All`, `Vector`, `Raster`, and `Basemap`; DEM appears under Raster when existing metadata identifies it as DEM.
- [x] **ADD-03**: Modal filter chips use only current supported dataset search filters, such as `record_type`, `source_organization`, `keywords`, and `collection`.
- [x] **ADD-04**: Data records not on the map show `Add to map` and create a new `MapLayer` at the top of the data stack or next append position per current sort-order behavior.
- [x] **ADD-05**: Data records already on the map show `(added)` and `another rendering`; `another rendering` creates the same duplicate-rendering result as the row overflow action.
- [x] **ADD-06**: Basemap records show `swap` when inactive and `in use` when active, writing only current basemap fields.
- [x] **ADD-07**: Expanded modal rows show preview/metadata and primary actions using existing dataset/search response data.
- [x] **ADD-08**: The modal footer links to existing `ImportPage` as `Import data...`; no upload, service, or STAC import logic is reimplemented inside the modal.

### Quality Gates

- [ ] **QA-01**: Unit tests cover every supported `renderAs` source/option mapping and every unsupported v1 punt.
- [ ] **QA-02**: Unit/component tests cover dataset-rendering headers, basemap row grouping, terrain row grouping, and visibility-at-zoom writes.
- [ ] **QA-03**: Tests prove duplicate rendering works from both the sidebar row and Add Dataset modal and that `is_3d` is never written in layer patches.
- [ ] **QA-04**: Add Dataset modal tests cover `swap`, `in use`, `Add to map`, `(added)`, and `another rendering` states.
- [ ] **QA-05**: Playwright or equivalent UI verification covers builder sidebar and Add Dataset modal at desktop and tablet widths with keyboard/a11y checks.
- [ ] **QA-06**: Focused frontend lint and relevant Vitest suites pass before milestone close; broader E2E smoke gaps are documented if unrelated failures remain.

## Future Requirements

- Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion, and additional Kepler-like renderers.
- Persisted basemap appearance presets or recipes.
- Map timeline and cross-layer time playback.
- Cross-layer filters.
- Org connector library, saved credentials, scheduled sync, and connector health.
- Cross-surface drag from Add Dataset directly into an exact stack position.
- Blend mode, once a specific MapLibre implementation decision exists.
- Curated, Your imports, and Public scope chips once the exact API contract is defined.
- Promote-imports-to-org administrative workflow.

## Out Of Scope

- Any database migration.
- Any new persistent group, recipe, preset, connector, or timeline entity.
- Replacing GeoLens MapLibre/map-stack architecture with Kepler.gl, Redux, deck.gl layer classes, or a monolithic saved scene JSON.
- Rebuilding file upload, service URL import, STAC import, or existing catalog pages inside the Add Dataset modal.

## Traceability

| Requirement | Phase |
|---|---|
| ARCH-01..04 | 1008 |
| STACK-01..05 | 1009 |
| RENDER-01..08 | 1010 |
| BASE-01..04, TERRAIN-01..02 | 1011 |
| ADD-01..08 | 1012 |
| QA-01..06 | 1013 |

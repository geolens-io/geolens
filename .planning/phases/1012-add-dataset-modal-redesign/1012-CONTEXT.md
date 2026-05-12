# Phase 1012: Add Dataset modal redesign - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1002 requirements, current `DatasetSearchPanel`, Phase 1010 duplicate rendering, Phase 1011 basemap row controls

<domain>
## Phase Boundary

Phase 1012 rewrites the existing Add Dataset modal in place. It must continue to use the current dataset search API, current basemap registry, existing map-layer add path, and existing import page.

The phase owns ADD-01..08:
- Search-first modal using `/search/datasets/`.
- Tabs: All, Vector, Raster, Basemap.
- Filter chips only for existing search params such as `record_type`, `source_organization`, and `keywords`.
- Data rows support Add to map, added state, and another rendering.
- Basemap rows support swap and in-use state through existing map-level basemap handlers.
- Expanded rows show preview/metadata and primary actions.
- Footer routes to existing `/import` page.
</domain>

<current_state>
## Current Code Shape

- `BuilderDialogs` hosts the Add Data dialog and renders `DatasetSearchPanel`.
- `DatasetSearchPanel` currently searches data records only, with All/Vector/Raster toggles and simple add/added actions.
- `useBuilderLayers.handleAddDataset` adds a layer by dataset id with existing `useAddLayer`.
- `useBuilderLayers.handleDuplicateRendering` duplicates an existing layer by layer id.
- Phase 1011 added inline basemap mutation handlers in `MapStackPanel`; the modal can call the same map-level state setters.
</current_state>

<decisions>
## Implementation Decisions

### Component Boundary
- Extend `DatasetSearchPanel` rather than adding a parallel modal component.
- Pass current layers, basemap state, and basemap/duplicate handlers through `BuilderDialogs`.
- Keep modal chrome in `BuilderDialogs`; make the panel responsible for tabs, rows, expansion, and footer link.

### Search Contract
- Keep `searchDatasets(searchParams)` as the only data search endpoint.
- Use tabs to set existing `record_type` where possible.
- Add only client-visible filter chips backed by existing params (`source_organization`, `keywords`); do not add Curated/Public/Your imports.

### Actions
- `Add to map` calls existing `onAddDataset(datasetId)`.
- `another rendering` finds the first existing layer for that dataset id and calls `onDuplicateRendering(layer.id)`.
- Basemap swap calls existing `onBasemapChange`, `onBasemapLabelsChange`, and `onBasemapConfigChange` with normalized config.
</decisions>

<specifics>
## Specific Ideas

- Raster tab should include raster datasets and VRTs visually under Raster; no DEM tab.
- Basemap tab should list enabled `BasemapEntry` registry options plus the blank basemap affordance.
- Expanded data rows can use the existing quicklook URL when `has_quicklook` is true; otherwise show a compact type/extent placeholder.
- Expanded basemap rows can use the existing basemap thumbnail helper.
</specifics>

<deferred>
## Deferred Ideas

- Dragging modal rows directly into exact stack positions remains punted.
- Curated/Your imports/Public scope chips remain punted until backend API contract exists.
- Import workflow remains routed to `/import`.
</deferred>

---

*Phase: 1012-add-dataset-modal-redesign*
*Context gathered: 2026-05-12 from current code and scoped handoff*

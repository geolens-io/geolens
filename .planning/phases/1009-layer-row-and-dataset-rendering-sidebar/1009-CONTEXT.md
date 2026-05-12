# Phase 1009: Layer row and dataset-rendering sidebar - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1002 requirements, Phase 1008 foundation, current builder sidebar code

<domain>
## Phase Boundary

Phase 1009 updates the existing Map Stack sidebar presentation. It keeps the six current system groups and does not change persistence, render-mode mutation behavior, basemap controls, terrain controls, duplicate-rendering creation, or the Add Dataset modal.

The phase owns STACK-01..05:
- Preserve the system groups: surface, relief, basemap, data, labels, interactions.
- Render the v1 primary layer row anatomy.
- Add UI-only dataset-rendering headers in the data group for datasets with two or more renderings.
- Omit LIVE or other metadata that is not present in the current API response.
- Surface visibility-at-zoom controls over existing `layout._minzoom` / `layout._maxzoom`.
</domain>

<decisions>
## Implementation Decisions

### Existing Surfaces
- Extend `MapStackPanel`, `MapStackItem`, and `map-stack.ts`; do not replace the sidebar architecture.
- Reuse the Phase 1008 `renderAs.ts` utility for row render labels.
- Keep mutation wiring on existing `useBuilderLayers` handlers: `handleOpacityChange` and `handleLayoutChange`.

### Dataset Headers
- Dataset-rendering headers are derived from data-group entries by `metadata.sourceDatasetId`.
- Headers render only when the count is two or more.
- Header metadata is limited to current response fields: dataset name, record/source type, geometry type, feature count, and count of renderings.
- No LIVE badge unless a future API field supports it.

### Zoom Range
- Row zoom controls write a full layout object that preserves existing layout keys while changing only `_minzoom` and `_maxzoom`.
- The controls must not write MapLibre real layout keys or new persisted fields.
</decisions>

<specifics>
## Specific Ideas

- Add compact row controls using existing shadcn/Radix primitives: `Button`, `Badge`, `Popover`, `Slider`, `Collapsible`.
- Keep row height predictable and text truncation stable.
- Add focused component tests for row anatomy, dataset headers, omitted LIVE metadata, opacity writes, and zoom-range writes.
</specifics>

<deferred>
## Deferred Ideas

- RenderAs mutation dispatch belongs to Phase 1010.
- Duplicate-rendering creation belongs to Phase 1010.
- Basemap row consolidation and terrain inline row actions belong to Phase 1011.
- Add Dataset modal changes belong to Phase 1012.
- Playwright visual validation belongs to Phase 1013 after the full sidebar/modal surface exists.
</deferred>

---

*Phase: 1009-layer-row-and-dataset-rendering-sidebar*
*Context gathered: 2026-05-12 from current code and scoped handoff*

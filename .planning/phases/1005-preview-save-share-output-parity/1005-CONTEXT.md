# Phase 1005: Preview, Save, Share, and Output Parity - Context

**Gathered:** 2026-05-11  
**Status:** Ready for planning  
**Source:** Roadmap, v1001 requirements, Phase 1002 inventory, Phase 1003/1004 summaries

<domain>
## Phase Boundary

Phase 1005 ensures the map a user authors in the builder is represented consistently in saved-map detail, shared-token public view, authenticated public view, and embedded output. The work should stay focused on preview/save/share/output parity, stable layer identity, and save-state clarity.

This phase should preserve the existing builder and public-viewer MapLibre architecture, including the shared layer-adapter path introduced by earlier milestones. Builder-only controls must stay out of public and embedded outputs.
</domain>

<decisions>
## Implementation Decisions

### Locked Scope
- Address OUTPUT-01 through OUTPUT-06.
- Close the Phase 1002 output-parity findings routed here: F-1002-01 public/order parity residual, F-1002-05 dirty/saved state clarity, and F-1002-07 public viewer legend identity.
- Preserve Phase 1003's stable add-layer ordering behavior for newly added layers.
- Preserve Phase 1004's `paint`, `style_config`, filter, label, popup, raster, DEM, and basemap contracts.
- Do not start Phase 1006 responsive/accessibility/copy hardening or Phase 1007 durable QA closeout.

### Output Identity
- Public output controls should use stable layer identity where possible, not `sort_order`, because legacy or imported maps can still contain duplicate orders.
- Authenticated public maps can use `MapLayerResponse.id`; shared-token maps should accept stable IDs if present and fall back conservatively for old responses.

### Save and Share Semantics
- Save feedback must distinguish unsaved, saving, saved, failed, and retryable states.
- Share/embed paths must communicate when public outputs still reflect the last saved version.

### Thumbnail Scope
- OUTPUT-06 is discovery-only for this phase. Record whether server-side thumbnails are needed for builder polish, but do not implement OPS-01.
</decisions>

<specifics>
## Specific Ideas

- Add a viewer-layer identity helper reused by shared-token viewer, authenticated viewer, legend, and viewer map sync.
- Change viewer visibility state from order-number identity to layer-key identity.
- Include authenticated map layer IDs in `toSharedLayer`; keep fallback identity for older shared payloads.
- Add save-status metadata to `useBuilderSave` and render it in `MapTitleBar`.
- Show a concise unsaved-output warning inside `ShareDialog` when a user opens share/embed before saving.
- Extend focused Vitest coverage for `LayerLegend`, `useViewerLayers`, `ViewerMap`, `PublicMapViewerPage`, `MapTitleBar`, `SharePanel`, and `useBuilderSave` as touched.
</specifics>

<deferred>
## Deferred Ideas

- Full server-side thumbnail pipeline remains OPS-01 / NEXT-04.
- Broad screenshot QA and cross-viewport accessibility gates remain Phase 1007 and Phase 1006 respectively.
- New export formats, collaboration, annotation layers, time sliders, and wholesale Kepler.gl replacement remain out of scope.
</deferred>

---

*Phase: 1005-preview-save-share-output-parity*  
*Context gathered: 2026-05-11*

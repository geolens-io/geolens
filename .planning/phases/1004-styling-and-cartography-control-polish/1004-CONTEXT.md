# Phase 1004: Styling and Cartography Control Polish - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning
**Milestone:** v1001 Map Builder UI/UX Polish Sweep

<domain>
## Phase Boundary

Phase 1004 smooths high-friction styling controls in the existing GeoLens builder inspector while preserving the current `paint`, `style_config`, MapLibre style JSON, import/export, and public rendering contracts. This phase owns selected-layer styling, filters, labels, popups, compact swatches, validation copy, and reset/recovery affordances. It must not introduce a new builder architecture or backend schema.

## Inputs

- Roadmap goal: Smooth high-friction styling controls while preserving the existing style contracts.
- Requirements: STYLE-01 through STYLE-08.
- Phase 1002 routed finding: F-1002-04 says filter scope is selected-layer-specific but the UI reads like a general map filter.
- Phase 1003 completed in commit `29c6794c`: Map Stack rows, selected/hidden/error-like state badges, data-first empty state, and inspector focus polish are now stable.
</domain>

<decisions>
## Implementation Decisions

### Locked

- Keep the current `paint` and `style_config` shapes. Builder-only UI state remains under `style_config.builder`; MapLibre paint remains canonical for rendering.
- Preserve `stripLegacyBuilderPaint`, `normalizeLayerStyleState`, map-sync adapters, style JSON import/export, and public viewer output contracts.
- Keep layer filters layer-scoped. Rename and explain the filter panel as a selected-layer filter instead of implying map-wide filtering.
- Group controls by visual intent: symbol/render choice, data-driven classification, geometry appearance, effects/relief/raster adjustments, visibility/zoom, labels, popups, and advanced JSON.
- Add recoverable validation and unsupported-state messaging for style controls before expanding features.
- Add compact geometry-aware swatches to reflect pending style changes before save. The swatch can reuse existing icon/swatch helpers and current in-memory layer props.
- Reset/cancel actions must affect only styling state for the current layer, not filters, labels, popups, layer metadata, or unrelated map settings.

### Claude's Discretion

- Exact component factoring, helper names, and test granularity.
- Whether polish lands in one or multiple plans, as long as every STYLE requirement is traceable.
- Exact wording, provided it is action-oriented and i18n keys are complete for touched builder copy.
</decisions>

<specifics>
## Specific Ideas

- Add an inspector style summary row showing point/line/polygon/raster/DEM swatches and copy indicating preview is local until save.
- Use section containers for "Color and shape", "Data-driven style", "Effects", "Visibility range", "Advanced JSON", "Layer filter", "Labels", and "Popup".
- Surface unsupported `style_config`/paint expressions as non-destructive warnings that point users to Advanced JSON.
- For raster controls, validate brightness min/max ordering and keep reset limited to raster/hillshade paint plus opacity.
- For labels and popups, show clear no-column empty states so disabled controls do not feel broken.
- Test that geometry swatches and builder controls still emit the same `paint` and `style_config` updates expected by map-sync and public output.
</specifics>

<deferred>
## Deferred Ideas

- Preview/save/share/public output parity belongs to Phase 1005.
- Mobile sheet sizing, auth shell, and broad accessibility/copy hardening belong to Phase 1006.
- Durable screenshot and full workflow QA gates belong to Phase 1007.
- New cartographic features such as blending modes, annotations, temporal controls, or server-side thumbnails are out of scope.
</deferred>

---

*Phase: 1004-styling-and-cartography-control-polish*
*Context gathered: 2026-05-11 from roadmap, requirements, Phase 1002 inventory, and Phase 1003 summaries*

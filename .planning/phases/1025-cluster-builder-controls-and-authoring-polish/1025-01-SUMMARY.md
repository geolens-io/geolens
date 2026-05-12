# Phase 1025 Summary: Cluster Builder Controls And Authoring Polish

**Phase:** 1025 — cluster-builder-controls-and-authoring-polish
**Milestone:** v1005 Builder Point Cluster Foundation
**Completed:** 2026-05-12
**Requirements:** CLUS-06

## Completed

- Added Cluster as an eligible point render mode in the layer style editor while preserving the existing renderAs patch path.
- Added cluster authoring controls for radius, max cluster zoom, cluster color, count text color, and count text size using existing builder UI primitives.
- Stored cluster authoring state under existing `style_config.builder` keys only; no persisted schema fields or new UI primitives were introduced.
- Taught the MapLibre cluster adapter to apply count text size and sync it live.
- Rebuilt clustered GeoJSON sources when source-level cluster options change, so radius/max zoom updates take effect without stale source state.
- Extended live map sync so cluster companion layers follow parent visibility, opacity, filters, and zoom range during authoring edits.
- Added snake_case normalization for `cluster_text_size` in imported style config paths.
- Localized cluster control copy in English, Spanish, French, and German.
- Added focused tests for cluster style-editor controls, renderAs patch defaults, cluster source rebuilds, and normalization.

## Notes

- Cluster remains gated by the bounded GeoJSON eligibility rules from Phase 1023.
- The implementation keeps normal point appearance controls available for unclustered points in cluster mode.
- The existing Vite large `map-vendor` chunk warning remains unchanged and predates this phase.

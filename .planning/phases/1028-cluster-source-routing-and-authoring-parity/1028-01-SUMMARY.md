# Phase 1028 Summary: Cluster Source Routing and Authoring Parity

**Status:** Complete
**Completed:** 2026-05-12
**Milestone:** v1006 Large Dataset Cluster Scaling

## One-Liner

Cluster authoring now supports both bounded client-side GeoJSON clusters and large-dataset server-side cluster vector tiles without changing persisted layer fields.

## Completed

- Added cluster source strategies:
  - `bounded-geojson` for point Cluster layers at or below the bounded GeoJSON limit;
  - `server-tile` for point Cluster layers above the bounded limit;
  - `fallback` for unsupported geometry, non-vector layers, or missing feature counts.
- Changed the renderAs capability model so Cluster is offered for bounded and large point datasets with count metadata.
- Added `buildClusterTileUrl()` for `/tiles/clusters/data.{table}/{z}/{x}/{y}.pbf`, preserving normal `sig`, `exp`, `scope`, `_v`, `cluster_radius`, and `cluster_max_zoom` params.
- Updated map sync to:
  - keep bounded Cluster on clustered GeoJSON sources;
  - route large Cluster to vector sources using server cluster tiles;
  - keep unsupported Cluster intent on the existing Point fallback path;
  - refresh server cluster vector source URLs when tokens or cluster options change.
- Updated cluster companion layers to emit `source-layer` for server cluster vector sources while continuing to omit it for GeoJSON sources.
- Updated builder and viewer bounded GeoJSON fetch logic so large server Cluster layers do not trigger full-table client data loads.

## Requirements Closed

- REND-01: Builder renderAs eligibility exposes Cluster for large point datasets.
- REND-02: Cluster changes still write only existing `style_config.render_mode` / `style_config.builder` plus existing paint/layer fields.
- REND-03: Map sync chooses bounded GeoJSON, server cluster tiles, or Point fallback by source strategy.
- REND-04: Builder and viewer paths share the same source strategy and preserve auth/embed token context.
- REND-05: Existing cluster style controls feed both bounded and server cluster source options.

## Deferred

- Cluster click/keyboard exploration interactions and aggregate popups.
- Legend/sidebar copy distinguishing bounded/server/fallback states.
- Style JSON metadata policy for server cluster sources.
- Live Playwright MCP UAT with a seeded large point dataset.

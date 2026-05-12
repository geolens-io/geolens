# Phase 1027 Summary: Server Cluster Tile Contract

**Status:** Complete
**Completed:** 2026-05-12
**Milestone:** v1006 Large Dataset Cluster Scaling

## One-Liner

Shipped the backend contract for authenticated, cache-separated, bounded server-side cluster vector tiles for point datasets.

## Completed

- Added `GET /tiles/clusters/data.{table}/{z}/{x}/{y}.pbf`.
- Refactored existing vector tile parsing, coordinate validation, dataset metadata lookup, authorization, and response headers into shared helpers used by normal and cluster tile routes.
- Added point-dataset validation so cluster tiles only serve vector point datasets.
- Added cluster tile query options:
  - `cluster_radius` bounded to `1..256`, default `48`;
  - `cluster_max_zoom` bounded to `0..22`, default `14`.
- Added bounded PostGIS MVT query generation:
  - spatial envelope filter using `ST_TileEnvelope`;
  - validated `data.{table}` identifier;
  - candidate cap and MVT feature cap;
  - cluster properties `cluster`, `point_count`, `point_count_abbreviated`, `cluster_id`, `expansion_zoom`, and `source_gid`;
  - unclustered points retain source gid identity.
- Added cluster cache keys shaped as `{table}:cluster:r{radius}:z{maxZoom}` so normal vector tiles and cluster tiles do not collide.
- Added tests for:
  - cluster endpoint returning gzipped MVT;
  - non-point dataset rejection;
  - cluster option cache-key separation;
  - private cluster tiles requiring and accepting normal HMAC signatures;
  - cluster SQL property shape;
  - embed-token cluster tile access.

## Requirements Closed

- SCL-01: Backend exposes a cluster tile/source contract for vector point datasets without new persisted fields.
- SCL-02: Cluster tile access reuses existing vector tile auth for public, signed private, and embed-token contexts; API-key behavior remains through the existing token/access model.
- SCL-03: Cluster tiles emit predictable cluster and unclustered properties needed by MapLibre rendering and future interactions.
- SCL-04: Cluster SQL is bounded and identifier-validated, with controlled `204`, `429`, and `503` responses.
- SCL-05: Cluster tile cache keys are separate from normal vector tile keys and include cluster-relevant options.

## Deferred

- Frontend source routing to this endpoint.
- Large-dataset Cluster eligibility in the builder.
- Cluster zoom/expand interactions and aggregate popups.
- Performance budget validation against a seeded or synthetic large point dataset.
- Playwright MCP live browser UAT, which belongs to later v1006 phases once the frontend can route to server-side cluster tiles.

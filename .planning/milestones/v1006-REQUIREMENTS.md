# Requirements: v1006 Large Dataset Cluster Scaling

**Defined:** 2026-05-12
**Shipped:** 2026-05-12
**Status:** 25 / 25 complete

## Milestone Goal

Extend v1005 Point Cluster from bounded client-side GeoJSON datasets to large point datasets by adding a server-side clustered tile/source path, preserving the existing saved-map shape and renderer controls, and adding the expected cluster exploration interactions without regressing normal vector tiles.

## Requirement Coverage

| Group | Requirements | Status |
|---|---|---|
| Server-side cluster tile contract | SCL-01..05 | 5/5 complete |
| Renderer routing and authoring | REND-01..05 | 5/5 complete |
| Cluster exploration UX | UX-01..04 | 4/4 complete |
| Compatibility and interop | COMP-01..05 | 5/5 complete |
| QA and closeout | QA-01..06 | 6/6 complete |

## Completed Requirements

### Server-Side Cluster Tile Contract

- [x] **SCL-01**: Backend exposes a cluster tile/source contract for vector point datasets above the bounded GeoJSON limit without adding new top-level map or layer fields.
- [x] **SCL-02**: Cluster tile access uses the existing vector tile authorization model, including public datasets, signed private tiles, API-key access, and embed-token access.
- [x] **SCL-03**: Cluster tiles emit predictable feature properties for cluster and unclustered features, including count labels and stable identifiers needed for interaction.
- [x] **SCL-04**: Cluster tile SQL is bounded by tile envelope, zoom, feature budgets, and validated table/column names, and returns controlled empty/error responses instead of raw failures.
- [x] **SCL-05**: Tile caching separates normal vector tiles from cluster tiles and includes cluster-relevant options in the cache key.

### Renderer Routing And Authoring

- [x] **REND-01**: Builder eligibility exposes Cluster for large vector point datasets when the server-side cluster contract is available.
- [x] **REND-02**: Switching large point datasets to Cluster writes only existing fields and preserves the v1005 `style_config.render_mode` / `style_config.builder` contract.
- [x] **REND-03**: Map sync chooses bounded client-side GeoJSON clustering for small datasets, server-side cluster tiles for large datasets, and normal Point fallback when clustering is unsupported.
- [x] **REND-04**: Builder, public, shared, and embed viewers use the same source-routing policy and preserve auth/API-key/embed-token context.
- [x] **REND-05**: Existing cluster controls for radius, max zoom, color, count color, and count text size apply consistently to server-side and bounded client-side clusters.

### Cluster Exploration UX

- [x] **UX-01**: User can click or keyboard-activate a cluster to zoom toward the clustered features without mutating the saved map view until save.
- [x] **UX-02**: User can inspect a cluster aggregate popup with count and bounded summary/sample information without triggering an expensive full-table scan.
- [x] **UX-03**: Legend, map stack, and row states clarify whether a layer is using bounded client-side clustering, server-side clustering, or Point fallback.
- [x] **UX-04**: Cluster interaction affordances work with pointer, keyboard, and touch input and do not interfere with existing popup/label behavior.

### Compatibility And Interop

- [x] **COMP-01**: Existing normal vector tile behavior and cache semantics remain unchanged for non-cluster render modes.
- [x] **COMP-02**: Existing bounded client-side Cluster behavior remains available and unchanged for small eligible point datasets.
- [x] **COMP-03**: Saved maps with Cluster intent reload in builder and public/shared/embed viewers regardless of whether the source path resolves to bounded GeoJSON, server tiles, or Point fallback.
- [x] **COMP-04**: Style JSON export/import preserves Cluster intent and documents any standalone fallback policy for server-side cluster sources.
- [x] **COMP-05**: Existing Point, Symbol, Heatmap, Arrow, Fill/Stroke, 3D extrusion, Raster, Hillshade, basemap, terrain, duplicate rendering, and Add Dataset behavior remains unchanged.

### QA And Closeout

- [x] **QA-01**: Backend tests cover cluster tile SQL/query construction, auth behavior, cache-key separation, empty tiles, and controlled error paths.
- [x] **QA-02**: Frontend tests cover eligibility, source routing, map-sync updates, style controls, fallback states, and companion-layer lifecycle.
- [x] **QA-03**: Public/shared/embed viewer tests prove server-side Cluster works with the same access contexts as normal tiles.
- [x] **QA-04**: Performance validation uses a seeded or synthetic large point dataset to prove cluster tiles avoid full-table GeoJSON and stay within a documented response budget.
- [x] **QA-05**: Playwright MCP verifies a live large point dataset can switch to Cluster, save, reload, interact with clusters, and remain console-clean.
- [x] **QA-06**: Focused Vitest, backend pytest, i18n checks, frontend lint, frontend build, backend ruff, builder smoke, and relevant Playwright specs pass before milestone close.

## Future Requirements

- Hexbin and H3 aggregation renderers.
- Animated path / Trips rendering plus map-level timeline controls.
- Point 3D extrusion.
- Cross-layer filters, recipes, blend mode, and persisted basemap appearance presets.
- Exact-position drag from Add Dataset directly into the stack.
- Full analytics-grade aggregation controls beyond cluster count/sample summaries.

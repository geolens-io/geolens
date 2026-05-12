# Requirements: v1006 Large Dataset Cluster Scaling

**Defined:** 2026-05-12
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Milestone Goal

Extend v1005 Point Cluster from bounded client-side GeoJSON datasets to large point datasets by adding a server-side clustered tile/source path, preserving the existing saved-map shape and renderer controls, and adding the expected cluster exploration interactions without regressing normal vector tiles.

## Constraints

- Preserve `Map`, `MapLayer`, `Dataset`, and `Record` persisted schemas unless implementation proves a narrowly justified migration is unavoidable.
- Keep Cluster intent in existing `style_config.render_mode` / `style_config.builder` fields.
- Do not replace the normal vector-tile path for Point, Symbol, Heatmap, Arrow, Fill/Stroke, Raster, Hillshade, or bounded client-side Cluster.
- Reuse existing vector tile auth, public visibility, API-key, embed-token, cache, and map-sync patterns where possible.
- Keep cluster queries bounded by tile envelope, zoom, feature limits, and cache keys; large datasets must not fall back to full-table GeoJSON.
- Keep MapLibre-first architecture; no deck.gl/H3 dependency in this milestone.

## v1006 Requirements

### Server-Side Cluster Tile Contract

- [x] **SCL-01**: Backend exposes a cluster tile/source contract for vector point datasets above the bounded GeoJSON limit without adding new top-level map or layer fields.
- [x] **SCL-02**: Cluster tile access uses the existing vector tile authorization model, including public datasets, signed private tiles, API-key access, and embed-token access.
- [x] **SCL-03**: Cluster tiles emit predictable feature properties for cluster and unclustered features, including count labels and stable identifiers needed for interaction.
- [x] **SCL-04**: Cluster tile SQL is bounded by tile envelope, zoom, feature budgets, and validated table/column names, and returns controlled empty/error responses instead of raw failures.
- [x] **SCL-05**: Tile caching separates normal vector tiles from cluster tiles and includes cluster-relevant options in the cache key.

### Renderer Routing And Authoring

- [ ] **REND-01**: Builder eligibility exposes Cluster for large vector point datasets when the server-side cluster contract is available.
- [ ] **REND-02**: Switching large point datasets to Cluster writes only existing fields and preserves the v1005 `style_config.render_mode` / `style_config.builder` contract.
- [ ] **REND-03**: Map sync chooses bounded client-side GeoJSON clustering for small datasets, server-side cluster tiles for large datasets, and normal Point fallback when clustering is unsupported.
- [ ] **REND-04**: Builder, public, shared, and embed viewers use the same source-routing policy and preserve auth/API-key/embed-token context.
- [ ] **REND-05**: Existing cluster controls for radius, max zoom, color, count color, and count text size apply consistently to server-side and bounded client-side clusters.

### Cluster Exploration UX

- [ ] **UX-01**: User can click or keyboard-activate a cluster to zoom toward the clustered features without mutating the saved map view until save.
- [ ] **UX-02**: User can inspect a cluster aggregate popup with count and bounded summary/sample information without triggering an expensive full-table scan.
- [ ] **UX-03**: Legend, map stack, and row states clarify whether a layer is using bounded client-side clustering, server-side clustering, or Point fallback.
- [ ] **UX-04**: Cluster interaction affordances work with pointer, keyboard, and touch input and do not interfere with existing popup/label behavior.

### Compatibility And Interop

- [ ] **COMP-01**: Existing normal vector tile behavior and cache semantics remain unchanged for non-cluster render modes.
- [ ] **COMP-02**: Existing bounded client-side Cluster behavior remains available and unchanged for small eligible point datasets.
- [ ] **COMP-03**: Saved maps with Cluster intent reload in builder and public/shared/embed viewers regardless of whether the source path resolves to bounded GeoJSON, server tiles, or Point fallback.
- [ ] **COMP-04**: Style JSON export/import preserves Cluster intent and documents any standalone fallback policy for server-side cluster sources.
- [ ] **COMP-05**: Existing Point, Symbol, Heatmap, Arrow, Fill/Stroke, 3D extrusion, Raster, Hillshade, basemap, terrain, duplicate rendering, and Add Dataset behavior remains unchanged.

### QA And Closeout

- [ ] **QA-01**: Backend tests cover cluster tile SQL/query construction, auth behavior, cache-key separation, empty tiles, and controlled error paths.
- [ ] **QA-02**: Frontend tests cover eligibility, source routing, map-sync updates, style controls, fallback states, and companion-layer lifecycle.
- [ ] **QA-03**: Public/shared/embed viewer tests prove server-side Cluster works with the same access contexts as normal tiles.
- [ ] **QA-04**: Performance validation uses a seeded or synthetic large point dataset to prove cluster tiles avoid full-table GeoJSON and stay within a documented response budget.
- [ ] **QA-05**: Playwright MCP verifies a live large point dataset can switch to Cluster, save, reload, interact with clusters, and remain console-clean.
- [ ] **QA-06**: Focused Vitest, backend pytest, i18n checks, frontend lint, frontend build, backend ruff, builder smoke, and relevant Playwright specs pass before milestone close.

## Future Requirements

- Hexbin and H3 aggregation renderers.
- Animated path / Trips rendering plus map-level timeline controls.
- Point 3D extrusion.
- Cross-layer filters, recipes, blend mode, and persisted basemap appearance presets.
- Exact-position drag from Add Dataset directly into the stack.
- Full analytics-grade aggregation controls beyond cluster count/sample summaries.

## Out of Scope

| Feature | Reason |
|---|---|
| deck.gl renderer adoption | v1006 can extend MapLibre/PostGIS clustering first without a second rendering stack. |
| H3/Hexbin implementation | These need different aggregation semantics and have ADRs from v1004. |
| Timeline playback | Time filtering and playback state are larger than clustering and remain a separate capability milestone. |
| Persisted cluster recipe/editor model | v1006 should keep the existing `style_config` contract and avoid new recipe tables. |
| Full-table GeoJSON fallback for large datasets | This is the problem v1006 is avoiding; fallback must be Point/vector-tile or bounded server output. |

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| SCL-01 | Phase 1027 | Complete |
| SCL-02 | Phase 1027 | Complete |
| SCL-03 | Phase 1027 | Complete |
| SCL-04 | Phase 1027 | Complete |
| SCL-05 | Phase 1027 | Complete |
| REND-01 | Phase 1028 | Pending |
| REND-02 | Phase 1028 | Pending |
| REND-03 | Phase 1028 | Pending |
| REND-04 | Phase 1028 | Pending |
| REND-05 | Phase 1028 | Pending |
| UX-01 | Phase 1029 | Pending |
| UX-02 | Phase 1029 | Pending |
| UX-03 | Phase 1029 | Pending |
| UX-04 | Phase 1029 | Pending |
| COMP-01 | Phase 1030 | Pending |
| COMP-02 | Phase 1030 | Pending |
| COMP-03 | Phase 1030 | Pending |
| COMP-04 | Phase 1030 | Pending |
| COMP-05 | Phase 1030 | Pending |
| QA-01 | Phase 1031 | Pending |
| QA-02 | Phase 1031 | Pending |
| QA-03 | Phase 1031 | Pending |
| QA-04 | Phase 1031 | Pending |
| QA-05 | Phase 1031 | Pending |
| QA-06 | Phase 1031 | Pending |

**Coverage:**
- v1006 requirements: 25 total
- Complete: 5
- Pending: 20
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-05-12*
*Last updated: 2026-05-12 after Phase 1027 completion*

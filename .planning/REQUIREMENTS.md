# Requirements: v1005 Builder Point Cluster Foundation

**Defined:** 2026-05-12
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Milestone Goal

Ship Point Cluster safely for eligible point datasets by proving a bounded GeoJSON source path, preserving saved-map compatibility, and falling back cleanly when clustering is not supported. v1005 remains MapLibre-first: no deck.gl, no H3 dependency, no schema migration, and no server-side clustered tile endpoint unless the existing feature-serving contract proves insufficient during implementation.

## Constraints

- Preserve `Map`, `MapLayer`, `Dataset`, and `Record` persisted schemas.
- Store cluster renderer intent only in existing writable fields: `layer_type`, `style_config`, `paint`, and `layout`.
- Do not write `is_3d` from sidebar, modal, or cluster code.
- Do not replace the default vector-tile path for normal point rendering.
- Do not expose Cluster for large, truncated, non-point, raster, DEM, or unsupported layers.
- Keep v1002-v1004 sidebar, Add Dataset, duplicate rendering, basemap, terrain, Arrow, saved-map, public-viewer, and shared-viewer behavior intact.

## v1005 Requirements

### Cluster Source Eligibility

- [x] **SRC-01**: Builder code exposes `Cluster` only for vector point layers whose dataset metadata advertises a safe bounded GeoJSON source path.
- [x] **SRC-02**: Cluster eligibility uses existing dataset metadata, including `dataset_geometry_type` and `dataset_feature_count`, without adding backend schema fields.
- [x] **SRC-03**: Cluster source loading fetches bounded GeoJSON only for cluster layers and never for ordinary Point, Symbol, or Heatmap renderers.
- [x] **SRC-04**: Builder, public, shared, and embed viewers pass the same auth/API-key/embed-token context used by existing GeoJSON-Z fetching.
- [x] **SRC-05**: Oversized, truncated, failed, or unsupported cluster source loads degrade to the normal Point renderer with a visible nonblocking warning in authoring contexts.

### Cluster RenderAs And MapLibre Rendering

- [x] **CLUS-01**: Point layers can switch to `Cluster` through the renderer capability registry when `SRC-01` eligibility is true.
- [x] **CLUS-02**: Switching to Cluster writes only existing fields and records intent under `style_config.render_mode` / `style_config.builder`.
- [x] **CLUS-03**: Cluster rendering uses a MapLibre GeoJSON source with `cluster`, `clusterRadius`, and `clusterMaxZoom` options rather than a new renderer dependency.
- [x] **CLUS-04**: Cluster rendering emits stable cluster circle, cluster count, and unclustered point layers while preserving the parent layer identity for map-stack and popup workflows.
- [x] **CLUS-05**: Cluster layers follow parent visibility, filter, opacity, zoom range, reorder, removal, and stale-cleanup behavior.
- [ ] **CLUS-06**: Users can configure basic cluster radius, max zoom, color, and count-label appearance using existing builder controls and i18n keys.

### Compatibility And Interop

- [ ] **COMP-01**: Existing Point, Symbol, Heatmap, Arrow, Fill/Stroke, 3D extrusion, Raster, and Hillshade renderAs behavior remains unchanged.
- [ ] **COMP-02**: Saved maps with Cluster intent reload in builder and viewers without adding, removing, or renaming persisted fields.
- [ ] **COMP-03**: Style JSON export/import preserves Cluster renderer intent or uses an explicit Point fallback when authenticated GeoJSON data cannot be represented in a standalone style.
- [ ] **COMP-04**: Public/shared/embed viewers render eligible Cluster layers or degrade to Point with no map crash and no noisy console error loops.

### QA And Closeout

- [ ] **QA-01**: Focused renderAs tests prove Cluster visibility, existing-field patch discipline, and unsupported renderer omissions.
- [ ] **QA-02**: Focused map-sync/adapter tests prove cluster layer add, update, visibility, filter, opacity, zoom, reorder, and stale cleanup behavior.
- [ ] **QA-03**: Backend style JSON tests prove Cluster export/import policy and fallback behavior.
- [ ] **QA-04**: Playwright MCP verifies a live eligible point layer can switch to Cluster, save, reload, and render without new console warnings/errors.
- [ ] **QA-05**: Focused Vitest, backend pytest, i18n checks, frontend lint, frontend build, ruff, and builder smoke pass before milestone close.

## Future Requirements

- Server-side clustered vector-tile endpoint for large point datasets.
- Cluster expansion/drill-down interactions and cluster-to-bounds camera actions.
- Cluster legends and aggregate popup summaries.
- Hexbin and H3 aggregation renderers.
- Animated path / Trips rendering plus map-level timeline controls.
- Point 3D extrusion.
- Cross-layer filters, recipes, blend mode, and persisted basemap appearance presets.
- Exact-position drag from Add Dataset directly into the stack.

## Out of Scope

| Feature | Reason |
|---|---|
| Database migrations or new persisted renderer tables | v1005 should preserve the schema discipline established in v1002-v1004. |
| Unconditional Cluster on every point layer | Large vector-tile-backed datasets need server-side clustering or another bounded source path first. |
| Server-side clustered vector-tile endpoint | Valuable follow-up, but too large for this milestone unless the existing bounded GeoJSON path proves unusable. |
| deck.gl adoption | Cluster can be attempted with native MapLibre GeoJSON clustering before adding a new rendering stack. |
| Hexbin/H3/Animated path/Point 3D extrusion implementation | These have separate ADRs and require different data-shape/dependency decisions. |
| Map timeline playback | Timeline state is larger than a renderer chip and remains a separate capability milestone. |
| New catalog/import APIs | Cluster should rely on current dataset metadata and feature-serving contracts unless implementation proves a narrow compatibility endpoint is required. |

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| SRC-01 | Phase 1023 | Complete |
| SRC-02 | Phase 1023 | Complete |
| SRC-03 | Phase 1023 | Complete |
| SRC-04 | Phase 1023 | Complete |
| SRC-05 | Phase 1023 | Complete |
| CLUS-01 | Phase 1024 | Complete |
| CLUS-02 | Phase 1024 | Complete |
| CLUS-03 | Phase 1024 | Complete |
| CLUS-04 | Phase 1024 | Complete |
| CLUS-05 | Phase 1024 | Complete |
| CLUS-06 | Phase 1025 | Pending |
| COMP-01 | Phase 1026 | Pending |
| COMP-02 | Phase 1026 | Pending |
| COMP-03 | Phase 1026 | Pending |
| COMP-04 | Phase 1026 | Pending |
| QA-01 | Phase 1026 | Pending |
| QA-02 | Phase 1026 | Pending |
| QA-03 | Phase 1026 | Pending |
| QA-04 | Phase 1026 | Pending |
| QA-05 | Phase 1026 | Pending |

**Coverage:**
- v1005 requirements: 20 total
- Complete: 10
- Pending: 10
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-05-12*
*Last updated: 2026-05-12 after Phase 1024 completion*

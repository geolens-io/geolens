# Requirements: v1004 Builder Renderer Expansion

**Defined:** 2026-05-12
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Milestone Goal

Add the next Map Builder render modes through a deliberate renderer capability layer. v1004 is MapLibre-first: it ships safe renderer expansion where the current stack supports it, and it records explicit architecture decisions before any deck.gl/H3/trips dependency enters the product.

## Constraints

- Preserve `Map`, `MapLayer`, `Dataset`, and `Record` persisted schemas.
- Store new renderer intent only in existing writable fields: `layer_type`, `style_config`, `paint`, and `layout`.
- Do not write `is_3d` from sidebar or modal code.
- Do not add deck.gl, h3-js, or other renderer dependencies until an ADR proves data flow, bundle budget, z-order, picking, terrain behavior, and viewer compatibility.
- Keep v1002-v1003 sidebar, Add Dataset, duplicate rendering, basemap, terrain, saved-map, public-viewer, and shared-viewer behavior intact.

## v1004 Requirements

### Renderer Capability Architecture

- [ ] **ARCH-01**: Builder code has a renderer capability registry that describes each renderAs option by geometry, record type, renderer backend, source requirement, persisted write shape, companion-layer behavior, viewer support, and style JSON support.
- [ ] **ARCH-02**: Sidebar and Add Dataset renderAs menus show only options supported by the selected layer's dataset metadata and source delivery path; unsupported renderer chips remain absent.
- [ ] **ARCH-03**: The renderer adapter contract can describe companion layers and cleanup IDs without breaking existing MapLibre adapters.
- [ ] **ARCH-04**: Every v1004-visible renderer has an explicit saved-map, public/shared viewer, and style JSON export/import policy.
- [ ] **ARCH-05**: Point Cluster has a documented go/no-go decision based on the current vector-tile source path versus a bounded GeoJSON or server-side clustered source path.

### Line Arrow Renderer

- [ ] **ARROW-01**: Line layers can expose `Arrow` as a renderAs option when the capability registry confirms a MapLibre-native companion-symbol renderer is available.
- [ ] **ARROW-02**: Switching a line layer to `Arrow` writes only existing fields and records intent under `style_config.render_mode` / `style_config.builder`.
- [ ] **ARROW-03**: Arrow rendering adds a stable companion MapLibre `symbol` layer placed along the line while preserving the primary line layer.
- [ ] **ARROW-04**: Arrow companion layers follow the parent layer's visibility, filter, opacity, zoom range, reorder, removal, and stale-cleanup behavior.
- [ ] **ARROW-05**: Users can configure basic arrow appearance using existing builder controls or minimal new controls composed from existing UI primitives.

### Cluster And Advanced Renderer Decisions

- [ ] **DECIDE-01**: Cluster remains hidden unless the milestone proves a safe source path; if deferred, the decision artifact explains the exact blocker and future implementation path.
- [ ] **DECIDE-02**: Hexbin has an ADR covering deck.gl HexagonLayer versus server-side aggregation, required data shape, bundle impact, and saved-map/viewer implications.
- [ ] **DECIDE-03**: H3 has an ADR covering required H3 index column detection, h3-js/deck.gl dependency impact, and fallback when the dataset lacks compatible cells.
- [ ] **DECIDE-04**: Animated path has an ADR covering required path/timestamp data shape, timeline/playback state, and why it is or is not part of v1004.
- [ ] **DECIDE-05**: Point 3D extrusion has an ADR covering MapLibre-only feasibility versus deck.gl ColumnLayer-style rendering and why it is or is not part of v1004.

### Compatibility And QA

- [ ] **QA-01**: Existing renderAs options from v1002-v1003 still patch only existing writable fields and continue to pass their focused tests.
- [ ] **QA-02**: New renderer state round-trips through builder save/reload without adding, removing, or renaming persisted schema fields.
- [ ] **QA-03**: Public and shared viewers either render v1004-visible renderer state correctly or degrade through an explicit documented fallback.
- [ ] **QA-04**: Style JSON export/import preserves v1004-visible renderer intent or documents a deliberate unsupported-export fallback.
- [ ] **QA-05**: Focused Vitest, builder smoke, Playwright MCP browser inspection, frontend lint, and frontend build pass before milestone close.

## Future Requirements

- Full Point Cluster implementation if v1004 defers it after the source-path decision.
- Hexbin and H3 render modes after a deck.gl/server-side aggregation decision.
- Animated path / Trips rendering plus map-level timeline controls.
- Point 3D extrusion.
- Cross-layer filters, recipes, blend mode, and persisted basemap appearance presets.
- Exact-position drag from Add Dataset directly into the stack.

## Out Of Scope

| Feature | Reason |
|---|---|
| Database migrations or new persisted renderer tables | v1004 should preserve the schema discipline established in v1002-v1003. |
| Unconditional deck.gl adoption | deck.gl changes bundle size, z-order, picking, terrain, and data-loading architecture; it needs an ADR first. |
| Promising Cluster on all point layers | MapLibre clustering is GeoJSON-source based; current catalog layers usually render through vector tiles. |
| Hexbin/H3/Animated path implementation | These require new data shapes and likely a new renderer stack; v1004 records decisions unless explicitly proven safe. |
| Map timeline playback | Timeline state is larger than a renderer chip and remains a separate capability milestone. |
| New catalog/import APIs | Renderer work should prove current dataset metadata and layer delivery before adding backend discovery surfaces. |

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| ARCH-01 | TBD | Pending |
| ARCH-02 | TBD | Pending |
| ARCH-03 | TBD | Pending |
| ARCH-04 | TBD | Pending |
| ARCH-05 | TBD | Pending |
| ARROW-01 | TBD | Pending |
| ARROW-02 | TBD | Pending |
| ARROW-03 | TBD | Pending |
| ARROW-04 | TBD | Pending |
| ARROW-05 | TBD | Pending |
| DECIDE-01 | TBD | Pending |
| DECIDE-02 | TBD | Pending |
| DECIDE-03 | TBD | Pending |
| DECIDE-04 | TBD | Pending |
| DECIDE-05 | TBD | Pending |
| QA-01 | TBD | Pending |
| QA-02 | TBD | Pending |
| QA-03 | TBD | Pending |
| QA-04 | TBD | Pending |
| QA-05 | TBD | Pending |

**Coverage:**
- v1004 requirements: 20 total
- Complete: 0
- Pending: 20
- Mapped to phases: 0
- Unmapped: 20

# Requirements: v1003 Builder v1 Hardening

**Defined:** 2026-05-12
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## Milestone Goal

Prove and harden the v1002 Map Builder layer sidebar and Add Dataset redesign through durable browser, accessibility, and round-trip coverage. v1003 ships no schema changes, no new renderers, and no new catalog/import capabilities.

## Frozen Constraints

- `Map`, `MapLayer`, `Dataset`, and `Record` schemas remain unchanged.
- `is_3d` remains read-only from sidebar/modal code.
- Basemap and terrain controls write map-level fields only.
- Add Dataset continues to use the existing dataset search/import surfaces.
- UI work continues to compose `frontend/src/components/ui/*`, lucide, Tailwind, Radix, and existing builder components.
- Kepler.gl remains a functionality reference for layer/workflow expectations, not a dependency or visual model.

## v1003 Requirements

### Browser Baseline And Responsive Shell

- [x] **BQA-01**: Builder smoke tests cover the redesigned sidebar and Add Dataset modal on desktop and tablet widths using the real app stack.
- [x] **BQA-02**: Playwright MCP manual verification records the Map Stack, Add Dataset modal, basemap states, and tablet layout with no browser console errors or warnings beyond expected development-only messages.
- [x] **BQA-03**: Persisted desktop sidebar widths are capped on tablet/narrow desktop viewports so at least 320px of map canvas remains visible, while the stored desktop preference is preserved.
- [x] **BQA-04**: Builder accessibility checks pass for the map builder page and Add Dataset dialog, including keyboard-reachable controls and no axe violations in the scoped flows.
- [x] **BQA-05**: Focused frontend lint, build, and relevant Vitest suites pass before milestone close.

### Duplicate Rendering And RenderAs Behavior

- [x] **DUP-01**: A user can duplicate a dataset rendering from a layer-row overflow action, producing a sibling `MapLayer` with the same `dataset_id` and independent style fields.
- [x] **DUP-02**: A user can add another rendering from the Add Dataset modal when a dataset is already on the map, producing the same sibling-layer result as the row action.
- [x] **DUP-03**: Duplicate renderings appear under the dataset-rendering header with the correct `N renderings` count and remain individually visible, renameable, reorderable, and removable.
- [x] **DUP-04**: RenderAs changes for supported v1 modes patch only existing writable fields (`layer_type`, `style_config`, `paint`, `layout`) and never write `is_3d`.
- [x] **DUP-05**: Unsupported v1-punted renderers remain absent from the UI and tests: Cluster, Hexbin, H3, Arrow, Animated path, and Point 3D extrusion.

### Basemap And Terrain Integration

- [x] **MAPCTL-01**: Basemap swap updates `basemap_style`, `show_basemap_labels`, and supported `basemap_config` keys without creating or mutating basemap `MapLayer` rows.
- [x] **MAPCTL-02**: Basemap reset restores normalized default appearance and keeps overlay/data layers intact after the MapLibre style reload.
- [x] **MAPCTL-03**: Basemap Add Dataset modal states (`swap`, `in use`) update immediately after selection and remain consistent with the sidebar row.
- [x] **MAPCTL-04**: Terrain enabled state, exaggeration, and source selection write only `terrain_config` and survive save/reload.
- [x] **MAPCTL-05**: `Use as terrain` on raster-dem rows sets `terrain_config.source_dataset_id` without changing the DEM layer's persisted fields.

### Add Dataset Modal State Hardening

- [ ] **ADDH-01**: Add Dataset tabs remain `All`, `Vector`, `Raster`, and `Basemap`, with DEM datasets represented under Raster when supported by existing metadata.
- [ ] **ADDH-02**: Existing dataset search filters used by the modal match the current API contract; unsupported scope chips such as Curated/Your imports/Public remain absent.
- [ ] **ADDH-03**: Data rows correctly transition among `Add to map`, `(added)`, and `another rendering` states without a full page reload.
- [ ] **ADDH-04**: Expanded modal rows show preview and metadata from existing response fields and keep primary actions reachable by keyboard.
- [ ] **ADDH-05**: The modal footer routes to the existing ImportPage as `Import data...` and no import logic is reimplemented inside the modal.

### Saved-Map Round Trip And Closeout

- [ ] **ROUND-01**: Existing saved maps load and save without adding, removing, or renaming persisted `Map`, `MapLayer`, `Dataset`, or `Record` fields.
- [ ] **ROUND-02**: Saved maps containing duplicate renderings, basemap appearance config, terrain config, and zoom-range layout settings round-trip through builder save/reload unchanged.
- [ ] **ROUND-03**: Public/shared viewer behavior remains compatible with builder-authored basemap and terrain settings.
- [ ] **ROUND-04**: v1003 closeout documents exact verification commands, Playwright MCP findings, screenshots/snapshot notes where relevant, and any residual unrelated gaps.

## Future Requirements

- Cluster, Hexbin, H3, Arrow, Animated path, Point 3D extrusion, and additional Kepler-like renderers.
- Persisted basemap appearance presets or recipes.
- Map timeline and cross-layer time playback.
- Cross-layer filters.
- Org connector library, saved credentials, scheduled sync, and connector health.
- Cross-surface drag from Add Dataset directly into an exact stack position.
- Blend mode, once a specific MapLibre implementation decision exists.
- Curated, Your imports, and Public scope chips once the exact API contract is defined.
- Promote-imports-to-org administrative workflow.

## Out Of Scope

| Feature | Reason |
|---|---|
| Database migrations or new persisted fields | v1003 is a hardening milestone over the shipped v1002 schema-preserving UI rewrite. |
| New rendering engines or deck.gl/Kepler layer classes | Renderer work belongs in a separate capability milestone with MapLibre/deck.gl architecture decisions. |
| New catalog/import endpoints | The modal must prove the existing API surface before adding new catalog filters or import flows. |
| Basemap preset persistence | Saved presets need a separate contract and likely `BasemapEntry.default_config` design. |
| Exact-position drag from modal into stack | Cross-surface drag needs separate hit-testing, insertion preview, and keyboard accessibility design. |
| Full release validation across backend, SDKs, and CLI | v1003 owns builder UI hardening; broader release gates remain normal ship/release scope. |

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| BQA-01 | Phase 1014 | Complete |
| BQA-02 | Phase 1014 | Complete |
| BQA-03 | Phase 1014 | Complete |
| BQA-04 | Phase 1014 | Complete |
| BQA-05 | Phase 1014 | Complete |
| DUP-01 | Phase 1015 | Complete |
| DUP-02 | Phase 1015 | Complete |
| DUP-03 | Phase 1015 | Complete |
| DUP-04 | Phase 1015 | Complete |
| DUP-05 | Phase 1015 | Complete |
| MAPCTL-01 | Phase 1016 | Complete |
| MAPCTL-02 | Phase 1016 | Complete |
| MAPCTL-03 | Phase 1016 | Complete |
| MAPCTL-04 | Phase 1016 | Complete |
| MAPCTL-05 | Phase 1016 | Complete |
| ADDH-01 | Phase 1017 | Pending |
| ADDH-02 | Phase 1017 | Pending |
| ADDH-03 | Phase 1017 | Pending |
| ADDH-04 | Phase 1017 | Pending |
| ADDH-05 | Phase 1017 | Pending |
| ROUND-01 | Phase 1018 | Pending |
| ROUND-02 | Phase 1018 | Pending |
| ROUND-03 | Phase 1018 | Pending |
| ROUND-04 | Phase 1018 | Pending |

**Coverage:**
- v1003 requirements: 24 total
- Complete: 15
- Pending: 9
- Mapped to phases: 24
- Unmapped: 0

---
*Requirements defined: 2026-05-12*
*Last updated: 2026-05-12 after Phase 1016 verification*

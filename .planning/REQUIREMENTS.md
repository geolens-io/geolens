# Requirements: GeoLens v1027 Map Builder Architecture Simplification

**Defined:** 2026-05-25
**Core Value:** Users can find any dataset in the catalog in seconds - search, see it on a map, understand what it is, and get it out in the format they need.

## v1027 Requirements

### Architecture Baseline

- [x] **ARCH-01**: The current map-builder architecture is audited with code references for `MapBuilderPage`, `use-builder-layers`, `BuilderMap`, `ViewerMap`, `map-sync`, `basemap-utils`, layer adapters, editor scenes, and AI chat style/layer entry points.
- [x] **ARCH-02**: A concrete complexity budget is defined before refactoring, including target ownership boundaries, files that should shrink, and behaviors that must remain unchanged.
- [x] **ARCH-03**: The milestone documents all user-visible regression surfaces from the v1025-v1026 dogfooding run, including terrain exaggeration, gradient-to-solid style changes, remove basemap, duplicate layer, background color, layer options, save/reload, viewer/embed, and AI chat actions.
- [x] **ARCH-04**: The refactor plan explicitly preserves the v1026 style reconciliation contract and names any accepted limitations before implementation begins.

### Basemap State Consolidation

- [x] **BASEMAP-01**: Basemap settings use one canonical state contract for provider/style selection, visibility, opacity, terrain, exaggeration, background color, sublayer overrides, and blank/removed-basemap modes.
- [x] **BASEMAP-02**: Temporary split basemap state, including separate sublayer override state, is removed or wrapped behind one controller so persisted config and UI state cannot drift.
- [x] **BASEMAP-03**: Remove basemap works reliably, persists correctly, preserves the configured map background color, and does not leave stale MapLibre sources/layers after save/reload.
- [x] **BASEMAP-04**: Basemap state transitions are covered by focused unit tests for preset changes, remove/restore, background color, terrain exaggeration clamp, sublayer override changes, and reload normalization.

### Builder and Viewer Sync

- [x] **SYNC-01**: Builder and viewer map synchronization share a small orchestrator or shared contract for source/layer/style/background/terrain ordering instead of duplicating sequencing logic.
- [x] **SYNC-02**: Shared sync preserves source-before-layer ordering, companion-layer handling, style reconciler cleanup, terrain activation retries, basemap/background ordering, and MapLibre error isolation.
- [x] **SYNC-03**: Public viewer, embed viewer, builder reload, and style JSON import/export remain visually consistent for the target ADK map and representative non-ADK maps.
- [x] **SYNC-04**: Sync changes reduce duplication without creating a generic abstraction that hides layer-type-specific adapter behavior.

### Builder Scene and Hook Extraction

- [x] **SCENE-01**: `MapBuilderPage` delegates editor scene routing, settings wiring, dialog state, selection state, and screenshot/UAT affordances to focused controllers or hooks.
- [x] **SCENE-02**: `use-builder-layers` is split along stable mutation boundaries so layer CRUD, style mutations, persistence, history, and AI-facing actions can be reasoned about independently.
- [x] **SCENE-03**: Layer editor save semantics are made explicit in the UI and implementation, either by retaining immediate apply plus map-level save with clearer dirty state or by adding a local style apply/save control after a documented decision.
- [x] **SCENE-04**: Extraction does not change existing keyboard, drag/drop, mobile sheet, selection, dirty-state, or unsaved-change behavior.

### Layer Action Contract and AI Bridge

- [x] **ACTION-01**: Layer actions use a typed command boundary for add, remove, duplicate, reorder, visibility, style, label, filter, basemap, terrain, and settings updates instead of ad hoc object surgery.
- [x] **ACTION-02**: Duplicate layer works for supported layer types, creates collision-free layer/source identifiers, preserves intended style/config, and does not duplicate transient live-only state.
- [x] **ACTION-03**: Manual UI actions, undo/history, dirty tracking, persistence, and AI chat style/layer actions route through the same command semantics where practical.
- [x] **ACTION-04**: Any backend chat tool schema or generated API type changes required by the action contract are refreshed and verified; if no schema changes are needed, the decision is documented.

### Test Fixture DRY-Up

- [x] **TEST-01**: Builder tests use shared fixtures/factories for map state, basemap configs, layer descriptors, style reconciler mocks, and MapLibre test doubles.
- [x] **TEST-02**: Regression tests cover remove basemap, duplicate layer, terrain exaggeration, gradient-to-solid, background color, layer option changes, save/reload, and viewer/embed parity.
- [x] **TEST-03**: Tests avoid overfitting to implementation details introduced by the refactor and continue to assert durable user-visible behavior.
- [x] **TEST-04**: The builder-audit command or skill guidance is updated with lessons from the architecture refactor if new recurring QA checks or failure modes are discovered.

### Verification and Close Gate

- [x] **VERIFY-01**: Focused frontend tests for touched builder areas pass, plus `npm run typecheck`, `npm run lint`, and `npm run build`.
- [x] **VERIFY-02**: Backend tests, OpenAPI, and SDK checks run only if the milestone touches backend chat schemas or generated API surfaces; otherwise the no-backend-change decision is recorded.
- [x] **VERIFY-03**: Playwright MCP verifies the target map at `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd`, including all layer options, remove basemap, duplicate layer, background color, terrain exaggeration, gradient-to-solid, save/reload, and viewer parity.
- [x] **VERIFY-04**: The target map remains optimized for a marketing screenshot that demonstrates GeoLens cartographic ability without console errors, unexpected warnings, failed network requests, or distorted terrain.
- [x] **VERIFY-05**: Phase summaries, CHANGELOG, and the milestone audit document architecture impact, AI-chat impact, accepted limitations, and any follow-up requirements.

## Future Requirements

### Follow-Up Architecture

- **ARCH-FU-01**: Consider a fuller typed map-builder domain model only after v1027 proves the narrower command/controller extraction reduces complexity without slowing feature work.
- **ARCH-FU-02**: Consider extracting a dedicated map-preview package if builder/viewer/embed sync remains duplicated after the shared orchestrator phase.

### CI Infrastructure

- **CI-01-v1027**: Live-verify `pytest-parallel-isolation` on real GitHub Actions infrastructure after geolens-io billing is resolved. This rolling external blocker remains outside the map-builder architecture invariant.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Rebuilding the entire builder UI | v1027 simplifies architecture and clarifies existing workflows; it is not a visual redesign milestone. |
| Replacing MapLibre or the adapter model | Existing MapLibre imperative integration remains appropriate; the goal is clearer ownership and less duplication. |
| New cartographic feature expansion | New controls should wait unless they are required to preserve or clarify existing behavior. |
| Broad AI chat redesign | AI chat is in scope only where map/layer/style actions cross the builder action boundary. |
| Closing the GitHub Actions billing blocker | CI live-verify remains an external operator prerequisite carried forward from earlier milestones. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ARCH-01 | Phase 1118 | Complete |
| ARCH-02 | Phase 1118 | Complete |
| ARCH-03 | Phase 1118 | Complete |
| ARCH-04 | Phase 1118 | Complete |
| BASEMAP-01 | Phase 1119 | Complete |
| BASEMAP-02 | Phase 1119 | Complete |
| BASEMAP-03 | Phase 1119 | Complete |
| BASEMAP-04 | Phase 1119 | Complete |
| SYNC-01 | Phase 1120 | Complete |
| SYNC-02 | Phase 1120 | Complete |
| SYNC-03 | Phase 1120 | Complete |
| SYNC-04 | Phase 1120 | Complete |
| SCENE-01 | Phase 1121 | Complete |
| SCENE-02 | Phase 1121 | Complete |
| SCENE-03 | Phase 1121 | Complete |
| SCENE-04 | Phase 1121 | Complete |
| ACTION-01 | Phase 1122 | Complete |
| ACTION-02 | Phase 1122 | Complete |
| ACTION-03 | Phase 1122 | Complete |
| ACTION-04 | Phase 1122 | Complete |
| TEST-01 | Phase 1123 | Complete |
| TEST-02 | Phase 1123 | Complete |
| TEST-03 | Phase 1123 | Complete |
| TEST-04 | Phase 1123 | Complete |
| VERIFY-01 | Phase 1123 | Complete |
| VERIFY-02 | Phase 1123 | Complete |
| VERIFY-03 | Phase 1123 | Complete |
| VERIFY-04 | Phase 1123 | Complete |
| VERIFY-05 | Phase 1123 | Complete |

**Coverage:**
- v1027 requirements: 29 total, 29 complete
- Mapped to phases: 29
- Unmapped: 0

---
*Requirements defined: 2026-05-25*
*Last updated: 2026-05-25 after Phase 1123 close*

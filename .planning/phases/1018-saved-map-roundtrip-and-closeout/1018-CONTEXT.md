# Phase 1018: Saved Map Roundtrip And Closeout - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1003 requirements, Phase 1014-1017 verification, and current save/viewer test inventory.

<domain>
## Phase Boundary

Phase 1018 closes v1003 by proving saved-map round trips and public/shared viewer compatibility for the v1002 sidebar/Add Dataset redesign. Prior phases already added browser coverage for duplicate renderings, Add Dataset state transitions, basemap persistence, and shell/accessibility behavior.

The remaining phase-owned gap is explicit round-trip evidence for layer zoom-range layout persistence and schema-shape preservation, plus focused tests that basemap/terrain config still flows through builder save and public/shared viewer boundaries.
</domain>

<decisions>
## Implementation Decisions

### Browser Coverage
- Extend `e2e/builder.spec.ts` with a zoom-range save/reload flow over the existing temporary builder map.
- Capture map and layer response keys before and after save to detect persisted shape drift.
- Keep the browser flow focused on layout round-trip; duplicate rendering and basemap save/reload are already covered by earlier phase browser tests in the same smoke suite.

### Focused Save/Viewer Coverage
- Extend `use-builder-save.test.ts` so duplicate renderings, basemap config, terrain config, and layer zoom-range updates are asserted in one save contract.
- Extend authenticated public and shared-token viewer tests to assert `terrainConfig` is forwarded to `ViewerMap`, matching existing `basemapConfig` coverage.
</decisions>

<specifics>
## Specific Checks

- Layer zoom range writes `_minzoom` / `_maxzoom`, saves through layer PATCH, persists via API, and remains visible after reload.
- `MapResponse` and `MapLayerResponse` key sets are unchanged across the browser save.
- Builder save metadata includes basemap and terrain config without forcing full layer replacement.
- Public and shared viewers forward persisted terrain config to `ViewerMap`.
- Closeout records exact commands and Playwright MCP observations.
</specifics>

<deferred>
## Deferred Ideas

- Full backend, SDK, CLI, and packaging release gates remain outside this builder UI hardening milestone.
- Browser DEM terrain provisioning remains deferred until stable seeded DEM fixtures are cheap to create for every local run.
</deferred>

---
*Phase: 1018-saved-map-roundtrip-and-closeout*
*Context gathered: 2026-05-12*

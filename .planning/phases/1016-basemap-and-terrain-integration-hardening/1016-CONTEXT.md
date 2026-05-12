# Phase 1016: Basemap And Terrain Integration Hardening - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1003 requirements, Phase 1011 implementation, and current test inventory.

<domain>
## Phase Boundary

Phase 1016 proves that basemap and terrain controls remain map-level writes after the v1002 sidebar/Add Dataset redesign. Existing component and unit tests already cover inline basemap controls, normalized reset behavior, terrain source/exaggeration controls, and raster DEM `Use as terrain` mutation discipline.

The missing phase-owned gap is browser-level proof that an Add Dataset basemap swap updates modal state, synchronizes the sidebar row, preserves overlay layers, and survives save/reload through the map API.
</domain>

<decisions>
## Implementation Decisions

### Browser Coverage
- Extend `e2e/builder.spec.ts` because it already creates and cleans up an authenticated test map with overlay layers.
- Drive basemap swap through the Add Dataset modal, since sidebar popover swap already has smoke coverage.
- Assert the API `basemap_style` changes after Save and remains visible after reload.
- Assert overlay layer count is unchanged so basemap changes do not create or mutate persisted basemap rows.

### Terrain Coverage
- Reuse focused tests in `MapStackPanel.test.tsx`, `TerrainControls.test.tsx`, and `BuilderMap.unit.test.ts` for `terrain_config` writes and DEM `Use as terrain` behavior.
- Do not require a browser DEM fixture in this phase; the local smoke dataset is vector-oriented and a DEM fixture would make the phase dependent on seed data outside the redesign contract.
</decisions>

<specifics>
## Specific Checks

- Add Dataset Basemap tab shows the selected basemap as `in use` immediately after a swap.
- Sidebar Basemap group updates to the selected `BasemapEntry.label`.
- Saving persists `basemap_style` through `PUT /api/maps/{id}` and API reload.
- Reloading the builder preserves the selected basemap label.
- Existing overlay/data layers remain present through the basemap style reload.
- Terrain tests prove enabled/source/exaggeration updates write `terrain_config` and `Use as terrain` does not mutate the DEM layer row.
</specifics>

<deferred>
## Deferred Ideas

- Modal filter chip and row expansion hardening belongs to Phase 1017.
- Full saved-map/public-viewer round-trip closeout belongs to Phase 1018.
- Browser DEM fixture coverage can be added later if seed data becomes stable and cheap to provision.
</deferred>

---
*Phase: 1016-basemap-and-terrain-integration-hardening*
*Context gathered: 2026-05-12*

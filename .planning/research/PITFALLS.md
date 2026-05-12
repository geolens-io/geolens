# v1004 Research: Pitfalls

## Pitfalls

- **Promising cluster on vector tiles.** MapLibre's built-in clustering applies to GeoJSON sources; GeoLens data layers usually render through vector tile sources. A cluster chip without a proven GeoJSON or server-side cluster source path would be misleading.
- **Adding deck.gl as a casual renderer dependency.** deck.gl can solve Hexbin/H3/Trips, but it changes bundle size, render lifecycle, picking, z-order, terrain behavior, and test strategy.
- **Persisting renderer fields too early.** v1002-v1003 deliberately preserved `MapLayer`; v1004 should keep new intent in `style_config` unless an architecture phase proves a schema need.
- **Breaking public/shared viewers.** Builder-only adapters must not produce saved maps that public viewers cannot load.
- **Duplicating labels and interactions.** Companion symbol layers for arrows or clusters can fight label layers, popup hit testing, and row visibility unless IDs and z-order are owned explicitly.
- **Invalid style JSON export.** Runtime-only renderers need explicit export/import behavior rather than accidentally emitting incomplete MapLibre styles.
- **Unbounded client data fetches.** deck.gl aggregation and GeoJSON clustering can require full feature sets; this must be bounded by feature count, viewport, server endpoint, or explicit fallback.

## Prevention Strategy

- Phase 1 owns capability registry and feasibility gates.
- Any new renderer must include adapter tests, renderAs tests, saved-map tests, style JSON tests, and Playwright smoke coverage.
- Any deck.gl-backed mode must first land behind an ADR with bundle/performance evidence and no visible UI chip until the data path works.


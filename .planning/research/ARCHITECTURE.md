# v1004 Research: Architecture

## Current Integration Points

- `renderAs.ts`: render option discovery, current render detection, and patch construction.
- `layer-adapters/registry.ts`: maps adapter type strings to MapLibre adapter modules.
- `layer-adapters/types.ts`: adapter input and adapter contract, currently limited to MapLibre layer IDs.
- `map-sync.ts`: creates MapLibre vector/raster sources, calls adapters, handles labels, opacity, zoom ranges, visibility, stale cleanup, and z-order.
- `style_json.py`: backend MapLibre style export/import for persisted maps.
- Viewer paths reuse the same `syncLayersToMap` concept, so builder-only renderer state can accidentally break public/shared compatibility.

## Architecture Direction

1. Add a renderer capability registry separate from the UI option list.
2. Extend adapter metadata to declare:
   - renderer backend: `maplibre` or `deckgl-future`
   - source requirement: vector tile, GeoJSON, raster, raster-dem, H3 column, path/timestamp
   - companion layers and cleanup IDs
   - style JSON export behavior
   - viewer support level
3. Keep `MapLayer` persisted shape unchanged in v1004; store new renderer intent under existing `style_config.render_mode` and `style_config.builder`.
4. Keep new MapLibre renderers in the existing adapter model when possible.
5. Add an ADR before any deck.gl package enters `package.json`.

## Build Order Implication

The first phase should not implement UI. It should decide the capability contract, prove cluster source feasibility, and define the exact render modes that are allowed into v1004 implementation phases.


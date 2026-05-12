# v1004 Research: Features

## Table Stakes

- RenderAs options must be capability-gated by dataset geometry, record type, source delivery mode, and installed renderer backend.
- Unsupported renderer chips must remain absent, not disabled in-place.
- Switching renderer modes must write existing fields when possible: `layer_type`, `style_config`, `paint`, and `layout`.
- Saved maps, public/shared viewers, and MapLibre style JSON export/import must either preserve new render intent or explicitly omit unsupported runtime-only modes with user-safe fallback.
- Sidebar row, Add Dataset another-rendering, legend, labels, filters, opacity, zoom range, and row visibility must keep working with new renderers.

## Candidate Renderers

| Renderer | User Value | Feasibility In v1004 | Notes |
|---|---|---|---|
| Point Cluster | Dense point maps become readable at low zoom | Conditional | MapLibre-native for GeoJSON sources; not directly available on current vector-tile source path. |
| Line Arrow | Directional networks and flows become easier to read | High | Can likely use a companion `symbol` layer with `symbol-placement: line`. |
| Hexbin | Aggregated point density with optional height | Research only | deck.gl HexagonLayer is a new dependency and needs client data access strategy. |
| H3 | H3-indexed datasets render as cells | Research only | Requires H3 index column and deck.gl/h3-js or server-side cell geometry. |
| Animated Path | Movement/trip playback | Research only | deck.gl TripsLayer needs path + timestamp arrays and animation state. |
| Point 3D extrusion | Point magnitude columns become vertical markers | Defer | Likely deck.gl ColumnLayer or MapLibre-generated polygons; not a small MapLibre-only change. |

## Recommended v1004 Scope

- Ship architecture and gating before exposing any new renderer.
- Ship line arrow if the MapLibre companion-symbol approach validates cleanly.
- Ship point clustering only if a bounded GeoJSON-source path can be added without changing persisted schema or breaking vector-tile performance.
- Produce explicit ADR/decision artifacts for Hexbin, H3, Animated path, and Point 3D extrusion instead of bundling deck.gl prematurely.


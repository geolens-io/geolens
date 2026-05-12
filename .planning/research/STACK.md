# v1004 Research: Stack

## Existing Stack

- Frontend: React 19, Vite 8, MapLibre GL JS 5.24.0, `@vis.gl/react-maplibre` 8.1.0.
- Current builder renderer model: MapLibre-native adapters in `frontend/src/components/builder/layer-adapters/` selected through `resolveAdapterType` and `getAdapter`.
- Current renderAs model: `frontend/src/components/builder/renderAs.ts` lists point, symbol, heatmap, line, fill, stroke, fill+stroke, polygon 3D extrusion, image, and hillshade.
- No deck.gl packages are currently installed.

## Official Capability Notes

- MapLibre style layers support `circle`, `symbol`, `line`, `fill`, `fill-extrusion`, `heatmap`, `raster`, `hillshade`, and related style-layer primitives. Source: https://maplibre.org/maplibre-style-spec/layers/
- MapLibre clustering is built into GeoJSON sources by setting `cluster: true`, then rendering cluster circles, labels, and unclustered points from the same source. Source: https://maplibre.org/maplibre-gl-js/docs/examples/create-and-style-clusters/
- MapLibre symbol layers can place icons/text along line geometry through `symbol-placement: line`, which is the likely MapLibre-native route for line direction arrows. Source: https://maplibre.org/maplibre-style-spec/layers/#symbol-placement
- deck.gl can integrate with MapLibre through overlaid or interleaved `MapboxOverlay`; interleaving works with MapLibre GL JS v3+ and needs WebGL2 for proper map/deck layer mixing. Source: https://deck.gl/docs/developer-guide/base-maps/using-with-maplibre
- deck.gl provides HexagonLayer in `@deck.gl/aggregation-layers`, H3HexagonLayer and TripsLayer in `@deck.gl/geo-layers`, and PathLayer/LineLayer in `@deck.gl/layers`. Sources: https://deck.gl/docs/api-reference/aggregation-layers/hexagon-layer, https://deck.gl/docs/api-reference/geo-layers/h3-hexagon-layer, https://deck.gl/docs/api-reference/geo-layers/trips-layer

## Stack Recommendation

1. Keep v1004 MapLibre-first.
2. Add a renderer capability registry that can describe MapLibre-native renderers now and deck.gl-backed renderers later.
3. Treat point clustering as conditional until a GeoJSON delivery path is proven for builder layers; current default vector-tile sources cannot receive `cluster: true`.
4. Treat line arrows as the first likely shippable MapLibre-native renderer because it can be represented as a companion symbol layer over existing line sources.
5. Do not add deck.gl in v1004 unless a phase explicitly proves bundle budget, z-order, picking, terrain behavior, and data-fetch strategy.


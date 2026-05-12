# v1004 Research Summary

## Decision Summary

v1004 should be a MapLibre-first renderer expansion milestone, not a deck.gl adoption milestone. The existing GeoLens stack can likely support line arrows as a companion MapLibre symbol layer. Point clustering is attractive but conditional because MapLibre clustering requires a GeoJSON source path, while GeoLens catalog layers normally use vector tile sources. Hexbin, H3, Trips/Animated path, and Point 3D extrusion should receive explicit feasibility/ADR treatment before implementation.

## Stack Additions

- No immediate dependency additions for the first phase.
- Potential later dependency: deck.gl modules only after ADR approval and bundle/performance proof.
- Potential later dependency: h3-js only if H3 mode ships and is not implemented server-side.

## Table Stakes

- Capability-gated renderAs options.
- Existing schema preservation.
- Viewer and style JSON compatibility.
- Adapter cleanup/z-order/legend/label/visibility parity.
- Browser and saved-map tests for any new visible renderer.

## Watch Outs

- Do not expose Cluster until vector-tile vs GeoJSON source feasibility is resolved.
- Do not add deck.gl just to match Kepler.gl's layer catalog.
- Do not let runtime-only renderers create saved maps that public/shared viewers cannot interpret.

## Proposed v1004 Phase Shape

1. Renderer capability architecture and feasibility gates.
2. MapLibre line arrow renderer.
3. Conditional point cluster renderer or cluster-deferred fallback, depending on Phase 1.
4. deck.gl/H3/Trips/Point-3D ADR and future-plan artifact.
5. Renderer QA, saved-map, style JSON, and Playwright closeout.


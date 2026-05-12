# Phase 1029 Summary: Cluster Exploration Interactions

## Completed

- Added `frontend/src/components/map/cluster-interactions.ts` for shared cluster hit-layer IDs, cluster feature detection, aggregate popup content, coordinate extraction, and zoom activation.
- Builder map hit-testing now includes cluster circle/count companion layers, shows aggregate cluster popup details, and zooms via MapLibre cluster expansion or server-provided `expansion_zoom`.
- Viewer map hit-testing now uses the same cluster activation behavior across public/shared/embed contexts.
- Canvas keyboard activation with Enter/Space targets the centered cluster, preserving non-mutating view movement until an explicit map save.
- Map Stack rows and viewer legend now distinguish bounded Cluster, server-side Cluster, and Point fallback states.

## Verification

- `cd frontend && npm run test -- src/components/map/__tests__/cluster-interactions.test.ts src/components/builder/__tests__/map-stack.test.ts src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx --run`
- `cd frontend && npm run lint -- --quiet`

## Notes

- Aggregate popups use properties already present on the rendered cluster feature. They do not issue full-table scans.
- Server-side clusters use `expansion_zoom` from the cluster tile response; bounded GeoJSON clusters use `GeoJSONSource#getClusterExpansionZoom`.

# Phase 1023 Summary: Cluster Source Eligibility And GeoJSON Contract

**Phase:** 1023 — cluster-source-eligibility-and-geojson-contract
**Milestone:** v1005 Builder Point Cluster Foundation
**Status:** Complete
**Completed:** 2026-05-12
**Requirements:** SRC-01, SRC-02, SRC-03, SRC-04, SRC-05

## Delivered

- Added a frontend cluster source eligibility helper that only treats vector point datasets with known bounded feature counts as cluster-eligible.
- Promoted `cluster` into the renderer capability surface while filtering it out for non-point, missing-count, oversized, raster, DEM, and unsupported layers.
- Added existing-field Cluster renderAs patches that write `layer_type`, `paint`, and `style_config.render_mode` / `style_config.builder` only.
- Generalized the existing GeoJSON-Z helper into a bounded GeoJSON fetch helper that preserves JWT, API-key, and embed-token contexts without double-prefixing `/api`.
- Wired builder and viewer cluster source prefetch for cluster-intent layers only, with nonfatal fallback behavior for ineligible, truncated, oversized, or failed loads.
- Added localized map-stack Cluster badges and authoring warnings for cluster fallback/load failures.

## Verification

- `cd frontend && npm run test -- src/components/builder/__tests__/renderAs.test.ts src/api/__tests__/geojson-z.test.ts src/lib/__tests__/normalize-style-config.test.ts` — 31 passed.
- `cd frontend && npm run test:i18n` — 2 passed.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed; existing large `map-vendor` chunk-size warning remains.
- `npm run e2e:smoke:builder` — 26 passed.
- Playwright MCP browser check loaded the local app and reported zero console warnings/errors at warning level.

## Notes

- The native MapLibre cluster adapter still lands in Phase 1024. Until then, saved cluster intent is safely eligible/gated and source-prefetched, while actual map rendering continues to fall back to normal point rendering.
- No backend schema, persisted map fields, dataset fields, migrations, or renderer dependencies were added.

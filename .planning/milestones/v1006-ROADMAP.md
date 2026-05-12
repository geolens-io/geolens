# Milestone v1006: Large Dataset Cluster Scaling

**Status:** Shipped 2026-05-12
**Audit:** passed / GO
**Phases:** 1027-1031
**Plans:** 5 / 5 complete
**Requirements:** 25 / 25 complete

## Overview

v1006 extended the v1005 Point Cluster renderer from bounded client-side GeoJSON datasets to large point datasets. GeoLens now keeps one Cluster authoring model while map sync selects bounded GeoJSON for small eligible point datasets, authenticated server-side cluster MVT tiles for large point datasets, and normal Point fallback for unsupported states.

The milestone preserved schema discipline: no new `Map`, `MapLayer`, `Dataset`, or `Record` fields, no migrations, no deck.gl/H3 dependency, and Cluster intent remains under `style_config.render_mode` / `style_config.builder`.

## Requirements

- Server-side cluster tile contract: SCL-01..05 complete.
- Renderer routing and authoring: REND-01..05 complete.
- Cluster exploration UX: UX-01..04 complete.
- Compatibility and interop: COMP-01..05 complete.
- QA and closeout: QA-01..06 complete.

Full requirement archive: `.planning/milestones/v1006-REQUIREMENTS.md`.

## Phases

### Phase 1027: server-cluster-tile-contract

**Goal:** Add the backend contract for clustered point tiles without changing persisted map/layer schemas or normal vector tile behavior.

**Requirements:** SCL-01, SCL-02, SCL-03, SCL-04, SCL-05

**Completed:**

- Added `GET /tiles/clusters/data.{table}/{z}/{x}/{y}.pbf`.
- Reused vector tile auth for public, signed private, API-key, and embed-token access.
- Added bounded server-side cluster MVT SQL with MapLibre-compatible cluster properties.
- Added cluster-specific cache keys including radius and max zoom.
- Covered endpoint success, point-only validation, private auth, embed-token access, cache separation, and SQL property shape.

**Evidence:** `.planning/phases/1027-server-cluster-tile-contract/1027-VERIFICATION.md`

### Phase 1028: cluster-source-routing-and-authoring-parity

**Goal:** Route Cluster layers to bounded GeoJSON or server-side cluster tiles based on source eligibility while keeping one authoring model.

**Requirements:** REND-01, REND-02, REND-03, REND-04, REND-05

**Completed:**

- Added shared cluster source strategy routing for bounded GeoJSON, server tiles, and fallback.
- Large point datasets expose Cluster through the same renderAs capability contract.
- Map sync builds authenticated cluster tile URLs and source-layer-aware cluster companion layers.
- Builder, public, shared, and embed viewers share the same source-routing policy.
- Cluster style controls feed both bounded and server-side source paths.

**Evidence:** `.planning/phases/1028-cluster-source-routing-and-authoring-parity/1028-VERIFICATION.md`

### Phase 1029: cluster-exploration-interactions

**Goal:** Add the expected map exploration affordances for clustered point datasets without disrupting existing popup and label behavior.

**Requirements:** UX-01, UX-02, UX-03, UX-04

**Completed:**

- Added shared cluster interaction helpers for builder and viewer maps.
- Cluster companion circle/count layers participate in hit-testing.
- Pointer click and canvas keyboard activation zoom toward cluster contents using MapLibre expansion or server `expansion_zoom`.
- Aggregate popups show count/source metadata without full-table scans.
- Map Stack and viewer legend distinguish bounded Cluster, server-side Cluster, and Point fallback.

**Evidence:** `.planning/phases/1029-cluster-exploration-interactions/1029-VERIFICATION.md`

### Phase 1030: cluster-compatibility-and-style-json-interop

**Goal:** Prove server-side Cluster keeps saved-map, style JSON, viewer, and previous renderer compatibility intact.

**Requirements:** COMP-01, COMP-02, COMP-03, COMP-04, COMP-05

**Completed:**

- Standalone style JSON output stays drawable through normal point/vector fallback.
- Cluster intent remains preserved in existing layer metadata for import/reload.
- Source metadata documents bounded, server-tile, and fallback cluster strategy plus standalone fallback policy.
- Backend style JSON coverage includes server-side cluster export metadata.

**Evidence:** `.planning/phases/1030-cluster-compatibility-and-style-json-interop/1030-VERIFICATION.md`

### Phase 1031: cluster-performance-browser-qa-closeout

**Goal:** Validate large-dataset cluster performance and close the milestone with automated and browser evidence.

**Requirements:** QA-01, QA-02, QA-03, QA-04, QA-05, QA-06

**Completed:**

- Ran focused frontend/backend/i18n/lint/build/ruff/builder-smoke gates.
- Added a multipoint cluster tile regression after live UAT exposed imported point-family data stored as `MULTIPOINT`.
- Fixed viewer/builder style-load resync so private vector sources are not created before tile tokens arrive.
- Used Playwright MCP against a synthetic 6,001-feature imported point dataset.
- Verified signed server-cluster tile requests, 200/204 tile responses, `Server cluster` sidebar state, aggregate cluster popup interaction, and zero current-page browser warnings/errors.

**Evidence:** `.planning/phases/1031-cluster-performance-browser-qa-closeout/1031-VERIFICATION.md`

## Verification

- Focused frontend tests: 149 passed.
- Backend tile/embed/style JSON suite: 61 passed, 1 Authlib deprecation warning.
- i18n resource test: 2 passed.
- Frontend lint: passed.
- Frontend production build: passed with the pre-existing large `map-vendor` chunk warning.
- Backend ruff check and format check: passed.
- Builder smoke: 26/26 passed.
- Playwright MCP live UAT: 6,001-feature server-cluster map loaded, signed cluster tile requests returned 200/204, cluster popup opened, current-page console had 0 warnings/errors.

## Milestone Summary

**Key decisions:**

- Large point Cluster uses server-side MVT tiles rather than full-table GeoJSON.
- Existing `style_config.render_mode` / `style_config.builder` remains the only persisted Cluster authoring contract.
- Style JSON standalone export remains point/vector drawable and records Cluster strategy metadata for GeoLens rehydration.
- Point-family `MULTIPOINT` imported data is valid for cluster tiles through representative-point bucketing.

**Issues resolved:**

- Large datasets no longer lose Cluster authoring solely because they exceed the bounded GeoJSON limit.
- Private cluster tile URLs stay signed through initial load and style reload.
- Imported multipoint point-family tables no longer produce PostGIS `ST_X()` runtime failures.
- Cluster companion layers now participate in pointer and keyboard map interaction.

**Issues deferred:**

- Hexbin and H3 aggregation renderers.
- Animated path / Trips rendering plus map-level timeline controls.
- Point 3D extrusion.
- Cross-layer filters, recipes, blend mode, persisted basemap appearance presets, exact-position Add Dataset drag, and analytics-grade aggregation controls beyond cluster count/sample summaries.

**Technical debt:**

- Frontend production build still emits the known large `map-vendor` chunk-size warning.

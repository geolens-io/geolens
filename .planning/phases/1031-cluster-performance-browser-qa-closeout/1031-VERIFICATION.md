# Phase 1031 Verification

## Automated

- PASS — focused frontend cluster suite:
  `cd frontend && npm run test -- src/components/builder/__tests__/cluster-source.test.ts src/components/builder/__tests__/map-sync.cluster.test.ts src/components/builder/__tests__/renderAs.test.ts src/components/builder/__tests__/layer-adapters.test.ts src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx src/components/map/__tests__/cluster-interactions.test.ts src/components/builder/__tests__/map-stack.test.ts src/lib/__tests__/tile-utils.test.ts --run`
  - 8 files, 149 tests passed.
- PASS — backend tile/embed/style JSON suite:
  `cd backend && POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_tiles.py tests/test_embed_tokens.py::TestTileEmbedTokenAccess tests/test_maps_style_json.py -q`
  - 61 tests passed, 1 Authlib deprecation warning.
- PASS — frontend lint:
  `cd frontend && npm run lint -- --quiet`
- PASS — frontend i18n:
  `cd frontend && npm run test:i18n`
  - 2 tests passed.
- PASS — frontend production build:
  `cd frontend && npm run build`
  - Passed with the pre-existing large `map-vendor` chunk warning.
- PASS — backend ruff check:
  `cd backend && uv run ruff check app/processing/tiles/service.py tests/test_tiles.py app/modules/catalog/maps/style_json.py tests/test_maps_style_json.py`
- PASS — backend ruff format check:
  `cd backend && uv run ruff format --check app/processing/tiles/service.py tests/test_tiles.py app/modules/catalog/maps/style_json.py tests/test_maps_style_json.py`
- PASS — existing builder smoke:
  `npm run e2e:smoke:builder`
  - 26/26 passed.

## Playwright MCP UAT

Synthetic large point dataset:

- Dataset: `Cluster UAT Large Points 1778621648562`
- Feature count: 6,001
- Geometry surfaced through map API as `MULTIPOINT`
- Map: `Cluster UAT Map 1778621650205`

Checks:

- PASS — saved map loaded in the live browser at `/maps/247aa96b-3cd2-4674-958b-1b53f37e8726`.
- PASS — map canvas existed and `data-tiles-loaded="true"`.
- PASS — sidebar showed `Large server cluster UAT`, `Cluster`, and `Server cluster`.
- PASS — token batch returned a vector token for the private dataset.
- PASS — cluster tile requests used `/api/tiles/clusters/data.cluster_uat_large_points_1778621648562/...` with `sig`, `exp`, `scope`, `cluster_radius=64`, and `cluster_max_zoom=12`.
- PASS — live cluster tile responses were 200 or 204; no 403 or 503 remained.
- PASS — clicking the canvas opened an aggregate cluster popup showing `Cluster: 20 features`, `Source: Server-side cluster tile`, and `Expansion Zoom 13`.
- PASS — current-page Playwright console after reload and interaction had zero warnings and zero errors.

Screenshot evidence: `cluster-server-tile-uat.png`.

## Issues Found And Fixed

- UAT blocker: `ST_X()` failed on imported point-family datasets stored as `MULTIPOINT`.
  - Fixed by normalizing cluster candidates with `ST_PointOnSurface(t.geom_4326)` and adding a real multipoint endpoint regression test.
- UAT blocker: viewer style-load resync could briefly create private vector sources before token arrival, causing unsigned cluster tile 403s and a session-expired toast.
  - Fixed by aligning style-load resync with the token gate and adding a builder-side pending-token guard.

## Requirement Mapping

- QA-01: backend tests cover SQL/query shape, auth, cache keys, empty tiles, embed-token access, style JSON, and multipoint runtime behavior.
- QA-02: frontend tests cover eligibility, routing, URL signing dispatch, source lifecycle, fallback state, and companion layers.
- QA-03: viewer source routing and token refresh remain covered; live authenticated viewer UAT proved private server-cluster tile access.
- QA-04: synthetic 6,001-feature point map routed to server-cluster MVT, not bounded full-table GeoJSON.
- QA-05: Playwright MCP browser verification passed with clean current-page console.
- QA-06: focused automated gates passed.

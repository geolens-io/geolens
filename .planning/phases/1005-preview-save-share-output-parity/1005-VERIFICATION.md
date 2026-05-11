---
phase: 1005-preview-save-share-output-parity
status: passed
verified: 2026-05-11T20:51:55Z
requirements: [OUTPUT-01, OUTPUT-02, OUTPUT-03, OUTPUT-04, OUTPUT-05, OUTPUT-06]
---

# Phase 1005 Verification

## Result

Status: passed

Phase goal verified: what users author in the builder now has stable layer identity through saved, shared-token, authenticated public, and embedded outputs, and save/share state makes publication lag explicit.

## Requirement Check

| Requirement | Status | Evidence |
|-------------|--------|----------|
| OUTPUT-01 | Passed | ViewerMap, LayerLegend, and `useViewerLayers` now use stable viewer-layer keys; authenticated public maps pass layer IDs; shared-token responses include layer IDs. |
| OUTPUT-02 | Passed | `useBuilderSave` returns saved/unsaved/saving/failed status plus retryability, and `MapTitleBar` renders the status and retry action. |
| OUTPUT-03 | Passed | Public and embed pages remain read-only viewer pages; share/embed output warning was added without exposing builder controls. |
| OUTPUT-04 | Passed | Existing public title, legend, navigation, scale, attribution, and widget surfaces are preserved while layer identity/toggles become stable. |
| OUTPUT-05 | Passed | Viewer basemap-config coverage still passes, and stable identity applies across blank/light/dark/raster/vector/mixed layer stacks without changing rendering contracts. |
| OUTPUT-06 | Passed | Thumbnail decision recorded: no server-side OPS-01 pipeline is needed for this phase; defer durable thumbnail generation to future OPS-01/NEXT-04 scope. |

## Finding Closure

- F-1002-01: Closed for public/order parity. New layers already receive stable order from Phase 1003; public output no longer depends on order alone for identity.
- F-1002-05: Closed. Save states are explicit in the title bar and share dialog.
- F-1002-07: Closed. Legend keys and toggles use stable viewer-layer keys instead of `sort_order`.

## Verification Commands

- `cd frontend && npm run test -- LayerLegend use-viewer-layers ViewerMap.basemap-config PublicViewerPage PublicMapViewerPage MapTitleBar SharePanel use-builder-save --run` - passed, 8 files / 59 tests.
- `cd frontend && npm run lint` - passed.
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -k "get_shared_map_success"` - passed, 1 test.
- `cd backend && uv run ruff check app/modules/catalog/maps/schemas.py app/modules/catalog/maps/service_public.py tests/test_maps.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/maps/schemas.py app/modules/catalog/maps/service_public.py tests/test_maps.py` - passed.
- `make openapi-check` - passed.

## Residual Risk

- The focused frontend run still prints the existing Vitest `--localstorage-file` warning and a jsdom navigation warning from existing tests; all selected tests passed.
- Broad screenshot QA remains Phase 1007 scope by roadmap design.

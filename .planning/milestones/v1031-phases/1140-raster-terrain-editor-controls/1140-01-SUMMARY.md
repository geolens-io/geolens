---
phase: 1140-raster-terrain-editor-controls
plan: "01"
subsystem: backend/raster-proxy
tags: [raster, titiler, colormap, backend, nginx, band_count, security]
dependency_graph:
  requires: []
  provides: [colormap_name-on-raster_tile_proxy, band_count-on-MapLayerResponse, nginx-colormap-cache-key]
  affects: [raster tile serving, MapLayerResponse schema, nginx raster-tiles location]
tech_stack:
  added: []
  patterns: [Literal-allowlist-validation, belt-and-suspenders-runtime-check, TDD-RED-GREEN]
key_files:
  created:
    - backend/tests/test_raster_colormap_proxy.py
  modified:
    - backend/app/processing/tiles/router.py
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/catalog/maps/service_shared.py
    - backend/app/modules/catalog/maps/router.py
    - frontend/src/types/api.ts
    - frontend/nginx.conf
decisions:
  - "colormap_name=gray treated as no-op (Titiler single-band default — not forwarded)"
  - "DEM layers (render_params starts with algorithm=) never receive colormap_name override"
  - "stretch=percentile/stddev accepted with minmax fallback + warning (Phase 1140 minmax-only scope)"
  - "belt-and-suspenders runtime frozenset check after FastAPI Literal gate (T-1140-01)"
metrics:
  duration: "7 minutes"
  completed: "2026-05-28"
  tasks: 3
  files_changed: 7
---

# Phase 1140 Plan 01: Backend Raster Colormap Support Summary

Backend half of EDITOR-RASTER-COLORMAP: validated colormap_name/stretch params on raster_tile_proxy, band_count on MapLayerResponse, nginx cache-key fix.

## What Was Built

### Task 1: band_count on MapLayerResponse

Added `band_count: int | None` as an additive, backwards-compatible field to:
- `DatasetMetaKwargs` TypedDict (`schemas.py`)
- `MapLayerResponse` Pydantic model (`schemas.py`, default `None`)
- `LayerRow` NamedTuple (`service_shared.py`)
- `_fetch_layer_rows_ordered` SELECT — appends `RasterAsset.band_count` (row[12]) after `band_info` (row[11])
- `_layers_from_tuples` and `_build_layer_response` in `router.py` — passes `band_count` from row/meta
- `_meta_to_kwargs` in `router.py` — sets `band_count=None` in both branches (get_dataset_meta path has no RasterAsset join; None safely hides the colormap control per plan gate `=== 1`)
- `MapLayerResponse` TypeScript interface in `frontend/src/types/api.ts` — adds `band_count?: number | null`

Existing map-layer tests: 35/35 pass. No regression.

### Task 2: colormap_name + stretch params on raster_tile_proxy (TDD)

**RED phase** (`3674ef81`): 16 tests in `test_raster_colormap_proxy.py`, 11 failing before implementation.

**GREEN phase** (`bd72f0e6`):
- Import `Literal` from `typing`
- Module-level `_ALLOWED_COLORMAPS: frozenset[str]` (8 names) + `_ALLOWED_STRETCH: frozenset[str]` (3 values)
- `colormap_name: Literal["gray","viridis","inferno","plasma","magma","ylorrd","bugn","terrain"] | None = Query(None)` param
- `stretch: Literal["minmax","percentile","stddev"] | None = Query(None)` param
- T-1140-01 runtime guard: `colormap_name not in _ALLOWED_COLORMAPS → HTTPException(422)` (belt-and-suspenders after FastAPI Literal gate; Titiler never called on invalid input)
- Forwarding logic: append `&colormap_name=X` when `colormap_name and colormap_name != "gray" and not render_params.startswith("algorithm=")`
- Stretch fallback: `logger.warning(...)` for percentile/stddev; render_params not altered (minmax-only scope per Finding 6)

All 16 tests pass (GREEN). Existing maps tests 143/143 pass.

### Task 3: nginx raster-tiles — forward colormap_name/stretch + cache key

Two-line change in `frontend/nginx.conf` raster-tiles location block:
1. Rewrite line: `$is_args$args` appended — `?colormap_name=viridis&stretch=minmax` now reaches the api in production (previously stripped by `rewrite break`)
2. Cache key: `"$dataset_id/$z/$x/$y.$fmt/$arg_colormap_name/$arg_stretch"` — distinct cache entries per colormap/stretch combination (worst-case 24× fan-out; bounded by 8 colormaps × 3 stretch values; acceptable per T-1140-02 accept disposition)

`nginx -t` passes (syntax ok). Auth headers, `proxy_pass`, `limit_req`, `error_page` unchanged.

## Verification

- `pytest -n 4 test_raster_colormap_proxy.py test_maps.py`: **159/159 PASS**
- `npx tsc -b --noEmit`: **0 errors**
- nginx grep gates: `is_args$args` present, `arg_colormap_name` in cache key

## Deviations from Plan

None — plan executed exactly as written.

## Phase 1143 Flag (STATE.md HARD INVARIANT 6)

**OpenAPI/SDK regeneration is DEFERRED to Phase 1143 (close-gate).** Do NOT run `make openapi` or `npm run fetch-openapi` before Phase 1143.

Two schema changes in this plan require OpenAPI/SDK refresh at Phase 1143:
1. `raster_tile_proxy` gained `colormap_name` + `stretch` query params (new endpoint parameters)
2. `MapLayerResponse` gained `band_count: int | None` (new response field)

Both are additive/backwards-compatible changes. The SDK is stale until Phase 1143 runs `make openapi`.

## Known Stubs

None — all data paths are fully wired. `band_count=None` for vector/no-asset layers is correct behavior (not a stub); the frontend gate `layer.band_count === 1` safely hides the colormap control.

## Minmax-Only Scope Note

`stretch=percentile` and `stretch=stddev` are accepted at the API boundary and logged as a minmax fallback. Actual statistics-based rescaling (Titiler `/cog/statistics` sub-call) is deferred to a v1032 follow-up. The API surface is complete so the Phase 1143 SDK refresh will include the full `stretch` Literal.

## Threat Surface Scan

No new threat surface beyond what is documented in the plan threat model (T-1140-01 mitigated by Literal + frozenset runtime check; T-1140-02 accepted bounded fan-out).

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `backend/tests/test_raster_colormap_proxy.py` | FOUND |
| `backend/app/processing/tiles/router.py` | FOUND |
| `frontend/nginx.conf` | FOUND |
| `1140-01-SUMMARY.md` | FOUND |
| commit e0daf9ab (band_count schema) | FOUND |
| commit 3674ef81 (RED tests) | FOUND |
| commit bd72f0e6 (GREEN implementation) | FOUND |
| commit d809c4e0 (nginx fix) | FOUND |

---
phase: quick-55
plan: 01
subsystem: datasets
tags: [raster, vrt, tile-url, api, frontend]
dependency_graph:
  requires: []
  provides: [absolute-tile-urls, vrt-connect-object]
  affects: [dataset-api, connect-dropdown]
tech_stack:
  added: []
  patterns: [absolute-url-with-api-key-placeholder, optional-download-url]
key_files:
  created: []
  modified:
    - backend/app/datasets/schemas.py
    - backend/app/datasets/router.py
    - frontend/src/components/dataset/ConnectDropdown.tsx
decisions:
  - "RasterConnect.download_url made optional (str | None) for VRT datasets that have no single COG download"
  - "api_key={your_key} placeholder appended only to connect.tile_url, not to top-level tile_url or quicklook_url"
  - "Renamed create_empty_dataset_endpoint body param from 'request' to 'body' to avoid shadowing Starlette Request"
metrics:
  duration: 2min
  completed: "2026-03-15T14:11:12Z"
---

# Quick Task 55: VRT/Raster XYZ Tile URL Endpoint Summary

Absolute tile URLs with api_key placeholder in connect object; VRT datasets get first-class connect support matching rasters.

## What Changed

### Backend (schemas.py, router.py)

- `RasterConnect.download_url` changed from `str` to `str | None = None` so VRT datasets can omit the COG download URL
- `_build_raster_metadata` now accepts `base_url` parameter and builds absolute URLs when provided:
  - `connect.tile_url`: `{base_url}/raster-tiles/{id}/tiles/{z}/{x}/{y}.png?api_key={your_key}`
  - `connect.download_url`: `{base_url}/api/datasets/{id}/download/cog` (raster only, None for VRT)
  - `quicklook_url` and top-level `tile_url`: absolute with base_url prefix
- `_dataset_to_response` passes `base_url` through to `_build_raster_metadata`
- All 4 callers updated to extract `base_url` from `request.base_url`:
  - `list_all_datasets` — added `request: Request` parameter
  - `get_single_dataset` — already had `request`
  - `create_empty_dataset_endpoint` — renamed body param from `request` to `body`, added `request: Request`
  - `update_dataset_metadata` — already had `request`

### Frontend (ConnectDropdown.tsx)

- Unified raster and VRT tile URL display via `connect.tile_url`
- Removed `window.location.origin` prefix from all raster/VRT URLs (backend now provides absolute)
- S3 URI now shown for both raster and VRT admin users
- COG download URL only shown when `download_url` is truthy (raster only)
- Removed separate VRT code path that used `dataset.raster?.tile_url`

## Deviations from Plan

None -- plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 2bcaa7ca | Backend absolute tile URLs with api_key and VRT connect |
| 2 | 26935d6f | Frontend ConnectDropdown simplified to use absolute URLs |

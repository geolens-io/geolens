---
phase: 230
plan: 02
status: complete
---

# Plan 02 Summary: migrate helper callers

## What Changed

- Migrated dataset data/export/reupload/VRT helpers to `get_catalog_port()`.
- Migrated feature SQL table quoting, layer ingest metadata helpers, and source preview/router/STAC helper usage to `get_catalog_port()`.
- Expanded `CatalogPort` / `DefaultCatalogPort` with the helper methods needed by the migrated files.

## Verification

- `git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/`
- `python -m py_compile backend/app/core/catalog_port.py backend/app/platform/extensions/defaults.py backend/app/platform/extensions/__init__.py backend/app/modules/catalog/datasets/api/router_data.py backend/app/modules/catalog/datasets/api/router_export.py backend/app/modules/catalog/datasets/api/router_reupload.py backend/app/modules/catalog/datasets/api/router_vrt.py backend/app/modules/catalog/features/service.py backend/app/modules/catalog/layers/service.py backend/app/modules/catalog/sources/preview.py backend/app/modules/catalog/sources/router.py backend/app/modules/catalog/sources/stac_router.py backend/app/modules/catalog/maps/service.py backend/app/modules/catalog/search/service.py`

## Self-Check: PASSED


---
phase: 230
plan: 03
status: complete
---

# Plan 03 Summary: migrate query callers

## What Changed

- Migrated `catalog/maps/service.py` shared-map `RasterAsset` query composition to `get_catalog_port().raster_asset_orm_class()`.
- Migrated `catalog/search/service.py` semantic search embedding helpers and `RecordEmbedding` query composition to `CatalogPort`.
- Preserved the pre-existing uncommitted advanced sharing edits in `maps/service.py`; only the CatalogPort import/RasterAsset changes are part of this phase.

## Verification

- `git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/`
- `python -m py_compile backend/app/modules/catalog/maps/service.py backend/app/modules/catalog/search/service.py`

## Self-Check: PASSED


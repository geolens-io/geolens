# Phase 230 Research: catalog-port-protocol-symmetric

## Research Complete

Phase 230 should mirror the Phase 225 port pattern in the opposite direction:

- Core Protocol: `backend/app/core/catalog_port.py`
- Community default: `DefaultCatalogPort` in `backend/app/platform/extensions/defaults.py`
- Accessor: `get_catalog_port()` in `backend/app/platform/extensions/__init__.py`
- Guard: `backend/tests/test_layering.py::test_no_catalog_imports_processing`

## Current Import Inventory

`git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/` currently reports 20 top-of-file import lines:

- `catalog/datasets/api/router_data.py`: `compute_quality_score`
- `catalog/datasets/api/router_export.py`: `safe_content_disposition`
- `catalog/datasets/api/router_reupload.py`: ingest constants, schemas, OGR preview, service helpers, reupload tasks, content validation
- `catalog/datasets/api/router_vrt.py`: `VrtMutationResponse`
- `catalog/features/service.py`: `_qtable`
- `catalog/layers/service.py`: ingest metadata helpers and `generate_table_name`
- `catalog/maps/service.py`: `RasterAsset`
- `catalog/search/service.py`: embedding helpers/model/service
- `catalog/sources/preview.py`: `IngestionError`, `extract_srid_from_json`
- `catalog/sources/router.py`: `IngestionError`, `resolve_service_type`
- `catalog/sources/stac_router.py`: `Visibility`, `RasterAsset`

The roadmap says 17 files, but the current codebase has 20 import lines across 11 files. The phase invariant is zero top-of-file imports, so all current matches are in scope.

## Protocol Surface

Keep the Protocol call-site driven. The initial surface should cover:

- ORM class accessors: `raster_asset_orm_class()`, `vrt_generation_orm_class()`, `record_embedding_orm_class()`
- Schema/type factories or aliases: `vrt_mutation_response_model()`, `ingestion_error_class()`, `visibility_type()` if needed by runtime annotations
- Ingest helper methods: `compute_quality_score`, `quote_table`, `generate_table_name`, `validate_file_content`, `validate_file_extension`, `save_upload_file`, `resolve_file_path`, `create_ingest_job`, `run_ogrinfo_preview`, `build_gdal_source` helper delegation already exists in `ProcessingPort` but catalog source preview needs the opposite direction for OGR helpers
- Reupload task dispatchers: `reupload_file`, `reupload_service`
- Search helpers: `has_embeddings`, `generate_embedding`
- Export helper: `safe_content_disposition`
- Service helper: `resolve_service_type`, `extract_srid_from_json`
- Layer metadata helpers: `add_4326_column`, `grant_reader_access`, `get_column_info`, `_humanize_column_name`, `_infer_units`, `_infer_semantic_role`, `_infer_domain_type`, `_validate_table_name`

For SQLAlchemy query composition, returning ORM classes from the port is acceptable and matches Phase 225's ORM class helpers. It removes module-load edges without changing query semantics.

## Migration Strategy

1. Add the scaffold without changing callers.
2. Migrate low-risk helper imports first: data validation, export, feature SQL quoting, layer creation, and source preview/router helpers.
3. Migrate ORM-class query sites: maps/search/VRT/STAC paths that need `RasterAsset`, `VrtGeneration`, or `RecordEmbedding`.
4. Add the guard once grep is clean.

Avoid moving broad domain logic into the port. The default implementation should only delegate via deferred imports or return existing processing-owned classes.

## Validation Architecture

Automated checks:

- `git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/` must return no matches.
- `pytest backend/tests/test_layering.py::test_no_catalog_imports_processing`
- Negative control: temporarily add a top-of-file `from app.processing.raster.models import RasterAsset` to a catalog file, run the guard, confirm failure, then revert.
- Focused tests around touched surfaces:
  - `pytest backend/tests/test_layering.py -m architecture`
  - `pytest backend/tests/test_maps.py`
  - `pytest backend/tests/test_search.py` if available
  - `pytest backend/tests/test_ingest.py` / reupload or sources tests if available

Full backend suite is the acceptance target when local DB dependencies are available.

## Risks

- Dirty user edits already touch `catalog/maps/service.py`, `catalog/maps/router.py`, schemas, embed token services/tests, and frontend files. Phase 230 only needs `catalog/maps/service.py` among those dirty files; preserve the existing sharing-gate edits while replacing the RasterAsset import.
- FastAPI response model annotations that previously imported processing schemas should be switched through local catalog aliases only if runtime type evaluation allows it. Prefer importing the concrete model via a local alias produced by the port only when FastAPI needs the class object.
- ORM class helpers must remain deferred inside `DefaultCatalogPort` method bodies so `platform/extensions/defaults.py` does not gain module-load processing imports.


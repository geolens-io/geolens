---
phase: 230
plan: 02
type: execute
wave: 2
depends_on:
  - 230-01
files_modified:
  - backend/app/modules/catalog/datasets/api/router_data.py
  - backend/app/modules/catalog/datasets/api/router_export.py
  - backend/app/modules/catalog/datasets/api/router_reupload.py
  - backend/app/modules/catalog/datasets/api/router_vrt.py
  - backend/app/modules/catalog/features/service.py
  - backend/app/modules/catalog/layers/service.py
  - backend/app/modules/catalog/sources/preview.py
  - backend/app/modules/catalog/sources/router.py
  - backend/app/modules/catalog/sources/stac_router.py
autonomous: true
requirements:
  - CATPORT-02
  - CATPORT-03
  - CATPORT-05
must_haves:
  truths:
    - Helper/function/schema imports from app.processing are removed from the listed catalog modules
    - Behavior is delegated through get_catalog_port()
    - Existing local catalog imports and dirty user edits outside these files are preserved
---

<objective>
Migrate helper-style catalog imports to CatalogPort while preserving existing behavior.
</objective>

<tasks>
<task type="auto">
  <name>Migrate dataset API helper imports</name>
  <files>router_data.py, router_export.py, router_reupload.py, router_vrt.py</files>
  <action>Replace processing helper, schema, constant, task, and exception imports with module-local catalog_port = get_catalog_port() calls and local aliases where FastAPI needs response_model classes.</action>
  <verify>python -m py_compile backend/app/modules/catalog/datasets/api/router_data.py backend/app/modules/catalog/datasets/api/router_export.py backend/app/modules/catalog/datasets/api/router_reupload.py backend/app/modules/catalog/datasets/api/router_vrt.py</verify>
  <done>No top-of-file app.processing imports remain in these files.</done>
</task>

<task type="auto">
  <name>Migrate feature/layer/source helpers</name>
  <files>features/service.py, layers/service.py, sources/preview.py, sources/router.py, sources/stac_router.py</files>
  <action>Use CatalogPort for quote-table, ingest metadata helpers, table-name generation, IngestionError, extract_srid_from_json, resolve_service_type, Visibility alias, and RasterAsset construction.</action>
  <verify>python -m py_compile backend/app/modules/catalog/features/service.py backend/app/modules/catalog/layers/service.py backend/app/modules/catalog/sources/preview.py backend/app/modules/catalog/sources/router.py backend/app/modules/catalog/sources/stac_router.py</verify>
  <done>No top-of-file app.processing imports remain in these helper caller files.</done>
</task>
</tasks>

<verification>
git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/
</verification>


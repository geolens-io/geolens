# Quick Task 260324-qu5: Test Non-Spatial Data Support - Research

**Researched:** 2026-03-24
**Domain:** Non-spatial dataset lifecycle (ingest, query, export, UI)
**Confidence:** HIGH

## Summary

Non-spatial datasets (CSV/XLSX without geometry) follow a distinct code path: `record_type = 'table'`, `geometry_type = None`. The frontend already handles the `isTable` branch on DatasetPage (showing DataTab hero instead of map). Two confirmed bugs need fixing, and existing test coverage has gaps in the end-to-end flow.

**Primary recommendation:** Write backend pytest tests that expose both bugs, fix them, then add a Vitest unit test for DatasetMap non-spatial handling.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Full stack testing: backend pytest (ingestion, features/OGC query, export) + frontend Vitest (DatasetMap component)
- Test data formats: CSV + XLSX
- Test + fix approach: write tests that expose bugs, then fix them
- Two bugs to fix: (1) vector tile URLs for non-spatial datasets, (2) empty map with no message

### Claude's Discretion
- Test file content/structure (column names, data types, row counts)
- Specific test assertions and selectors
- Organization of test files

### Deferred Ideas (OUT OF SCOPE)
- Playwright E2E tests (no non-spatial upload E2E needed per task scope)
</user_constraints>

## Bug Analysis

### Bug 1: Vector Tile URLs Generated for Non-Spatial Datasets

**Location:** `backend/app/records/service.py:327-404` (`generate_distributions`)

**Root cause:** `generate_distributions(session, dataset_id, record_id, table_name)` does NOT receive `geometry_type`. It unconditionally creates ALL distributions including:
- 4 download formats (gpkg, geojson, shp, csv) -- gpkg/geojson/shp will 400 at export time
- OGC Features endpoint
- Vector tiles (pbf) -- will 404 at tile request time

**Called from:** `backend/app/datasets/service.py:211` -- has access to `geometry_type` in scope but does not pass it.

**Fix approach:** Pass `geometry_type` to `generate_distributions`. When `geometry_type is None`:
- Skip vector_tiles distribution entirely
- Skip gpkg, geojson, shp download distributions (export router already blocks these at line 87)
- Keep csv download and OGC features (features API works for non-spatial)

**Test:** Assert that registering a non-spatial dataset produces only csv + ogc_features distributions, NOT vector_tiles/gpkg/geojson/shp.

### Bug 2: DatasetMap Renders Empty for Non-Spatial

**Location:** `frontend/src/pages/DatasetPage.tsx:612-619`

**Status:** Already handled. The frontend checks `isTable` (line 417: `const isTable = dataset.record_type === 'table'`) and renders a DataTab hero grid instead of DatasetMap (lines 612-619). The map is only rendered when `!isTable` (line 622).

**However:** If a non-spatial dataset somehow has `record_type` that is NOT `'table'` (edge case), DatasetMap would receive `geometryType=null` and `addVectorLayers` would still fire (line 660) since it only guards on `!tableName` (line 430), not on `geometryType`. The vector tile source would be added but no layers would render (isPoint/isLine both false, falls through to polygon fill layer).

**Recommended fix:** Add an early return guard in DatasetMap's `addVectorLayers` callback when `geometryType` is null. Also consider adding an informational message or ensuring the DataTab-hero path is always taken for non-spatial.

## Existing Test Coverage

### Backend: `test_ingest.py:439-504`
- `test_csv_non_spatial_full_pipeline`: Creates table directly in SQL, registers via `/ingest/register`, verifies `record_type='table'` and `geometry_type=None`, queries features. Does NOT test distributions or export.

### Backend: `test_export.py:286-323`
- `test_export_non_spatial_dataset_spatial_format`: Verifies gpkg export returns 400 for non-spatial
- `test_export_non_spatial_dataset_csv_allowed`: Verifies csv export returns 200 for non-spatial
- Both use `_create_dataset()` helper with `geometry_type=None`

### Frontend: `DatasetMap.test.tsx`
- Tests edit trigger visibility, interactive prop, fullscreen toggle
- Does NOT test non-spatial (geometryType=null) rendering behavior

### Gaps
1. No test verifying distributions generated for non-spatial datasets
2. No test for actual CSV/XLSX file upload (existing test creates table via SQL, not file upload)
3. No Vitest test for DatasetMap behavior when geometryType is null
4. No test for OGC /collections/{id}/items with non-spatial dataset

## Test Patterns and Conventions

### Backend pytest
- Test classes in `backend/tests/test_*.py`
- Use `AsyncClient`, `admin_auth_header` fixture, `test_db_session` fixture
- Helper `_create_dataset()` in test_export.py accepts `geometry_type=None`
- Direct SQL table creation for non-spatial tables (no ogr2ogr needed)
- Cleanup in `finally` blocks with `DROP TABLE IF EXISTS`

### Frontend Vitest
- Files in `__tests__/` subdirectories, named `*.test.tsx`
- Import from `@/test/test-utils` (custom render with providers)
- Heavy mocking: `@vis.gl/react-maplibre`, hooks, stores
- DatasetMap tests mock MapGL as a div with data-testid

### Playwright E2E
- Config: `playwright.config.ts`, test dir: `e2e/`
- Fixtures in `e2e/fixtures/` (currently only `sample.geojson`)
- Upload test: `e2e/upload.spec.ts` -- uses `page.locator('input[type="file"]').setInputFiles()`
- Auth setup in `e2e/auth.setup.ts`, stored in `playwright/.auth/user.json`

### Test Data
- No existing CSV/XLSX test fixtures -- need to create them
- `e2e/fixtures/sample.geojson` is the only fixture file
- Backend tests create tables via SQL rather than file fixtures

## Code Paths Summary

| Operation | Non-spatial behavior | Code location |
|-----------|---------------------|---------------|
| Ingest/register | Sets `record_type='table'`, `geometry_type=None` | `backend/app/ingest/service.py` |
| Distributions | BUG: generates all 6 including vector_tiles | `backend/app/records/service.py:327` |
| Features API | Works -- returns `geometry: null` per feature | `backend/app/features/` |
| Export | Blocks gpkg/geojson/shp, allows csv | `backend/app/export/router.py:87` |
| Dataset page | Shows DataTab hero, hides map | `frontend/src/pages/DatasetPage.tsx:612` |
| DatasetMap | Would render empty basemap if reached | `frontend/src/components/dataset/DatasetMap.tsx:428` |

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `backend/app/records/service.py` (distribution generation)
- Direct code inspection of `frontend/src/pages/DatasetPage.tsx` (isTable branching)
- Direct code inspection of `frontend/src/components/dataset/DatasetMap.tsx` (addVectorLayers)
- Direct code inspection of `backend/tests/test_ingest.py` and `backend/tests/test_export.py`

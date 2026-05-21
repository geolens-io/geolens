# Quick Task 260322-lv3: Test & Quality Follow-ups - Research

**Researched:** 2026-03-22
**Domain:** e2e testing, backend integration testing, code verification
**Confidence:** HIGH

## Summary

Three items researched: e2e seed data, retroactive verification of two tasks, and a non-spatial CSV integration test. All findings are based on direct codebase inspection.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Claude's Discretion
- Seed script format (Python script, SQL fixture, or pytest fixture)
- Which datasets the seed script creates
- Verification approach for the two retroactive items
- Whether the CSV e2e test uses the existing test DB or a fresh fixture
</user_constraints>

## Item 1: E2e Seed Data Script

### What e2e Tests Expect

The e2e tests depend on datasets already existing in a running GeoLens instance. Key dependencies:

| Spec File | Dataset Required | How Referenced |
|-----------|-----------------|----------------|
| `dataset-detail.spec.ts` | "Admin 0 Countries (10m)" | Search `/?q=Admin+0+Countries`, click link by name |
| `search.spec.ts` | "Reefs (10m)" | Search `/?q=Reefs`, typeahead navigate |
| `collections.spec.ts` | "World Countries" | Search by `countries`, expect "World Countries" |
| `builder.spec.ts` | Any 1 dataset | `GET /api/datasets/?limit=1`, uses first result |
| `upload.spec.ts` | None (self-contained) | Uploads `e2e/fixtures/sample.geojson` |
| `export-runtime.spec.ts` | At least 1 dataset | Resolves via API |
| `record-detail-ux-audit.spec.ts` | Multiple types (vector, raster, vrt, collection) | Discovered via API |

**Critical datasets needed:** "Admin 0 Countries (10m)" and "Reefs (10m)" from Natural Earth seed. The "World Countries" reference in collections.spec.ts likely refers to the same Admin 0 Countries dataset added to a collection.

### Existing Seed Infrastructure

Three seed scripts exist:
- `scripts/seed-natural-earth.py` -- Downloads 130+ NE 10m datasets via API (httpx, async). This is the main seed script. Uses `--api-key`, `--base-url`, `--dataset` (single stem filter), `--cache-dir`, `--dry-run`. Creates collections post-import.
- `scripts/seed-ago-data.py` -- ArcGIS Online data seeder
- `scripts/seed-perf-data.py` -- Performance test data

### Playwright Config

- `playwright.config.ts`: `globalSetup` is NOT used. Auth is handled via `e2e/auth.setup.ts` (project dependency).
- Auth setup logs in as admin, saves storage state to `playwright/.auth/user.json`.
- `baseURL`: `http://localhost:8080` (nginx).
- Workers: 1, sequential.

### Recommendation: Minimal E2e Seed Script

Create `scripts/seed-e2e.py` that seeds only the 2 critical datasets needed for e2e tests:
- `ne_10m_admin_0_countries` (for dataset-detail, collections tests)
- `ne_10m_reefs` (for search test)

Reuse the `seed-natural-earth.py` pattern (httpx, upload API, poll job) but with a hardcoded 2-dataset manifest. Should take ~30 seconds vs ~30 minutes for the full NE seed. Alternatively, pass `--dataset ne_10m_admin_0_countries` twice to the existing script, but a dedicated e2e script is cleaner and could also create a test collection.

**DB connection not needed** -- seed scripts use the HTTP API, not direct DB access.

## Item 2: Retroactive Verification of 260320-m42 and 260321-f9l

### 260320-m42: Multi-Part Geometry Safety

**Status: INTACT -- recommend marking Verified.**

Verified by grep:

1. **`_geometry_sql()` helper** in `backend/app/features/service.py` (line 29): wraps with `ST_Multi()` for Multi* typed columns. Used at lines 222, 264, 310 (insert, update, replace paths).

2. **`isMultiPartGeometry()`** in `frontend/src/hooks/use-terra-draw.ts` (line 78): exported function checking coordinates.length > 1 for Multi* geometry types.

3. **Multi-part editing guard** in `frontend/src/hooks/use-feature-editing.ts` (line 267): calls `isMultiPartGeometry()` before allowing edit.

4. **Unit tests**: 7 tests for `isMultiPartGeometry` in `use-terra-draw.test.ts`, 4 promotion tests in `backend/tests/test_features_crud.py`.

5. **i18n key** `map.multiPartNotEditable` in `en/dataset.json`.

No subsequent tasks modified these files in ways that would remove the guard.

### 260321-f9l: Error Boundaries with i18n

**Status: INTACT -- recommend marking Verified.**

Verified by grep and file existence:

1. **All 4 boundary components exist:**
   - `frontend/src/components/error/AppErrorBoundary.tsx`
   - `frontend/src/components/error/MapErrorBoundary.tsx`
   - `frontend/src/components/error/RouteErrorBoundary.tsx`
   - `frontend/src/components/error/LazyLoadErrorBoundary.tsx`

2. **Wiring confirmed:**
   - `AppErrorBoundary` wraps everything in `main.tsx` (lines 32-41)
   - `LazyLoadErrorBoundary` wraps `Suspense` in `App.tsx` (lines 37-41)
   - `RouteErrorBoundary` on `datasets/:id` and `maps/:id` routes in `App.tsx` (lines 54, 61)
   - `MapErrorBoundary` wraps `BuilderMap` in `MapBuilderPage.tsx` (lines 329-337)

3. **i18n keys**: `errorBoundary` namespace present in all 4 locales (en, es, fr, de).

4. **Unit tests**: 12 tests in `ErrorBoundaries.test.tsx`.

5. **260322-l97 fix**: AppErrorBoundary was updated to use `useTranslation` ready flag instead of try/catch (per STATE.md decision). This is an improvement, not a regression.

## Item 3: Non-Spatial CSV E2e Integration Test

### Existing Test Infrastructure

- **conftest.py fixtures**: `client` (AsyncClient with ASGI transport), `admin_auth_header`, `editor_auth_header`, `viewer_auth_header`, `test_db_session`. Full DB lifecycle with PostGIS + Alembic.
- **TestCsvUpload** exists in `test_ingest.py` but only tests upload (status 201, job created). The ingest task (`ingest_file`) is mocked via `mock_ingest_task` fixture -- `defer_async` returns None.
- **Ingest task** runs as a Procrastinate background task. In tests, it's always mocked. Running it synchronously would require calling `ingest_file()` directly with the right arguments.

### Full Pipeline Test Strategy

The challenge: the ingest task calls `ogr2ogr` and `ogrinfo` (subprocess calls requiring GDAL). These only work inside the Docker container, not in local pytest unless GDAL is installed.

**Option A: Mock ogr2ogr, test DB registration** -- Create a pre-loaded table in the test DB, then call `create_dataset()` directly with `geometry_type=None`. Verify record_type='table', no spatial columns, queryable via features API.

**Option B: Call ingest_file() directly** -- Skip the mock, call the task function with a real CSV file. Requires GDAL installed in test environment (works in Docker, fails locally).

**Recommendation: Option A (mock approach)**. More reliable, tests the important business logic (record_type detection, features API for non-spatial data) without external dependency. Structure:

```python
class TestCsvNonSpatialPipeline:
    async def test_csv_non_spatial_full_pipeline(
        self, client, admin_auth_header, test_db_session
    ):
        # 1. Create a non-spatial table directly in test DB
        await test_db_session.execute(text("""
            CREATE TABLE data.test_csv_nonspatial (
                ogc_fid serial PRIMARY KEY,
                name text, value integer
            )
        """))
        await test_db_session.execute(text("""
            INSERT INTO data.test_csv_nonspatial (name, value)
            VALUES ('Alice', 100), ('Bob', 200)
        """))
        await test_db_session.commit()

        # 2. Register via API (POST /ingest/register)
        resp = await client.post("/ingest/register", json={
            "table_name": "test_csv_nonspatial",
            "title": "Test CSV Table",
        }, headers=admin_auth_header)

        # 3. Verify dataset.record_type == 'table'
        # 4. Verify GET /features/{id}/ returns rows
        # 5. Verify no geometry columns
```

The `/ingest/register` endpoint registers an existing table as a dataset -- this is the path that `ingest_file` ultimately uses. It calls `create_dataset()` which sets `record_type = "table"` when `geometry_type is None`.

### Key Code Paths

- `backend/app/datasets/service.py` line 161: `record_type = "table" if geometry_type is None else "vector_dataset"`
- `backend/app/ingest/ogr.py` line 250: `is_non_spatial = geometry_type is None` -- skips spatial columns, clipping, 4326 transform
- `backend/app/ingest/service.py` line 288: Non-spatial tables get `grant_reader_access` but skip `extract_metadata` spatial parts

## Sources

All findings from direct codebase inspection (HIGH confidence):
- `scripts/seed-natural-earth.py` -- seed pattern
- `playwright.config.ts` -- e2e config
- `e2e/*.spec.ts` -- dataset dependencies
- `backend/tests/conftest.py` -- test fixtures
- `backend/tests/test_ingest.py` -- existing CSV test
- `backend/app/features/service.py` -- ST_Multi verification
- `frontend/src/components/error/` -- error boundary verification
- `backend/app/datasets/service.py` -- record_type logic

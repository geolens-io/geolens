# Quick Task 260322-l97: Test Coverage and Error Handling Fixes - Research

**Researched:** 2026-03-22
**Domain:** Backend integration testing, React error boundaries, frontend component testing
**Confidence:** HIGH

## Summary

Three targeted fixes with clear patterns to follow from the existing codebase. The CSV ingestion test follows the established `test_ingest.py` pattern with mocked procrastinate tasks. The AppErrorBoundary has a hooks-in-try-catch anti-pattern that only exists in that one component (the other 3 error boundaries are clean). Frontend component tests follow the established vitest + @testing-library/react pattern with a well-equipped `test-utils.tsx` wrapper.

## 1. CSV Ingestion Integration Test

### Existing Test Pattern (HIGH confidence)
File: `backend/tests/test_ingest.py` -- all tests use:
- `client: AsyncClient` fixture (from conftest, uses real DB via ASGITransport)
- `admin_auth_header` fixture for auth
- `mock_ingest_task` autouse fixture -- patches `app.ingest.router.ingest_file` to prevent procrastinate deferral
- `mock_file_save` autouse fixture -- saves uploads to tmp_path instead of real staging dir
- `test_db_session` for direct DB assertions

### CSV Upload Test Strategy
Upload a minimal CSV (no geometry columns) and verify:
1. POST `/ingest/upload` returns 201 with job_id
2. IngestJob record created in DB with status="pending"

The test only exercises the upload endpoint (which creates an IngestJob and defers the task). The actual ingestion pipeline (ogrinfo, ogr2ogr) runs in `ingest_file` which is mocked out. So the test confirms the upload path accepts CSV files.

### Minimal CSV Content
```python
csv_content = b"id,name,value\n1,Alice,100\n2,Bob,200\n"
```
No lat/lon/geometry columns = non-spatial. The `.csv` extension is in the allowed list (`backend/app/ingest/validation.py:27`).

### How geometry_type=None Gets Set
In `backend/app/ingest/ogr.py:run_ogrinfo()`:
- JSON path (line 110): If `geom_fields` is empty list, `geometry_type = None`
- Text path (line 54): Default is `None`, only set if "Geometry:" line found
- In `tasks.py:108`: `has_geometry = geometry_type is not None` gates all spatial operations

### What to Test
Add a `TestCsvUpload` class to `test_ingest.py`:
- `test_csv_upload_success` -- upload CSV, verify 201, verify job created
- Optionally: test that the CSV content is a valid file the mock_file_save writes correctly

### Key Detail
The test mirrors `test_upload_success` but with CSV content and `.csv` filename instead of GeoJSON.

## 2. AppErrorBoundary Hooks-in-Try-Catch Fix

### The Anti-Pattern (HIGH confidence)
File: `frontend/src/components/error/AppErrorBoundary.tsx`, lines 15-28:

```tsx
function AppErrorFallback({ error }: { error: Error | null }) {
  let title = 'Something went wrong';
  let message = '...';
  let reload = 'Reload page';

  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { t } = useTranslation('common');  // <-- HOOK INSIDE TRY/CATCH
    title = t('errorBoundary.appTitle');
    message = t('errorBoundary.appMessage');
    reload = t('errorBoundary.appReload');
  } catch {
    // i18n not available -- use hardcoded English fallbacks above
  }
  // ...
}
```

This violates React's Rules of Hooks -- hooks must be called unconditionally at the top level, never inside try/catch. The eslint-disable comment confirms it was intentional but incorrect.

### Other Error Boundaries -- All Clean
- `MapErrorBoundary.tsx` -- `MapErrorFallback` calls `useTranslation('common')` at top level, no try/catch. Clean.
- `LazyLoadErrorBoundary.tsx` -- `LazyLoadFallback` calls `useTranslation('common')` at top level. Clean.
- `RouteErrorBoundary.tsx` -- function component calls `useTranslation('common')` at top level. Clean.

Only `AppErrorBoundary` has this problem.

### Correct Fix
Call `useTranslation` unconditionally at the top of the component. Use a fallback strategy that does not wrap hooks:

```tsx
function AppErrorFallback({ error }: { error: Error | null }) {
  const { t, ready } = useTranslation('common');

  const title = ready ? t('errorBoundary.appTitle') : 'Something went wrong';
  const message = ready ? t('errorBoundary.appMessage') : 'An unexpected error occurred...';
  const reload = ready ? t('errorBoundary.appReload') : 'Reload page';
  // ...
}
```

Since this is the app-level error boundary (outermost), i18n might not be initialized when it catches. The `ready` flag from `useTranslation` handles this -- if i18n is not initialized, `ready` is false and we use hardcoded strings.

Alternative: Since the test setup initializes i18n, and in production i18n initializes synchronously before render, the simplest fix may be just calling `useTranslation` at top level without the try/catch, since the i18nProvider wraps below this boundary level. If i18n truly fails, useTranslation returns the key as-is which is acceptable for an error fallback.

### Existing Tests
`frontend/src/components/error/__tests__/ErrorBoundaries.test.tsx` already tests all 4 boundaries. The AppErrorBoundary tests check for hardcoded English strings ("Something went wrong", "Reload page"). After the fix, since test setup initializes i18n, tests should check for i18n-resolved strings instead (or the English translations which should match).

## 3. Frontend Component Tests

### Test Infrastructure (HIGH confidence)
- **Framework:** vitest with jsdom environment, globals enabled
- **Config:** `frontend/vite.config.ts` (test section at line 79)
- **Setup:** `frontend/src/test/setup.ts` -- imports jest-dom matchers, initializes i18n, mocks maplibre-gl
- **Test utils:** `frontend/src/test/test-utils.tsx` -- wraps render with QueryClientProvider + MemoryRouter
- **Run:** `npm test` or `vitest run --passWithNoTests`
- **Pattern:** Tests in `__tests__/` subdirectories adjacent to source files
- **Existing tests:** 50+ test files following consistent patterns

### RelatedRecordsPanel Test Plan
File: `frontend/src/components/dataset/RelatedRecordsPanel.tsx`
Create: `frontend/src/components/dataset/__tests__/RelatedRecordsPanel.test.tsx`

**Testable states:**
1. **Loading** -- query in flight, shows Skeleton elements
2. **Error** -- query fails, shows error message
3. **Empty** -- no relationships returned, renders null (nothing in DOM)
4. **Populated** -- relationships returned, shows title + collapsible sections

**Mocking strategy:** Mock `@/api/datasets` module (listRelationships, getRelatedRecords). Pattern from existing tests like `SearchResultCard.test.tsx` -- provide mock data directly.

**Key mock shape:**
```ts
const mockRelationship: DatasetRelationship = {
  id: 'rel-1',
  source_dataset_id: 'ds-1',
  source_column: 'county_id',
  target_dataset_id: 'ds-2',
  target_column: 'id',
  target_dataset_title: 'Counties',
  label: 'County Records',
};
```

**Approach:** Use `vi.mock('@/api/datasets')` and control return values per test. Need QueryClientProvider wrapper (already in test-utils render).

### NotFoundPage Test Plan
File: `frontend/src/pages/NotFoundPage.tsx`
Create: `frontend/src/pages/__tests__/NotFoundPage.test.tsx`

**Testable behavior:**
1. Renders "404" text
2. Renders i18n title and description
3. Has a link/button pointing to "/"
4. Uses correct i18n keys (notFound.title, notFound.description, notFound.goHome)

**Simple test -- no mocking needed** since it is a pure presentational component. Just render with the test-utils wrapper (provides MemoryRouter for Link) and assert text content + link target.

## Pitfalls

### Pitfall 1: AppErrorBoundary i18n Context
**What goes wrong:** AppErrorBoundary wraps the entire app including the i18n provider, so if i18n crashes, useTranslation may throw.
**How to avoid:** Use `useTranslation` with Suspense disabled (default in this project's i18n config), check `ready` flag, keep hardcoded fallbacks for the case where i18n is completely broken.

### Pitfall 2: CSV Test May Need Correct Content-Type
**What goes wrong:** Upload validation may check MIME type.
**How to avoid:** Use `"text/csv"` as the content type in the files tuple: `("data.csv", csv_bytes, "text/csv")`.

### Pitfall 3: RelatedRecordsPanel Returns Null for Empty
**What goes wrong:** Testing "empty state" -- component returns `null` when no relationships, so there is nothing to assert in the DOM.
**How to avoid:** Assert that the container is empty or that specific elements are NOT present.

## Sources

### Primary (HIGH confidence)
- `backend/tests/test_ingest.py` -- existing upload test patterns
- `backend/tests/conftest.py` -- test fixtures (client, auth, db_session)
- `frontend/src/components/error/AppErrorBoundary.tsx` -- the anti-pattern source
- `frontend/src/components/error/__tests__/ErrorBoundaries.test.tsx` -- existing boundary tests
- `frontend/src/test/test-utils.tsx` -- test render wrapper
- `frontend/src/test/setup.ts` -- vitest setup with i18n and maplibre mocks
- `frontend/vite.config.ts` -- vitest configuration

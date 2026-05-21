# Quick Task 260322-irw: Polish Shipped Work - Research

**Researched:** 2026-03-22
**Domain:** UI/UX, test coverage, error handling across 17 quick tasks (03/19-03/22)
**Confidence:** HIGH

## Summary

Systematic audit of 17 shipped quick tasks found **1 critical runtime bug**, **3 high-impact issues**, and several medium/low items. The critical bug is that all 4 FK relationship endpoints use `get_session` (never imported) instead of `get_db`, meaning they throw `NameError` at runtime. The high-impact issues are: missing i18n keys for RelatedRecordsPanel, missing error state handling in RelatedRecordsPanel, and zero test coverage for FK relationship endpoints.

**Primary recommendation:** Fix the `get_session` bug immediately, then add i18n keys and error handling to RelatedRecordsPanel, then add basic test coverage for FK relationship CRUD.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- All 17 quick tasks from 03/19 to 03/22 in scope
- All three dimensions equally weighted: test coverage, UI/UX visual polish, error handling
- Fix top issues; catalog remaining as todos

### Claude's Discretion
- Which specific issues qualify as "highest impact" vs. cataloged
- Grouping strategy for fixes
- Test framework/tooling choices

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Findings by Priority

### CRITICAL: FK Relationship Endpoints Use Non-Existent `get_session`

**Category:** Error handling / Runtime bug
**Impact:** CRITICAL
**Files:** `backend/app/datasets/router.py` lines 2169-2230

All 4 FK relationship endpoints (`list_dataset_relationships`, `create_dataset_relationship`, `delete_dataset_relationship`, `get_feature_related_records`) use `Depends(get_session)` but `get_session` is never imported. The rest of the file (32 other endpoints) uses `Depends(get_db)`. These endpoints will throw `NameError` at runtime on any request.

**Fix:** Replace `get_session` with `get_db` in all 4 endpoints.

Additionally, `list_dataset_relationships` and `get_feature_related_records` have **no auth dependency** -- they accept only `db` as a parameter, no `user` or `current_user`. The list endpoint should at minimum follow the pattern of other read endpoints using `get_optional_user` for visibility checks. The related records endpoint similarly has no visibility check on either the source or target dataset.

---

### HIGH: RelatedRecordsPanel Missing i18n Keys (4 locales)

**Category:** UI/UX - i18n
**Impact:** HIGH
**File:** `frontend/src/components/dataset/RelatedRecordsPanel.tsx`

The component uses `t('dataset.relatedRecords', { defaultValue: 'Related Records' })` but this key does **not exist** in any of the 4 locale files (en, de, es, fr). The `defaultValue` fallback means English works, but the key is absent from the translation system.

Additional hardcoded strings on lines 33, 54, 80-82:
- `'Related Records'` fallback in label (line 33) -- not wrapped in `t()`
- `'No related records'` (line 54) -- not wrapped in `t()`
- `'Showing {n} of {m} records'` (line 81) -- not wrapped in `t()`

**Fix:** Add `dataset.relatedRecords`, `dataset.noRelatedRecords`, `dataset.showingRecords` keys to all 4 locale files and use `t()` for all visible strings.

---

### HIGH: RelatedRecordsPanel Missing Error State

**Category:** Error handling
**Impact:** HIGH
**File:** `frontend/src/components/dataset/RelatedRecordsPanel.tsx`

Both `useQuery` calls destructure `{ data, isLoading }` but never check `isError` or `error`. If the API call fails (which it currently always will due to the `get_session` bug above), the component silently shows nothing -- no loading skeleton, no error message. The `RelatedSection` inner component has the same gap.

**Fix:** Add `isError` destructuring to both queries and render an error state (e.g., `ErrorState` component or inline text).

---

### HIGH: Zero Test Coverage for FK Relationship Endpoints

**Category:** Test coverage
**Impact:** HIGH
**Files:** No test file exists

The 4 FK relationship endpoints have zero test coverage:
- `GET /datasets/{id}/relationships/` -- list
- `POST /datasets/{id}/relationships/` -- create
- `DELETE /datasets/relationships/{id}/` -- delete
- `GET /datasets/{id}/features/{gid}/related/{rel_id}/` -- query

The existing `test_related_datasets.py` tests semantic similarity (pgvector), not FK relationships. `test_records_related.py` tests contacts/keywords, not FK relationships.

**Fix:** Create `test_fk_relationships.py` covering: create, list, delete, related records query, auth enforcement, 404 for missing dataset/relationship.

---

### MEDIUM: Non-Spatial CSV Ingestion -- No Dedicated Test

**Category:** Test coverage
**Impact:** MEDIUM
**Files:** `backend/tests/test_ingest.py`, `backend/app/ingest/ogr.py`

The non-spatial ingestion path (`geometry_type=None` detection, skipping clip/4326/quicklook steps) has only indirect test coverage via export tests (`test_export_non_spatial_dataset_*`). No test exercises the actual ingestion pipeline for a CSV without geometry.

**Catalog as todo:** Add a test that ingests a pure CSV (no lat/lon columns) and verifies `geometry_type=None` on the resulting dataset.

---

### MEDIUM: Error Boundaries -- Good Coverage, One Pattern Issue

**Category:** Error handling
**Impact:** MEDIUM
**File:** `frontend/src/components/error/AppErrorBoundary.tsx` line 22

`AppErrorFallback` calls `useTranslation()` inside a try/catch with an eslint-disable comment (`rules-of-hooks`). This works but is an anti-pattern -- hooks should not be called conditionally. The other error boundaries (`MapErrorBoundary`, `RouteErrorBoundary`) do not have this issue.

**Catalog as todo:** Extract a safe wrapper or use a context-check pattern instead of try/catch around hooks.

---

### MEDIUM: FK Relationship Read Endpoints Lack Visibility Checks

**Category:** Error handling / Security
**Impact:** MEDIUM
**Files:** `backend/app/datasets/router.py` lines 2169-2230

Even after fixing `get_session` to `get_db`, the list and query endpoints don't enforce visibility. A public/anonymous user could list relationships and query related records for private datasets. Other dataset read endpoints use `get_optional_user` + `check_dataset_access`.

**Fix (bundle with get_session fix):** Add `user: User | None = Depends(get_optional_user)` and `check_dataset_access()` to the list and query endpoints.

---

### LOW: NotFoundPage and Error Boundaries -- Complete and Well-Structured

**Category:** UI/UX
**Impact:** N/A (no issues found)

The 404 page (`NotFoundPage.tsx`) uses proper i18n with `notFound.title`, `notFound.description`, `notFound.goHome` -- all present in all 4 locales. Error boundaries are tested in `ErrorBoundaries.test.tsx`. The unsaved changes guard and all error boundary variants look solid.

---

### LOW: ArcGIS Auth -- Well-Handled

**Category:** Error handling
**Impact:** N/A (no issues found)

The ArcGIS auth flow in `services/router.py` has comprehensive error handling: SSRF validation, token errors (498/499), HTTP auth errors, timeouts, transport errors, and all are audit-logged. The `test_arcgis_auth.py` covers probe behavior, token errors, and objectIdField extraction. No issues found.

---

### LOW: OGC Conformance -- Has Test Coverage

**Category:** Test coverage
**Impact:** N/A (no issues found)

`test_ogc_records_conformance.py` exists and was added as part of the 260322-c9b task. The OGC router changes appear tested.

## Prioritized Fix Plan

| # | Issue | Category | Impact | Effort |
|---|-------|----------|--------|--------|
| 1 | Fix `get_session` -> `get_db` in 4 FK endpoints | Runtime bug | CRITICAL | 5 min |
| 2 | Add visibility checks to FK list/query endpoints | Security | MEDIUM | 15 min |
| 3 | Add i18n keys for RelatedRecordsPanel (4 locales) | i18n | HIGH | 15 min |
| 4 | Add error state handling to RelatedRecordsPanel | Error handling | HIGH | 10 min |
| 5 | Add `test_fk_relationships.py` | Test coverage | HIGH | 30 min |

**Items 1-4 are bundled into the fix task (< 1 hour). Item 5 is a separate test task.**

## Catalog (Backlog Todos)

- Non-spatial CSV ingestion test (MEDIUM)
- AppErrorBoundary hooks-in-try-catch anti-pattern (LOW)
- Frontend test for RelatedRecordsPanel, NotFoundPage, unsaved changes guard (LOW -- these are UI components without complex logic)

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `backend/app/datasets/router.py` (lines 2165-2230)
- Direct code inspection of `frontend/src/components/dataset/RelatedRecordsPanel.tsx`
- AST parse confirming `get_session` not in imports
- Grep across all locale files confirming missing i18n keys
- Grep across all test files confirming zero FK relationship test coverage

## Metadata

**Confidence breakdown:**
- Runtime bug (`get_session`): HIGH -- verified via AST parse
- i18n gaps: HIGH -- verified via grep across all 4 locale directories
- Error handling gaps: HIGH -- verified via code inspection
- Test coverage gaps: HIGH -- verified via grep across test directories

**Research date:** 2026-03-22
**Valid until:** 2026-04-22

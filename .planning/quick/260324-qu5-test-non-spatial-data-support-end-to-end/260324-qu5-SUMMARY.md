---
phase: quick-260324-qu5
plan: 01
subsystem: api, ui, testing
tags: [non-spatial, distributions, DatasetMap, playwright, vitest]

requires:
  - phase: quick-260322-hv0
    provides: non-spatial CSV detection and ingestion pipeline
provides:
  - geometry_type-aware distribution generation (2 for non-spatial, 6 for spatial)
  - DatasetMap guard preventing vector tile source addition for null geometryType
  - E2E coverage for non-spatial CSV upload-to-viewing flow
affects: [dataset-ingestion, distribution-generation, dataset-map]

tech-stack:
  added: []
  patterns: [geometry_type parameter gating in generate_distributions]

key-files:
  created:
    - e2e/non-spatial.spec.ts
    - e2e/fixtures/sample-nonspatial.csv
  modified:
    - backend/app/records/service.py
    - backend/app/datasets/service.py
    - backend/tests/test_ingest.py
    - frontend/src/components/dataset/DatasetMap.tsx
    - frontend/src/components/dataset/__tests__/DatasetMap.test.tsx

key-decisions:
  - "Non-spatial datasets get exactly 2 distributions (csv download + ogc_features) vs 6 for spatial"
  - "geometry_type guard added inside addVectorLayers callback, not at component render level"
  - "Distribution tests use /records/{record_id}/distributions/ endpoint since DatasetResponse does not embed distributions"

patterns-established:
  - "geometry_type=None gating: generate_distributions skips gpkg/geojson/shp/vector_tiles when geometry_type is None"

requirements-completed: [NS-TEST-01, NS-BUG-01, NS-BUG-02]

duration: 6min
completed: 2026-03-24
---

# Quick Task 260324-qu5: Non-Spatial Data Support E2E Summary

**Distribution filtering by geometry_type for non-spatial datasets, DatasetMap null guard, and full E2E test coverage from upload to attribute table**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-24T23:34:16Z
- **Completed:** 2026-03-24T23:40:30Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- Non-spatial datasets now produce only csv download + ogc_features distributions (not gpkg/geojson/shp/vector_tiles)
- DatasetMap safely handles null geometryType with early return guard in addVectorLayers
- 3 backend tests: CSV distribution filtering, XLSX distribution filtering, OGC items with null geometry
- 2 frontend Vitest tests: non-spatial shell rendering and no edit/zoom controls
- 3 Playwright E2E tests: upload non-spatial CSV, graceful dataset page, attribute table rows

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix distribution generation for non-spatial datasets + backend tests** - `a56bf818` (fix)
2. **Task 2: Fix DatasetMap null geometryType guard + Vitest test** - `099d75be` (fix)
3. **Task 3: Playwright E2E tests for non-spatial upload and dataset page** - `24cc319f` (test)

## Files Created/Modified
- `backend/app/records/service.py` - Added geometry_type param to generate_distributions, filters non-spatial distributions
- `backend/app/datasets/service.py` - Passes geometry_type kwarg to generate_distributions call
- `backend/tests/test_ingest.py` - 3 new tests in TestCsvNonSpatialPipeline class
- `frontend/src/components/dataset/DatasetMap.tsx` - Early return guard for null geometryType in addVectorLayers
- `frontend/src/components/dataset/__tests__/DatasetMap.test.tsx` - 2 non-spatial rendering tests
- `e2e/non-spatial.spec.ts` - 3 Playwright E2E tests for non-spatial flow
- `e2e/fixtures/sample-nonspatial.csv` - Test fixture with 3 rows (Alice, Bob, Charlie)

## Decisions Made
- Distribution tests query `/records/{record_id}/distributions/` endpoint because DatasetResponse schema does not embed distributions directly
- Frontend tests use `tableName="nonspatial_table"` (realistic) instead of `tableName={null}` since real non-spatial datasets have table names
- geometry_type guard placed inside addVectorLayers callback since the edit trigger already had a geometryType check at line 841

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed test distribution access pattern**
- **Found during:** Task 1 (RED phase)
- **Issue:** Plan specified accessing distributions via `GET /datasets/{id}` response, but DatasetResponse schema does not include distributions
- **Fix:** Used `/records/{record_id}/distributions/` endpoint instead, fetching record_id from dataset response first
- **Files modified:** backend/tests/test_ingest.py
- **Verification:** All 4 backend tests pass

**2. [Rule 1 - Bug] Adjusted frontend test props for realistic non-spatial scenario**
- **Found during:** Task 2 (RED phase)
- **Issue:** Plan specified `tableName={null}` for non-spatial tests, but real non-spatial datasets have table names. With null tableName, component renders "No spatial extent" placeholder (different element) instead of map shell
- **Fix:** Used `tableName="nonspatial_table"` to match real-world non-spatial dataset behavior
- **Files modified:** frontend/src/components/dataset/__tests__/DatasetMap.test.tsx
- **Verification:** All 20 frontend tests pass

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes align tests with actual API/component behavior. No scope creep.

## Issues Encountered
- pytest not available via `python -m pytest` in api container; resolved by using `uv run pytest` instead

## Known Stubs
None - all functionality is fully wired.

## Next Phase Readiness
- Non-spatial data path is now fully tested end-to-end
- Distribution generation correctly differentiates spatial vs non-spatial datasets

---
## Self-Check: PASSED

All 7 files verified present. All 3 commit hashes verified in git log.

---
*Phase: quick-260324-qu5*
*Completed: 2026-03-24*

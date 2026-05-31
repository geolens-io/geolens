---
phase: 1157-backend-export-access-route-hygiene
plan: 02
subsystem: test
tags: [pytest, authorization, export, ogc, anonymous-access, regression]

# Dependency graph
requires:
  - phase: 1157-01
    provides: "EXP-01 anonymous vector export gate + API-01 trailing-slash alias (the code under test)"
provides:
  - "EXP-02 regression test pinning export allow/deny matrix"
  - "API-01 trailing-slash parity test"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "mock_export_service fixture: monkeypatch.setattr on app.processing.export.router.export_dataset, writes b'mock export data' to tempdir, mirrors test_export_hardening.py:181-220"
    - "OGC items parity test: create real data.{table_name} table via sqlalchemy text() for get_features() query path; cleanup in finally block"

key-files:
  created:
    - backend/tests/test_export_access.py
  modified: []

key-decisions:
  - "OGC items test creates the actual data table (not mocked) — get_features() queries data.{table_name} directly; the test creates/drops the table in a try/finally block"
  - "Parametrized format test covers gpkg/geojson/csv (shp excluded — gate logic identical, zip handling adds noise)"
  - "Denied assertions use {401,403,404} set per PATTERNS.md contract — check_dataset_access_or_anonymous raises 404 for anon denials"

# Metrics
duration: 8min
completed: 2026-05-30
---

# Phase 1157 Plan 02: EXP-02 + API-01 Regression Tests Summary

**Export access-control matrix + OGC items trailing-slash parity: 9 tests covering the full allow/deny matrix for anonymous and non-owner export, plus the dual-shape alias**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-05-30
- **Tasks:** 2
- **Files created:** 1

## Accomplishments

- EXP-02: 6 export tests pin the Plan 01 gate end-to-end
  - Positive guard (over-gating): anon + public+published → 200 with body (`geojson`)
  - Format sweep: anon + public+published → 200 for `gpkg`, `geojson`, `csv` (parametrized)
  - Deny matrix: anon + public-unpublished → `{401,403,404}`; anon + private → `{401,403,404}`; anon + restricted → `{401,403,404}`; non-owner (viewer) + private → `{401,403,404}`
- API-01: 1 OGC items test proves `/collections/{id}/items/` and `/collections/{id}/items` resolve to identical status (neither 404; canonical = 200)
- `mock_export_service` fixture patches `app.processing.export.router.export_dataset` so allow-case asserts the gate, not OGR/GDAL
- OGC items test seeds a real `data.{table_name}` PostGIS table so `get_features()` can run; cleaned up in a `finally` block

## Task Commits

1. **Task 1+2: EXP-02 + API-01 regression tests** - `f3509867` (test)

**Pytest summary:** `9 passed, 22 warnings in 6.23s`

## Files Created/Modified

- `backend/tests/test_export_access.py` (created) — 9 tests: 6 export allow/deny + 1 trailing-slash parity

## Decisions Made

- The OGC items endpoint (`get_collection_items`) calls `get_features()` which queries `data.{table_name}` directly. A Record+Dataset row alone is insufficient — the test must CREATE the actual PostGIS table. Added DDL in the test body using `sqlalchemy.text()`, mirroring the `_create_point_data_table` helper in `test_vector_tile_auth.py`, with cleanup in a `finally` block.
- Shp format excluded from the format parametrize sweep (gpkg/geojson/csv covers the gate; shp produces a zip and would add FileResponse handling noise without adding gate coverage).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] OGC items test needs real data table**
- **Found during:** Task 2 (first test run)
- **Issue:** `test_collection_items_trailing_slash_matches_no_slash` raised `asyncpg.exceptions.UndefinedTableError: relation "data.{table_name}" does not exist`. The OGC items handler calls `get_features()` which queries the PostGIS data table directly; a Record+Dataset row alone is not enough.
- **Fix:** Added `CREATE TABLE data.{table_name}` DDL + one INSERT row inside the test using `sqlalchemy.text()`, with `DROP TABLE` in a `finally` block for cleanup. Mirrors the `_create_point_data_table` pattern from `test_vector_tile_auth.py`.
- **Files modified:** `backend/tests/test_export_access.py`
- **Commit:** `f3509867` (same commit — fixed before the commit was made)

## Self-Check

- `backend/tests/test_export_access.py` exists: FOUND
- Commit `f3509867` exists: FOUND
- pytest result: `9 passed, 22 warnings in 6.23s`

## Self-Check: PASSED

---
*Phase: 1157-backend-export-access-route-hygiene*
*Completed: 2026-05-30*

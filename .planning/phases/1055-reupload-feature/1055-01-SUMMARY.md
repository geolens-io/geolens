---
phase: 1055-reupload-feature
plan: 01
subsystem: api
tags: [fastapi, reupload, validation, pytest, record-type]

requires: []
provides:
  - Cross-record-type validation guard at both reupload API entry points
  - _assert_compatible_record_type helper in router_reupload.py
  - Three pinned pytest cases: vector→raster, raster→vector, any→VRT reject

affects: [reupload, ingestion, catalog]

tech-stack:
  added: []
  patterns:
    - "Guard-before-validation: synchronous record_type check fires before async allowed_extensions lookup for precise user feedback"
    - "Extension classification via frozenset: inline _RASTER_EXTENSIONS/_VECTOR_EXTENSIONS constants, not delegated to runtime config"

key-files:
  created: []
  modified:
    - backend/app/modules/catalog/datasets/api/router_reupload.py
    - backend/tests/test_reupload.py

key-decisions:
  - "Guard wired at both reupload_dataset (multipart) and request_presigned_reupload (S3) entry points — reupload_service_preview excluded per CONTEXT.md deferred block"
  - "Audit action reupload.commit preserved unchanged — shipped and pinned by test_provenance_attribution.py; NOT renamed to dataset.reupload despite earlier CONTEXT.md draft"
  - "Extension sets defined inline as frozensets, independent of runtime allowed_extensions config which merges all record types"
  - "vrt_dataset rejects all file uploads defensively even though frontend gates the button — backend boundary validation is independent"

requirements-completed:
  - IMPORT-04

duration: 18min
completed: 2026-05-19
---

# Phase 1055 Plan 01: Cross-Record-Type Reupload Guard Summary

**HTTP 400 guard `_assert_compatible_record_type` blocks vector→raster, raster→vector, and any→VRT file swaps at both multipart and presigned reupload entry points, with record_type-aware error messages.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-19T22:10Z
- **Completed:** 2026-05-19T22:28Z
- **Tasks:** 2 (TDD: RED → GREEN per task)
- **Files modified:** 2

## Accomplishments

- Added `_RASTER_EXTENSIONS` and `_VECTOR_EXTENSIONS` module-level frozensets to `router_reupload.py`
- Added synchronous `_assert_compatible_record_type(dataset, filename)` helper covering four reject cases (vrt_dataset → any, vector_dataset/table + raster ext, raster_dataset + vector ext)
- Wired guard at both `reupload_dataset` and `request_presigned_reupload` after dataset lookup, before extension validation — user sees precise cross-record-type message before generic "extension not allowed"
- Extended `_create_dataset` test helper with `record_type` kwarg (default `"vector_dataset"`)
- Added three new `TestReuploadUpload` tests: `test_reupload_rejects_raster_file_for_vector_dataset`, `test_reupload_rejects_vector_file_for_raster_dataset`, `test_reupload_rejects_any_file_for_vrt_dataset`
- All 22 existing tests in `test_reupload.py` continue to pass; provenance attribution test `test_reupload_swap_stamps_actor_and_emits_reupload_commit_audit` still passes; `test_reupload_service.py` (3 tests) still passes

## Task Commits

1. **Task 1 (RED): Pin failing cross-record-type tests** - `0be508f5` (test)
2. **Task 2 (GREEN): Implement _assert_compatible_record_type guard** - `aa852239` (feat)

## Files Created/Modified

- `backend/app/modules/catalog/datasets/api/router_reupload.py` — Added `_RASTER_EXTENSIONS`, `_VECTOR_EXTENSIONS` constants and `_assert_compatible_record_type` helper; guard wired into `reupload_dataset` and `request_presigned_reupload`
- `backend/tests/test_reupload.py` — Extended `_create_dataset` helper with `record_type` kwarg; added three cross-record-type rejection tests

## Decisions Made

- **Guard placement:** Called immediately after dataset lookup in both file-upload entry points, before `get_allowed_extensions_list`. This ensures the user gets a clear record_type-aware message rather than a generic extension error.
- **Guard NOT added to `reupload_service_preview`:** CONTEXT.md `<deferred>` block explicitly defers service-URL reupload record-type handling. The service-URL path filters by service type, not file extension.
- **Audit action name preserved:** Shipped code uses `action="reupload.commit"` (pinned by `test_provenance_attribution.py`). The CONTEXT.md `<decisions>` block initially listed `dataset.reupload` as a decision, but the planner resolved this divergence in favor of the shipped name. No rename was made.
- **frozenset over runtime config:** `allowed_extensions` is a runtime-configurable list that merges all record types. Using it for the cross-record-type check would conflate vector and raster. Independent frozensets are the correct boundary.

## Pre-existing Reupload Backend Discovery

The audit noted that `router_reupload.py` (613 LOC), `tasks_reupload.py`, and `test_reupload.py` (30+ cases) were already shipped prior to this plan. Plan 01 closes the single remaining gap: the cross-record-type validation that the shipped code was missing at the API boundary. The Celery worker layer was intentionally NOT modified — record_type validation belongs at the API so the user gets immediate feedback.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Test runner requires `POSTGRES_HOST=localhost POSTGRES_PORT=5434` env vars to connect to the Dockerized Postgres from the host. Without these, tests fail with `database "geolens_test_<uuid>" does not exist`. Standard pattern for this project per `.env.test.example`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Cross-record-type guard is complete and pinned by tests
- Ready for Phase 1055 Plan 02+ (if any remaining reupload plans exist)
- The `reupload.commit` audit action is intact and preserved

---
*Phase: 1055-reupload-feature*
*Completed: 2026-05-19*

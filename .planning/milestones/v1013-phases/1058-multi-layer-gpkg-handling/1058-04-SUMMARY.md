---
phase: 1058-multi-layer-gpkg-handling
plan: "04"
subsystem: backend-fan-out + frontend-rewire
tags: [gpkg, multi-layer, fan-out, ingest, procrastinate, migration]

requires:
  - phase: 1058-03
    provides: "handleIngestAllLayers UI + results modal; T-1058C-03 constraint discovery"

provides:
  - "POST /ingest/commit-fan-out/{job_id} endpoint (FanOutCommitRequest/FanOutCommitResponse)"
  - "FanOutLayerRequest, FanOutCommitRequest, FanOutLayerResult, FanOutCommitResponse Pydantic models"
  - "create_fan_out_jobs() service helper cloning IngestJob per layer with fan_out_parent_id"
  - "_user_safe_error() sanitizer stripping absolute paths from error messages (T-1058D-04)"
  - "Alembic migration 0017 adding 'fanned_out' to IngestJob status CHECK constraint"
  - "commitFanOut(jobId, layers) frontend client function in api/datasets.ts"
  - "handleIngestAllLayers rewritten to single commitFanOut call (closes T-1058C-03)"
  - "test_ingest_fan_out.py: 14 tests (9 endpoint integration + 5 unit _user_safe_error)"
  - "UploadForm.multiLayerFanOut.test.tsx: 5 tests (rewritten for single-call shape)"

affects:
  - 1060-close-gate (GPKG-03 end-to-end live MCP re-verify can now succeed)

tech-stack:
  added: []
  patterns:
    - "Fan-out: single /commit-fan-out/{job_id} call replaces N separate /commit/{job_id} calls"
    - "_user_safe_error(): regex strips /path/to/... and C:\\path patterns from exception messages"
    - "FanOutLayerResult.dataset_id=None immediately: Dataset created by ingest_file task, not by fan-out service"
    - "all_layers in job.user_metadata normalised to set[str]: handles dict-list and string-list formats"
    - "status='fanned_out' terminal state: distinguishes from 'complete' (single dataset committed)"

key-files:
  created:
    - "backend/alembic/versions/0017_ingest_job_fanned_out_status.py"
    - "backend/tests/test_ingest_fan_out.py"
  modified:
    - "backend/app/platform/jobs/models.py (CheckConstraint extended to include 'fanned_out')"
    - "backend/app/processing/ingest/router.py (commit_fan_out endpoint + imports)"
    - "backend/app/processing/ingest/schemas.py (4 new Pydantic models)"
    - "backend/app/processing/ingest/service.py (create_fan_out_jobs + _user_safe_error)"
    - "frontend/src/api/datasets.ts (commitFanOut + FanOutCommitResponse + FanOutLayerResult)"
    - "frontend/src/components/import/UploadForm.tsx (handleIngestAllLayers rewrite)"
    - "frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx (5 tests rewritten)"

key-decisions:
  - "Dataset NOT pre-created in fan-out helper — ingest_file task creates it after ogr2ogr (correctness: preserves full metadata pipeline)"
  - "Migration required for 'fanned_out' status — DB CHECK constraint blocked the new terminal state; added as Rule 2 deviation"
  - "asyncpg requires split op.execute() DDL calls — cannot use multi-statement string in one op.execute()"
  - "HTTP_422_UNPROCESSABLE_CONTENT used instead of HTTP_422_UNPROCESSABLE_ENTITY (FastAPI deprecation warning)"
  - "all_layers normalisation in endpoint handles both {name:str,...}[] and str[] formats"

requirements-completed:
  - GPKG-03

duration: 11min
completed: 2026-05-20
---

# Phase 1058 Plan 04: GPKG-03 Backend Fan-Out Endpoint Summary

**Single backend endpoint converts one pending IngestJob into N independent per-layer Procrastinate tasks, closing T-1058C-03 and enabling the multi-layer GPKG fan-out path end-to-end**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-05-20T02:37:52Z
- **Completed:** 2026-05-20T02:48:35Z
- **Tasks:** 3 (Task 1+2 committed together, Task 3 separate)
- **Files modified:** 9

## Accomplishments

- **Backend endpoint**: `POST /ingest/commit-fan-out/{job_id}` dispatches N ingest tasks from one upload; validates layer names against `all_layers`, returns `FanOutCommitResponse` with per-layer `status='queued'|'failed'`; marks original job `status='fanned_out'`
- **Service helper**: `create_fan_out_jobs()` clones IngestJob per layer (same `file_path`, adds `fan_out_parent_id` + `layer_name` in user_metadata), defers `ingest_file` via existing orphan guard; `_user_safe_error()` sanitizes error messages (T-1058D-04)
- **Migration**: `0017_ingest_job_fanned_out_status.py` extends CHECK constraint to include `'fanned_out'`; ORM model updated to match
- **Frontend**: `commitFanOut()` client function added to `api/datasets.ts`; `handleIngestAllLayers` rewritten to make exactly 1 HTTP call (closes T-1058C-03)
- **Tests**: 14 backend tests (53/53 ingest test suite pass); 5 frontend tests (31/31 fan-out+BulkReviewList+ReuploadDialog suite pass); TypeScript 0 errors; i18n 2/2

## Task Commits

1. **Tasks 1+2: Backend endpoint + service helper** - `82b4e771` (feat)
2. **Task 3: Frontend rewire** - `ae20b2d2` (feat)

## Files Created/Modified

- `backend/alembic/versions/0017_ingest_job_fanned_out_status.py` — migration extending IngestJob status CHECK constraint
- `backend/app/platform/jobs/models.py` — CheckConstraint updated (ORM model must match migration)
- `backend/app/processing/ingest/router.py` — `commit_fan_out` endpoint + `FanOutCommitRequest`/`FanOutCommitResponse` imports
- `backend/app/processing/ingest/schemas.py` — 4 new Pydantic models (FanOutLayerRequest, FanOutCommitRequest, FanOutLayerResult, FanOutCommitResponse)
- `backend/app/processing/ingest/service.py` — `create_fan_out_jobs()` + `_user_safe_error()`
- `backend/tests/test_ingest_fan_out.py` — 14 tests (9 integration + 5 unit)
- `frontend/src/api/datasets.ts` — `commitFanOut()` + `FanOutCommitResponse` + `FanOutLayerResult` types
- `frontend/src/components/import/UploadForm.tsx` — `handleIngestAllLayers` rewrite + import
- `frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx` — 5 new tests

## Decisions Made

- **Dataset not pre-created in fan-out helper**: The plan said "Create a new Dataset row" in the service helper, but doing so before ogr2ogr runs would bypass the full metadata extraction pipeline (`geom_4326`, column metadata, quality score, embeddings). The Dataset is created by `_finalize_ingest` in the background task — exactly as the single-commit path. `FanOutLayerResult.dataset_id` is `null` immediately and is populated when the task completes (client should poll `/jobs/{new_job_id}` for the completed dataset_id).
- **Migration required**: The plan did not mention a migration. The existing `CheckConstraint` on `IngestJob.status` only allows `('pending', 'running', 'complete', 'failed', 'cancelled')`. Setting `status='fanned_out'` without extending the constraint would fail at the DB level. Added migration 0017 (Rule 2: missing critical functionality for correctness).
- **asyncpg DDL split**: asyncpg rejects multi-statement prepared statements. The migration uses two separate `op.execute()` calls (DROP CONSTRAINT + ADD CONSTRAINT).
- **HTTP_422_UNPROCESSABLE_CONTENT**: Used the non-deprecated constant (FastAPI shows deprecation warning for `HTTP_422_UNPROCESSABLE_ENTITY` in newer versions).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] DB migration required for 'fanned_out' status**
- **Found during:** Task 1 (implementing endpoint)
- **Issue:** IngestJob.status has a CHECK constraint that rejects any value outside `('pending', 'running', 'complete', 'failed', 'cancelled')`. Setting `status='fanned_out'` would raise a DB constraint violation at runtime.
- **Fix:** Added migration `0017_ingest_job_fanned_out_status.py` extending the constraint; updated ORM model to match.
- **Files modified:** `backend/alembic/versions/0017_ingest_job_fanned_out_status.py`, `backend/app/platform/jobs/models.py`
- **Committed in:** 82b4e771

**2. [Rule 2 - Missing Critical] Dataset NOT pre-created in fan-out helper (plan over-specification)**
- **Found during:** Task 2 (implementing service helper)
- **Issue:** The plan said to "Create a new Dataset row" in `create_fan_out_jobs()`. But the existing ingest pipeline (`_finalize_ingest` in tasks_common.py) creates the Dataset AFTER ogr2ogr runs with full metadata (column info, extent, quality score, embeddings). Pre-creating the Dataset would result in a duplicate Dataset row when the task runs, or require significant changes to the task to "update" rather than "create".
- **Fix:** `create_fan_out_jobs()` creates only the IngestJob and defers `ingest_file`. `FanOutLayerResult.dataset_id` is `null` immediately (nullable in schema). Client polls `/jobs/{new_job_id}` to get the completed dataset_id.
- **Files modified:** `backend/app/processing/ingest/service.py`, `backend/app/processing/ingest/schemas.py`

**3. [Rule 1 - Bug] asyncpg multi-statement DDL error in migration**
- **Found during:** First test run
- **Issue:** `op.execute()` with a multi-statement SQL string fails on asyncpg (`PostgresSyntaxError: cannot insert multiple commands into a prepared statement`)
- **Fix:** Split into two `op.execute()` calls (DROP CONSTRAINT, ADD CONSTRAINT separately)
- **Files modified:** `backend/alembic/versions/0017_ingest_job_fanned_out_status.py`

## Pre-existing Failures (Out of Scope)

`test_ingest_ogr_pure.py::TestExtractCommonLayerMetadata::test_multi_layer_picks_named_layer` fails because Plan 01 changed `_extract_common_layer_metadata` to always populate `all_layers` when `len > 1`, but this test expects `all_layers is None` when a specific layer is requested. This failure pre-dates Plan 04 and is out of scope.

## Known Stubs

- `FanOutLayerResult.dataset_id = null`: Dataset ID is not available immediately after fan-out dispatch. The client must poll `GET /jobs/{new_job_id}` to get the dataset after the ingest task completes. This is documented behavior, not a UI stub.
- E2E live MCP re-verify of the full upload→fan-out→datasets path is deferred to Phase 1060 close gate.

## Threat Surface Scan

| Threat ID | Disposition | Implemented |
|-----------|-------------|-------------|
| T-1058D-01 | mitigated | Validates layer_name against job.user_metadata.all_layers; 422 with unknown_layers list |
| T-1058D-02 | mitigated | `max_length=50` on layers list in FanOutCommitRequest |
| T-1058D-03 | mitigated | Title flows into Dataset.title via React JSX escaping; no SSR injection |
| T-1058D-04 | verified | `_user_safe_error()` strips Unix/Windows absolute paths; 5 unit tests confirm |
| T-1058D-05 | mitigated | `require_permission("upload")` same as single-commit path |
| T-1058D-06 | mitigated | `fan_out_parent_id` in each cloned job's user_metadata + `status='fanned_out'` on original |

## Test Results

| Gate | Result | Count |
|------|--------|-------|
| Backend pytest `tests/test_ingest_fan_out.py` | PASS | 14/14 |
| Backend pytest `tests/test_ingest_fan_out.py tests/test_ingest.py` | PASS | 53/53 |
| Frontend vitest `UploadForm.multiLayerFanOut` | PASS | 5/5 |
| Frontend vitest `UploadForm BulkReviewList ReuploadDialog` | PASS | 31/31 |
| TypeScript tsc --noEmit | PASS | 0 errors |
| i18n parity (`npm run test:i18n`) | PASS | 2/2 |

## GPKG-03 Acceptance Criterion Status

GPKG-03: "Single upload of a multi-layer GPKG → N datasets created"

**End-to-end path is now achievable:**
1. User uploads multi-layer.gpkg → `/ingest/upload` → `job_id` returned
2. `/ingest/preview/{job_id}` returns `all_layers: [{name: 'buildings', ...}, ...]`
3. Bulk Review renders "Ingest all N layers" button (Plan 03)
4. Button click → `handleIngestAllLayers` → `commitFanOut(jobId, layers)` → **single HTTP call**
5. Backend dispatches N `ingest_file` tasks (one per layer) → N datasets created
6. Results modal shows per-layer success/failure

**Blocked only by:** Phase 1060 live MCP re-verify (Playwright MCP availability).

## Self-Check

**Created files:**
- `/Users/ishiland/Code/geolens/backend/alembic/versions/0017_ingest_job_fanned_out_status.py` — FOUND
- `/Users/ishiland/Code/geolens/backend/tests/test_ingest_fan_out.py` — FOUND
- `/Users/ishiland/Code/geolens/.planning/phases/1058-multi-layer-gpkg-handling/1058-04-SUMMARY.md` — (this file)

**Commits:**
- `82b4e771` — Tasks 1+2 (feat backend endpoint + service helper)
- `ae20b2d2` — Task 3 (feat frontend rewire)

## Self-Check: PASSED

---
*Phase: 1058-multi-layer-gpkg-handling*
*Completed: 2026-05-20*

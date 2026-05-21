---
phase: 1073-audit-remediation
plan: 2
subsystem: backend
tags: [pydantic, sqlalchemy, alembic, fastapi, ingest, jobs, progress]

# Dependency graph
requires:
  - phase: 1072-fresh-audits
    provides: ingest-audit P2-07 finding (JobStatusResponse missing progress/current_step/rows_processed)
provides:
  - "JobStatusResponse declares progress (float ge=0 le=1), current_step (Literal of 7 step names), rows_processed (int ge=0) — all default to None for back-compat"
  - "IngestJob model gains 3 nullable columns: progress (Float), current_step (String(32)), rows_processed (Integer)"
  - "Alembic migration 0022 adds the 3 columns to catalog.ingest_jobs — round-trips cleanly (upgrade/downgrade/upgrade)"
  - "tasks_vector.ingest_file writes current_step at 4 step boundaries: validating (0.0), ogr2ogr (0.1, brief-session), finalize (0.7, phase-2), complete (1.0, via _finalize_ingest)"
  - "tasks_vector.ingest_service mirrors the same 4-step pattern minus archiving"
  - "tasks_raster.ingest_raster writes current_step at 5 step boundaries: validating (0.0), cog_convert (0.2, brief-session), quicklook (0.6, brief-session), finalize (0.8, phase-2), complete (1.0)"
  - "tasks_common._finalize_ingest is the single terminal-write site for vector ingests — stamps progress=1.0, current_step=complete, rows_processed=metadata[feature_count] atomically with status=complete"
  - "Worker progress regression test (test_ingest_progress.py) — 3 tests including load-bearing brief-session pin"
affects: [1073-03, 1073-04, 1074-close-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Brief-session pattern for progress writes ahead of long-running subprocess work — open async_session, re-load job, set current_step/progress, commit, close. Mirrors the existing #100 split shape but lifts the progress write OUT of the long-running transaction so the UI sees the step transition even if the subprocess crashes."
    - "Phase-2 progress writes (finalize step) are uncommitted on purpose — participate in _finalize_ingest's terminal transaction so a rollback cleans them up. The durable mid-flight checkpoints are the brief-session writes above."
    - "Pydantic Literal at API boundary + flexible String(32) DB column — current_step values are validated by JobStatusResponse, no DB CHECK constraint. Adding a new step only requires touching the schema (single-source-of-truth per project KNOWN-04)."

key-files:
  created:
    - backend/alembic/versions/0022_ingest_jobs_progress_columns.py
    - backend/tests/test_ingest_progress.py
  modified:
    - backend/app/platform/jobs/schemas.py
    - backend/app/platform/jobs/models.py
    - backend/app/platform/jobs/router.py
    - backend/app/processing/ingest/tasks_vector.py
    - backend/app/processing/ingest/tasks_raster.py
    - backend/app/processing/ingest/tasks_common.py
    - backend/tests/test_jobs_router.py

key-decisions:
  - "current_step Literal includes the union of vector + raster step names (7 total: validating, ogr2ogr, finalize, archiving, complete, cog_convert, quicklook). Per-path subsets are encoded in the worker code, not in the schema — the schema accepts any of the 7 so future cross-path reuse doesn't require a contract change."
  - "rows_processed is set to metadata.get('feature_count') in _finalize_ingest. Raster ingests do NOT call _finalize_ingest (they use tasks_raster's own phase-2 flow) so rows_processed stays NULL for raster — documented inline at tasks_raster.py:444 (no rows for raster)."
  - "Brief-session ogr2ogr write uses _progress_session as the local name to avoid shadowing the outer `session` variable that the phase-1/2 blocks own. Same convention applied to all 4 brief-session sites (vector ogr2ogr x2, raster cog_convert, raster quicklook)."
  - "Router _job_to_status_response forwards the 3 new fields from job ORM attrs to JobStatusResponse — necessary because the router builds the response explicitly (not via from_attributes auto-mapping)."

patterns-established:
  - "Brief-session progress write: when adding a UX-visible signal that must survive subprocess failure, lift the write into its own async_session block before the work. Distinct from #100 lifecycle rule (no session across subprocess) — this pattern composes ON TOP of that rule."
  - "Phase-2 progress write piggybacks on terminal transaction: when the same field is also written terminally, the phase-2 mid-flight stamp does NOT need its own commit — _finalize_ingest's commit owns the row lifecycle."
  - "Pydantic Literal + flexible String(32) for evolving enum-like text columns — keeps the contract boundary at the API, lets the DB schema stay stable across step additions."

requirements-completed: [REMED-02]

# Metrics
duration: ~30min
completed: 2026-05-21
---

# Phase 1073 Plan 02: JobStatusResponse Progress Fields Summary

**JobStatusResponse adds progress (0.0-1.0), current_step (7-name Literal), and rows_processed fields; vector + raster workers write them at every natural step boundary so multi-minute ingests surface progress to the polling UI instead of looking dead.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-05-21T14:39Z
- **Completed:** 2026-05-21T14:50Z
- **Tasks:** 6 (5 implementation + 1 verification)
- **Files modified:** 7 (5 modified, 2 created)

## Accomplishments

- Contract surface: `JobStatusResponse.progress` / `current_step` / `rows_processed` (Pydantic bounds: ge=0/le=1 on progress, Literal allowlist on step, ge=0 on rows).
- DB surface: `catalog.ingest_jobs` gains 3 nullable columns via reversible Alembic migration `0022_ingest_jobs_progress_columns`.
- Vector worker (file + service paths): 4 step boundaries written. Brief-session pattern ahead of `run_ogr2ogr` ensures the UI sees the transition even if ogr2ogr crashes.
- Raster worker: 5 step boundaries written. Brief-session pattern ahead of `check_and_prepare_cog` AND `generate_quicklook` covers the two CPU/IO hotspots.
- Shared `_finalize_ingest` is the single terminal-write site for vector — `progress=1.0`, `current_step="complete"`, `rows_processed=metadata["feature_count"]` are stamped atomically with `status="complete"` and `dataset_id`.
- 3 new regression tests pinning the contract, including the load-bearing `test_vector_worker_writes_ogr2ogr_step_before_subprocess` that verifies the brief-session pattern survives an ogr2ogr crash.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add progress fields to JobStatusResponse + IngestJob + router** — `29167a28` (feat)
2. **Task 2: Alembic migration 0022 adds 3 nullable columns** — `690cd661` (feat)
3. **Task 3: Wire vector ingest worker (ingest_file + ingest_service + _finalize_ingest)** — `b4a4f47d` (feat)
4. **Task 4: Wire raster ingest worker (ingest_raster)** — `880946be` (feat)
5. **Task 5: Worker write regression tests** — `771a4e68` (test)
6. **Task 6: Touched-area pytest spot-check** — (verification only, no code)

Task 1 was committed as a single GREEN-after-RED commit (the failing tests + the schema/model/router fixes that make them pass + the inline router forward of the new fields, which the plan implicitly required but did not enumerate as a separate fix — see deviations).

## Files Created/Modified

### Created

- `backend/alembic/versions/0022_ingest_jobs_progress_columns.py` — adds 3 nullable columns to `catalog.ingest_jobs`. No CHECK constraint on `current_step` per project KNOWN-04 (Pydantic Literal is the contract).
- `backend/tests/test_ingest_progress.py` — 3 regression tests pinning the worker writes + brief-session pattern.

### Modified

- `backend/app/platform/jobs/schemas.py` — `JobStatusResponse` adds `progress`, `current_step` (Literal of 7 step names), `rows_processed`.
- `backend/app/platform/jobs/models.py` — `IngestJob` adds matching nullable columns (Float / String(32) / Integer).
- `backend/app/platform/jobs/router.py` — `_job_to_status_response` forwards the 3 new fields from `job` ORM attrs to the explicit Pydantic constructor. (See deviations Rule 1.)
- `backend/app/processing/ingest/tasks_vector.py` — `ingest_file` writes validating/ogr2ogr/finalize; `ingest_service` mirrors the same 4-step shape minus archiving.
- `backend/app/processing/ingest/tasks_raster.py` — `ingest_raster` writes validating/cog_convert/quicklook/finalize/complete with brief-session pattern at the two CPU/IO hotspots.
- `backend/app/processing/ingest/tasks_common.py` — `_finalize_ingest` stamps terminal progress alongside `status="complete"`.
- `backend/tests/test_jobs_router.py` — 3 new tests: default-None back-compat, written-value round-trip, Pydantic bounds (ge/le/Literal).

## Decisions Made

- **`current_step` Literal as union of vector + raster step names (7 total).** Per-path step subsets are encoded in the worker code, not in the schema. The schema accepts any of the 7 so future cross-path reuse doesn't require a contract change. The DB column stays `String(32)` — Pydantic is the boundary (per project KNOWN-04).
- **`rows_processed` is NULL for raster.** Raster ingests don't go through `_finalize_ingest` (they have their own phase-2 in `tasks_raster.py`). The inline comment at the terminal write site documents this so a future maintainer doesn't misread the missing assignment as a bug.
- **Brief-session writes commit; phase-2 writes don't.** The two patterns serve different purposes — brief-session writes are durable mid-flight checkpoints that must survive subprocess crashes; phase-2 writes are "while in this transaction" updates that participate in rollback. Without this split, either the contract leaks (phase-2-only would lose mid-flight signal on failure) or the rollback semantics break (brief-session-everywhere would orphan a partial transition).
- **OpenAPI snapshot NOT regenerated.** Project memory's "OpenAPI dual-snapshot refresh order" + locked Phase 1074 close-gate decision: Phase 1074 owns `make openapi` (geolens) + `npm run fetch-openapi` (sibling docs) so the dual snapshot is refreshed in the correct order, once, with everything else that ships.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Router did not forward the 3 new fields**

- **Found during:** Task 1 (GREEN phase, `test_job_status_returns_written_progress_values` failed after schema + model changes alone)
- **Issue:** `_job_to_status_response` builds `JobStatusResponse` via an explicit constructor (not `from_attributes` auto-mapping). Adding the 3 fields to the schema + model alone meant the API response still returned `None` for them even when the DB row had values.
- **Fix:** Added `progress=job.progress`, `current_step=job.current_step`, `rows_processed=job.rows_processed` to the constructor call.
- **Files modified:** `backend/app/platform/jobs/router.py`
- **Verification:** `test_job_status_returns_written_progress_values` passes.
- **Committed in:** `29167a28` (Task 1)

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary for the contract surface to actually surface to clients. Plan's `<files_modified>` listed the schema + model + tests but did not enumerate `router.py` — the router forward was implicit in the contract surface goal.

## Issues Encountered

- **Pre-existing test failures in `test_ingest.py`** (out of scope per deviation rules):
  - `TestUpload::test_upload_success` — mock `_save_to_temp` doesn't accept new `max_size_bytes` kwarg added in Phase 1066.
  - `TestCsvUpload::test_csv_upload_success` — same `max_size_bytes` mock mismatch.
  - `TestCommitImportDispatch::test_service_job_commits_with_service_body` — DNS resolution failure for `example.arcgis.com` (post-Phase 1066 SSRF check actively resolves hostnames at commit time; example.com domains were never the right test fixture).
  - All 3 reproduce on the previous commit before this plan started. Deferred — not introduced by this plan and outside its scope. Mention in close-gate handoff for whichever phase owns IA-P0-02 / IA-P0-03 follow-through.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Phase 1073-03 / 1073-04:** unblocked. Worker contract is now durable; downstream consumers (frontend `BulkTrackingList`, `ReuploadDialog`) can wire to the new fields as they come online.
- **Phase 1074 close-gate:** owns `make openapi` (geolens) + `npm run fetch-openapi` (sibling docs) so the dual snapshot includes the 3 new schema fields. Per project memory's "OpenAPI dual-snapshot refresh order", this MUST run in geolens first.
- **Documentation:** consumer-side guidance (when to poll, how to render `current_step` in i18n) is a frontend wave concern, not blocked by this plan.

## Verification Summary

- `pytest tests/test_jobs_router.py` — 32/32 PASS (3 new tests)
- `pytest tests/test_ingest_progress.py` — 3/3 PASS (incl. brief-session pin)
- `pytest tests/test_raster_ingest.py` — 20/20 PASS
- `pytest tests/test_ingest.py` — 36 PASS, 3 FAIL (all pre-existing, documented above)
- Alembic round-trip: `upgrade head` -> `downgrade -1` -> `upgrade head` all succeed
- `grep -cE 'current_step\s*=\s*"' backend/app/processing/ingest/tasks_vector.py` = 6 (4+ required)
- `grep -cE 'current_step\s*=\s*"' backend/app/processing/ingest/tasks_raster.py` = 5 (5+ required)
- `git diff --name-only HEAD~5 HEAD -- backend/openapi.json frontend/src/types/openapi.ts` = empty (OpenAPI snapshots untouched)

## Self-Check: PASSED

All claimed files exist on disk:
- `backend/app/platform/jobs/schemas.py` — FOUND
- `backend/app/platform/jobs/models.py` — FOUND
- `backend/app/platform/jobs/router.py` — FOUND
- `backend/alembic/versions/0022_ingest_jobs_progress_columns.py` — FOUND
- `backend/app/processing/ingest/tasks_vector.py` — FOUND
- `backend/app/processing/ingest/tasks_raster.py` — FOUND
- `backend/app/processing/ingest/tasks_common.py` — FOUND
- `backend/tests/test_jobs_router.py` — FOUND
- `backend/tests/test_ingest_progress.py` — FOUND

All claimed commits exist in `git log --oneline --all`:
- `29167a28` — FOUND (Task 1)
- `690cd661` — FOUND (Task 2)
- `b4a4f47d` — FOUND (Task 3)
- `880946be` — FOUND (Task 4)
- `771a4e68` — FOUND (Task 5)

---
*Phase: 1073-audit-remediation*
*Plan: 02*
*Completed: 2026-05-21*

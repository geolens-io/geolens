---
phase: 1073-audit-remediation
plan: 3
subsystem: backend
tags: [sqlalchemy, asynccontextmanager, ingest, jobs, refactor]

# Dependency graph
requires:
  - phase: 1072-fresh-audits
    provides: ingest-audit P2-05 finding (duplicated two-phase session-bracket pattern across tasks_vector.py + tasks_raster.py — load-bearing #100 greenlet-isolation rule is copy-pasted at 4+ call sites)
  - phase: 1073-02
    provides: brief-session pattern for progress writes (current_step="ogr2ogr", "cog_convert", "quicklook") ahead of subprocess work — this plan's refactor preserves the brief-session writes byte-for-byte while routing them through the new helper
provides:
  - "_job_phase_session async context manager in tasks_common.py — single source of truth for ingest worker session-bracket lifecycle (load IngestJob → handle missing-row warning → rollback-on-exception → caller-owned commits)"
  - "tasks_vector.ingest_file uses _job_phase_session at 5 sites (phase-1, brief-session ogr2ogr write, phase-2, error-write, finally-block cleanup-check)"
  - "tasks_vector.ingest_service uses _job_phase_session at 4 sites (phase-1, brief-session ogr2ogr write, phase-2, error-write)"
  - "tasks_raster.ingest_raster uses _job_phase_session at 5 sites (phase-1, brief-session cog_convert write, brief-session quicklook write, phase-2, error-write)"
  - "Zero direct ``async with async_session()`` calls survive in either refactored worker file — helper is the only path"
  - "4 regression tests in test_tasks_common_phase_brackets.py pin: loads-existing-job / yields-none-when-missing / rolls-back-on-exception / commit-persists-on-normal-exit"
affects: [1074-close-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Session-bracket helper as async context manager: the four pieces of repeated boilerplate (open async_session, SELECT IngestJob, warn+early-return on missing row, rollback-on-exception) live in one place so the #100 greenlet rule is testable as a single contract surface instead of 14+ copy-pastes."
    - "Caller-owned commits inside the helper block: the helper does NOT auto-commit on exit because the existing worker code does 'load → mark running → commit → keep mutating → commit again' inside a single phase block. The pin test_phase_session_commit_persists_on_normal_exit prevents a future refactor from silently adding auto-commit and breaking that flow."
    - "Helper routes BOTH the durable brief-session progress writes AND the participate-in-rollback phase-2 progress writes through the same code path — Plan 02's brief-session semantics survive because the commit decision is delegated to the caller, not the helper."

key-files:
  created:
    - backend/tests/test_tasks_common_phase_brackets.py
  modified:
    - backend/app/processing/ingest/tasks_common.py
    - backend/app/processing/ingest/tasks_vector.py
    - backend/app/processing/ingest/tasks_raster.py

key-decisions:
  - "Helper signature ``_job_phase_session(job_uuid, *, phase)`` yields ``(session, job)`` where job is ``None`` on missing row. Plan called for this exact shape — caller checks ``if job is None: return``, helper does NOT raise. Preserves the existing 'Ingest job vanished between phases, skipping' early-return semantics."
  - "Error-write and cleanup-check sites (which don't strictly need the IngestJob row, just a session) ALSO route through the helper. This gives a uniform call surface and ensures the done-criteria 'zero ``async_session()`` calls in the worker files' holds — the price is one extra SELECT per error path, which is acceptable on the failure path. The helper yields ``(session, None)`` on a missing row, which the err_session caller ignores because it issues a SQL UPDATE rather than mutating the ORM."
  - "Brief-session progress writes use ``phase=\"progress_write_ogr2ogr\"`` / ``\"progress_write_cog_convert\"`` / ``\"progress_write_quicklook\"`` so the helper's missing-row warning carries the originating site. Distinct from ``phase=\"phase1\"`` / ``\"phase2\"`` / ``\"error_write\"`` / ``\"cleanup_check\"`` so operators reading the log stream can disambiguate which bracket lost the row."
  - "Inner try/except: rollback; raise blocks in phase-2 of all three call sites are REMOVED. The helper owns rollback-on-exception. The outer ``except Exception as exc:`` handler that writes the failure record via a fresh err_session is unchanged — it still runs after the helper has rolled back the phase-2 session."

patterns-established:
  - "When the same multi-statement session-lifecycle pattern appears at 4+ call sites with subtle drift potential (e.g., one forgets to rollback, another forgets to warn on missing row), lift it into an async context manager. Keep the contract narrow: the helper owns session OPEN, the SELECT, the missing-row warning, and rollback-on-exception. Commits stay at the call site because the existing code has legitimate multiple-commit-per-block patterns."
  - "Refactor verification grep: ``grep -c 'async_session(' <worker_file>`` returning 0 is a structural pin that future maintainers will see in CI. Combined with the regression tests that exercise the helper's rollback + missing-row contract, this prevents a future change from silently re-introducing the bare-async_session pattern at a new site."

requirements-completed: [REMED-03]

# Metrics
duration: ~10min
completed: 2026-05-21
---

# Phase 1073 Plan 03: _job_phase_session helper — ingest worker session-bracket consolidation Summary

**Two-phase session-bracket pattern (load IngestJob → mark-running → close → CPU/subprocess work → re-open for finalize) lifted from 14 copy-paste call sites into a single ``_job_phase_session`` async context manager; tasks_vector + tasks_raster + their err_write paths all route through the helper; 4 regression tests pin the contract surface; Plan 02's brief-session progress writes preserved byte-for-byte.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-21T15:03:45Z
- **Completed:** 2026-05-21T15:13:00Z
- **Tasks:** 5 (4 implementation + 1 verification)
- **Files modified:** 4 (3 modified, 1 created)

## Accomplishments

- New `_job_phase_session` async context manager in `tasks_common.py` centralizes session-bracket lifecycle: open `async_session()`, SELECT `IngestJob`, warn + yield None on missing row, rollback-on-exception, re-raise.
- `tasks_vector.ingest_file` refactored: 5 call sites (phase-1, brief-session ogr2ogr write, phase-2, error-write, finally-block cleanup-check) all consume the helper. Manual `try/except: rollback; raise` removed from phase-2.
- `tasks_vector.ingest_service` refactored: 4 call sites (phase-1, brief-session ogr2ogr write, phase-2, error-write) all consume the helper.
- `tasks_raster.ingest_raster` refactored: 5 call sites (phase-1, brief-session cog_convert write, brief-session quicklook write, phase-2, error-write) all consume the helper.
- 4 regression tests in `test_tasks_common_phase_brackets.py` pin the helper's contract: load-existing / yield-None-on-missing / rollback-on-exception / commit-persists-on-normal-exit.
- Plan 02's load-bearing brief-session pin (`test_vector_worker_writes_ogr2ogr_step_before_subprocess`) still passes — proves the brief-session progress write commits BEFORE the subprocess runs, even after routing through the helper.
- Zero direct `async with async_session()` calls survive in either refactored worker file (`grep -c 'async_session(' ... = 0` for both).

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement `_job_phase_session` async context manager** — `86356123` (feat)
2. **Task 2: Refactor tasks_vector.py to use `_job_phase_session`** — `b748a88c` (refactor)
3. **Task 3: Refactor tasks_raster.py to use `_job_phase_session`** — `436aa7bb` (refactor)
4. **Task 4: Pin `_job_phase_session` contract with regression tests** — `005416a0` (test)
5. **Task 5: Touched-area test sweep + behavior-preservation grep** — (verification only, no code)

## Files Created/Modified

### Created

- `backend/tests/test_tasks_common_phase_brackets.py` — 4 regression tests pinning the helper's contract. Mirrors the `test_db_session` fixture pattern from `test_ingest_progress.py`. Each test that asserts post-state re-queries from a fresh transaction so it crosses session boundaries cleanly.

### Modified

- `backend/app/processing/ingest/tasks_common.py` — Adds `_job_phase_session` `@asynccontextmanager` near `_bind_task_log_context` (per plan D-01). New imports: `from collections.abc import AsyncGenerator`, `from contextlib import asynccontextmanager`. Helper docstring carries the #100 greenlet rule.
- `backend/app/processing/ingest/tasks_vector.py` — 9 session-bracket sites converted (5 in `ingest_file`, 4 in `ingest_service`). Removes manual `try/except: rollback; raise` shapes from phase-2 blocks. Drops now-unused `from sqlalchemy import select` + `from app.core.db import async_session` imports.
- `backend/app/processing/ingest/tasks_raster.py` — 5 session-bracket sites converted in `ingest_raster`. Removes manual `try/except: rollback; raise` shape from phase-2 block. Drops now-unused `from sqlalchemy import select` + `from app.core.db import async_session` imports.

## Decisions Made

- **Helper yields `(session, job)` not `job` alone.** The plan called for this exact shape because err_write and cleanup-check call sites only need the session (job ignored), and the missing-job path still has to yield a session so the caller can decide what to do.
- **All `async_session()` call sites — including the error-write and finally-block cleanup-check — route through the helper.** This gives uniform call shape and ensures the structural pin `grep -c 'async_session(' = 0` holds. The price is one extra SELECT on the error-write path, acceptable on the failure path.
- **`phase=...` keyword discriminates call sites in the missing-row warning log.** Distinct values (`phase1`, `phase2`, `progress_write_ogr2ogr`, `progress_write_cog_convert`, `progress_write_quicklook`, `error_write`, `cleanup_check`) so operators can disambiguate which bracket lost a row.
- **Phase-2 inner `try/except: rollback; raise` blocks REMOVED.** Helper owns rollback-on-exception. The outer `except Exception as exc:` block (which writes failure via a fresh err_session) is unchanged — it runs after the helper has already rolled back the phase-2 session.
- **Brief-session progress writes preserved byte-for-byte.** Plan 02's writes commit inside the helper block (caller-owned commit decision) — this is exactly the contract that lets a future failure of the long-running subprocess leave the durable mid-flight checkpoint intact. Verified by the pre-existing `test_vector_worker_writes_ogr2ogr_step_before_subprocess` still passing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed unused `from sqlalchemy import select` imports**

- **Found during:** Tasks 2 + 3 (after the refactor, the only `select(IngestJob)...` calls were inside the helper).
- **Issue:** `tasks_vector.py` and `tasks_raster.py` both imported `select` at module level. After the refactor neither file used `select` anymore (the helper does the SELECT internally). Leaving the imports would trigger lint failures on `ruff` / `unused-import` checks.
- **Fix:** Removed the `from sqlalchemy import select` lines from both files.
- **Files modified:** `backend/app/processing/ingest/tasks_vector.py`, `backend/app/processing/ingest/tasks_raster.py`
- **Verification:** test_ingest.py + test_raster_ingest.py + test_ingest_progress.py + test_tasks_common_phase_brackets.py — full touched-area sweep passes with no new failures.
- **Committed in:** `b748a88c` (Task 2) and `436aa7bb` (Task 3) respectively.

**2. [Rule 3 - Blocking] Removed unused `from app.core.db import async_session` imports**

- **Found during:** Tasks 2 + 3 (same as #1 — after the refactor, neither file calls `async_session()` directly).
- **Issue:** Plan said "the helper is the only path" but did not enumerate removing the now-dead import. Same lint concern as #1.
- **Fix:** Removed the function-level (`tasks_vector.ingest_file`) and module-level (`tasks_raster`) `async_session` imports.
- **Files modified:** `backend/app/processing/ingest/tasks_vector.py`, `backend/app/processing/ingest/tasks_raster.py`
- **Verification:** Same touched-area sweep as #1.
- **Committed in:** `b748a88c` (Task 2) and `436aa7bb` (Task 3) respectively.

---

**Total deviations:** 2 auto-fixed (2 blocking — both dead-import sweeps required for clean refactor commit).
**Impact on plan:** Trivial — refactor consequence. Plan said "the helper is the only call into async_session" but didn't enumerate the dead-import removal as a separate step. Both removals are mechanical.

## Issues Encountered

- **Test database missing on first run.** `tests/test_ingest_progress.py` errored with `InvalidCatalogNameError: database "geolens_test_..." does not exist` on the first attempt because the default `POSTGRES_HOST=localhost:5432` env points at an unrelated 6-day-old `spatialflow-postgres` container, not the geolens-db container on port 5434. Resolved by setting `POSTGRES_PORT=5434` for all test runs. This is a test-runner env quirk, not a regression introduced by this plan.
- **Pre-existing test failures in `test_ingest.py`** (out of scope per deviation rules — same 3 failures Plan 02's SUMMARY documented):
  - `TestUpload::test_upload_success` — mock `_save_to_temp` doesn't accept new `max_size_bytes` kwarg added in Phase 1066.
  - `TestCsvUpload::test_csv_upload_success` — same `max_size_bytes` mock mismatch.
  - `TestCommitImportDispatch::test_service_job_commits_with_service_body` — DNS resolution failure for `example.arcgis.com` (post-Phase 1066 SSRF check actively resolves hostnames at commit time).
  - All 3 reproduce identically on `005416a0~4` (pre-Task-1 baseline). Not introduced by this plan. Mention in close-gate handoff for whichever phase owns IA-P0-02 / IA-P0-03 follow-through.

## Plan 1073-02 integration note

Plan 02 (REMED-02 progress fields) had already shipped on `main` at execution time (commits `29167a28` through `771a4e68` + `56247724` SUMMARY commit landed in the previous wave). This plan's refactor therefore included Plan 02's brief-session writes from day one — both `current_step="ogr2ogr"` brief sessions in `tasks_vector` and both `current_step="cog_convert"` / `current_step="quicklook"` brief sessions in `tasks_raster` were already in the file when Task 2/3 started. They were converted to use `_job_phase_session(job_uuid, phase="progress_write_*")` with the same commit-inside-block semantics, so the durable mid-flight checkpoint pattern is preserved. The pre-existing `test_vector_worker_writes_ogr2ogr_step_before_subprocess` continues to pass — it's the load-bearing test that proves the refactor is byte-equivalent for the brief-session pattern.

## Next Phase Readiness

- **Phase 1074 close-gate:** unblocked. The helper is the single test-pinnable surface for the #100 greenlet rule, and the regression tests in `test_tasks_common_phase_brackets.py` will catch any future drift. Close-gate's full pytest sweep + e2e:smoke:builder + typecheck gates can run unchanged.
- **No follow-ups for this plan.** The refactor is behavior-preserving and the contract is pinned. Future work that extends the worker (e.g., new ingest path) inherits the helper for free — call `async with _job_phase_session(job_uuid, phase="...") as (session, job): if job is None: return; ...` and the #100 rule is enforced.

## Verification Summary

- `pytest tests/test_tasks_common_phase_brackets.py` — 4/4 PASS (the new contract pins)
- `pytest tests/test_ingest.py` — 36 PASS, 3 FAIL (all pre-existing per Plan 02 SUMMARY)
- `pytest tests/test_raster_ingest.py` — 20/20 PASS
- `pytest tests/test_ingest_progress.py` — 3/3 PASS (incl. brief-session pin)
- `pytest tests/test_jobs_router.py` — 32/32 PASS
- `grep -c '_job_phase_session' backend/app/processing/ingest/tasks_vector.py` = 19 (≥4 required)
- `grep -c '_job_phase_session' backend/app/processing/ingest/tasks_raster.py` = 12 (≥2 required)
- `grep -v '^\s*#' backend/app/processing/ingest/tasks_vector.py backend/app/processing/ingest/tasks_raster.py | grep -c 'async_session('` = 0 (helper is the only path)

## Self-Check: PASSED

All claimed files exist on disk:
- `backend/app/processing/ingest/tasks_common.py` — FOUND
- `backend/app/processing/ingest/tasks_vector.py` — FOUND
- `backend/app/processing/ingest/tasks_raster.py` — FOUND
- `backend/tests/test_tasks_common_phase_brackets.py` — FOUND

All claimed commits exist in `git log --oneline --all`:
- `86356123` — FOUND (Task 1)
- `b748a88c` — FOUND (Task 2)
- `436aa7bb` — FOUND (Task 3)
- `005416a0` — FOUND (Task 4)

---
*Phase: 1073-audit-remediation*
*Plan: 03*
*Completed: 2026-05-21*

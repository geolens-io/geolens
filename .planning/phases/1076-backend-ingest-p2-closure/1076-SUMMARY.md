---
phase: 1076-backend-ingest-p2-closure
completed_at: 2026-05-21
requirements: [ING-02, ING-03, ING-04, ING-06, ING-07]
plans_completed: 6
verdict: PASS
tests_run: 256
tests_passed: 256
tests_failed: 0
tests_skipped: 0
duration_minutes: ~85 (cumulative across 6 plans)
---

# Phase 1076 — Backend Ingest P2 Closure

**Closed 5 backend P2 lifecycle hardening findings from `INGEST-AUDIT-2026-05-21.md` (deferred from v1015 / v1016 per Phase 1073 remediation plan); 256/256 targeted regression tests passing; zero cross-plan interference.**

## Summary

Phase 1076 closes the backend ingest P2 tail of v1017 — five surgical fixes that remove forward-only commit hazards, eliminate the 5 GB resident-memory pre-stream on self-hosters' COG downloads, prevent rolling-deploy truncation of in-flight exports, recover from autovacuum-induced reupload-swap lock_timeouts, and add an opt-in strict-COG enforcement flag:

- **ING-02 (P2-02)** — Dropped 4 internal `await session.commit()` calls from `backend/app/processing/ingest/metadata.py` phase-2 helpers (`ensure_geom_column`, `clip_to_mercator_bounds`, `add_4326_column`, `grant_reader_access`). `_finalize_ingest` now owns the only phase-2 commit boundary at `tasks_common.py:821`. New regression test (`test_phase_2_commit_boundary.py`, 204 LOC, 3 methods) pins the rollback invariant with a fresh-session probe pattern.

- **ING-03 (P2-03)** — Added `StorageProvider.get_stream(key) -> AsyncIterator[bytes]` Protocol method + `LocalStorageProvider` chunked async-generator implementation (1 MiB chunks via `asyncio.to_thread`); `S3StorageProvider` raises a defensive `NotImplementedError` (S3 path returns 302 presigned redirect upstream). Rewired `router_export.py` local-storage COG download to stream directly from disk into `StreamingResponse` — a 5 GB COG no longer pins 5 GB of resident memory before the first byte streams. Pre-stream `storage.exists()` probe preserves the HTTP 404 contract on missing keys.

- **ING-04 (P2-04)** — Worker exports temp-dir sweep at `worker.py:174-185` no longer unconditionally wipes the entire `<staging>/exports/` directory on startup; it now guards on `stat.st_mtime > 1 hour` via the new `EXPORTS_SWEEP_AGE_SECONDS = 3600` constant + extracted `_sweep_orphaned_exports` helper. Per-skipped-entry structured `sweep_skipped_recent_export` log event correlates worker boot timing with in-flight large-export ages.

- **ING-06 (P2-08)** — `_apply_reupload_swap` retries once on `LockNotAvailableError` (SQLSTATE 55P03) with `SET LOCAL lock_timeout = '15s'` (up from `'5s'`) plus a 200ms sleep. New `_is_lock_timeout_error` helper detects 55P03 across asyncpg + SQLAlchemy-wrapped exceptions; `session.begin_nested()` SAVEPOINTs bracket each attempt for clean retry state. WARNING `reupload_swap_lock_contention` + INFO `reupload_swap_retry_succeeded` events emit on contention/recovery.

- **ING-07 (P2-09)** — Added optional `strict_cog: bool = False` field to `RasterCommitRequest`. When `True`, raster commit pre-flights `check_cog_compliance` via a module-level `_enforce_strict_cog` helper and rejects non-COG TIFFs at commit time (raises `ValueError` that bubbles to the existing `error_write` job-phase-session) instead of silently routing through `check_and_prepare_cog` conversion. Backward-compatible default preserves all 67 existing raster-test cases unchanged.

## Plan References

- [Plan 01 — ING-02 metadata.py phase-2 commit boundary](1076-01-SUMMARY.md) (~30 min, 2 commits)
- [Plan 02 — ING-03 local-storage COG streaming](1076-02-SUMMARY.md) (~10 min, 3 commits)
- [Plan 03 — ING-04 worker exports sweep mtime guard](1076-03-SUMMARY.md) (~5 min, 2 commits)
- [Plan 04 — ING-06 reupload swap lock_timeout retry](1076-04-SUMMARY.md) (~22 min, 2 commits)
- [Plan 05 — ING-07 strict_cog opt-in flag](1076-05-SUMMARY.md) (~18 min, 3 commits)
- Plan 06 — Phase verification + close-gate (this file; commits to follow)

## Production-Code Files Touched

- `backend/app/processing/ingest/metadata.py` — 4 internal commits removed; inline `# ING-02 / P2-02 (Phase 1076)` comment markers preserve the contract self-documentation at each removal site (ING-02).
- `backend/app/processing/ingest/tasks_common.py` — `_is_lock_timeout_error` helper, `_apply_reupload_swap` refactor with retry via `_swap_with_timeout` inner closure + `session.begin_nested()` SAVEPOINTs, `asyncio` import added (ING-06).
- `backend/app/processing/ingest/schemas.py` — `RasterCommitRequest.strict_cog: bool = Field(default=False, ...)` (ING-07).
- `backend/app/processing/ingest/tasks_raster.py` — module-level `_enforce_strict_cog(...)` helper + import of `check_cog_compliance` + gate wire between CRS validation and `cog_convert` progress write (ING-07).
- `backend/app/platform/storage/provider.py` — `get_stream(key) -> AsyncIterator[bytes]` Protocol method (ING-03).
- `backend/app/platform/storage/local.py` — `LocalStorageProvider.get_stream` async-generator + `_STREAM_CHUNK_BYTES = 1024 * 1024` module constant + finally-cleanup on file handle (ING-03).
- `backend/app/platform/storage/s3.py` — `S3StorageProvider.get_stream` NotImplementedError stub with explicit cross-reference to the bypassing redirect site (ING-03).
- `backend/app/modules/catalog/datasets/api/router_export.py` — local-storage COG branch rewired; `io.BytesIO` removed; `storage.exists()` pre-stream probe (ING-03).
- `backend/app/platform/jobs/worker.py` — `EXPORTS_SWEEP_AGE_SECONDS = 3600` constant + extracted `_sweep_orphaned_exports(exports_dir, *, age_threshold_seconds=...)` helper; `sweep_skipped_recent_export` + `exports_sweep_complete` structured logs (ING-04).

## Tests Added

- `backend/tests/test_phase_2_commit_boundary.py` — **204 LOC**, 3 methods (rollback-undoes, commit-keeps, all-four-helpers-pend); fresh-session probe pattern (ING-02).
- `backend/tests/test_storage_get_stream.py` — **87 LOC**, 4 methods (3 MiB roundtrip, exact-chunk-size, missing-key FileNotFoundError, post-aclose handle cleanup); imports `_STREAM_CHUNK_BYTES` from module under test (ING-03).
- `backend/tests/test_worker_exports_sweep.py` — **134 LOC**, 5 methods (deletes-only-old, recursive subdirs, log emission, empty-dir, missing-dir defensive guard) (ING-04).
- `backend/tests/test_reupload_swap_lock_retry.py` — **357 LOC**, 5 methods across 2 classes (3 helper unit + 2 DB-touching retry-path); `structlog.testing.capture_logs()` for log assertions (ING-06).
- `backend/tests/test_strict_cog_enforcement.py` — **99 LOC**, 4 methods (strict+non-compliant rejected, strict+compliant passes, non-strict skipped, VRT bypassed) (ING-07).
- `backend/tests/test_commit_request_schemas.py` — extended with 3 new tests for `RasterCommitRequest.strict_cog` (default, opt-in, model_validate omission) (ING-07).

**Test artifact totals:** 5 new files (881 LOC across the new files), 1 file extended, 21 new test methods.

## Cross-Plan Interactions

All 5 plans landed in Wave 1 with **zero `files_modified` overlap** and **zero test interference** under a single `pytest -x` sweep:

- Plans 01 (ING-02) and 04 (ING-06) both touch the ingest worker pipeline but in disjoint regions (`metadata.py` phase-2 helpers vs `tasks_common.py`'s `_apply_reupload_swap`); no file overlap.
- Plan 02 (ING-03) adds the only new method to the storage Protocol; no other plan touches storage providers.
- Plan 03 (ING-04) is isolated in the worker boot path; no test or production-code overlap with the other plans.
- Plan 05 (ING-07) extends `RasterCommitRequest` and adds a guard in `tasks_raster.ingest_raster`; orthogonal to the vector path touched by Plan 01.

Combined regression sweep (18 test files, 256 tests) passes cleanly under `-x` (fail-fast first failure). No cross-plan dependency was needed.

## Verification

See [1076-VERIFICATION.md](1076-VERIFICATION.md) for the full test evidence trail.

**Headline:** 256/256 tests passing; 0 failures; 0 unexpected skips; 0 anomalies. All grep gates green:

- ING-02: `grep -c "await session.commit" metadata.py == 1`
- ING-03: `storage.get_stream` Protocol method present; `io.BytesIO` removed from router
- ING-04: `EXPORTS_SWEEP_AGE_SECONDS` (4 occurrences) + `st_mtime` + `sweep_skipped_recent_export` (1) all present
- ING-06: `_RETRY_TIMEOUT = "15s"` + `reupload_swap_lock_contention` (1) + `_is_lock_timeout_error` (2)
- ING-07: `strict_cog` field on schemas.py (1) + integration in tasks_raster.py (8)

## Deferred / Out of Scope

Per the per-plan SUMMARYs and the threat model, three pre-existing environmental issues observed during regression are tracked separately (NOT Phase 1076 regressions — reproduce on commits prior to `5b514802`):

- **ENV-01:** `ogrinfo` binary missing from devbox PATH (`deferred-items.md`).
- **ENV-02:** `services.example.com` DNS does not resolve in test environment.
- **ENV-03:** `test_job_phase_session_none_branch_rolls_back_on_exception` pytest-asyncio event-loop quirk.

These overlap with the 7 verification-gap findings already handed from Phase 1075 to Phase 1079 (`1075-05-VERIFICATION.md` `NEW-DISCOVERY` table) and remain queued for v1018 hygiene or Phase 1079 follow-up dispositioning.

## Patterns Established

Documented at the per-plan level:

1. **Phase-2 helper contract** (ING-02): inline comment block at each removal site marking the helper as participating in `_finalize_ingest`'s transaction; rollback-invariant pinning test via fresh `async_session()` probe (avoids session-cache false positives).
2. **Storage provider chunked streaming** (ING-03): async-generator with `try/finally` file-handle cleanup; pre-stream existence probe before handing iterator to a deferred-consumption response object; defensive NotImplementedError on unreachable provider branches with explicit code-site cross-reference; async-generator Protocol shape is `def method(...) -> AsyncIterator[T]` (not `async def`).
3. **Worker startup sweep** (ING-04): gate destructive housekeeping on a published threshold constant named after the requirement ID (`EXPORTS_SWEEP_AGE_SECONDS`); helper extraction for testability when a destructive block lives inside an `async def main()` that test code cannot conveniently drive; per-skipped-entry structured logging on the skip branch for forensic correlation.
4. **Single-retry on SQLSTATE-aware error** (ING-06): `session.begin_nested()` SAVEPOINT around each attempt; inner async closure captures session+table-name+staging-table by lexical scope (vs module-level helper with 4 positional params); named-constant timeouts (`_FIRST_TIMEOUT` / `_RETRY_TIMEOUT` / `_RETRY_SLEEP_MS`) for greppable knobs.
5. **Opt-in commit-request flag with default-False backward-compat** (ING-07): Pydantic `Field(default=False)` preserves existing call sites; module-level async helper extracted from inline gate block for clean test surface; bubble `ValueError` to existing outer `except` handler instead of new error-write plumbing.

## Next Phases

Phase 1076 → ✅ Complete. Three downstream phases are now eligible:

- **Phase 1077 — Frontend Ingest P2 Closure** (ING-01, ING-05): unblocked (depends only on Phase 1075, already complete). Parallel-eligible with Phase 1078.
- **Phase 1078 — CI Alembic Clean-DB Upgrade Workflow** (CI-01): independent of test infra and ingest work. Parallel-eligible with Phase 1077.
- **Phase 1079 — Close Gate + Hygiene** (TI-03, VG-01, HYG-01): gated on Phase 1075 + 1076 + 1077 + 1078 (requires Phase 1077 and Phase 1078 to land before TI-03 captures the post-fix steady state).

## Self-Check: PASSED

Verified post-write:

- `.planning/phases/1076-backend-ingest-p2-closure/1076-VERIFICATION.md` — FOUND (162 lines)
- `.planning/phases/1076-backend-ingest-p2-closure/1076-SUMMARY.md` — FOUND (this file)
- `.planning/phases/1076-backend-ingest-p2-closure/1076-01..05-SUMMARY.md` — all FOUND
- `.planning/STATE.md` — updated (Phase 1076 complete; completed_phases 2; percent 20)
- `.planning/ROADMAP.md` — updated (`- [x] **Phase 1076`; progress table `6/6 Complete 2026-05-21`)
- `.planning/REQUIREMENTS.md` — updated (ING-02..07 all `Complete` in traceability table; checkbox flipped to `[x]` for ING-06)
- 256/256 targeted regression tests pass
- All 5 ING grep gates green

---

*Phase: 1076-backend-ingest-p2-closure*
*Completed: 2026-05-21*

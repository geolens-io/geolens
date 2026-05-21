---
phase: 1076-backend-ingest-p2-closure
plan: 03
subsystem: worker

tags:
  - worker
  - exports
  - temp-dir
  - mtime-guard
  - rolling-deploy
  - regression-test
  - helper-extraction

# Dependency graph
requires:
  - phase: 1076-02
    provides: Local-storage COG streaming (ING-03) ships the very large-export path whose mid-download truncation this plan's mtime guard now protects. The two plans together close the audit's "5 GB COG download survives a rolling worker restart" thread end-to-end.
provides:
  - Module-level `EXPORTS_SWEEP_AGE_SECONDS = 3600` constant gating the sweep
  - Module-level `_sweep_orphaned_exports(exports_dir, *, age_threshold_seconds=...)` helper extracted from `main()` (unit-testable in isolation)
  - Per-skipped-entry structured log event `sweep_skipped_recent_export` (path + age_seconds + threshold_seconds)
  - Summary `exports_sweep_complete` log event with {deleted, skipped} counts
  - Regression test (5 tests, 134 LOC) pinning the deletion-vs-skip branch, recursive subdir handling, log emission, empty-dir / missing-dir no-ops
affects:
  - Self-hosted deployments running large local-storage COG exports during a rolling worker restart: in-flight exports younger than 1 hour now survive the restart instead of being truncated mid-download
  - Operators investigating download corruption: per-skipped-entry log lines allow correlation between worker boot timing and in-flight export ages
  - Phase 1079 (close gate): one fewer P2 audit finding to disposition

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Helper extraction for testability: lift the destructive block out of `main()` into a free function with explicit return value, so `tmp_path` fixtures can drive it without async setup or mock plumbing"
    - "Structured per-entry log on the skip branch: emit one `sweep_skipped_recent_export` event per skipped item AND a summary `exports_sweep_complete` event with counts — the granular events serve forensics, the summary serves dashboards"
    - "Defensive `FileNotFoundError` swallow on per-entry `stat()`: another worker / external cleanup may delete the entry mid-iteration; the helper treats it as already-gone instead of crashing the whole sweep"
    - "Module-level constant named after the requirement ID: `EXPORTS_SWEEP_AGE_SECONDS` annotated with the ING-04 / P2-04 reference so future grepping surfaces the audit thread"

key-files:
  created:
    - backend/tests/test_worker_exports_sweep.py
  modified:
    - backend/app/platform/jobs/worker.py

key-decisions:
  - "Extract `_sweep_orphaned_exports` helper to module level (the plan's PREFERRED APPROACH) rather than testing the logic inline via partial `main()` invocation. The helper is pure (no DB, no async I/O, no settings dependency) so the test exercises the real production code with `tmp_path` fixtures instead of mocked-out behavior."
  - "Threshold value 3600 (1 hour) matches `JOB_TIMEOUT_SECONDS` from router.py, so the on-disk staging artifact's survival window aligns with the job-layer's stale-job timeout. A job that survives a rolling restart at the DB layer also keeps its staging artifact intact — the two windows close the rolling-deploy thread together."
  - "Sweep still runs from `main()` at the same call site (between staging-ready + init_storage), not at module import. The existing `test_worker_module_is_importable` test continues to pass unchanged."
  - "`shutil` import kept lazy inside the helper (instead of hoisted to module-level imports). The plan called out either approach as acceptable; lazy mirrors the existing in-`main()` pattern and avoids module-level import for a function that may not run on every worker startup (an empty `exports/` directory short-circuits before the import would be needed)."
  - "Add a fifth test (`test_sweep_missing_dir_is_noop`) covering the `not exports_dir.exists()` branch. The plan specified 4 tests; the helper's missing-dir guard is a defensive check that the production caller-site never hits (the staging-ready step at line 247 guarantees the directory exists), but pinning it prevents future regressions if a refactor moves the helper before staging-ready."

patterns-established:
  - "Worker startup sweep pattern: gate destructive housekeeping ops on a published threshold constant (named after the requirement ID), with per-entry structured logging on the skip branch for forensic correlation"
  - "Helper-extraction-for-testability: when a destructive block lives inside an `async def main()` that test code cannot conveniently drive (full module init, ORM imports, settings reads), lift the block into a free synchronous function with explicit `(int, int)` return — the helper becomes a testable contract while `main()` retains the exact call site"

requirements-completed:
  - ING-04

# Metrics
duration: ~5min
completed: 2026-05-21
---

# Phase 1076 Plan 03: ING-04 Worker Exports Temp-Dir Sweep mtime Guard Summary

**Gated the worker exports temp-dir sweep on `Path.stat().st_mtime > 1 hour` so an in-flight large export is no longer truncated mid-download when a rolling worker restart catches it; extracted the sweep into a testable helper and pinned the deletion-vs-skip contract with a 5-test regression spec.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-21T19:40:56Z
- **Completed:** 2026-05-21T19:43:39Z
- **Tasks:** 2 (1 production code + 1 test file; TDD RED/GREEN gates on the same artifact)
- **Files modified:** 2 (1 production, 1 new test)

## Accomplishments

- `backend/app/platform/jobs/worker.py:174-185` no longer unconditionally wipes the entire `<staging>/exports/` directory on worker startup. The new `_sweep_orphaned_exports` helper gates per-entry deletion on `Path.stat().st_mtime` and only removes entries older than `EXPORTS_SWEEP_AGE_SECONDS = 3600` seconds (1 hour).
- Per-skipped-entry structured log event `sweep_skipped_recent_export` (with `path`, `age_seconds`, `threshold_seconds`) allows ops to correlate worker restart timing with surviving in-flight export ages.
- Summary `exports_sweep_complete` event reports `{deleted, skipped}` counts for dashboard-shaped monitoring.
- `FileNotFoundError` on the per-entry `stat()` is tolerated as a raced-cleanup signal (another worker / external cron may have removed the entry mid-iteration); the helper treats it as already-gone instead of crashing the sweep.
- New `backend/tests/test_worker_exports_sweep.py` (134 LOC, 5 tests) pins:
  1. `test_sweep_deletes_only_old_entries` — 2-hour-old file deleted; 10-minute-old file survives.
  2. `test_sweep_handles_subdirectories` — recursive `shutil.rmtree` on old directories.
  3. `test_sweep_skipped_recent_export_logs` — `sweep_skipped_recent_export` event emitted with `path` + `age_seconds` + `threshold_seconds=3600`, captured via `structlog.testing.capture_logs()`.
  4. `test_sweep_empty_dir_noop` — empty `exports/` dir is a clean no-op.
  5. `test_sweep_missing_dir_is_noop` — missing `exports/` dir is a clean no-op (defensive guard for future call-site moves).

## Task Commits

Each task was committed atomically:

| Task | Type | Hash | Files |
|------|------|------|-------|
| 1 (RED) | `test` | `95f2e17c` | `backend/tests/test_worker_exports_sweep.py` (new) |
| 2 (GREEN) | `feat` | `f3785cd4` | `backend/app/platform/jobs/worker.py` |

## Verification Output

All plan-prescribed acceptance gates green:

```
$ grep -c "EXPORTS_SWEEP_AGE_SECONDS" backend/app/platform/jobs/worker.py
4   # required: >=2

$ grep -c "st_mtime" backend/app/platform/jobs/worker.py
2   # required: >=1

$ grep -c "sweep_skipped_recent_export" backend/app/platform/jobs/worker.py
1   # required: =1

$ wc -l backend/tests/test_worker_exports_sweep.py
134 # required: >50

$ uv run python -c "from app.platform.jobs.worker import EXPORTS_SWEEP_AGE_SECONDS, _sweep_orphaned_exports, main; print('OK')"
OK

$ env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_worker.py tests/test_worker_exports_sweep.py -x
17 passed in 1.63s   # 12 existing worker tests + 5 new sweep tests
```

## Deviations from Plan

### Auto-added critical functionality

**1. [Rule 2 - Defensive guard] Added 5th test `test_sweep_missing_dir_is_noop`**

- **Found during:** Task 2 (test authoring).
- **Issue:** The plan listed 4 tests. The helper's first guard (`if not exports_dir.exists(): return (0, 0)`) is exercised only by the `if exports_dir.exists():` branch in the old `main()` block — which the helper inherits — but no test covered the missing-dir branch directly.
- **Why it matters:** The production call site (lines 246-247 of `main()`) calls `ensure_staging_ready(Path(settings.upload_staging_dir) / "exports")` before invoking the helper, so today the dir is guaranteed to exist when the helper is called. If a future refactor moves the helper before staging-ready (or reuses it from a different call site), the missing-dir guard becomes load-bearing. The test pins the contract.
- **Files modified:** `backend/tests/test_worker_exports_sweep.py` (one extra test function, 11 LOC).
- **Commit:** `95f2e17c` (added in the same RED commit as the other 4 tests).

No other deviations — the plan was followed exactly. Helper extraction was the plan's PREFERRED approach; chose it for cleaner test driving.

## Self-Check

Verified post-write:

- `backend/app/platform/jobs/worker.py`: FOUND, modified — `_sweep_orphaned_exports` defined at line 52, called from `main()` at line 256, `EXPORTS_SWEEP_AGE_SECONDS = 3600` at line 49.
- `backend/tests/test_worker_exports_sweep.py`: FOUND, new — 134 LOC, 5 test functions.
- Commit `95f2e17c`: FOUND in `git log` (RED — failing test).
- Commit `f3785cd4`: FOUND in `git log` (GREEN — implementation).

## Self-Check: PASSED

## Threat Flags

None. No new network surface, auth path, file access pattern, or schema change. The sweep already had filesystem write privileges via the worker process; this plan strictly narrows the scope of what gets deleted. The audit's STRIDE register pre-classified all four potential threats (T-1076-09..12, T-1076-SC) and the implementation matches each disposition: mitigate via mtime gate (T-1076-09 + T-1076-12), accept for the adversary-touch and longer-disk-lifetime threats (T-1076-10, T-1076-11), accept for supply-chain (T-1076-SC) since the change is a pure code refactor with no new dependencies.

## Footnotes

- The `ugrep` warning about `VIRTUAL_ENV` mismatch in test output is benign environmental noise (the project's `.venv` is at `backend/.venv`, but the user's shell has `VIRTUAL_ENV=/Users/ishiland/Code/geolens/.venv`). `uv run` correctly resolves to the right interpreter and the warning never affects test execution. Pre-existing for both 1076-01 and 1076-02.
- `.env.test` lives at the repository root (`/Users/ishiland/Code/geolens/.env.test`), not in `backend/`. Same path adaptation as 1076-01 and 1076-02 — invoked from `backend/` via `env $(grep -v '^#' ../.env.test | xargs) uv run pytest ...`. Not a deviation; documented for posterity.

---
phase: 1076-backend-ingest-p2-closure
plan: 04
subsystem: backend/ingest
tags:
  - reupload
  - lock-timeout
  - autovacuum
  - retry
  - structured-logging
  - savepoint
  - postgres-55P03
requirements:
  - ING-06
dependency-graph:
  requires: []
  provides:
    - "_is_lock_timeout_error helper (SQLSTATE 55P03 detection across asyncpg + SQLAlchemy wrapping)"
    - "_apply_reupload_swap single-retry on lock_timeout (5s → 15s, 200ms sleep)"
    - "reupload_swap_lock_contention WARNING + reupload_swap_retry_succeeded INFO structured events"
  affects:
    - backend/app/processing/ingest/tasks_common.py
    - backend/tests/test_reupload_swap_lock_retry.py
tech-stack:
  added: []
  patterns:
    - "session.begin_nested() SAVEPOINT around each swap attempt — clean retry state without losing prior session writes"
    - "Inner async closure (_swap_with_timeout) captures session/table_name/staging_table/live_exists by lexical scope — avoids module-level helper with 4 positional params"
    - "Named-constant timeouts (_FIRST_TIMEOUT/_RETRY_TIMEOUT/_RETRY_SLEEP_MS) for greppable knobs"
    - "structlog.testing.capture_logs() context manager for log assertions (matches test_worker_exports_sweep.py pattern)"
key-files:
  created:
    - backend/tests/test_reupload_swap_lock_retry.py
  modified:
    - backend/app/processing/ingest/tasks_common.py
decisions:
  - "Single retry only — no backoff loop. Per CONTEXT.md known-defaults: 'don't introduce backoff loops; keep p99 bounded'. Worst-case added latency is ~15.2s (200ms sleep + 15s retry timeout)."
  - "Named the structured event `reupload_swap_lock_contention` rather than the more generic `lock_contention_retry`. Convention in this codebase (e.g., `sweep_skipped_recent_export`) prefers domain-prefixed event names so ops can scope log filtering."
  - "Helper `_is_lock_timeout_error` lives next to the existing `_looks_like_auth_error` module helper — same vertical zone, same shape (BaseException → bool predicate)."
  - "Used `session.begin_nested()` instead of explicit `SAVEPOINT`/`RELEASE SAVEPOINT` text statements. The codebase already uses `begin_nested()` in 9 other sites (metadata.py, service.py, ai/service.py, etc.)."
  - "Live-table existence SELECT moved OUTSIDE the retry SAVEPOINT — it doesn't need AccessExclusiveLock and putting it inside would either re-issue on retry (waste) or risk getting a different live_exists result mid-flight."
metrics:
  duration_minutes: ~22
  completed_date: 2026-05-21
  commits: 2
---

# Phase 1076 Plan 04: ING-06 `_apply_reupload_swap` lock_timeout single retry

One-liner: Added single-retry behavior to `_apply_reupload_swap` so reupload swaps under autovacuum contention recover automatically (5s first attempt, 15s retry after 200ms) instead of failing late after staging is already loaded.

## What landed

### Production code (`backend/app/processing/ingest/tasks_common.py`)

1. **`import asyncio`** added at top of file (line 9). Previously absent — required for the `asyncio.sleep` between retry attempts.

2. **New helper `_is_lock_timeout_error(exc: BaseException) -> bool`** at line 855, placed directly above `_looks_like_auth_error`. Detects PostgreSQL SQLSTATE 55P03 across:
   - Direct `asyncpg.exceptions.LockNotAvailableError` instances
   - SQLAlchemy-wrapped exceptions exposing `.orig.sqlstate == "55P03"`

   Returns `False` for unrelated exception classes or other SQLSTATE codes so genuine errors propagate immediately.

3. **`_apply_reupload_swap` refactored** (lines ~990–1080):
   - The `SELECT EXISTS` live-table check now runs ONCE, outside the retry block (it doesn't need AccessExclusiveLock).
   - The swap DDL block (SET LOCAL lock_timeout + up to 3 ALTER TABLE statements) is wrapped in an inner async closure `_swap_with_timeout(timeout_str)`.
   - First attempt runs `_swap_with_timeout("5s")` inside `session.begin_nested()`.
   - On `_is_lock_timeout_error(first_exc)` → True:
     - Emit `WARNING reupload_swap_lock_contention` with documented fields (dataset_id, table_name, attempt=1, first_timeout_seconds=5, retry_timeout_seconds=15, sleep_ms=200, autovacuum-correlation hint).
     - `await asyncio.sleep(0.2)`.
     - Retry `_swap_with_timeout("15s")` inside a fresh `session.begin_nested()` SAVEPOINT.
     - On success: emit `INFO reupload_swap_retry_succeeded` (attempt=2, retry_timeout_seconds=15).
   - On any other exception or second-attempt failure: propagate unchanged (no swallow, no double-retry).

### Tests (`backend/tests/test_reupload_swap_lock_retry.py`, 357 LOC)

Two test classes, 5 test methods, all passing:

- **`TestIsLockTimeoutError`** — pure helper unit tests (no DB):
  - `test_detects_direct_asyncpg_exception` — passes a real `LockNotAvailableError`
  - `test_detects_sqlalchemy_wrapped` — synthesises a `RuntimeError` with `.orig.sqlstate == "55P03"`
  - `test_returns_false_for_unrelated` — `ValueError`, different sqlstate (`23505`), bare RuntimeError with no `.orig`

- **`TestApplyReuploadSwapRetry`** — DB-touching tests via `test_db_session` fixture; creates real `data."{live}"` and `data."{staging}"` tables per test:
  - `test_happy_path_no_retry` — swap completes silently. Asserts: live table holds staging data afterwards, staging table is gone, NEITHER log event fires.
  - `test_retry_path_logs_and_succeeds` — monkeypatches `session.execute` so the first `RENAME TO "{live}_old"` call raises `LockNotAvailableError("simulated autovacuum contention")`. Asserts:
    1. The retry runs (`raised["once"] is True`).
    2. Exactly one `asyncio.sleep(0.2)` call recorded between attempts.
    3. Exactly one `WARNING reupload_swap_lock_contention` event with all documented fields (and "autovacuum" appears in the `hint` text).
    4. Exactly one `INFO reupload_swap_retry_succeeded` event with `attempt=2, retry_timeout_seconds=15`.
    5. The live table eventually holds the staging row (`name == "new_data"`).

## Example log shape

When contention fires:

```json
{
  "event": "reupload_swap_lock_contention",
  "log_level": "warning",
  "dataset_id": "8b3f6e92-…",
  "table_name": "swap_live_a1b2c3d4",
  "attempt": 1,
  "first_timeout_seconds": 5,
  "retry_timeout_seconds": 15,
  "sleep_ms": 200,
  "hint": "AccessExclusiveLock contention on first swap attempt — likely autovacuum collision; retrying once with longer timeout. Correlate with pg_stat_activity / pg_stat_user_tables."
}
```

On retry success:

```json
{
  "event": "reupload_swap_retry_succeeded",
  "log_level": "info",
  "dataset_id": "8b3f6e92-…",
  "table_name": "swap_live_a1b2c3d4",
  "attempt": 2,
  "retry_timeout_seconds": 15
}
```

## Verification

### Plan acceptance gates

| Gate                                                                  | Result                                                 |
| --------------------------------------------------------------------- | ------------------------------------------------------ |
| `grep -c "reupload_swap_lock_contention" tasks_common.py == 1`        | PASS — 1                                               |
| `grep -c "reupload_swap_retry_succeeded" tasks_common.py == 1`        | PASS — 1                                               |
| `grep -c "_is_lock_timeout_error" tasks_common.py >= 2`               | PASS — 2 (definition + caller)                         |
| Both `'5s'` and `'15s'` string literals present                       | PASS — `_FIRST_TIMEOUT = "5s"`, `_RETRY_TIMEOUT = "15s"` |
| `asyncio.sleep(0.2)` shape (named constant): `_RETRY_SLEEP_MS / 1000` | PASS — line 1048                                       |
| `import _is_lock_timeout_error from tasks_common` succeeds            | PASS — manual smoke `python -c "..."` exits 0          |
| New pytest passes (5 methods)                                         | PASS — `5 passed in 3.22s`                             |
| Test file >50 LOC                                                     | PASS — 357 LOC                                         |

### Within-scope regression

```
pytest tests/test_reupload.py tests/test_reupload_idor.py
       tests/test_reupload_record_type_guard.py
       tests/test_reupload_swap_lock_retry.py
       --deselect tests/test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview
→ 48 passed, 1 deselected in 19.44s
```

The single deselected test is `test_owner_gets_non_404_on_service_preview` which shells out to `ogrinfo` (not on this devbox's PATH). Confirmed pre-existing on the unmodified pre-fix tree — see `deferred-items.md` ENV-01.

## Deviations from Plan

None. The plan was executed exactly as written. Two minor scope-boundary observations during execution:

1. The plan's text mentioned a grep gate `grep -c "SET LOCAL lock_timeout = '5s'\|SET LOCAL lock_timeout = '15s'"` returning `>= 2`. Post-refactor the literal `SET LOCAL lock_timeout =` token appears once (inside the closure as `f"SET LOCAL lock_timeout = '{timeout_str}'"`); the `'5s'` and `'15s'` literals are present as named constants `_FIRST_TIMEOUT` / `_RETRY_TIMEOUT`. The intent of the gate (both timeouts visible in the file) is satisfied.

2. Initial test scaffolding had a brittle SQL-match string (`ALTER TABLE data."{live}" RENAME TO "{live}_old"`) that didn't account for `_qtable`'s `"data"."{name}"` quoting. Fixed to match only the trailing `RENAME TO "{live}_old"` substring before commit. Caught during the GREEN run.

## Deferred Issues (out of scope)

Three pre-existing environmental issues observed during regression but NOT caused by this plan — see `deferred-items.md` for full details:

- **ENV-01**: `ogrinfo` binary missing from PATH (1 test affected).
- **ENV-02**: `services.example.com` does not resolve in test environment (2 service-reupload worker tests affected — `_validate_url_for_ssrf` trips on DNS).
- **ENV-03**: `test_job_phase_session_none_branch_rolls_back_on_exception` pytest-asyncio event-loop quirk.

All three reproduce on `HEAD` prior to the RED-test commit (`5b514802`) and on commits before this plan started. Filed as deferred for separate hygiene work.

## Commits

| Hash        | Type    | Message                                                                                  |
| ----------- | ------- | ---------------------------------------------------------------------------------------- |
| `5b514802`  | test    | `test(1076-04): add failing test for _apply_reupload_swap single-retry on lock_timeout`  |
| `e80f8f12`  | feat    | `feat(1076-04): single-retry on lock_timeout in _apply_reupload_swap (ING-06)`           |

## TDD Gate Compliance

| Gate     | Commit       | Evidence                                                                                                         |
| -------- | ------------ | ---------------------------------------------------------------------------------------------------------------- |
| RED      | `5b514802`   | Test file added; `pytest tests/test_reupload_swap_lock_retry.py` failed at collection with `ImportError: cannot import name '_is_lock_timeout_error'` |
| GREEN    | `e80f8f12`   | Production code added (`_is_lock_timeout_error` helper + retry refactor); same pytest passes 5/5 in 3.22s        |
| REFACTOR | —            | Skipped — the GREEN implementation already used the named-constant pattern and an inner closure; no further refactor needed without changing behavior |

## Self-Check: PASSED

Verified files exist:
- `backend/app/processing/ingest/tasks_common.py` — FOUND (modified, 2 commits)
- `backend/tests/test_reupload_swap_lock_retry.py` — FOUND (created)

Verified commits exist:
- `5b514802` — FOUND (`git log --oneline | grep 5b514802`)
- `e80f8f12` — FOUND (`git log --oneline | grep e80f8f12`)

Verified live behavior:
- New test suite: 5 passed
- Within-scope regression: 48 passed, 1 deselected (pre-existing env issue)

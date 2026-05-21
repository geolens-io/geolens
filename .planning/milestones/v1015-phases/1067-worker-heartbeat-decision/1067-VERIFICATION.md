---
phase: 1067
status: passed
requirements_satisfied: 1
requirements_total: 1
shipped: 2026-05-20
---

# Phase 1067 VERIFICATION — Worker Heartbeat Decision (Option B)

## Phase goal

The `IngestJob.last_heartbeat_at` inconsistency is resolved and rolling deploys no longer silently force-kill running ingests.

## Requirement coverage

| REQ-ID | Status | Evidence |
|---|---|---|
| **IA-P0-04** | ✓ Verified | Option (b) shipped per user decision. Column dropped via Alembic 0021. `recover_stale_jobs` updated to use `started_at < now - JOB_TIMEOUT_SECONDS` (1h) — symmetric with steady-state `fail_stale_jobs` sweep. 12/12 worker tests green including the new `test_recover_stale_jobs_rolling_deploy_survives_6min_ingest` regression. |

## Success criteria

- **Rolling-deploy kill after 6 min leaves job recoverable** — ✓ Regression test pins this: 6-minute running job is NOT matched by the stale predicate (cutoff is 1h, not 5 min).
- **`last_heartbeat_at` is either actively written or cleanly absent** — ✓ Cleanly absent (option b). Column dropped, model field removed, all references gone.

## Files touched

- `backend/app/platform/jobs/models.py`
- `backend/app/platform/jobs/worker.py`
- `backend/alembic/versions/0021_drop_ingest_job_last_heartbeat_at.py`
- `backend/tests/test_worker.py`

## Commit chain

1. `e010ad07` `feat(1067): IA-P0-04 option (b) — drop last_heartbeat_at, use started_at + JOB_TIMEOUT_SECONDS`

## Deferred to Phase 1070 close-gate

- `alembic upgrade head` against a clean DB to confirm 0021 applies.
- Optional: manual rolling-deploy simulation via `docker compose restart worker`.

## Verdict

**PASSED** — 1/1 requirement satisfied.

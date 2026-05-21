# Phase 1067: Worker Heartbeat Decision - Context

**Gathered:** 2026-05-20
**Status:** Decision locked — option (b)
**Mode:** Decision pre-resolved via AskUserQuestion (2026-05-20)

<domain>
## Phase Boundary

`IngestJob.last_heartbeat_at` was declared in `models.py:61` and queried in `worker.py:recover_stale_jobs` (the IS NULL + age comparison branches), but no code path writes the column. The stale-recovery query effectively collapsed to `created_at < now - 5min`, force-killing any running ingest >5 minutes old on every rolling deploy.

</domain>

<decisions>
## Implementation Decisions

### Heartbeat strategy: **OPTION (B)** — Drop the column

User decision 2026-05-20 (AskUserQuestion).

Rationale:
- Less code, fewer moving parts. The 1h `JOB_TIMEOUT_SECONDS` sweep in `platform/jobs/router.fail_stale_jobs` already runs every 5 min via the `_stale_jobs_sweeper` lifespan task.
- A 6-minute ingest survives rolling deploys (previously force-killed). Long-running ingests (>1h) still get failed by both startup recovery and the steady-state sweeper — same as today, no UX regression.
- No per-task heartbeat instrumentation needed.

### Implementation shape

1. Drop `catalog.ingest_jobs.last_heartbeat_at` column via Alembic 0021.
2. Remove the `last_heartbeat_at: Mapped[datetime | None]` field from `IngestJob` in `platform/jobs/models.py`.
3. Update `recover_stale_jobs` in `platform/jobs/worker.py`:
   - Use `started_at < now - JOB_TIMEOUT_SECONDS` (1h) as the stale predicate.
   - Drop the `IS NULL` OR clause.
   - Update the docstring to explain rolling-deploy behavior.
4. Update existing `test_recover_stale_jobs_marks_running_as_failed` test (error message changed) and add a `test_recover_stale_jobs_rolling_deploy_survives_6min_ingest` regression test.
5. Migration is reversible (downgrade re-adds the column as nullable, default NULL).

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- `platform/jobs/router.py:34` — `JOB_TIMEOUT_SECONDS = 3600`. The sweep also runs every 5 min via `api/main.py:_stale_jobs_sweeper`.
- `platform/jobs/router.py:39-79` — `fail_stale_jobs(db)` already implements the running + pending sweep using `started_at < cutoff` and `created_at < pending_cutoff`. Mirror this in `recover_stale_jobs`.

### Established Patterns

- **Alembic migration shape:** schema="catalog", upgrade()/downgrade() pattern. See 0019_users_token_version.py for closest analog (single-column add).
- **Worker startup recovery:** advisory lock via `pg_try_advisory_xact_lock(RECOVERY_LOCK_KEY)`. Keep this — it prevents concurrent recovery on rolling restart.

### Integration Points

- `recover_stale_jobs` (worker startup) — touch.
- `fail_stale_jobs` + `_stale_jobs_sweeper` (lifespan, periodic) — UNCHANGED. They already use the right logic.
- Frontend / OpenAPI — no impact (internal worker behavior).

</code_context>

<specifics>
## Specific Ideas

- The migration revision is `0021_drop_ingest_job_last_heartbeat_at`; baseline already contains the column at line 1026 of `0001_baseline.py`. No baseline edit needed — Alembic applies migrations forward.

</specifics>

<deferred>
## Deferred Ideas

- Add a per-task watchdog with a shorter timeout for fast-iteration ingests (e.g., 5 min for vector, 30 min for raster). Speculative; current 1h works for now.
- Surface the `_stale_jobs_sweeper` activity in the admin UI. Out of phase scope.

</deferred>

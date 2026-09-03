"""Procrastinate job queue metrics for Prometheus.

Exposes queue depth, active jobs, completed totals, and failed totals
as Prometheus gauges and counters. Metrics update every 15 seconds
via a background asyncio task.
"""

import asyncio

import structlog
from prometheus_client import Counter, Gauge
from sqlalchemy import text

logger = structlog.stdlib.get_logger(__name__)

# --- Gauges (current state) ---
jobs_queue_depth = Gauge(
    "geolens_jobs_queue_depth",
    "Number of jobs waiting in queue (status=todo)",
    ["queue"],
)
jobs_active = Gauge(
    "geolens_jobs_active",
    "Number of jobs currently executing (status=doing)",
    ["queue"],
)

# --- Counters (monotonically increasing) ---
jobs_completed_total = Counter(
    "geolens_jobs_completed_total",
    "Total number of successfully completed jobs",
    ["queue"],
)
jobs_failed_total = Counter(
    "geolens_jobs_failed_total",
    "Total number of failed jobs",
    ["queue"],
)

# fix(#1249): staging objects deleted because no ingest_jobs row tracks them.
# A true counter rather than a polled gauge, and safe as one for a reason
# worth stating (the concern refresh.py's module docstring raises): the
# reconciliation pass runs under a `pg_try_advisory_xact_lock`, so at most one
# process per interval deletes — and therefore counts — any given object,
# where a poll-and-increment design would report N times the truth under
# UVICORN_WORKERS>1. Incremented only after the provider delete returns, so
# the number counts completed deletions, not intentions.
#
# The series matters most when it is non-zero and STAYS non-zero: a steady
# trickle means something is leaking staging objects faster than one-off
# incidents explain.
staging_orphans_deleted_total = Counter(
    "geolens_staging_orphans_deleted_total",
    "Staging objects deleted for having no ingest-job row tracking them",
)

# fix(#1778 codex r1): the delta snapshot this module used to keep is gone with
# the last counter branch that read it. NOTE(#655) recorded that the first cycle
# after boot seeded the counters with historical row counts; nothing seeds them
# now, because neither counter is derived from a row count any more.

# Queues whose gauge children have been set at least once — zeroed (not
# removed) when their todo/doing rows disappear from a cycle. fix(#655)
_known_queues: set[str] = set()


async def _refresh_job_metrics() -> None:
    """Run one metrics collection cycle (no loop, no sleep).

    Queries procrastinate_jobs for status counts grouped by queue and updates
    the two gauges. fix(#1778 codex r1): gauges only. Both counters are
    incremented at the terminal transition, in platform/jobs/worker.py.
    """
    from app.core.db import engine

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT status, queue_name, COUNT(*) AS cnt "
                    "FROM catalog.procrastinate_jobs "
                    "GROUP BY status, queue_name"
                )
            )
            rows = result.fetchall()

        # Queues absent from this cycle get zeroed after the loop via
        # _known_queues, so a drained queue reads 0 instead of its last value
        seen_todo: set[str] = set()
        seen_doing: set[str] = set()

        for status, queue, count in rows:
            q = queue or "default"

            if status == "todo":
                jobs_queue_depth.labels(queue=q).set(count)
                seen_todo.add(q)
            elif status == "doing":
                jobs_active.labels(queue=q).set(count)
                seen_doing.add(q)
            # fix(#1778): there is deliberately no `succeeded` branch. The
            # worker runs with delete_jobs="successful", which makes
            # procrastinate_finish_job_v1 DELETE the row while it is still
            # `doing`, so status='succeeded' is never written and this 15s poll
            # could never observe it. geolens_jobs_completed_total read a flat
            # zero from the day it was added, and the RUNBOOK entry and the
            # "Job throughput" Grafana panel read zero with it -- a healthy
            # ingest burst looked identical to a dead worker.
            #
            # fix(#1778 codex r1): and no `failed` branch either. That one was
            # a delta against a snapshot of a row count, which stops working
            # the moment rows can disappear. purge_expired_terminal_jobs ages
            # terminal rows out, so a queue's failed group shrinks while
            # _prev_counts held the pre-purge figure, and the next burst
            # produced a non-positive delta the counter never saw --
            # GeoLensJobFailures with it.
            #
            # Both counters are incremented at the terminal transition now, by
            # the worker middleware and the stalled-job sweep in
            # platform/jobs/worker.py, where there is no snapshot to go stale.

        # fix(#655): zero gauges for previously seen queues with no todo/doing
        # rows this cycle — they used to freeze at their last non-zero value
        for q in _known_queues - seen_todo:
            jobs_queue_depth.labels(queue=q).set(0)
        for q in _known_queues - seen_doing:
            jobs_active.labels(queue=q).set(0)
        _known_queues.update(seen_todo, seen_doing)

    except Exception:  # broad: metrics refresh is non-fatal; DB/aggregation errors should not crash background loop
        logger.warning("Failed to refresh job metrics", exc_info=True)


async def update_job_metrics() -> None:
    """Background loop that refreshes job metrics every 15 seconds."""
    while True:
        await _refresh_job_metrics()
        await asyncio.sleep(15)

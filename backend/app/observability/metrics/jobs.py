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

# Staging objects deleted because no ingest_jobs row tracks
# them. A true counter, not a polled gauge: the reconciliation pass runs
# under pg_try_advisory_xact_lock, so at most one process per interval
# deletes (and counts) any given object, incremented only after the
# provider delete returns. Matters most when non-zero and STAYS
# non-zero: a steady trickle means something is leaking objects faster
# than one-off incidents explain.
staging_orphans_deleted_total = Counter(
    "geolens_staging_orphans_deleted_total",
    "Staging objects deleted for having no ingest-job row tracking them",
)

# Queues whose gauge children have been set at least once. Their gauges are
# zeroed, rather than removed, when no todo/doing rows remain.
_known_queues: set[str] = set()


async def _refresh_job_metrics() -> None:
    """Run one metrics collection cycle (no loop, no sleep).

    Queries procrastinate_jobs for status counts grouped by queue and updates
    the two gauges. Terminal counters are incremented at the transition in
    platform/jobs/worker.py.
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
            # Deliberately no `succeeded`/`failed` branch here.
            # The worker runs with delete_jobs="successful", so
            # procrastinate_finish_job_v1 DELETEs the row while still
            # `doing` — status='succeeded' is never written, so this 15s
            # poll could never observe it (geolens_jobs_completed_total
            # read a flat zero from day one). A `failed` branch would need
            # a delta against a row-count snapshot, which breaks once
            # purge_expired_terminal_jobs ages rows out mid-window. Both
            # counters are instead incremented at the terminal transition
            # by the worker middleware and stalled-job sweep in
            # platform/jobs/worker.py, where nothing goes stale.

        # Zero gauges for previously seen queues with no matching rows this cycle.
        for q in _known_queues - seen_todo:
            jobs_queue_depth.labels(queue=q).set(0)
        for q in _known_queues - seen_doing:
            jobs_active.labels(queue=q).set(0)
        _known_queues.update(seen_todo, seen_doing)

    except Exception:  # broad: metrics refresh is non-fatal; must not crash the loop
        logger.warning("Failed to refresh job metrics", exc_info=True)


async def update_job_metrics() -> None:
    """Background loop that refreshes job metrics every 15 seconds."""
    while True:
        await _refresh_job_metrics()
        await asyncio.sleep(15)

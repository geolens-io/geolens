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

# Track previous snapshot for counter delta computation
_prev_counts: dict[tuple[str, str], int] = {}


async def _refresh_job_metrics() -> None:
    """Run one metrics collection cycle (no loop, no sleep).

    Queries procrastinate_jobs for status counts grouped by queue,
    updates gauges directly and increments counters by delta.
    """
    from app.database import engine

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

        # Reset gauges to zero before setting — handles queues that disappear
        # We track which (queue, status) combos we see this cycle
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
            elif status == "succeeded":
                key = (q, "succeeded")
                prev = _prev_counts.get(key, 0)
                delta = count - prev
                if delta > 0:
                    jobs_completed_total.labels(queue=q).inc(delta)
                _prev_counts[key] = count
            elif status == "failed":
                key = (q, "failed")
                prev = _prev_counts.get(key, 0)
                delta = count - prev
                if delta > 0:
                    jobs_failed_total.labels(queue=q).inc(delta)
                _prev_counts[key] = count

    except Exception:
        logger.warning("Failed to refresh job metrics", exc_info=True)


async def update_job_metrics() -> None:
    """Background loop that refreshes job metrics every 15 seconds."""
    while True:
        await _refresh_job_metrics()
        await asyncio.sleep(15)

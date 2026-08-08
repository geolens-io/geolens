"""Prometheus series for the dataset-refresh lifecycle.

feat(#1268) / ADR-002 Amendment A10. Before this, nothing about refresh runs
was observable: an operator could see that ingest jobs existed and nothing
about whether refreshes were queueing, failing, or silently being swept.

### Why these are gauges polled from the table, not counters at the event

The obvious design — increment a counter where a run finishes — cannot work
here, and both reasons are structural rather than stylistic:

- **The worker is a different process with no scrape endpoint.** Terminal
  transitions happen in the ingest worker, which serves no ``/metrics`` and
  does not share ``PROMETHEUS_MULTIPROC_DIR`` with the API container. A
  counter incremented there is written to a file nothing ever reads.
- **Every API worker would count the same run.** Under ``UVICORN_WORKERS>=2``
  each worker runs its own background loop, and ``MultiProcessCollector`` SUMS
  counters across processes — so a poll-and-increment design reports N times
  the truth, which is the same class of fabricated number #1240 existed to
  remove.

So the state lives where it already is (``catalog.dataset_refresh_runs``, a
durable table that outlives both processes) and every worker publishes the
same computed answer as a gauge in ``livemostrecent`` mode. The collector
reports one worker's value rather than a sum, so the series is correct at
``UVICORN_WORKERS=1`` and at 8, and a worker that dies mid-cycle costs one
scrape's freshness rather than corrupting a running total.

The distribution series are SQL percentiles rather than histogram buckets for
the same reason: a histogram is cumulative state, and cumulative state is
exactly what cannot be shared across these processes. ``percentile_cont`` over
a trailing window gives the two numbers an operator actually pages on, and the
window makes them recover on their own after an incident instead of being
diluted by history forever.

Counters DO appear in this module, but only for events an API request
observes directly — one request is handled by exactly one worker, so there is
no double count to avoid.
"""

from __future__ import annotations

import asyncio

import structlog
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import text

logger = structlog.stdlib.get_logger(__name__)

# How often the derived gauges are recomputed. Matches the job-queue metrics
# cadence so a dashboard mixing the two has one refresh rate.
_REFRESH_INTERVAL_SECONDS = 15

# Trailing window for the outcome counts and the latency percentiles. An hour
# is long enough that a quiet instance still reports something and short
# enough that a fixed incident stops showing up by itself.
_WINDOW_SECONDS = 3600

# `livemostrecent` on every derived gauge: each API worker computes the SAME
# value from the SAME table, so the collector must report one of them rather
# than adding them up. The default `all` mode would emit one series per pid
# and the default aggregation for gauges would sum them.
_DERIVED = {"multiprocess_mode": "livemostrecent"}

refresh_runs_active = Gauge(
    "geolens_refresh_runs_active",
    "Refresh runs currently pending or running, by origin kind",
    ["origin_kind"],
    **_DERIVED,
)

refresh_runs_recent = Gauge(
    "geolens_refresh_runs_recent",
    "Refresh runs that reached a terminal status in the last hour",
    ["origin_kind", "trigger", "status"],
    **_DERIVED,
)

refresh_run_queue_wait_seconds = Gauge(
    "geolens_refresh_run_queue_wait_seconds",
    (
        "Seconds between dispatch and a worker claiming the run, over the last "
        "hour. This is only measurable because started_at and claimed_at are "
        "separate columns"
    ),
    ["origin_kind", "quantile"],
    **_DERIVED,
)

refresh_run_duration_seconds = Gauge(
    "geolens_refresh_run_duration_seconds",
    "Seconds a claimed run took to reach its outcome, over the last hour",
    ["origin_kind", "status", "quantile"],
    **_DERIVED,
)

# A true counter: the sweep runs inside one API request on one worker, so
# there is nothing to double count. It is also the series that matters most
# when it is NON-zero — every increment is a run that reached a terminal
# status without any worker reporting one.
refresh_sweep_reconciled_total = Counter(
    "geolens_refresh_sweep_reconciled_total",
    "Refresh runs finalized by the stale-run sweep rather than by a worker",
)

# Probe series (#1222's endpoint), also request-scoped and therefore safe as
# real instruments. `detail` is the probe's closed DETAIL_CODES vocabulary
# plus "none", so the label set is bounded by construction — the reason that
# vocabulary is closed in the first place.
origin_probe_total = Counter(
    "geolens_origin_probe_total",
    "Origin health probes by verdict",
    ["origin_kind", "health", "detail"],
)

origin_probe_duration_seconds = Histogram(
    "geolens_origin_probe_duration_seconds",
    "Seconds an origin health probe took, by verdict",
    ["origin_kind", "health"],
)


# Gauge children are never removed, only zeroed: a label combination that
# stops appearing must read 0 rather than freeze at its last value, which is
# the #655 lesson from the job-queue gauges.
_seen_active: set[str] = set()
_seen_recent: set[tuple[str, str, str]] = set()
_seen_wait: set[tuple[str, str]] = set()
_seen_duration: set[tuple[str, str, str]] = set()

_ACTIVE_SQL = text(
    """
    SELECT origin_kind, COUNT(*) AS cnt
    FROM catalog.dataset_refresh_runs
    WHERE status IN ('pending', 'running')
    GROUP BY origin_kind
    """
)

_RECENT_SQL = text(
    """
    SELECT origin_kind, trigger, status, COUNT(*) AS cnt
    FROM catalog.dataset_refresh_runs
    WHERE finished_at IS NOT NULL
      AND finished_at > now() - make_interval(secs => :window)
    GROUP BY origin_kind, trigger, status
    """
)

# claimed_at IS NOT NULL is the whole predicate for queue wait: a run the
# sweep cancelled before any worker claimed it never waited in a queue, it
# waited for a worker that never came, and averaging the two together would
# hide an outage inside a latency number.
_QUEUE_WAIT_SQL = text(
    """
    SELECT origin_kind,
           percentile_cont(0.5) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (claimed_at - started_at))
           ) AS p50,
           percentile_cont(0.95) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (claimed_at - started_at))
           ) AS p95
    FROM catalog.dataset_refresh_runs
    WHERE claimed_at IS NOT NULL
      AND claimed_at > now() - make_interval(secs => :window)
    GROUP BY origin_kind
    """
)

# Measured from claimed_at, not started_at, so a slow queue does not read as
# a slow ingest. The two numbers answer different questions and adding the
# queue wait into the duration would make both unusable.
_DURATION_SQL = text(
    """
    SELECT origin_kind, status,
           percentile_cont(0.5) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (finished_at - claimed_at))
           ) AS p50,
           percentile_cont(0.95) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (finished_at - claimed_at))
           ) AS p95
    FROM catalog.dataset_refresh_runs
    WHERE claimed_at IS NOT NULL
      AND finished_at IS NOT NULL
      AND finished_at > now() - make_interval(secs => :window)
    GROUP BY origin_kind, status
    """
)


async def _refresh_run_metrics_once() -> None:
    """Recompute every derived gauge. One cycle, no loop, no sleep."""
    from app.core.db import engine

    window = {"window": _WINDOW_SECONDS}
    try:
        async with engine.connect() as conn:
            active = (await conn.execute(_ACTIVE_SQL)).fetchall()
            recent = (await conn.execute(_RECENT_SQL, window)).fetchall()
            waits = (await conn.execute(_QUEUE_WAIT_SQL, window)).fetchall()
            durations = (await conn.execute(_DURATION_SQL, window)).fetchall()
    except Exception:  # broad: metrics must never crash the background loop
        logger.warning("Failed to refresh dataset-refresh metrics", exc_info=True)
        return

    seen_active = set()
    for origin_kind, count in active:
        refresh_runs_active.labels(origin_kind=origin_kind).set(count)
        seen_active.add(origin_kind)
    for origin_kind in _seen_active - seen_active:
        refresh_runs_active.labels(origin_kind=origin_kind).set(0)
    _seen_active.update(seen_active)

    seen_recent = set()
    for origin_kind, trigger, run_status, count in recent:
        key = (origin_kind, trigger, run_status)
        refresh_runs_recent.labels(
            origin_kind=origin_kind, trigger=trigger, status=run_status
        ).set(count)
        seen_recent.add(key)
    for origin_kind, trigger, run_status in _seen_recent - seen_recent:
        refresh_runs_recent.labels(
            origin_kind=origin_kind, trigger=trigger, status=run_status
        ).set(0)
    _seen_recent.update(seen_recent)

    seen_wait = set()
    for origin_kind, p50, p95 in waits:
        for quantile, value in (("0.5", p50), ("0.95", p95)):
            refresh_run_queue_wait_seconds.labels(
                origin_kind=origin_kind, quantile=quantile
            ).set(float(value or 0.0))
            seen_wait.add((origin_kind, quantile))
    for origin_kind, quantile in _seen_wait - seen_wait:
        refresh_run_queue_wait_seconds.labels(
            origin_kind=origin_kind, quantile=quantile
        ).set(0)
    _seen_wait.update(seen_wait)

    seen_duration = set()
    for origin_kind, run_status, p50, p95 in durations:
        for quantile, value in (("0.5", p50), ("0.95", p95)):
            refresh_run_duration_seconds.labels(
                origin_kind=origin_kind, status=run_status, quantile=quantile
            ).set(float(value or 0.0))
            seen_duration.add((origin_kind, run_status, quantile))
    for origin_kind, run_status, quantile in _seen_duration - seen_duration:
        refresh_run_duration_seconds.labels(
            origin_kind=origin_kind, status=run_status, quantile=quantile
        ).set(0)
    _seen_duration.update(seen_duration)


async def update_refresh_metrics() -> None:
    """Background loop refreshing the derived gauges every 15 seconds."""
    while True:
        await _refresh_run_metrics_once()
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)

"""SQLAlchemy connection pool metrics for Prometheus.

Exposes pool utilization gauges that update every 15 seconds
via a background asyncio task. Gracefully skips when using
an external connection pooler (NullPool has no stats).

fix(#1240, #651): each uvicorn worker owns its own SQLAlchemy engine, so
these gauges are genuinely per-worker values. Under PROMETHEUS_MULTIPROC_DIR
(multiprocess mode), the default Gauge aggregation ('all') would auto-label
every sample by pid, turning one series into N and silently breaking any
existing alert/dashboard expression that reads the bare metric name. Declare
'livesum' explicitly so a scrape keeps returning one series -- the fleet-wide
total across live workers -- matching the metric's pre-fix single-value shape.
"""

import asyncio

import structlog
from prometheus_client import Gauge
from sqlalchemy.pool import QueuePool

logger = structlog.stdlib.get_logger(__name__)

# --- Gauges (current pool state) ---
db_pool_checkedout = Gauge(
    "geolens_db_pool_checkedout",
    "Number of connections currently checked out from the pool",
    multiprocess_mode="livesum",
)
db_pool_checkedin = Gauge(
    "geolens_db_pool_checkedin",
    "Number of connections currently available in the pool",
    multiprocess_mode="livesum",
)
db_pool_overflow = Gauge(
    "geolens_db_pool_overflow",
    "Number of overflow connections currently open",
    multiprocess_mode="livesum",
)
db_pool_size = Gauge(
    "geolens_db_pool_size",
    "Configured pool size",
    multiprocess_mode="livesum",
)


async def _refresh_pool_metrics() -> None:
    """Run one metrics collection cycle (no loop, no sleep).

    Reads SQLAlchemy pool stats. Skips when using external pooler
    or when pool is not a QueuePool.
    """
    from app.core.config import settings
    from app.core.db import engine

    try:
        if settings.db_use_external_pooler:
            return

        pool = engine.pool
        if not isinstance(pool, QueuePool):
            return

        db_pool_checkedout.set(pool.checkedout())
        db_pool_checkedin.set(pool.checkedin())
        db_pool_overflow.set(pool.overflow())
        db_pool_size.set(pool.size())

    except Exception:  # broad: pool metrics refresh is non-fatal; engine/pool errors should not crash background loop
        logger.warning("Failed to refresh pool metrics", exc_info=True)


async def update_pool_metrics() -> None:
    """Background loop that refreshes pool metrics every 15 seconds."""
    while True:
        await _refresh_pool_metrics()
        await asyncio.sleep(15)

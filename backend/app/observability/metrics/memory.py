"""Per-worker RSS memory metrics for Prometheus + log watermarks.

fix(#643): an api uvicorn worker was OOM-killed at the container cgroup cap
(~1.9 GB RSS) with nothing in the normal logs — the event was only visible
in the VM's dmesg. Expose each worker's RSS as a gauge and, because many
deployments never scrape /metrics, WARN in the structured logs whenever a
worker crosses the memory watermark, so runaway growth is diagnosable from
`docker logs` alone.

Reads /proc directly (Linux containers; no psutil dependency). On platforms
without /proc (macOS dev) the loop idles silently.

fix(#1778): the Procrastinate worker starts this loop too. It hosts GDAL/OGR
and carries a 4 GB mem_limit against the API's 2 GB precisely because a large
raster ingest is memory-hungry, so it is the process most likely to reproduce
#643 -- and it published no gauge and no watermark warning at all. The prose
below says "api worker" because that is where the finding came from; both
services run it now.

fix(#1240, #651): the api service runs in prometheus_client multiprocess
mode, so a scrape reports every live worker's gauge in one response instead
of whichever single worker answered. The gauge's own `pid` label plus
`multiprocess_mode="liveall"` (rather than the default `"all"`) means a
recycled worker's series actually disappears once its mmap file is removed
by `shutdown_worker_metrics()` on that worker's own shutdown -- `"all"`
would keep a dead pid's last value forever, since prometheus_client's
`mark_process_dead()` only unlinks files for `live*`-mode gauges.
"""

import asyncio
import os
import time

import structlog
from prometheus_client import Gauge

logger = structlog.stdlib.get_logger(__name__)

worker_rss_bytes = Gauge(
    "geolens_worker_rss_bytes",
    "Resident set size of an API uvicorn worker or the job worker process",
    ["pid"],
    multiprocess_mode="liveall",
)

_INTERVAL_SECONDS = 60
# WARN when a single worker exceeds this share of the container memory limit
# (two workers share one cgroup, so one worker at 60% starves its sibling).
_WARN_FRACTION_OF_LIMIT = 0.6
# Fallback watermark when no cgroup limit is readable (bytes).
_WARN_DEFAULT_BYTES = 1200 * 1024 * 1024
# Re-warn at most every 5 minutes while above the watermark.
_WARN_REPEAT_SECONDS = 300


def read_rss_bytes() -> int | None:
    """Current process RSS from /proc/self/status, or None off-Linux."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def read_cgroup_limit_bytes() -> int | None:
    """Container memory limit (cgroup v2 then v1), or None if unlimited."""
    for path in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        try:
            with open(path) as f:
                raw = f.read().strip()
        except OSError:
            continue
        if raw == "max" or not raw.isdigit():
            return None
        limit = int(raw)
        # cgroup v1 reports a huge sentinel when unlimited.
        return limit if limit < 1 << 60 else None
    return None


class MemoryWatch:
    """One sampling pass + watermark state, separated from the loop for tests."""

    def __init__(self) -> None:
        self._warn_bytes: int | None = None
        # -inf so the very first over-watermark sample always warns.
        self._last_warned_at: float = float("-inf")
        self._samples = 0

    def _watermark(self) -> int:
        if self._warn_bytes is None:
            limit = read_cgroup_limit_bytes()
            self._warn_bytes = (
                int(limit * _WARN_FRACTION_OF_LIMIT) if limit else _WARN_DEFAULT_BYTES
            )
        return self._warn_bytes

    def sample(self, now: float | None = None) -> int | None:
        rss = read_rss_bytes()
        if rss is None:
            return None
        worker_rss_bytes.labels(pid=str(os.getpid())).set(rss)
        self._samples += 1
        watermark = self._watermark()
        now = time.monotonic() if now is None else now
        fields = {"pid": os.getpid(), "rss_mb": rss // (1024 * 1024)}
        if rss >= watermark and now - self._last_warned_at >= _WARN_REPEAT_SECONDS:
            self._last_warned_at = now
            logger.warning(
                "API worker memory above watermark",
                watermark_mb=watermark // (1024 * 1024),
                **fields,
            )
        elif self._samples == 1 or self._samples % 60 == 0:
            # Hourly heartbeat (plus a startup baseline) so a growth curve
            # exists in plain logs even when /metrics is never scraped.
            logger.info("API worker memory", **fields)
        else:
            logger.debug("API worker memory", **fields)
        return rss


async def update_memory_metrics() -> None:
    """Background loop that samples worker RSS every 60 seconds."""
    watch = MemoryWatch()
    while True:
        try:
            watch.sample()
        except (
            Exception
        ):  # broad: metrics sampling is non-fatal; must not crash the loop
            logger.warning("Failed to sample worker memory", exc_info=True)
        await asyncio.sleep(_INTERVAL_SECONDS)

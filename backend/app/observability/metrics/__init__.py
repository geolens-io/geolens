"""Prometheus metrics module for GeoLens: HTTP request instrumentation,
job queue gauges, and connection pool gauges.

Without multiprocess mode, each worker answers /metrics
from its own registry, so scrapes sawtooth between per-process values and
Prometheus reads every downward step as a fabricated counter reset.
`expose()` already serves a merged registry whenever
PROMETHEUS_MULTIPROC_DIR is set, which both compose files do by default
(including development), so the behavior requires no extra environment wiring.
"""

import asyncio
import glob
import os
from collections.abc import Iterator

import structlog
from fastapi import FastAPI, Request

from .instrumentator import create_instrumentator

logger = structlog.stdlib.get_logger(__name__)

# How often every worker sweeps PROMETHEUS_MULTIPROC_DIR for gauge files left
# by a sibling that died without running its own shutdown hook.
_SWEEP_INTERVAL_SECONDS = 60

# Must match the endpoint create_instrumentator() +
# instrumentator.expose() below actually serve (its default, unoverridden).
_METRICS_ENDPOINT_PATH = "/metrics"

# How long the scrape-side non-blocking lock poll waits between attempts.
# The sweep's exclusive hold is brief (a handful of file operations every
# 60s), so contention is rare and short-lived.
_SCRAPE_LOCK_POLL_SECONDS = 0.005


def _sweep_lock_path(multiproc_dir: str) -> str:
    """Path to the reader/writer lock file guarding PROMETHEUS_MULTIPROC_DIR
    against concurrent scrape-vs-sweep file mutation. See
    _consolidate_dead_cumulative_metric_files() (writer/exclusive side)
    and the metrics-scrape middleware in init_metrics() (reader/shared
    side).
    """
    return os.path.join(multiproc_dir, "sweep.lock")


# Upper bounds for http_request_duration_seconds (the only
# `handler`-labelled latency histogram). The library default — (0.1, 0.5,
# 1) + implicit +Inf — clamps p95 at 1.0, since histogram_quantile
# returns the highest FINITE bound when the quantile lands in +Inf;
# GeoLensApiInteractiveLatencyP95 fired on that ceiling, not real
# latency. Kept short despite the cost (each bound adds one series per
# `method` label value)
# because the unlabelled sibling can't answer "p95 excluding tiles".
LATENCY_LOWR_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def init_metrics(app: FastAPI):
    """Instrument the FastAPI app and expose /metrics endpoint."""
    instrumentator = create_instrumentator()
    # Buckets are passed HERE, not in create_instrumentator() —
    # Instrumentator.__init__ takes no bucket args; instrument() is the
    # only place they can be set (prometheus_fastapi_instrumentator 8.1.0).
    instrumentator.instrument(app, latency_lowr_buckets=LATENCY_LOWR_BUCKETS)
    instrumentator.expose(app, include_in_schema=False, should_gzip=True)

    @app.middleware("http")
    async def _hold_scrape_lock_during_metrics_response(request: Request, call_next):
        """Hold a shared (reader) lock on PROMETHEUS_MULTIPROC_DIR for the
        duration of a /metrics scrape, so the consolidation sweep's
        exclusive lock can never rename a .db file out from under a
        scrape that already globbed it.

        MultiProcessCollector.collect() tolerates a
        path disappearing mid-scan only for gauge_live*.db; cumulative
        types re-raise FileNotFoundError, which would surface as an
        intermittent 500 when the 60s sweep's os.rename() lands
        mid-scrape. Non-blocking poll loop (fcntl.flock isn't awaitable)
        so a brief wait never blocks this worker's event loop. Excluded
        from instrumentation so the wait is never measured as latency.
        """
        multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if request.url.path != _METRICS_ENDPOINT_PATH or not multiproc_dir:
            return await call_next(request)

        import fcntl

        with open(_sweep_lock_path(multiproc_dir), "a+b") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(_SCRAPE_LOCK_POLL_SECONDS)
            try:
                return await call_next(request)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    return instrumentator


def shutdown_worker_metrics() -> None:
    """Mark this worker process's multiprocess metric files dead.

    Under UVICORN_MAX_REQUESTS recycling, a
    worker respawns mid-lifetime, not just at container shutdown;
    without this its mmap files linger and keep summing into every
    future scrape as a stale series. No-op when multiprocess mode isn't
    active. Runs only on graceful lifespan shutdown — see
    sweep_dead_worker_metrics() for the OOM-kill/SIGKILL case.
    """
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(os.getpid())


def _dead_worker_pids() -> Iterator[int]:
    """PIDs with a live-mode multiprocess file but no longer running.

    Reads pids from gauge_live*_<pid>.db filenames and checks each with
    a signal-0 kill (prometheus_client's recommended reaping pattern). A
    pid reused before the next sweep is skipped as "alive" — an accepted
    limitation, not fixable from inside a dying process.
    """
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    seen: set[int] = set()
    for path in glob.glob(os.path.join(multiproc_dir, "gauge_live*_*.db")):
        pid_str = os.path.basename(path).rsplit("_", 1)[-1].removesuffix(".db")
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid in seen or pid == os.getpid():
            continue
        seen.add(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            yield pid
        except PermissionError:
            # Process exists (just not signalable by us) -- treat as alive.
            continue


def _iter_dead_pid_files(prefix: str, multiproc_dir: str) -> Iterator[tuple[int, str]]:
    """Yield (pid, path) for prefix_<pid>.db files whose pid is no longer
    running. Used for counter/histogram/summary files, which are named
    "<type>_<pid>.db" with no mode segment (unlike gauge's
    "gauge_<mode>_<pid>.db") -- see _dead_worker_pids() for that one.
    """
    for path in glob.glob(os.path.join(multiproc_dir, f"{prefix}_*.db")):
        pid_str = os.path.basename(path)[len(prefix) + 1 : -len(".db")]
        try:
            pid = int(pid_str)
        except ValueError:
            # Not a live pid's file -- e.g. the "_archived" consolidation
            # file this sweep itself writes below.
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
            continue  # still alive
        except ProcessLookupError:
            pass
        except PermissionError:
            continue  # exists, just not signalable by us -- treat as alive
        yield pid, path


# Non-numeric suffix so _iter_dead_pid_files never
# mistakes this file itself for a dead worker's file.
_ARCHIVE_SUFFIX = "archived"


def _consolidate_dead_cumulative_metric_files() -> None:
    """Fold dead workers' counter/histogram/summary files into one
    running total per type ("<type>_archived.db") instead of letting
    them accumulate forever. ``mark_process_dead()`` never touches these
    because their values are cumulative and summed across every
    pid's file, so deleting one would silently subtract its contribution.

    Runs under one exclusive hold of the same lock the /metrics scrape
    middleware takes as shared (_sweep_lock_path()), closing a
    lost-update race between two sweeps and a FileNotFoundError a scrape
    would hit if a rename landed mid-glob. Must run off the event loop
    via asyncio.to_thread (see sweep_dead_worker_metrics()) — its
    flock() blocks, and run inline it could deadlock against this
    worker's own scrape middleware holding the shared lock on the file.
    """
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    import fcntl

    from prometheus_client.mmap_dict import MmapedDict

    with open(_sweep_lock_path(multiproc_dir), "a+b") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            for prefix in ("counter", "histogram", "summary"):
                claimed_paths = []
                for _pid, path in _iter_dead_pid_files(prefix, multiproc_dir):
                    claimed_path = f"{path}.claimed"
                    # A kill after the rename but before the merge orphans the claimed
                    # file, invisible to scrapes and sweeps: an accepted residual.
                    try:
                        os.rename(path, claimed_path)
                    except FileNotFoundError:
                        continue  # another worker's sweep already claimed this
                    claimed_paths.append(claimed_path)

                if not claimed_paths:
                    continue

                archive_path = os.path.join(
                    multiproc_dir, f"{prefix}_{_ARCHIVE_SUFFIX}.db"
                )
                archive = MmapedDict(archive_path)
                try:
                    for claimed_path in claimed_paths:
                        # read_all_values_from_file yields
                        # (key, value, timestamp, pos) -- the trailing byte
                        # offset is an implementation detail of the
                        # instance-level reader that write_value doesn't need.
                        for (
                            key,
                            value,
                            timestamp,
                            _pos,
                        ) in MmapedDict.read_all_values_from_file(claimed_path):
                            current, _ts = archive.read_value(key)
                            archive.write_value(key, current + value, timestamp)
                        os.remove(claimed_path)
                finally:
                    archive.close()
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _sweep_dead_worker_metrics_once() -> None:
    """Run one metrics-file reap pass."""
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    for pid in _dead_worker_pids():
        multiprocess.mark_process_dead(pid)
    _consolidate_dead_cumulative_metric_files()


async def sweep_dead_worker_metrics() -> None:
    """Background loop: reap and consolidate files left by dead workers.

    Shutdown_worker_metrics() only runs on graceful
    shutdown, so an OOM-killed or SIGKILLed worker leaves its
    RSS/pool gauges and cumulative metric files behind (see
    _consolidate_dead_cumulative_metric_files()), inflating /metrics
    until the container restarts. No-op when multiprocess mode isn't
    active; safe in every worker since both passes are idempotent once
    a dead pid's files are gone. Dispatches via asyncio.to_thread — its
    flock() blocks, and inline on the event loop it could deadlock
    against this worker's own scrape middleware holding a lock on the
    same file via a different fd.
    """
    while True:
        try:
            await asyncio.to_thread(_sweep_dead_worker_metrics_once)
        except Exception:  # broad: sweep is non-fatal; must not crash the loop
            logger.warning("Failed to sweep dead worker metrics", exc_info=True)
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

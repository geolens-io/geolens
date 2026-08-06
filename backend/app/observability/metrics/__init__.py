"""Prometheus metrics module for GeoLens.

Provides HTTP request instrumentation, job queue gauges, and connection pool gauges.

fix(#1240, #651): under UVICORN_WORKERS>=2 (the prod compose default), each
worker used to answer /metrics from its own local prometheus_client registry,
so successive scrapes sawtoothed between per-process values and Prometheus
read every downward step as a counter reset -- fabricating rate() traffic and
collapsing latency averages to a worker's lifetime mean. `init_metrics` itself
needs no multiprocess-specific code: prometheus_fastapi_instrumentator's
`expose()` already serves a fresh CollectorRegistry wrapped by
multiprocess.MultiProcessCollector whenever PROMETHEUS_MULTIPROC_DIR is set
(see its `metrics()` closure), and falls back to the plain default registry
otherwise. Both docker-compose.yml and docker-compose.prod.yml set
PROMETHEUS_MULTIPROC_DIR for the api service by default, so multiprocess mode
is active in dev too, not just prod -- deliberately, so bumping
UVICORN_WORKERS locally to reproduce #651 (per its own verification recipe)
needs no extra env wiring. It works correctly at UVICORN_WORKERS=1: there is
just one process's files for MultiProcessCollector to merge.
"""

import asyncio
import glob
import os
from collections.abc import Iterator

import structlog
from fastapi import FastAPI

from .instrumentator import create_instrumentator

logger = structlog.stdlib.get_logger(__name__)

# How often every worker sweeps PROMETHEUS_MULTIPROC_DIR for gauge files left
# by a sibling that died without running its own shutdown hook.
_SWEEP_INTERVAL_SECONDS = 60


def init_metrics(app: FastAPI):
    """Instrument the FastAPI app and expose /metrics endpoint."""
    instrumentator = create_instrumentator()
    instrumentator.instrument(app)
    instrumentator.expose(app, include_in_schema=False, should_gzip=True)
    return instrumentator


def shutdown_worker_metrics() -> None:
    """Mark this worker process's multiprocess metric files dead.

    fix(#1240, #651): under UVICORN_MAX_REQUESTS recycling (#643) a worker
    exits and is respawned mid-lifetime, not just at container shutdown.
    Without this, the exited worker's mmap files linger under
    PROMETHEUS_MULTIPROC_DIR and keep being summed into every future scrape
    as a stale series. No-op when multiprocess mode isn't active -- both
    compose files set PROMETHEUS_MULTIPROC_DIR by default (dev included), so
    this is live in normal local development too; it only stays unset for a
    bespoke deployment that runs the api image directly, outside these
    compose files, without setting the var itself.

    This only runs on a graceful lifespan shutdown -- see
    sweep_dead_worker_metrics() for the OOM-kill/SIGKILL case, where this
    function never gets a chance to run at all.
    """
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(os.getpid())


def _dead_worker_pids() -> Iterator[int]:
    """PIDs with a live-mode multiprocess file but no longer running.

    Reads pids off of gauge_live*_<pid>.db filenames (prometheus_client's own
    naming scheme) and checks each with a signal-0 kill, the same liveness
    probe prometheus_client's own docs recommend for this exact reaping
    pattern. A pid that gets reused by an unrelated process before the next
    sweep would be skipped as "alive" -- an accepted, documented limitation
    of pid-based reaping, not something this sweep can close from inside a
    dying process.
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


def _sweep_dead_worker_metrics_once() -> None:
    """Run one reap pass (no loop, no sleep) -- split out for tests."""
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    for pid in _dead_worker_pids():
        multiprocess.mark_process_dead(pid)


async def sweep_dead_worker_metrics() -> None:
    """Background loop: reap multiprocess files left by a hard-killed worker.

    fix(#1240, #651 review round 2): shutdown_worker_metrics() only runs on a
    graceful lifespan shutdown. A worker OOM-killed or SIGKILLed (the #643
    scenario this whole gauge exists to catch) never reaches that shutdown
    path, while the uvicorn supervisor stays up and respawns a replacement in
    the same PROMETHEUS_MULTIPROC_DIR -- so the dead worker's RSS and pool
    gauges would otherwise linger, inflating /metrics, until the whole
    container restarts. No-op when multiprocess mode isn't active. Safe to
    run in every worker: mark_process_dead() is idempotent once a pid's files
    are gone, so a race between two workers sweeping the same dead pid is
    harmless.
    """
    while True:
        try:
            _sweep_dead_worker_metrics_once()
        except Exception:  # broad: sweep is non-fatal; must not crash the loop
            logger.warning("Failed to sweep dead worker metrics", exc_info=True)
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

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
otherwise -- so this stays a no-op for the dev single-worker default.
"""

import os

from fastapi import FastAPI

from .instrumentator import create_instrumentator


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
    as a stale series. No-op when multiprocess mode isn't active (e.g. the
    dev single-worker default has no PROMETHEUS_MULTIPROC_DIR set).
    """
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(os.getpid())

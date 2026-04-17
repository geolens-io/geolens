"""Prometheus metrics module for GeoLens.

Provides HTTP request instrumentation, job queue gauges, and connection pool gauges.
"""

from fastapi import FastAPI

from .instrumentator import create_instrumentator


def init_metrics(app: FastAPI):
    """Instrument the FastAPI app and expose /metrics endpoint."""
    instrumentator = create_instrumentator()
    instrumentator.instrument(app)
    instrumentator.expose(app, include_in_schema=False, should_gzip=True)
    return instrumentator
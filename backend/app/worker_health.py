"""Lightweight Starlette health server for the Procrastinate worker.

Serves liveness, readiness, and Prometheus metrics on port 8001.
Designed to run alongside the worker loop via asyncio.create_task().
"""

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

# Bind service field for worker log entries. Safe to call even if already bound
# by the worker entrypoint -- bind_contextvars is idempotent (last call wins).
structlog.contextvars.bind_contextvars(service="worker")


def _get_engine():
    """Lazy import to avoid triggering DB connection at module load time."""
    from app.database import engine

    return engine


async def liveness(request: Request) -> JSONResponse:
    """Liveness probe -- confirms process is up, no dependency checks."""
    return JSONResponse({"status": "ok"})


async def readiness(request: Request) -> JSONResponse:
    """Readiness probe -- DB connectivity check via SELECT 1."""
    try:
        engine = _get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        return JSONResponse(
            {"status": "not_ready", "error": str(exc)},
            status_code=503,
        )


async def metrics(request: Request) -> Response:
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


app = Starlette(
    routes=[
        Route("/health/live", liveness),
        Route("/health/ready", readiness),
        Route("/metrics", metrics),
    ],
)

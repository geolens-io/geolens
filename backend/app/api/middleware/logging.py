"""Request logging middleware with structured output and request ID tracking."""

import re
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

access_logger = structlog.stdlib.get_logger("api.access")

_SHARED_MAP_PATH = re.compile(r"^(?P<prefix>/(?:api/)?maps/shared/)[^/]+")


def safe_access_log_path(path: str) -> str:
    """Remove bearer capability segments from paths written to access logs."""
    return _SHARED_MAP_PATH.sub(r"\g<prefix>[REDACTED]", path, count=1)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing, status, and a unique request ID."""

    async def dispatch(self, request: Request, call_next) -> Response:
        structlog.contextvars.clear_contextvars()

        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(service="api", request_id=request_id)
        # Stash on request.state so the global exception handler can read the
        # ID without parsing client-supplied headers (RESILIENCE-9).
        request.state.request_id = request_id

        # fix(#1778 codex r2): the moment the request entered the app, on the
        # same clock a handler can compare against. A route that must answer
        # inside the edge proxy's read timeout cannot start its own clock at
        # its function body: FastAPI resolves that route's dependencies first,
        # and one of those can block on a database pool checkout for as long
        # as ``db_pool_timeout``. Stamped here, beside the request id and for
        # the same reason, so the handler measures from where the proxy's own
        # clock started rather than from where it got control.
        #
        # ``monotonic`` rather than ``perf_counter``: both are monotonic and
        # both are ns-resolution here, and one read serves both the deadline
        # below and the duration this middleware already logs.
        started_at = time.monotonic()
        request.state.started_at_monotonic = started_at
        response: Response | None = None

        try:
            response = await call_next(request)
        except Exception:  # broad: middleware boundary — log any unhandled exception with request context, then re-raise
            structlog.stdlib.get_logger("api.error").exception("Unhandled exception")
            raise
        finally:
            duration_ms = (time.monotonic() - started_at) * 1000
            status_code = response.status_code if response is not None else 500

            access_logger.info(
                "request_completed",
                http_method=request.method,
                path=safe_access_log_path(request.url.path),
                status_code=status_code,
                duration_ms=round(duration_ms, 2),
                request_id=request_id,
            )

        # Set on every response, including those built by the global error
        # handler — needed because that handler runs *after* call_next raises
        # (RESILIENCE-5).
        if response is not None:
            response.headers["X-Request-ID"] = request_id
        return response

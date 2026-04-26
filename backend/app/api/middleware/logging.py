"""Request logging middleware with structured output and request ID tracking."""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

access_logger = structlog.stdlib.get_logger("api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing, status, and a unique request ID."""

    async def dispatch(self, request: Request, call_next) -> Response:
        structlog.contextvars.clear_contextvars()

        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(service="api", request_id=request_id)
        # Stash on request.state so the global exception handler can read the
        # ID without parsing client-supplied headers (RESILIENCE-9).
        request.state.request_id = request_id

        start_time = time.perf_counter_ns()
        response: Response | None = None

        try:
            response = await call_next(request)
        except Exception:
            structlog.stdlib.get_logger("api.error").exception("Unhandled exception")
            raise
        finally:
            duration_ms = (time.perf_counter_ns() - start_time) / 1_000_000
            status_code = response.status_code if response is not None else 500

            access_logger.info(
                "request_completed",
                http_method=request.method,
                path=request.url.path,
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

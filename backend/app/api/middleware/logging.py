"""Request logging middleware with structured output and request ID tracking."""

import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# fix(#1778): one redactor for every log line carrying a request path,
# moved to core/ so the two 5xx handlers (which logged the raw path) can
# use it too. Re-exported here since callers/tests import it from here.
from app.core.logging_config import safe_access_log_path
from app.core.service_tokens import reset_registered_credential_secrets

__all__ = ["RequestLoggingMiddleware", "access_logger", "safe_access_log_path"]

access_logger = structlog.stdlib.get_logger("api.access")


class RequestLoggingMiddleware:
    """Log every HTTP request with timing, status, and a unique request ID.

    The access line is written when the response starts, or with status 500
    when the request ends without one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        structlog.contextvars.clear_contextvars()
        # fix(#1770): the credential-secret registry is scoped to one
        # request like these contextvars — a reused worker must not let
        # one request's secrets scrub (or fail to scrub) another's logs.
        reset_registered_credential_secrets()

        request = Request(scope)
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(service="api", request_id=request_id)
        # Stash on request.state so the global exception handler can read the
        # ID without parsing client-supplied headers.
        request.state.request_id = request_id

        # fix(#1778): stamped the moment the request entered the app, on
        # the same clock a handler can compare against — a route with a
        # proxy read-timeout budget can't start its own clock in the
        # function body, since FastAPI resolves dependencies first (one
        # can block on a DB pool checkout up to db_pool_timeout).
        #
        # ``monotonic``, not ``perf_counter``: both are monotonic and
        # ns-resolution here, and one read serves both the deadline and
        # the duration this middleware logs.
        started_at = time.monotonic()
        request.state.started_at_monotonic = started_at
        response_started = False

        def log_completed(status_code: int) -> None:
            access_logger.info(
                "request_completed",
                http_method=request.method,
                path=safe_access_log_path(request.url.path),
                status_code=status_code,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                request_id=request_id,
            )

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start" and not response_started:
                response_started = True
                log_completed(message["status"])
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:  # broad: log any unhandled exception with request context
            if not response_started:
                structlog.stdlib.get_logger("api.error").exception(
                    "Unhandled exception"
                )
            raise
        finally:
            if not response_started:
                log_completed(500)

"""Global default rate limit as a plain ASGI middleware.

Replaces slowapi's ``SlowAPIMiddleware``, a ``BaseHTTPMiddleware`` that checks
the default limit through limits' sync storage, a blocking Redis round trip on
the event loop for every request. The limit itself is evaluated by
``limiter.check_default_limits`` (``app/platform/ratelimit.py``); this layer
resolves the route, applies slowapi's exemptions, answers the 429 and adds
the configured rate-limit headers to a response that passed.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import _find_route_handler as _slowapi_find_route_handler
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.platform.request_credential import mark_refused_before_auth


def find_route_handler(
    routes: Iterable[BaseRoute], scope: Scope
) -> Callable[..., Any] | None:
    """The endpoint that would serve *scope*, including nested includes.

    slowapi <= 0.1.10 scans ``app.routes`` for a matching route with an
    ``endpoint``; fastapi 0.140 keeps included-router routes nested, so the
    scan finds nothing and global rate limiting silently stops enforcing.
    Misses resolve through the flattened route contexts instead. Guarded by
    tests/test_middleware.py::test_rate_limiting.
    """
    handler = _slowapi_find_route_handler(routes, scope)
    if handler is not None:
        return handler
    from fastapi.routing import iter_route_contexts

    # Route regexes never include the ASGI root_path; starlette's own matching
    # strips it too (starlette._utils.get_route_path, mirrored here to avoid the
    # private import). Without this, ROOT_PATH deployments would silently lose the
    # global rate limit.
    path = scope.get("path", "")
    root_path = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        stripped = path[len(root_path) :]
        if not stripped or stripped.startswith("/"):
            path = stripped
    method = scope.get("method", "")
    for ctx in iter_route_contexts(list(routes)):
        path_regex = getattr(ctx, "path_regex", None)
        if path_regex is None or not path_regex.match(path):
            continue
        # Registration order matches starlette routing order, so the first
        # method-compatible hit is the route that would handle the request.
        if ctx.methods and method not in ctx.methods:
            continue
        if ctx.endpoint is not None:
            return ctx.endpoint
    return None


class GlobalRateLimitMiddleware:
    """Enforce the limiter's default limits on routes without their own."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        app = scope["app"]
        limiter = app.state.limiter
        endpoint = find_route_handler(app.routes, scope) if limiter.enabled else None
        if limiter.is_exempt_from_default_limits(endpoint):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive, send=send)
        try:
            await limiter.check_default_limits(request, endpoint)
        except RateLimitExceeded as exc:
            mark_refused_before_auth(scope)
            handler = app.exception_handlers.get(
                RateLimitExceeded, _rate_limit_exceeded_handler
            )
            response = handler(request, exc)
            if inspect.isawaitable(response):
                response = await response
            await response(scope, receive, send)
            return
        if not limiter.injects_rate_limit_headers:
            await self.app(scope, receive, send)
            return

        async def send_with_rate_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                await limiter.rate_limit_headers(request, MutableHeaders(scope=message))
            await send(message)

        await self.app(scope, receive, send_with_rate_limit_headers)

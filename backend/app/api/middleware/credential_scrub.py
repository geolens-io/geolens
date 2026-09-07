"""Scrub registered credential secrets from an unhandled exception, while
it can still be read from — before it crosses a middleware task boundary.

fix(#1770): `register_credential_secret` records the exact header line a
request's credential composed into a `ContextVar`, so the redaction
processors can exact-scrub it — but only for a reader in the SAME async
task, which an UNHANDLED exception's readers are not. Measured
(`test_credential_scrub_middleware.py`): Starlette's
`BaseHTTPMiddleware.dispatch` runs `call_next` in a SEPARATELY SPAWNED
task, so `ContextVar.set()` never propagates back — both
`RequestLoggingMiddleware` and a bare `@app.exception_handler(Exception)`
read the registry as empty.

This module is a plain ASGI callable, not `BaseHTTPMiddleware`, so it
shares the route handler's exact task and, registered INNERMOST, can
read the registry the handler populated — mutating the exception's
`args`/chain IN PLACE so the unwound object already carries scrubbed
text by the time any outer, task-isolated context reads it.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.url_redaction import scrub_registered_credentials_from_exception

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class CredentialScrubASGIMiddleware:
    """Scrubs registered credential secrets from an exception before it
    leaves this request's own async task. See module docstring for why a
    plain ASGI callable, not `BaseHTTPMiddleware`, is what makes that true.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except (
            Exception
        ) as exc:  # broad: must catch anything raised to scrub before re-raising
            scrub_registered_credentials_from_exception(exc)
            raise

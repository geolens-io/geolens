"""Scrub registered credential secrets from an unhandled exception, while
it can still be read from -- before it crosses a middleware task boundary.

fix(#1770 round 44 P2). `register_credential_secret` (`core/service_tokens.py`)
records the exact header line a request's credential composed into a
`ContextVar`, so `redact_exception_text`/the structlog `_scrub_text`
processor can later exact-scrub it out of anything that echoes it back. That
works for any reader in the SAME async task the handler ran in -- which an
UNHANDLED exception's readers are not.

Measured directly (see `test_credential_scrub_middleware.py`): Starlette's
`BaseHTTPMiddleware.dispatch` runs `call_next` -- the rest of the middleware
stack, the router, and the route handler -- in a SEPARATELY SPAWNED task.
`ContextVar.set()` inside that task never propagates back to the parent, so
`RequestLoggingMiddleware`'s own broad exception-logging clause -- see
`api/middleware/logging.py` -- reads the registry as empty. So does an
`@app.exception_handler(Exception)`,
for a different reason: Starlette dispatches a bare `Exception` handler
through `ServerErrorMiddleware`, which wraps EVERY user middleware -- an even
more distant task than `RequestLoggingMiddleware`'s own.

This module is a plain ASGI callable, not a `BaseHTTPMiddleware` subclass, so
it spawns no task of its own: `await self.app(...)` runs in whatever task is
already current. Registered as the INNERMOST middleware -- `main.py` adds it
BEFORE anything else, and `add_middleware` prepends, so the first call ends
up closest to the router (see that file's own ordering comment) -- it shares
the route handler's exact task, and can read the registry the handler
populated. It mutates the exception's `args`/chain IN PLACE
(`scrub_registered_credentials_from_exception`), so the SAME object,
unwound normally up through every outer, task-isolated context afterward,
already carries the scrubbed text by the time anything else reads it.
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
        except Exception as exc:  # broad: must catch whatever the app raises, of any type, to scrub it before re-raising unchanged
            scrub_registered_credentials_from_exception(exc)
            raise

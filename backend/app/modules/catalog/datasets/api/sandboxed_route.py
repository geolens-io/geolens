"""The route class for endpoints that serve uploaded files from the API origin."""

from __future__ import annotations

from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message, Receive, Scope, Send

# Uploaded bytes served from the API origin as HTML, SVG or script would run
# there, so nothing a browser renders gets through.
SANDBOX_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Vary": "Authorization, X-Api-Key",
}


class SandboxedRoute(APIRoute):
    """Puts the sandbox headers on every answer the route gives, errors included."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def sandboxed(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(SANDBOX_HEADERS)
                headers.setdefault("Cache-Control", "private, no-store")
            await send(message)

        try:
            await super().handle(scope, receive, sandboxed)
        except StarletteHTTPException as exc:
            # A refused method is raised before the route sends anything itself.
            exc.headers = {
                **(exc.headers or {}),
                **SANDBOX_HEADERS,
                "Cache-Control": "private, no-store",
            }
            raise

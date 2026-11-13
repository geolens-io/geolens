"""The desktop entry: the OGC API served again under ``/desktop`` to signed-in callers.

ArcGIS Pro sends its saved login only after a Basic challenge, and after a
restart it asks the address it stored, without a login, before anything
else. Under the entry every request without a working credential is
challenged, and every link to a path the entry serves stays under it.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.public_urls import (
    DESKTOP_ENTRY_PATH,
    desktop_entry_serves,
    is_desktop_entry,
    mark_desktop_entry,
)
from app.modules.auth.dependencies import (
    BASIC_CHALLENGE,
    get_optional_user_no_security_schema,
)

_OPENAPI_PATH = "/openapi.json"
_METHODS = ("GET", "HEAD")


async def _refusal(request: Request) -> JSONResponse | None:
    """The 401 for a caller without a working credential, or None for a signed-in one.

    A caller that sent no credential is challenged for Basic. A credential that
    does not resolve is refused as ``get_optional_user`` refuses it.
    """
    from app.core.db import async_session

    try:
        async with async_session() as db:
            user = await get_optional_user_no_security_schema(request, db)
    except HTTPException as exc:
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers={**(exc.headers or {}), "Cache-Control": "no-store"},
        )
    if user is not None:
        return None
    return JSONResponse(
        {"detail": "Not authenticated"},
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": BASIC_CHALLENGE, "Cache-Control": "no-store"},
    )


class DesktopEntryRewriteMiddleware:
    """Hand a request under the entry to the API route it names.

    Mounted outside the rate limiter, which finds a request's limits by its
    route. The scope is copied, so outer layers keep the path the caller sent.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        root_path = scope.get("root_path", "").rstrip("/")
        root = root_path if root_path and path.startswith(root_path + "/") else ""
        route_path = path[len(root) :]
        if route_path != DESKTOP_ENTRY_PATH and not route_path.startswith(
            DESKTOP_ENTRY_PATH + "/"
        ):
            await self.app(scope, receive, send)
            return
        tail = route_path[len(DESKTOP_ENTRY_PATH) :] or "/"
        if not desktop_entry_serves(tail):
            await self.app(scope, receive, send)
            return
        if scope["method"] not in _METHODS:
            response = JSONResponse(
                {"detail": "Method Not Allowed"},
                status_code=405,
                headers={"Allow": ", ".join(_METHODS)},
            )
            await response(scope, receive, send)
            return
        scope = dict(scope)
        if tail != _OPENAPI_PATH:
            scope["path"] = root + tail
            raw_path = scope.get("raw_path")
            if raw_path is not None:
                scope["raw_path"] = raw_path.replace(
                    DESKTOP_ENTRY_PATH.encode(), b"", 1
                )
        mark_desktop_entry(scope)
        await self.app(scope, receive, send)


class DesktopEntryGateMiddleware:
    """Refuse a request under the entry until its credential resolves.

    Mounted inside the tenant and rate-limit layers, since resolving a
    credential reads the database.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_desktop_entry(scope):
            refusal = await _refusal(Request(scope, receive=receive))
            if refusal is not None:
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)


desktop_router = APIRouter()


# The gate has resolved the caller already; resolving here too keeps the route
# refusing a dead credential on its own, as every key-reading route does.
@desktop_router.api_route(
    DESKTOP_ENTRY_PATH + _OPENAPI_PATH,
    methods=list(_METHODS),
    include_in_schema=False,
    dependencies=[Depends(get_optional_user_no_security_schema)],
)
async def desktop_openapi(request: Request) -> JSONResponse:
    """The OpenAPI document of the routes the entry serves, with the entry as server."""
    schema = request.app.openapi()
    return JSONResponse(
        {
            **schema,
            "servers": [
                {**server, "url": server["url"].rstrip("/") + DESKTOP_ENTRY_PATH}
                for server in schema.get("servers", [])
            ],
            "paths": {
                path: item
                for path, item in schema.get("paths", {}).items()
                if desktop_entry_serves(path)
            },
        },
        headers={"Cache-Control": "no-store"},
    )

"""The desktop entry: the OGC API served again under ``/desktop`` to signed-in callers.

ArcGIS Pro sends its saved login only after a Basic challenge, and after a
restart it asks the address it stored, without a login, before anything
else. Under the entry every request without a working credential is
challenged, and every link to a path the entry serves stays under it.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.dependencies import get_db
from app.core.public_urls import (
    DESKTOP_ENTRY_PATH,
    get_public_api_url,
    desktop_entry_serves,
    is_desktop_entry,
    mark_desktop_entry,
)
from app.modules.auth.dependencies import (
    BASIC_CHALLENGE,
    get_optional_user_no_security_schema,
)
from app.standards.ogc.errors import ProblemDetail
from app.standards.ogc.utils import build_url

_OPENAPI_PATH = "/openapi.json"
_METHODS = ("GET", "HEAD")
_CALLER_RESOLVED = "geolens.desktop_caller_resolved"
_NO_STORE = {"Cache-Control": "no-store"}


def _problem(status_code: int, title: str, detail: str, headers: dict) -> JSONResponse:
    return JSONResponse(
        ProblemDetail(title=title, status=status_code, detail=detail).model_dump(),
        status_code=status_code,
        media_type="application/problem+json",
        headers=headers,
    )


def _challenge() -> JSONResponse:
    return _problem(
        status.HTTP_401_UNAUTHORIZED,
        "Unauthorized",
        "Not authenticated",
        {"WWW-Authenticate": BASIC_CHALLENGE, **_NO_STORE},
    )


async def desktop_entry_gate(request: Request) -> None:
    """Refuse a request made through the desktop entry until its caller resolves.

    Runs as a route dependency, so the credential is judged against the route
    it reaches, as on ``/api``. A caller that sent no credential is challenged
    for Basic; one whose credential does not resolve is refused as
    ``get_optional_user`` refuses it. Elsewhere it does nothing.
    """
    if not is_desktop_entry(request.scope):
        return
    from app.core.db import async_session

    try:
        async with async_session() as db:
            user = await get_optional_user_no_security_schema(request, db)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **_NO_STORE}
        raise
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": BASIC_CHALLENGE, **_NO_STORE},
        )
    request.scope.setdefault("state", {})[_CALLER_RESOLVED] = True


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
            response = _problem(
                status.HTTP_405_METHOD_NOT_ALLOWED,
                "Method Not Allowed",
                "Method Not Allowed",
                {"Allow": ", ".join(_METHODS)},
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
    """Refuse any answer under the entry that ``desktop_entry_gate`` did not pass.

    A route that serves the entry without the gate is answered with the
    challenge instead of its content, so a route added without it fails closed.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_desktop_entry(scope):
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        refused = False

        async def guarded_send(message: Message) -> None:
            nonlocal refused
            if refused:
                return
            if (
                message["type"] == "http.response.start"
                and message["status"] < 400
                and not state.get(_CALLER_RESOLVED)
            ):
                refused = True
                await _challenge()(scope, receive, send)
                return
            await send(message)

        await self.app(scope, receive, guarded_send)


desktop_router = APIRouter(dependencies=[Depends(desktop_entry_gate)])


_CREDENTIALS = [
    {"HTTPBasic": []},
    {"OAuth2PasswordBearer": []},
    {"ApiKeyHeader": []},
    {"ApiKeyQuery": []},
]
_BASIC_SCHEME = {
    "type": "http",
    "scheme": "basic",
    "description": "Any username, with a GeoLens API key as the password. Reads only.",
}
_UNAUTHORIZED = {
    "description": "No working credential; a request without one is challenged for Basic",
    "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}},
    "content": {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
        }
    },
}


_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def _entry_path_item(item: dict) -> dict:
    """A path item as the entry serves it: reads only, each requiring a credential."""
    return {
        key: (
            {
                **value,
                "security": _CREDENTIALS,
                "responses": {**value.get("responses", {}), "401": _UNAUTHORIZED},
            }
            if key in ("get", "head")
            else value
        )
        for key, value in item.items()
        if key in ("get", "head") or key not in _HTTP_METHODS
    }


# Declared so the route's dependencies show the key it reads, which the
# CORS header-key lane relies on.
@desktop_router.api_route(
    DESKTOP_ENTRY_PATH + _OPENAPI_PATH,
    methods=list(_METHODS),
    include_in_schema=False,
    dependencies=[Depends(get_optional_user_no_security_schema)],
)
async def desktop_openapi(
    request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    """The OpenAPI document of the routes the entry serves, with the entry as server."""
    schema = request.app.openapi()
    entry_url = build_url("/", base_url=await get_public_api_url(db, request=request))
    components = schema.get("components", {})
    return JSONResponse(
        {
            **schema,
            "servers": [{"url": entry_url.rstrip("/")}],
            "paths": {
                path: _entry_path_item(item)
                for path, item in schema.get("paths", {}).items()
                if desktop_entry_serves(path)
            },
            "components": {
                **components,
                "securitySchemes": {
                    **components.get("securitySchemes", {}),
                    "HTTPBasic": _BASIC_SCHEME,
                },
            },
        },
        headers={"Cache-Control": "no-store"},
    )

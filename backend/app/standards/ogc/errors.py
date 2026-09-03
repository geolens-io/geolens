"""RFC 7807 Problem Details error responses for the GeoLens API."""

import json
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging_config import safe_access_log_path
from app.core.url_redaction import redact_query_credentials
from app.standards.ogc.utils import standards_api_path

logger = structlog.stdlib.get_logger(__name__)


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | dict[str, Any] | list[Any]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "about:blank",
                    "title": "Not Found",
                    "status": 404,
                    "detail": "Dataset not found",
                }
            ]
        }
    )


# Reusable OpenAPI `responses` blocks for 4xx/5xx error documentation.
# Import these in routers and merge into per-endpoint `responses=` dicts.
PROBLEM_RESPONSE = {
    "content": {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
        }
    },
}

RATE_LIMIT_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Too many requests — retry after the advertised interval",
    "headers": {
        "Retry-After": {
            "description": "Seconds until the request may be retried",
            "schema": {"type": "integer", "minimum": 0},
        }
    },
}

INTERNAL_SERVER_ERROR_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Internal server error",
}

DATABASE_UNAVAILABLE_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Service unavailable — the database could not serve the request",
}

BAD_REQUEST_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Bad request — invalid query parameters or payload",
}

UNRESOLVABLE_CREDENTIAL_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": (
        "Unauthenticated — a credential was supplied and could not be resolved "
        "(expired, revoked, or malformed). Sending no credential at all is not "
        "an error on these operations; they answer anonymously with the public "
        "subset. Neither is sending an unresolvable credential alongside a "
        "capability that authorizes the request on its own — a valid "
        "X-Embed-Token or a valid signed tile template (sig, exp, scope). Those "
        "are served and the unrelated credential is ignored."
    ),
}

FORBIDDEN_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Forbidden — caller lacks access to this resource",
}

NOT_FOUND_RESPONSE = {**PROBLEM_RESPONSE, "description": "Not found"}

CONFLICT_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Conflict — resource state prevents the operation",
}

PRECONDITION_FAILED_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": (
        "Precondition failed — the caller's If-Match no longer matches the "
        "current representation"
    ),
}

GONE_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Gone — the resource existed but is no longer available",
}

PAYLOAD_TOO_LARGE_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Payload too large",
}

BAD_GATEWAY_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Bad gateway — an upstream provider failed",
}

SERVICE_UNAVAILABLE_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Service unavailable — required publication metadata is missing",
}

# fix(#1550 review P3): a 503 from a queue dispatch failure is a different
# condition from the publication-metadata one above, and the description ships
# to clients in the committed OpenAPI document and both generated SDKs. Reusing
# the constant told every SDK consumer the wrong reason for the failure.
QUEUE_UNAVAILABLE_RESPONSE = {
    **PROBLEM_RESPONSE,
    "description": "Service unavailable — the background job queue could not be reached",
}

ERROR_RESPONSES_AUTH = {
    400: BAD_REQUEST_RESPONSE,
    401: {
        **PROBLEM_RESPONSE,
        "description": "Unauthorized — missing or invalid credentials",
    },
    403: FORBIDDEN_RESPONSE,
    404: NOT_FOUND_RESPONSE,
    422: {**PROBLEM_RESPONSE, "description": "Validation error"},
    500: INTERNAL_SERVER_ERROR_RESPONSE,
}

ERROR_RESPONSES_PUBLIC = {
    400: BAD_REQUEST_RESPONSE,
    404: NOT_FOUND_RESPONSE,
    422: {**PROBLEM_RESPONSE, "description": "Validation error"},
    500: INTERNAL_SERVER_ERROR_RESPONSE,
}

ERROR_RESPONSES_WRITE = {
    400: {**PROBLEM_RESPONSE, "description": "Bad request — invalid payload"},
    401: {
        **PROBLEM_RESPONSE,
        "description": "Unauthorized — missing or invalid credentials",
    },
    403: {**PROBLEM_RESPONSE, "description": "Forbidden — caller lacks write access"},
    404: NOT_FOUND_RESPONSE,
    409: CONFLICT_RESPONSE,
    422: {**PROBLEM_RESPONSE, "description": "Validation error"},
    500: INTERNAL_SERVER_ERROR_RESPONSE,
}


def _serialize_detail(detail: object) -> str:
    """Serialize non-JSON HTTPException detail to a safe fallback string.

    The exception handler preserves dict/list details directly. Plain strings
    pass through here unchanged; any other object is JSON-encoded with a
    string fallback so the response remains serializable.
    """
    if isinstance(detail, str):
        return detail
    return json.dumps(detail, default=str)


def _status_title(status_code: int) -> str:
    titles = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        410: "Gone",
        413: "Payload Too Large",
        422: "Validation Error",
        429: "Too Many Requests",
        502: "Bad Gateway",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }
    return titles.get(status_code, "Error")


def _is_standards_path(request: Request) -> bool:
    """Return whether request validation is governed by an OGC/STAC profile.

    FastAPI normally reports query/path/body validation as 422.  OGC API
    Common and the standards implemented on top of it require malformed
    request parameters to be reported as 400 instead.  Keep the conversion
    scoped to the machine-client standards surface so native application APIs
    retain their established 422 contract.
    """

    return (
        standards_api_path(
            request.scope.get("path", request.url.path),
            root_path=request.scope.get("root_path", ""),
        )
        is not None
    )


def _allow_header_with_head(headers: dict[str, str] | None) -> dict[str, str] | None:
    """Add HEAD to a 405's ``Allow`` header when GET is already listed.

    fix(#1470): ``_register_standards_head_routes`` serves HEAD beside every
    standards GET, but as a SEPARATE route. It has to be separate — FastAPI
    derives a route's operation id from its name and path rather than its
    method, so one route carrying ``{GET, HEAD}`` emits duplicate operation
    ids and 48 phantom operations into ``openapi.json`` (measured, not
    assumed). The cost of that separation is that starlette builds a 405's
    ``Allow`` from the FIRST partial match, which is the GET-only canonical
    route, so the header understated what the surface answers.

    Restated here rather than in the route table because this is where the
    standards error contract already lives, and because the rule is an
    invariant of that surface rather than of any one route: HEAD is
    registered for every standards GET, so GET being allowed means HEAD is
    too. Keyed off GET for exactly that reason — a standards route that
    allows only POST (``/stac/search``) gains nothing here.
    """
    if not headers:
        return headers
    allow_key = next((key for key in headers if key.lower() == "allow"), None)
    if allow_key is None:
        return headers
    methods = [
        value.strip() for value in headers[allow_key].split(",") if value.strip()
    ]
    if "GET" not in methods or "HEAD" in methods:
        return headers
    updated = dict(headers)
    updated[allow_key] = ", ".join([*methods, "HEAD"])
    return updated


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        # Preserve structured details for callers that inspect their fields;
        # serialize only non-JSON detail objects to the safe string fallback.
        detail = (
            exc.detail
            if isinstance(exc.detail, (dict, list))
            else _serialize_detail(exc.detail)
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=ProblemDetail(
                title=_status_title(exc.status_code),
                status=exc.status_code,
                detail=detail,
            ).model_dump(),
            media_type="application/problem+json",
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def framework_http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        """Correct the ``Allow`` header on a framework-raised standards 405.

        Registered on starlette's base class specifically: the handler above
        is bound to fastapi's SUBCLASS, which routers raise explicitly, while
        the 405 comes from ``fastapi.routing`` (which imports HTTPException
        from ``starlette.exceptions``) and so never reached it. Handler
        lookup walks the MRO and prefers the most specific registration, so
        the problem-detail contract for router-raised errors is untouched.

        Everything else is delegated to fastapi's own default, unchanged --
        this deliberately does NOT convert framework 405/404 bodies to
        problem+json, which would be a separate contract change.
        """
        if exc.status_code == 405 and _is_standards_path(request):
            exc.headers = _allow_header_with_head(exc.headers)
        return await default_http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        status_code = 400 if _is_standards_path(request) else 422
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        return JSONResponse(
            status_code=status_code,
            content=ProblemDetail(
                title=_status_title(status_code),
                status=status_code,
                detail=detail,
            ).model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Collect diagnostic context for the log only (do NOT leak any of this
        # into the response body — production responses stay generic).
        user_id: str | None = None
        try:
            user = getattr(request.state, "user", None)
            if user is not None:
                user_id = str(getattr(user, "id", None))
        except Exception:  # broad: diagnostic context only — user_id stays None on any attribute access failure
            pass

        # Prefer the middleware-generated UUID stashed on request.state — this
        # is the same ID bound to structlog contextvars and emitted by the
        # access log, so client errors correlate cleanly with server logs
        # (RESILIENCE-9). Fall back to client-supplied header for legacy compat.
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("x-request-id")
            or request.headers.get("x-correlation-id")
        )
        client_ip = None
        try:
            if request.client is not None:
                client_ip = request.client.host
        except Exception:  # broad: diagnostic context only — client_ip stays None on any attribute access failure
            pass

        logger.exception(
            "Unhandled error",
            # fix(#1778): same capability-in-the-path rule the access log has
            # followed since #821 -- a 500 on /api/maps/shared/{token} used to
            # write the token verbatim.
            path=safe_access_log_path(request.url.path),
            method=request.method,
            query=redact_query_credentials(str(request.url.query))
            if request.url.query
            else None,
            user_id=user_id,
            request_id=request_id,
            client_ip=client_ip,
            exc_type=type(exc).__name__,
        )
        # Echo the request ID on the error response so clients can include
        # it in support tickets (RESILIENCE-5).
        headers = {"X-Request-ID": request_id} if request_id else {}
        return JSONResponse(
            status_code=500,
            content=ProblemDetail(
                title="Internal Server Error",
                status=500,
                detail="Internal server error",
            ).model_dump(),
            media_type="application/problem+json",
            headers=headers,
        )

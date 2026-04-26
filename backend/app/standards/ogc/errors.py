"""RFC 7807 Problem Details error responses for the GeoLens API."""

import json

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = structlog.stdlib.get_logger(__name__)


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str


# Reusable OpenAPI `responses` blocks for 4xx/5xx error documentation.
# Import these in routers and merge into per-endpoint `responses=` dicts.
PROBLEM_RESPONSE = {
    "model": ProblemDetail,
    "content": {"application/problem+json": {}},
}

ERROR_RESPONSES_AUTH = {
    400: {
        **PROBLEM_RESPONSE,
        "description": "Bad request — invalid query parameters or payload",
    },
    401: {
        **PROBLEM_RESPONSE,
        "description": "Unauthorized — missing or invalid credentials",
    },
    403: {
        **PROBLEM_RESPONSE,
        "description": "Forbidden — caller lacks access to this resource",
    },
    404: {**PROBLEM_RESPONSE, "description": "Not found"},
    422: {**PROBLEM_RESPONSE, "description": "Validation error"},
    500: {**PROBLEM_RESPONSE, "description": "Internal server error"},
}

ERROR_RESPONSES_PUBLIC = {
    400: {
        **PROBLEM_RESPONSE,
        "description": "Bad request — invalid query parameters or payload",
    },
    404: {**PROBLEM_RESPONSE, "description": "Not found"},
    422: {**PROBLEM_RESPONSE, "description": "Validation error"},
    500: {**PROBLEM_RESPONSE, "description": "Internal server error"},
}

ERROR_RESPONSES_WRITE = {
    400: {**PROBLEM_RESPONSE, "description": "Bad request — invalid payload"},
    401: {
        **PROBLEM_RESPONSE,
        "description": "Unauthorized — missing or invalid credentials",
    },
    403: {**PROBLEM_RESPONSE, "description": "Forbidden — caller lacks write access"},
    404: {**PROBLEM_RESPONSE, "description": "Not found"},
    409: {
        **PROBLEM_RESPONSE,
        "description": "Conflict — resource state prevents the operation",
    },
    422: {**PROBLEM_RESPONSE, "description": "Validation error"},
    500: {**PROBLEM_RESPONSE, "description": "Internal server error"},
}


def _serialize_detail(detail: object) -> str:
    """Serialize HTTPException detail to a string.

    Dicts and lists are JSON-encoded so the frontend can reliably parse
    structured error payloads.  Plain strings pass through unchanged.
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
        422: "Validation Error",
        429: "Too Many Requests",
        500: "Internal Server Error",
    }
    return titles.get(status_code, "Error")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        # When the detail is a structured object (dict/list), preserve it as-is
        # so that callers can reliably access its fields (e.g. 409 duplicate_source).
        # Plain strings go through the standard ProblemDetail serialization path.
        if isinstance(exc.detail, (dict, list)):
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "type": "about:blank",
                    "title": _status_title(exc.status_code),
                    "status": exc.status_code,
                    "detail": exc.detail,
                },
                media_type="application/problem+json",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=ProblemDetail(
                title=_status_title(exc.status_code),
                status=exc.status_code,
                detail=_serialize_detail(exc.detail),
            ).model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content=ProblemDetail(
                title="Validation Error",
                status=422,
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
        except Exception:
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
        except Exception:
            pass

        logger.exception(
            "Unhandled error",
            path=request.url.path,
            method=request.method,
            query=str(request.url.query) if request.url.query else None,
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

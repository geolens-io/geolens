"""The security headers, request logging and tenant context layers are plain ASGI.

``BaseHTTPMiddleware`` buffered nothing but ran the rest of the stack in a
task of its own and relayed every message through a memory stream. As plain
ASGI callables these layers see the raw message flow instead, so these tests
pin what they must still do on the responses that flow differs on most:
streamed bodies, conditional 304s, handled errors and unhandled exceptions,
before and after the response has started.
"""

from __future__ import annotations

import contextvars
import uuid

import pytest
import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

import app.api.middleware.logging as logging_mw
import app.api.middleware.tenant_context as tenant_mw
from app.api.middleware.security import SecurityHeadersMiddleware
from app.core.db.tenant_session import current_tenant_var

pytestmark = pytest.mark.anyio

_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "content-security-policy": "frame-ancestors 'self'",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


class _Boom(RuntimeError):
    pass


def _probe_app(middleware, seen: list | None = None) -> FastAPI:
    """Routes covering each response shape, behind *middleware*."""
    app = FastAPI()

    @app.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        async def chunks():
            for part in (b"one,", b"two,", b"three"):
                if seen is not None:
                    seen.append(current_tenant_var.get())
                yield part

        return StreamingResponse(chunks(), media_type="text/plain")

    @app.get("/stream-then-fail")
    async def stream_then_fail() -> StreamingResponse:
        async def chunks():
            yield b"partial"
            raise _Boom("failed mid-stream")

        return StreamingResponse(chunks(), media_type="text/plain")

    @app.get("/not-modified")
    async def not_modified() -> Response:
        return Response(status_code=304, headers={"ETag": '"v1"'})

    @app.get("/handled-error")
    async def handled_error() -> None:
        raise HTTPException(status_code=404, detail="nope")

    @app.get("/unhandled")
    async def unhandled() -> None:
        if seen is not None:
            seen.append(current_tenant_var.get())
        raise _Boom("unhandled")

    app.add_middleware(middleware)
    return app


def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


_handler_mark: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "handler_mark", default=None
)


@pytest.mark.parametrize(
    "middleware",
    [
        SecurityHeadersMiddleware,
        logging_mw.RequestLoggingMiddleware,
        tenant_mw.TenantContextMiddleware,
    ],
)
async def test_the_handler_runs_in_the_request_task(middleware):
    """No layer spawns a task: what the handler sets, the caller can read.

    ``BaseHTTPMiddleware`` ran the downstream app in a task of its own, so a
    context variable set by the handler never reached the layers outside it.
    """
    app = FastAPI()

    @app.get("/mark")
    async def mark() -> dict:
        _handler_mark.set("set-by-handler")
        return {}

    app.add_middleware(middleware)
    seen_outside: list[str | None] = []

    async def outer(scope, receive, send):
        _handler_mark.set(None)
        await app(scope, receive, send)
        seen_outside.append(_handler_mark.get())

    async with AsyncClient(
        transport=ASGITransport(app=outer), base_url="http://test"
    ) as http:
        assert (await http.get("/mark")).status_code == 200

    assert seen_outside == ["set-by-handler"]


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "status"),
    [("/stream", 200), ("/not-modified", 304), ("/handled-error", 404)],
)
async def test_security_headers_on_streamed_conditional_and_error_responses(
    path: str, status: int
):
    async with _client(_probe_app(SecurityHeadersMiddleware)) as http:
        resp = await http.get(path, headers={"X-Forwarded-Proto": "https"})

    assert resp.status_code == status
    for name, value in _SECURITY_HEADERS.items():
        assert resp.headers[name] == value, name
    assert resp.headers["strict-transport-security"].startswith("max-age=")
    if path == "/stream":
        assert resp.content == b"one,two,three"


async def test_security_headers_set_once_on_a_response_that_carries_them():
    """Assignment replaces a header; it never appends a second copy."""
    app = FastAPI()

    @app.get("/dup")
    async def dup() -> Response:
        return Response(
            headers={"X-Content-Type-Options": "sniff", "Permissions-Policy": "x=()"}
        )

    app.add_middleware(SecurityHeadersMiddleware)
    async with _client(app) as http:
        resp = await http.get("/dup")

    assert resp.headers.get_list("x-content-type-options") == ["nosniff"]
    assert resp.headers.get_list("permissions-policy") == [
        _SECURITY_HEADERS["permissions-policy"]
    ]


async def test_an_unhandled_exception_still_propagates_through_security_headers():
    app = _probe_app(SecurityHeadersMiddleware)

    with pytest.raises(_Boom):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            await http.get("/unhandled")


# ---------------------------------------------------------------------------
# Request logging
# ---------------------------------------------------------------------------


@pytest.fixture
def access_events(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    events: list[dict] = []

    class _CaptureLogger:
        def info(self, event: str, **fields) -> None:
            events.append({"event": event, **fields})

    monkeypatch.setattr(logging_mw, "access_logger", _CaptureLogger())
    return events


async def test_a_streamed_response_is_logged_once_with_its_request_id(access_events):
    async with _client(_probe_app(logging_mw.RequestLoggingMiddleware)) as http:
        resp = await http.get("/stream")

    assert resp.content == b"one,two,three"
    assert [e["status_code"] for e in access_events] == [200]
    entry = access_events[0]
    assert entry["event"] == "request_completed"
    assert entry["http_method"] == "GET"
    assert entry["path"] == "/stream"
    assert entry["request_id"] == resp.headers["x-request-id"]
    assert isinstance(entry["duration_ms"], float)
    uuid.UUID(entry["request_id"])


@pytest.mark.parametrize(
    ("path", "status"), [("/not-modified", 304), ("/handled-error", 404)]
)
async def test_conditional_and_handled_error_responses_log_their_status(
    access_events, path: str, status: int
):
    async with _client(_probe_app(logging_mw.RequestLoggingMiddleware)) as http:
        resp = await http.get(path)

    assert resp.status_code == status
    assert [e["status_code"] for e in access_events] == [status]
    assert resp.headers["x-request-id"] == access_events[0]["request_id"]


async def test_an_unhandled_exception_logs_500_and_propagates(access_events):
    app = _probe_app(logging_mw.RequestLoggingMiddleware)

    with structlog.testing.capture_logs() as captured:
        async with _client(app) as http:
            resp = await http.get("/unhandled")

    assert resp.status_code == 500, "ServerErrorMiddleware answers outside this layer"
    assert [e["status_code"] for e in access_events] == [500]
    errors = [e for e in captured if e["event"] == "Unhandled exception"]
    assert len(errors) == 1
    assert errors[0]["log_level"] == "error"


async def test_a_failure_after_the_response_started_keeps_the_logged_status(
    access_events,
):
    """The access line is written at response start, as before the conversion."""
    app = _probe_app(logging_mw.RequestLoggingMiddleware)

    with structlog.testing.capture_logs() as captured:
        async with _client(app) as http:
            resp = await http.get("/stream-then-fail")

    assert resp.status_code == 200
    assert [e["status_code"] for e in access_events] == [200]
    assert not [e for e in captured if e["event"] == "Unhandled exception"]


async def test_each_request_starts_with_fresh_log_context(access_events):
    """Context bound by one request never reaches the next one's log lines."""
    app = FastAPI()
    bound: list[dict] = []

    @app.get("/bind")
    async def bind() -> dict:
        bound.append(structlog.contextvars.get_contextvars())
        structlog.contextvars.bind_contextvars(leaked="from-the-previous-request")
        return {}

    app.add_middleware(logging_mw.RequestLoggingMiddleware)
    async with _client(app) as http:
        await http.get("/bind")
        await http.get("/bind")

    assert "leaked" not in bound[1]
    assert bound[1]["request_id"] == access_events[1]["request_id"]


# ---------------------------------------------------------------------------
# Tenant context
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_tenant(monkeypatch: pytest.MonkeyPatch) -> str:
    tenant_id = str(uuid.uuid4())

    async def _resolve(signal):
        return tenant_id if signal == "acme" else None

    monkeypatch.setattr(tenant_mw, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_mw.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_mw, "_resolve_tenant_uuid", _resolve)
    return tenant_id


async def _tenant_get(app: FastAPI, path: str):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://acme.geolens.app",
    ) as http:
        return await http.get(path)


async def test_the_tenant_stays_set_while_a_streamed_body_is_produced(multi_tenant):
    seen: list = []
    resp = await _tenant_get(
        _probe_app(tenant_mw.TenantContextMiddleware, seen), "/stream"
    )

    assert resp.content == b"one,two,three"
    assert seen == [multi_tenant] * 3
    assert current_tenant_var.get() is None, "reset once the body was sent"


async def test_the_tenant_is_reset_when_the_handler_raises(multi_tenant):
    seen: list = []
    resp = await _tenant_get(
        _probe_app(tenant_mw.TenantContextMiddleware, seen), "/unhandled"
    )

    assert resp.status_code == 500
    assert seen == [multi_tenant]
    assert current_tenant_var.get() is None


async def test_the_tenant_is_reset_when_a_streamed_body_fails(multi_tenant):
    resp = await _tenant_get(
        _probe_app(tenant_mw.TenantContextMiddleware), "/stream-then-fail"
    )

    assert resp.status_code == 200, "the failure came after the response started"
    assert current_tenant_var.get() is None


async def test_an_unresolved_tenant_host_is_refused_before_the_app(multi_tenant):
    seen: list = []
    app = _probe_app(tenant_mw.TenantContextMiddleware, seen)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://unknown.geolens.app"
    ) as http:
        resp = await http.get("/stream")

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Tenant host could not be resolved"}
    assert seen == []
    assert current_tenant_var.get() is None

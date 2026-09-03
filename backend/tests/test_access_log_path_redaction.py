"""Access-log paths must not persist bearer capability values."""

import pytest

import app.api.middleware.logging as logging_mw
from app.api.middleware.logging import safe_access_log_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/maps/shared/SYNTHETIC_SENTINEL", "/maps/shared/[REDACTED]"),
        (
            "/maps/shared/SYNTHETIC_SENTINEL/card",
            "/maps/shared/[REDACTED]/card",
        ),
        (
            "/api/maps/shared/SYNTHETIC_SENTINEL/card",
            "/api/maps/shared/[REDACTED]/card",
        ),
        # fix(#1778): the embed shell, which frontend/nginx.conf has always
        # redacted at the edge and the Python regex did not.
        ("/m/SYNTHETIC_SENTINEL", "/m/[REDACTED]"),
        ("/m/SYNTHETIC_SENTINEL/anything", "/m/[REDACTED]/anything"),
        ("/maps/ordinary-map-id", "/maps/ordinary-map-id"),
        ("/maps/shared", "/maps/shared"),
        ("/m/", "/m/"),
    ],
)
def test_safe_access_log_path(path: str, expected: str) -> None:
    logged_path = safe_access_log_path(path)

    assert logged_path == expected
    assert "SYNTHETIC_SENTINEL" not in logged_path


@pytest.mark.anyio
async def test_access_log_never_contains_query_credentials(monkeypatch) -> None:
    """fix(#821): the deprecated ?api_key= lane puts the credential in the URL.

    Our own access log line must never include the query string — the
    middleware logs request.url.path only. This test pins that contract so a
    future refactor that logs the full URL fails loudly.
    """
    from httpx import ASGITransport, AsyncClient
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    events: list[tuple[str, dict]] = []

    class _CaptureLogger:
        def info(self, event: str, **kwargs) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(logging_mw, "access_logger", _CaptureLogger())

    async def ok(_request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/things", ok)])
    app.add_middleware(logging_mw.RequestLoggingMiddleware)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        resp = await http.get("/things?api_key=SYNTHETIC_KEY_SENTINEL&x=1")

    assert resp.status_code == 200
    assert events, "middleware did not emit an access log event"
    logged = repr(events)
    assert "SYNTHETIC_KEY_SENTINEL" not in logged
    assert "api_key" not in logged
    assert events[0][1]["path"] == "/things"


def test_the_two_5xx_handlers_redact_the_path_they_log() -> None:
    """fix(#1778): a 500 or a 503 must not publish a share capability.

    Both handlers logged ``request.url.path`` raw, so the access-log line for
    a failing ``/api/maps/shared/{token}`` request was redacted while the
    error line beside it carried the token in full. Asserted on the source so
    the check does not depend on provoking a DB failure inside a request.
    """
    import inspect

    from app.api.main import _database_error_handler
    from app.standards.ogc.errors import register_error_handlers

    for fn in (_database_error_handler, register_error_handlers):
        src = inspect.getsource(fn)
        assert "path=request.url.path," not in src, (
            f"{fn.__qualname__} logs an unredacted request path"
        )
        assert "safe_access_log_path(request.url.path)" in src, (
            f"{fn.__qualname__} must route its logged path through the redactor"
        )

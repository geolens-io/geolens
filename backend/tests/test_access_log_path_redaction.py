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
        ("/maps/ordinary-map-id", "/maps/ordinary-map-id"),
        ("/maps/shared", "/maps/shared"),
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

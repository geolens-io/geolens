"""fix(#1778): the GLOBAL default rate limit must answer with the app envelope.

slowapi enforces the default limit inside `SlowAPIMiddleware.dispatch`, a
synchronous BaseHTTPMiddleware. Its `sync_check_limits` refuses to run a
coroutine exception handler there and silently substitutes slowapi's own,
which returns a bare `{"error": ...}` in application/json with no Retry-After
(the Limiter is not built with `headers_enabled`). Routes carrying an explicit
`@limiter.limit` decorator are exempted from the middleware and take the
exception-handler path instead, so every existing test of the 429 contract
drives a decorated route and passes. This one drives an undecorated one.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


def _app_with(handler) -> FastAPI:
    """A one-route app whose only limit is the global default."""
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["1/minute"],
        key_style="endpoint",
    )
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/undecorated")
    async def undecorated() -> dict[str, bool]:  # pragma: no cover - trivial
        return {"ok": True}

    return app


async def _second_call(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        first = await http.get("/undecorated")
        assert first.status_code == 200, "first call should be under the limit"
        return await http.get("/undecorated")


@pytest.mark.anyio
async def test_global_limit_429_carries_retry_after_and_problem_detail():
    from app.api.main import _rate_limit_handler

    resp = await _second_call(_app_with(_rate_limit_handler))

    assert resp.status_code == 429
    assert "retry-after" in resp.headers, (
        f"global-limit 429 lost Retry-After; headers: {dict(resp.headers)}"
    )
    assert int(resp.headers["retry-after"]) > 0
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    for field in ("type", "title", "status", "detail"):
        assert field in body, f"ProblemDetail field {field!r} missing from {body}"
    assert body["status"] == 429


@pytest.mark.anyio
async def test_a_coroutine_handler_is_discarded_by_the_middleware():
    """The positive control: this is what the app used to send.

    Keeps the failure mode legible if slowapi ever changes -- if the
    substitution stops happening, this test fails and the fix above becomes
    unnecessary rather than wrong.
    """
    from app.api.main import _rate_limit_handler

    async def _async_handler(request, exc):
        return _rate_limit_handler(request, exc)

    resp = await _second_call(_app_with(_async_handler))

    assert resp.status_code == 429
    assert "retry-after" not in resp.headers
    assert resp.headers["content-type"].startswith("application/json")
    assert set(resp.json()) == {"error"}

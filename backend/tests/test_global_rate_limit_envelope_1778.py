"""fix(#1778): the GLOBAL default rate limit must answer with the app envelope.

The default limit is enforced by `GlobalRateLimitMiddleware`, before routing.
Routes carrying an explicit `@limiter.limit` decorator are exempted from it and
take the exception-handler path instead, so every test of the 429 contract that
drives a decorated route passes regardless of this layer. This one drives an
undecorated one. slowapi's own `SlowAPIMiddleware` used to sit here and
silently swapped a coroutine exception handler for slowapi's bare
`{"error": ...}` body with no Retry-After.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.middleware.rate_limit import GlobalRateLimitMiddleware
from app.platform.ratelimit import _FallbackAnnouncingLimiter


def _app_with(handler) -> FastAPI:
    """A one-route app whose only limit is the global default."""
    limiter = _FallbackAnnouncingLimiter(
        key_func=get_remote_address,
        default_limits=["1/minute"],
        key_style="endpoint",
    )
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, handler)
    app.add_middleware(GlobalRateLimitMiddleware)

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
async def test_a_coroutine_handler_is_awaited_not_replaced():
    """slowapi's middleware dropped a coroutine handler for its own bare body.

    This layer awaits it, so an async handler keeps the same contract.
    """
    from app.api.main import _rate_limit_handler

    async def _async_handler(request, exc):
        return _rate_limit_handler(request, exc)

    resp = await _second_call(_app_with(_async_handler))

    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 429

"""fix(#1770 round 44 P2, `api/middleware/logging.py:63` / `standards/ogc/
errors.py:320`).

`register_credential_secret` (`core/service_tokens.py`) records a request's
composed credential header line in a `ContextVar`, so `redact_exception_text`
and the structlog `_scrub_text` processor can exact-scrub it out of anything
that echoes it back. That only works for a reader in the SAME async task the
handler ran in.

Measured directly here (not assumed): Starlette's `BaseHTTPMiddleware.
dispatch` runs `call_next` -- the rest of the middleware stack, the router,
and the route handler -- in a separately spawned task. A `ContextVar.set()`
made inside that task never propagates back to the parent, so
`RequestLoggingMiddleware`'s own `except Exception: logger.exception(...)`
and an `@app.exception_handler(Exception)` (which Starlette actually
dispatches through `ServerErrorMiddleware`, outside every user middleware --
an even more distant task) both read the registry as empty, no matter what
the handler registered.

`CredentialScrubASGIMiddleware` (`api/middleware/credential_scrub.py`) is
what closes it: a plain ASGI callable, not a `BaseHTTPMiddleware`, registered
as the innermost middleware in `main.py`, so it shares the handler's exact
task and can scrub the exception's own `args` in place before it starts
propagating through any task-isolated context.
"""

import contextvars

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api.main import app as real_app
from app.api.middleware.credential_scrub import CredentialScrubASGIMiddleware
from app.core.service_tokens import (
    register_credential_secret,
    reset_registered_credential_secrets,
)

pytestmark = pytest.mark.anyio


def test_credential_scrub_middleware_is_registered_innermost() -> None:
    """`add_middleware` prepends, so the FIRST call ends up at the HIGHEST
    index of `app.user_middleware` -- closest to the router. Pinned the same
    way `test_phase_273_middleware_order.py` pins GZip vs SecurityHeaders."""
    classes = [mw.cls for mw in real_app.user_middleware]
    assert classes[-1] is CredentialScrubASGIMiddleware, classes


class _CapturingOuterMiddleware(BaseHTTPMiddleware):
    """Mirrors `RequestLoggingMiddleware`'s own shape closely enough for this
    pin: a `BaseHTTPMiddleware` whose `except` clause tries to read the
    registry after `call_next` raises."""

    captured: dict[str, str] = {}

    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            _CapturingOuterMiddleware.captured["middleware_except_str"] = str(exc)
            raise


_captured_from_exc_handler: dict[str, str] = {}


async def _exc_handler(request, exc):
    _captured_from_exc_handler["exc_handler_str"] = str(exc)
    return JSONResponse({"detail": "error"}, status_code=500)


async def _route_registers_and_raises(request):
    secret = "s3cret-credential-value"
    register_credential_secret(f"Authorization: Bearer {secret}")
    raise RuntimeError(f"upstream said: token {secret} was rejected")


def _build_app(*, with_scrub_middleware: bool) -> Starlette:
    middleware = []
    if with_scrub_middleware:
        # Innermost: added first in the `middleware=[...]` list ordering,
        # which (unlike `add_middleware`) applies in LIST order -- first
        # entry outermost. See `main.py`'s own comment on the opposite
        # convention for `add_middleware`.
        middleware = [
            Middleware(_CapturingOuterMiddleware),
            Middleware(CredentialScrubASGIMiddleware),
        ]
    else:
        middleware = [Middleware(_CapturingOuterMiddleware)]
    return Starlette(
        routes=[Route("/boom", _route_registers_and_raises)],
        middleware=middleware,
        exception_handlers={Exception: _exc_handler},
    )


async def test_a_registered_secret_is_scrubbed_from_every_reader() -> None:
    """With the middleware in place, the exception both the outer
    `BaseHTTPMiddleware` and the app-level exception handler see has the
    registered secret scrubbed, in both readers, despite neither sharing the
    handler's own task."""
    reset_registered_credential_secrets()
    _CapturingOuterMiddleware.captured.clear()
    _captured_from_exc_handler.clear()
    app = _build_app(with_scrub_middleware=True)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")

    assert resp.status_code == 500
    secret = "s3cret-credential-value"
    assert secret not in _CapturingOuterMiddleware.captured.get(
        "middleware_except_str", ""
    )
    assert secret not in _captured_from_exc_handler.get("exc_handler_str", "")
    reset_registered_credential_secrets()


async def test_without_the_middleware_the_secret_leaks_in_both_readers() -> None:
    """Positive control / counterfactual: remove `CredentialScrubASGIMiddleware`
    and the exact same secret leaks into both readers -- proving the pin
    above is not vacuous, and reproducing the bug this round closes."""
    reset_registered_credential_secrets()
    _CapturingOuterMiddleware.captured.clear()
    _captured_from_exc_handler.clear()
    app = _build_app(with_scrub_middleware=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")

    assert resp.status_code == 500
    secret = "s3cret-credential-value"
    assert secret in _CapturingOuterMiddleware.captured.get("middleware_except_str", "")
    assert secret in _captured_from_exc_handler.get("exc_handler_str", "")
    reset_registered_credential_secrets()


async def test_registering_across_the_task_boundary_reads_back_unset() -> None:
    """The premise, isolated from this fix: a plain ContextVar set inside a
    `BaseHTTPMiddleware`-wrapped handler is genuinely invisible to the
    middleware's own `except` clause. Not specific to the credential
    registry -- any ContextVar behaves this way under
    `BaseHTTPMiddleware.dispatch`."""
    var: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="UNSET")
    seen = {}

    class _Outer(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            try:
                return await call_next(request)
            except Exception:
                seen["value"] = var.get()
                raise

    async def _sets_and_raises(request):
        var.set("SET_BY_HANDLER")
        raise RuntimeError("boom")

    app = Starlette(
        routes=[Route("/x", _sets_and_raises)],
        middleware=[Middleware(_Outer)],
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/x")

    assert seen["value"] == "UNSET"

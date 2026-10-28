"""The global rate-limit middleware answers exactly as slowapi's did.

Each case builds one app twice: slowapi's ``Limiter`` behind its own
``SlowAPIMiddleware``, and the app's limiter behind
``GlobalRateLimitMiddleware`` with its async store swapped for limits' async
in-memory twin of the same strategy. The same request sequence must give the
same statuses, the same rate-limit headers and the same storage keys.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from limits.aio.storage import MemoryStorage as AsyncMemoryStorage
from limits.storage import MemoryStorage
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.wrappers import LimitGroup

from app.api.middleware.rate_limit import GlobalRateLimitMiddleware
from app.platform.ratelimit import _FallbackAnnouncingLimiter

pytestmark = pytest.mark.anyio

_TIME_HEADERS = {"x-ratelimit-reset", "retry-after", "x-custom-reset"}


def _app(limiter: Limiter, middleware, handler: Callable | None) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    if handler is not None:
        app.add_exception_handler(RateLimitExceeded, handler)
    app.add_middleware(middleware)

    @app.get("/plain")
    @app.post("/plain")
    async def plain() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/other")
    async def other() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @app.get("/retry-after")
    async def retry_after() -> Response:
        return Response(headers={"Retry-After": "120"})

    @app.get("/exempt")
    @limiter.exempt
    async def exempt(request: Request) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/decorated")
    @limiter.limit("3/minute")
    async def decorated(request: Request) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/dynamic")
    @limiter.limit(lambda: "3/minute")
    async def dynamic(request: Request) -> dict[str, bool]:
        return {"ok": True}

    return app


def _ours(**kwargs: Any) -> _FallbackAnnouncingLimiter:
    """The app's limiter on a stand-in shared store of the effective strategy."""
    limiter = _FallbackAnnouncingLimiter(
        storage_uri="redis://parity.invalid:6379/0", **kwargs
    )
    limiter._async_limiter = type(limiter._async_limiter)(AsyncMemoryStorage())
    limiter._storage = MemoryStorage()
    limiter._limiter = type(limiter._limiter)(limiter._storage)
    return limiter


def _keys(storage) -> set[str]:
    return set(getattr(storage, "storage", {})) | set(getattr(storage, "events", {}))


def _rate_limit_headers(resp) -> list[tuple[str, str]]:
    return [
        (name.lower(), value)
        for name, value in resp.headers.multi_items()
        if name.lower().startswith(("x-ratelimit", "x-custom")) or name == "retry-after"
    ]


def _as_epoch(name: str, value: str) -> float:
    if name == "retry-after" and not value.isdigit():
        return parsedate_to_datetime(value).timestamp()
    if name == "retry-after":
        return time.time() + int(value)
    return float(value)


def _assert_same_headers(expected, actual) -> None:
    """Equal, except that time-derived values may straddle one second."""
    assert [name for name, _ in actual] == [name for name, _ in expected]
    for (name, want), (_, got) in zip(expected, actual, strict=True):
        if name in _TIME_HEADERS:
            assert abs(_as_epoch(name, got) - _as_epoch(name, want)) <= 2, name
            assert got.isdigit() == want.isdigit(), (name, want, got)
        else:
            assert got == want, name


@pytest.fixture(autouse=True)
def _one_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Storage keys carry the minute window, so both limiters read one clock."""
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)


async def _drive(app: FastAPI, calls: list[tuple[str, str]]):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return [await http.request(method, path) for method, path in calls]


async def _compare(
    kwargs: dict[str, Any],
    calls: list[tuple[str, str]],
    *,
    handler: Callable | None = None,
    prepare: Callable[[Limiter, Limiter], None] | None = None,
    shared_store: bool = True,
) -> tuple[list[int], list[list[tuple[str, str]]]]:
    if handler is None:
        from app.api.main import _rate_limit_handler as handler
    if handler == "slowapi-default":
        handler = None
    reference = Limiter(**kwargs)
    ours = _ours(**kwargs) if shared_store else _FallbackAnnouncingLimiter(**kwargs)
    if prepare is not None:
        prepare(reference, ours)

    expected = await _drive(_app(reference, SlowAPIMiddleware, handler), calls)
    actual = await _drive(_app(ours, GlobalRateLimitMiddleware, handler), calls)

    assert [r.status_code for r in actual] == [r.status_code for r in expected]
    for want, got in zip(expected, actual, strict=True):
        _assert_same_headers(_rate_limit_headers(want), _rate_limit_headers(got))
    ours_keys = _keys(ours._storage)
    if ours._async_limiter is not None:
        ours_keys |= _keys(ours._async_limiter.storage)
    assert ours_keys == _keys(reference._storage)
    if reference._in_memory_fallback_enabled:
        assert _keys(ours._fallback_storage) == _keys(reference._fallback_storage)
    return [r.status_code for r in expected], [_rate_limit_headers(r) for r in expected]


def _base(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "key_func": get_remote_address,
        "default_limits": ["2/minute"],
        "key_style": "endpoint",
        "in_memory_fallback_enabled": True,
    }
    kwargs.update(overrides)
    return kwargs


_EVERY_ROUTE = [
    ("GET", path)
    for path in ["/plain", "/exempt", "/decorated", "/dynamic", "/missing"]
    for _ in range(4)
]


async def test_defaults_and_exemptions():
    statuses, _ = await _compare(_base(), _EVERY_ROUTE)
    assert 429 in statuses


async def test_disabled():
    statuses, headers = await _compare(
        _base(enabled=False, headers_enabled=True), _EVERY_ROUTE
    )
    assert 429 not in statuses
    assert not any(headers)


@pytest.mark.parametrize("key_style", ["endpoint", "url"])
async def test_key_style(key_style: str):
    calls = [("GET", "/items/a"), ("GET", "/items/b"), ("GET", "/items/a")] * 2
    await _compare(_base(key_style=key_style), calls)


async def test_key_prefix():
    _, _ = await _compare(_base(key_prefix="geolens"), [("GET", "/plain")] * 3)


@pytest.mark.parametrize(
    "strategy", ["fixed-window", "moving-window", "sliding-window-counter"]
)
@pytest.mark.parametrize("source", ["argument", "environment"])
async def test_strategy(monkeypatch: pytest.MonkeyPatch, strategy: str, source: str):
    """The async limiter follows the strategy slowapi actually selected."""
    kwargs = _base()
    if source == "argument":
        kwargs["strategy"] = strategy
    else:
        monkeypatch.setenv("RATELIMIT_STRATEGY", strategy)
    ours = _ours(**kwargs)
    assert type(ours._async_limiter).__name__ == type(ours._limiter).__name__

    await _compare(kwargs, [("GET", "/plain")] * 3 + [("GET", "/other")] * 3)


async def test_headers_on_passing_responses():
    """Includes a callable-limited route, where both layers append headers."""
    calls = (
        [("GET", "/plain")] * 2 + [("GET", "/dynamic")] * 2 + [("GET", "/retry-after")]
    )
    _, headers = await _compare(_base(headers_enabled=True), calls)
    assert headers[0], "the old middleware injected headers on a passing response"


async def test_headers_with_http_date_retry_after():
    calls = [("GET", "/plain"), ("GET", "/retry-after")]
    await _compare(_base(headers_enabled=True, retry_after="http-date"), calls)


async def test_header_name_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATELIMIT_HEADER_LIMIT", "X-Custom-Limit")
    monkeypatch.setenv("RATELIMIT_HEADER_REMAINING", "X-Custom-Remaining")
    monkeypatch.setenv("RATELIMIT_HEADER_RESET", "X-Custom-Reset")
    _, headers = await _compare(_base(headers_enabled=True), [("GET", "/plain")])
    assert {name for name, _ in headers[0]} >= {"x-custom-limit", "x-custom-reset"}


async def test_headers_through_slowapis_own_429_handler():
    """With no app handler, both answer through slowapi's default handler.

    That handler is synchronous and reads the window from the limiter's sync
    storage. With a shared store that is the same Redis the async check
    counts in, so this runs on one in-memory store; the app registers its
    own handler anyway.
    """
    await _compare(
        _base(headers_enabled=True),
        [("GET", "/plain")] * 3,
        handler="slowapi-default",
        shared_store=False,
    )


async def test_application_limits_span_every_route():
    calls = [
        ("GET", "/plain"),
        ("GET", "/other"),
        ("GET", "/items/x"),
        ("GET", "/plain"),
    ]
    statuses, _ = await _compare(
        _base(default_limits=["5/minute"], application_limits=["3/minute"]), calls
    )
    assert statuses[-1] == 429


def _default_group(**options: Any) -> Callable[[Limiter, Limiter], None]:
    """Install one default LimitGroup with per-limit options on both sides."""

    def _prepare(reference: Limiter, ours: Limiter) -> None:
        for limiter in (reference, ours):
            limiter._default_limits = [
                LimitGroup(
                    options.get("limit", "2/minute"),
                    limiter._key_func,
                    None,
                    options.get("per_method", False),
                    options.get("methods"),
                    None,
                    options.get("exempt_when"),
                    options.get("cost", 1),
                    False,
                )
            ]

    return _prepare


_MIXED_METHODS = [("GET", "/plain"), ("POST", "/plain")] * 3


@pytest.mark.parametrize(
    "options",
    [
        {"per_method": True},
        {"methods": ["POST"]},
        {"cost": 2, "limit": "3/minute"},
        {
            "cost": lambda request: 2 if request.method == "POST" else 1,
            "limit": "4/minute",
        },
        {"exempt_when": lambda: True},
        {"exempt_when": lambda request: request.method == "POST"},
    ],
    ids=[
        "per-method",
        "methods",
        "cost",
        "callable-cost",
        "exempt-when",
        "exempt-when-request",
    ],
)
async def test_per_limit_options(options: dict[str, Any]):
    await _compare(_base(), _MIXED_METHODS, prepare=_default_group(**options))


def _failing_store(*, alive: bool = False) -> Callable[[Limiter, Limiter], None]:
    def _prepare(reference: Limiter, ours: Limiter) -> None:
        def _unreachable(*_args, **_kwargs):
            raise ConnectionError("rate-limit store unreachable")

        async def _async_unreachable(*_args, **_kwargs):
            raise ConnectionError("rate-limit store unreachable")

        async def _async_check() -> bool:
            return alive

        reference._limiter.hit = _unreachable
        reference._storage.check = lambda: alive
        ours._async_limiter.hit = _async_unreachable
        ours._async_limiter.storage.check = _async_check

    return _prepare


async def test_in_memory_fallback_limits_replace_the_defaults_on_an_outage():
    statuses, _ = await _compare(
        _base(default_limits=["5/minute"], in_memory_fallback=["1/minute"]),
        [("GET", "/plain")] * 3,
        prepare=_failing_store(),
    )
    assert statuses == [200, 429, 429]


async def test_in_memory_fallback_enabled_keeps_the_defaults_on_an_outage():
    statuses, _ = await _compare(
        _base(), [("GET", "/plain")] * 3, prepare=_failing_store()
    )
    assert statuses == [200, 200, 429]


async def test_swallow_errors_without_fallback_lets_requests_through():
    """A deliberate difference: slowapi's middleware answered 500 here.

    Its check swallows the store error, but the middleware then reads
    ``request.state.view_rate_limit``, which the failed check never set, and
    the AttributeError escapes. Swallowing is meant to let the request
    through, so the new layer does.
    """
    from app.api.main import _rate_limit_handler

    kwargs = _base(in_memory_fallback_enabled=False, swallow_errors=True)
    reference = Limiter(**kwargs)
    ours = _ours(**kwargs)
    _failing_store()(reference, ours)
    calls = [("GET", "/plain")] * 3

    old = await _drive(_app(reference, SlowAPIMiddleware, _rate_limit_handler), calls)
    new = await _drive(
        _app(ours, GlobalRateLimitMiddleware, _rate_limit_handler), calls
    )

    assert [r.status_code for r in old] == [500, 500, 500]
    assert [r.status_code for r in new] == [200, 200, 200]


async def test_no_fallback_and_no_swallow_answers_500():
    statuses, _ = await _compare(
        _base(in_memory_fallback_enabled=False),
        [("GET", "/plain")] * 2,
        prepare=_failing_store(),
    )
    assert statuses == [500, 500]


async def test_a_failed_header_lookup_degrades_instead_of_failing_the_response():
    """A deliberate difference: slowapi answered 500 after the handler ran.

    Its header lookup falls back only when an ``in_memory_fallback`` list is
    configured, so with ``in_memory_fallback_enabled`` alone a store error
    while reading the window escaped after the route had already done its
    work. The new layer reads the window from the fallback instead.
    """
    from app.api.main import _rate_limit_handler

    kwargs = _base(headers_enabled=True)
    reference = Limiter(**kwargs)
    ours = _ours(**kwargs)

    def _unreachable(*_args, **_kwargs):
        raise ConnectionError("rate-limit store unreachable")

    async def _async_unreachable(*_args, **_kwargs):
        raise ConnectionError("rate-limit store unreachable")

    reference._limiter.get_window_stats = _unreachable
    ours._async_limiter.get_window_stats = _async_unreachable
    calls = [("GET", "/plain")]

    old = await _drive(_app(reference, SlowAPIMiddleware, _rate_limit_handler), calls)
    new = await _drive(
        _app(ours, GlobalRateLimitMiddleware, _rate_limit_handler), calls
    )

    assert [r.status_code for r in old] == [500]
    assert [r.status_code for r in new] == [200]
    assert new[0].headers["x-ratelimit-limit"] == "2"
    assert ours._storage_dead is True

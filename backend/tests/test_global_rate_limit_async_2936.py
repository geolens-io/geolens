"""The global default rate limit is checked without blocking the event loop.

With ``REDIS_URL`` set, slowapi's middleware made a synchronous Redis round
trip on the event loop for every non-exempt request. These tests drive
``GlobalRateLimitMiddleware`` against a limiter built the way the app builds
its own, with the shared store replaced by an in-memory async twin (the fake
Redis in the dev dependencies cannot run the store's Lua) or by a socket that
never answers.
"""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import Iterator

import pytest
import structlog
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from limits.aio.storage import MemoryStorage as AsyncMemoryStorage
from limits.aio.strategies import FixedWindowRateLimiter as AsyncFixedWindow
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.middleware.rate_limit import GlobalRateLimitMiddleware
from app.platform import ratelimit
from app.platform.ratelimit import _FallbackAnnouncingLimiter

pytestmark = pytest.mark.anyio


def _limiter(storage_uri: str, limit: str = "2/minute") -> _FallbackAnnouncingLimiter:
    return _FallbackAnnouncingLimiter(
        key_func=get_remote_address,
        default_limits=[limit],
        key_style="endpoint",
        storage_uri=storage_uri,
        storage_options=dict(ratelimit.limiter._storage_options),
        in_memory_fallback_enabled=True,
    )


def _app(limiter: Limiter, middleware=GlobalRateLimitMiddleware) -> FastAPI:
    from app.api.main import _rate_limit_handler

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(middleware)

    @app.get("/plain")
    async def plain() -> dict[str, bool]:
        return {"ok": True}

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


async def _statuses(app: FastAPI, path: str, count: int) -> list[int]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return [(await http.get(path)).status_code for _ in range(count)]


class _CountingAsyncLimiter(AsyncFixedWindow):
    """The async strategy over an in-memory store, counting its hits."""

    def __init__(self) -> None:
        super().__init__(AsyncMemoryStorage())
        self.hits = 0

    async def hit(self, *args, **kwargs) -> bool:
        self.hits += 1
        return await super().hit(*args, **kwargs)


@pytest.fixture
def shared_limiter(monkeypatch: pytest.MonkeyPatch) -> _FallbackAnnouncingLimiter:
    """A limiter on a redis:// store whose sync path must never be taken."""
    limiter = _limiter("redis://rate-limit-store.invalid:6379/0")
    limiter._async_limiter = _CountingAsyncLimiter()

    def _blocking_round_trip(*_args, **_kwargs):
        raise AssertionError("the global check took the sync storage path")

    monkeypatch.setattr(limiter._limiter, "hit", _blocking_round_trip)
    return limiter


def test_a_redis_store_gets_an_async_twin_on_the_same_url():
    """The default limits count in the same store, through the async client."""
    limiter = _limiter("redis://valkey/0")
    storage = limiter._async_limiter.storage
    assert type(storage).__module__.startswith("limits.aio.")
    assert storage.bridge.prefixed_key("k") == limiter._storage.prefixed_key("k")
    connection = storage.bridge.storage.connection_pool.connection_kwargs
    assert connection["host"] == "valkey"
    assert connection["socket_timeout"] == ratelimit.STORAGE_SOCKET_TIMEOUT_SECONDS
    assert (
        connection["socket_connect_timeout"] == ratelimit.STORAGE_SOCKET_TIMEOUT_SECONDS
    )
    assert connection["protocol"] == ratelimit.REDIS_PROTOCOL


def test_without_a_shared_store_there_is_no_async_client():
    """In-memory counting does no I/O, so it stays on the decorators' storage."""
    assert _limiter(None)._async_limiter is None


async def test_allowed_then_limited_through_the_async_store(shared_limiter):
    statuses = await _statuses(_app(shared_limiter), "/plain", 3)

    assert statuses == [200, 200, 429]
    assert shared_limiter._async_limiter.hits == 3


async def test_the_429_keeps_the_app_envelope(shared_limiter):
    app = _app(shared_limiter)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        for _ in range(2):
            await http.get("/plain")
        resp = await http.get("/plain")

    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0
    assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("path", ["/exempt", "/decorated", "/missing"])
async def test_exempt_decorated_and_unrouted_requests_skip_the_global_check(
    shared_limiter, path: str
):
    """slowapi's exemptions: @limiter.exempt, an own limit, no route at all."""
    shared_limiter._limiter = FixedWindowRateLimiter(MemoryStorage())
    await _statuses(_app(shared_limiter), path, 2)

    assert shared_limiter._async_limiter.hits == 0


@pytest.mark.parametrize(
    "path", ["/plain", "/exempt", "/decorated", "/dynamic", "/missing"]
)
async def test_every_route_kind_answers_as_slowapis_middleware_did(path: str):
    """The same request sequence gets the same statuses from both layers.

    ``/dynamic`` is the subtle one: a callable limit does not exempt a route
    from slowapi's middleware, so it pays the 2/minute default as well as its
    own 3/minute.
    """
    reference = Limiter(
        key_func=get_remote_address, default_limits=["2/minute"], key_style="endpoint"
    )
    ours = _limiter("redis://rate-limit-store.invalid:6379/0")
    ours._async_limiter = _CountingAsyncLimiter()
    ours._limiter = FixedWindowRateLimiter(MemoryStorage())

    expected = await _statuses(_app(reference, SlowAPIMiddleware), path, 5)
    actual = await _statuses(_app(ours), path, 5)

    assert actual == expected
    if path == "/dynamic":
        assert expected == [200, 200, 429, 429, 429]


async def test_a_disabled_limiter_checks_nothing(shared_limiter):
    shared_limiter.enabled = False

    assert await _statuses(_app(shared_limiter), "/plain", 3) == [200, 200, 200]
    assert shared_limiter._async_limiter.hits == 0


async def test_the_async_path_writes_slowapis_keys(shared_limiter):
    """Same identifiers, so both paths count into one bucket per caller."""
    reference = Limiter(
        key_func=get_remote_address, default_limits=["2/minute"], key_style="endpoint"
    )
    await _statuses(_app(reference, SlowAPIMiddleware), "/plain", 1)
    await _statuses(_app(shared_limiter), "/plain", 1)

    async_keys = set(shared_limiter._async_limiter.storage.storage)
    assert async_keys
    assert async_keys == set(reference._storage.storage)


async def test_a_dead_store_falls_back_to_the_same_limits_then_recovers(
    shared_limiter,
):
    """Fail open into per-process counting, announce both edges once each."""
    healthy = shared_limiter._async_limiter

    class _Unreachable(_CountingAsyncLimiter):
        async def hit(self, *args, **kwargs) -> bool:
            self.hits += 1
            raise ConnectionError("rate-limit store unreachable")

    dead = _Unreachable()

    async def _check() -> bool:
        return False

    dead.storage.check = _check
    shared_limiter._async_limiter = dead
    app = _app(shared_limiter)

    with structlog.testing.capture_logs() as outage:
        statuses = await _statuses(app, "/plain", 3)

    assert statuses == [200, 200, 429], "the fallback enforces the same 2/minute"
    assert shared_limiter._storage_dead is True
    assert [e["event"] for e in outage if e["event"].startswith("rate_limit_")] == [
        "rate_limit_storage_unreachable"
    ]
    assert dead.hits == 1, "once dead, requests stop trying the store"

    shared_limiter._async_limiter = healthy
    shared_limiter._Limiter__last_check_backend = 0.0
    with structlog.testing.capture_logs() as recovery:
        assert await _statuses(app, "/plain", 1) == [200]

    assert shared_limiter._storage_dead is False
    assert [e["event"] for e in recovery if e["event"].startswith("rate_limit_")] == [
        "rate_limit_storage_recovered"
    ]
    assert healthy.hits == 1


@pytest.fixture
def unanswering_store() -> Iterator[int]:
    """A TCP port that accepts connections and never replies."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    try:
        yield server.getsockname()[1]
    finally:
        server.close()


async def test_a_hung_store_is_bounded_and_never_blocks_the_loop(unanswering_store):
    """The store waits its socket timeout without stalling other requests.

    Against the sync storage the loop froze for the whole timeout, so the
    ticker below saw one gap as long as the wait.
    """
    limiter = _limiter(f"redis://127.0.0.1:{unanswering_store}/0", limit="100/minute")
    app = _app(limiter)
    gaps: list[float] = []
    stop = asyncio.Event()

    async def _ticker() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.005)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    ticker = asyncio.create_task(_ticker())
    await asyncio.sleep(0.02)
    started = time.monotonic()
    try:
        statuses = await _statuses(app, "/plain", 1)
    finally:
        elapsed = time.monotonic() - started
        stop.set()
        await ticker

    assert statuses == [200], "a hung store fails open, as an unreachable one does"
    assert limiter._storage_dead is True
    assert elapsed >= ratelimit.STORAGE_SOCKET_TIMEOUT_SECONDS
    assert elapsed < 1.5, f"the store wait was not bounded: {elapsed:.2f}s"
    assert max(gaps) < 0.1, f"the event loop stalled for {max(gaps):.3f}s"

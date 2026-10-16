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
import redis
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

from app.api.middleware.rate_limit import GlobalRateLimitMiddleware, find_route_handler
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


@pytest.mark.parametrize(
    "url",
    [
        "redis://valkey/0",
        "redis://valkey:6380/2",
        "redis://valkey:/0",
        "redis://[::1]:/0",
        "redis://[::1]:6380/1",
        "redis://:6379/0",
        "redis://:secret-pw@valkey:/0",
        "redis://user:secret-pw@:6379/0",
        "redis://valkey/0?client_name=geolens&health_check_interval=5",
        "rediss://",
        "rediss://valkey",
        "rediss://user:secret-pw@valkey:6380/1?ssl_cert_reqs=required",
    ],
)
def test_the_async_client_connects_exactly_where_the_sync_client_does(url: str):
    """Both clients come from redis-py's own parse of one URL.

    Host and port defaults, auth, db, query options and TLS must match, or a
    URL that works for the decorators either fails at import or points the
    global limit somewhere else, possibly without TLS.
    """
    limiter = _limiter(url)
    sync_pool = limiter._storage.storage.connection_pool
    async_pool = limiter._async_limiter.storage.bridge.storage.connection_pool

    assert async_pool.connection_class.__name__ == sync_pool.connection_class.__name__
    # A per-pool registry object, never equal across two pools.
    per_pool = {"himport_registry"}

    def _settings(pool) -> dict:
        return {k: v for k, v in pool.connection_kwargs.items() if k not in per_pool}

    assert _settings(async_pool) == _settings(sync_pool)
    if url.startswith("rediss://"):
        assert async_pool.connection_class.__name__ == "SSLConnection"


def test_an_unusable_async_config_refuses_boot_without_the_secret(
    monkeypatch: pytest.MonkeyPatch,
):
    import redis.asyncio

    def _refuse(url, **_options):
        raise ValueError(f"cannot use {url}")

    monkeypatch.setattr(redis.asyncio.ConnectionPool, "from_url", _refuse)

    with pytest.raises(RuntimeError, match="async client: ValueError") as raised:
        _limiter("redis://user:secret-pw@valkey:6379/0")

    assert "secret-pw" not in str(raised.value)
    assert raised.value.__cause__ is None


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


async def _concurrent_statuses(app: FastAPI, path: str, count: int) -> list[int]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        responses = await asyncio.gather(*(http.get(path) for _ in range(count)))
    return [r.status_code for r in responses]


@pytest.mark.parametrize("path", ["/plain", "/dynamic"])
@pytest.mark.parametrize(
    "failure",
    [
        ConnectionError("rate-limit store unreachable"),
        redis.exceptions.TimeoutError("Timeout reading from socket"),
    ],
    ids=["connection-error", "timeout"],
)
async def test_concurrent_checks_all_fall_back_when_the_store_fails_mid_flight(
    shared_limiter, path: str, failure: Exception
):
    """Every check awaiting the store when it fails is counted in the fallback.

    Only the first failure flips the store dead; the others land after it and
    must still answer from the fallback rather than re-raise into a 500. A
    callable-limited route pays the default limit on the same path.
    """
    shared_limiter._limiter = FixedWindowRateLimiter(MemoryStorage())
    release = asyncio.Event()
    waiting = 0

    class _FailsTogether(_CountingAsyncLimiter):
        async def hit(self, *args, **kwargs) -> bool:
            nonlocal waiting
            self.hits += 1
            waiting += 1
            await release.wait()
            raise failure

    shared_limiter._async_limiter = _FailsTogether()
    app = _app(shared_limiter)

    async def _release_when_all_wait() -> None:
        while waiting < 6:
            await asyncio.sleep(0)
        release.set()

    with structlog.testing.capture_logs() as captured:
        statuses, _ = await asyncio.gather(
            _concurrent_statuses(app, path, 6), _release_when_all_wait()
        )

    assert shared_limiter._async_limiter.hits == 6, "all six were in flight"
    assert sorted(statuses) == [200, 200, 429, 429, 429, 429], statuses
    assert [e["event"] for e in captured if e["event"].startswith("rate_limit_")] == [
        "rate_limit_storage_unreachable"
    ]


async def test_concurrent_checks_recover_the_store_once(shared_limiter):
    """One check probes the recovered store; the rest keep the fallback."""
    healthy = shared_limiter._async_limiter
    release = asyncio.Event()
    probes = 0

    async def _slow_check() -> bool:
        nonlocal probes
        probes += 1
        await release.wait()
        return True

    healthy.storage.check = _slow_check
    shared_limiter._storage_dead = True
    shared_limiter._Limiter__last_check_backend = 0.0
    app = _app(shared_limiter)

    async def _release_when_probed() -> None:
        while probes == 0:
            await asyncio.sleep(0)
        for _ in range(50):
            await asyncio.sleep(0)
        release.set()

    with structlog.testing.capture_logs() as captured:
        statuses, _ = await asyncio.gather(
            _concurrent_statuses(app, "/plain", 4), _release_when_probed()
        )

    assert probes == 1
    assert set(statuses) <= {200, 429} and 200 in statuses, statuses
    assert shared_limiter._storage_dead is False
    assert healthy.hits == 1, "only the probing request counted in the store"
    assert [e["event"] for e in captured if e["event"].startswith("rate_limit_")] == [
        "rate_limit_storage_recovered"
    ]


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


async def test_concurrent_checks_on_a_hung_store_all_get_normal_enforcement(
    unanswering_store,
):
    """Requests that time out together all answer from the fallback."""
    limiter = _limiter(f"redis://127.0.0.1:{unanswering_store}/0", limit="2/minute")
    app = _app(limiter)

    with structlog.testing.capture_logs() as captured:
        statuses = await _concurrent_statuses(app, "/plain", 4)

    assert sorted(statuses) == [200, 200, 429, 429], statuses
    assert limiter._storage_dead is True
    assert [e["event"] for e in captured if e["event"].startswith("rate_limit_")] == [
        "rate_limit_storage_unreachable"
    ]


def test_every_alias_of_a_callable_limited_route_reaches_the_global_check(
    monkeypatch: pytest.MonkeyPatch,
):
    """The concurrent-failure fallback above covers these routes too.

    A callable ``@limiter.limit`` does not exempt a route from the default
    limits, so each method and path alias must resolve to its handler here.
    """
    import re
    import uuid

    from app.api.main import _iter_api_routes, app

    monkeypatch.setattr(ratelimit.limiter, "enabled", True)
    callable_limited = set(ratelimit.limiter._dynamic_route_limits)
    reached: dict[str, set[tuple[str, str]]] = {}
    for ctx in _iter_api_routes(app):
        endpoint = ctx.route.endpoint
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        if name not in callable_limited:
            continue
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), ctx.path_format)
        for method in ctx.route.methods:
            scope = {"type": "http", "method": method, "path": path, "root_path": ""}
            resolved = find_route_handler(app.routes, scope)
            assert resolved is endpoint, (method, path)
            assert not ratelimit.limiter.is_exempt_from_default_limits(resolved)
            reached.setdefault(endpoint.__name__, set()).add((method, ctx.path_format))

    assert set(reached) == {
        "arcgis_signin",
        "get_basemaps",
        "list_related_datasets",
        "login",
        "sandbox_query_endpoint",
        "search_datasets_endpoint",
        "search_facets_endpoint",
    }
    assert all(len(aliases) == 2 for aliases in reached.values()), reached

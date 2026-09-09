"""Pin #2018: rate-limit buckets count in a shared store, and degrade safely.

The bundled prod compose runs two uvicorn workers, so slowapi's default
in-memory storage made every configured cap really N caps. These tests cover
the storage selection, the outage transition and the invariants the switch
must not disturb. The cross-worker claim tests live in test_rate_limits.py.
"""

import inspect
import pathlib
import uuid

import pytest
import slowapi.extension
import structlog
from httpx import AsyncClient
from limits import RateLimitItemPerMinute
from limits.storage import MemoryStorage
from slowapi.util import get_remote_address

from app.core.config import settings
from app.modules.catalog.search.router import (
    search_datasets_endpoint,
    search_facets_endpoint,
)
from app.platform import ratelimit, ratelimit_claims
from app.platform.ratelimit import (
    _FallbackAnnouncingLimiter,
    _global_rate_limit,
    emit_startup_notices,
    limiter,
    shared_storage_uri,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def uncached_storage_uri():
    """Drop the process-wide memo and the queued notices from importing.

    The module queues its notice while it is imported, and in the app that
    queue is drained once at startup; here each test needs to see only what
    its own call queued.
    """
    shared_storage_uri.cache_clear()
    ratelimit._startup_notices.clear()
    yield
    shared_storage_uri.cache_clear()
    ratelimit._startup_notices.clear()


def test_no_configured_store_keeps_counting_per_process_and_says_so(
    monkeypatch: pytest.MonkeyPatch, uncached_storage_uri
):
    """The one configuration where limiting is not cluster-wide announces itself.

    Every other degradation in this module logs; a silent one here would be
    the only way to end up with per-worker buckets and no trace of it.
    """
    monkeypatch.setattr(settings, "redis_url", None)

    with structlog.testing.capture_logs() as captured:
        assert shared_storage_uri() is None
        assert captured == [], "the decision is made before logging is configured"
        emit_startup_notices()

    assert [e["event"] for e in captured] == ["rate_limit_storage_not_configured"]
    assert ratelimit_claims._build_store() is None


def test_url_parameters_that_lengthen_one_call_are_dropped(
    monkeypatch: pytest.MonkeyPatch, uncached_storage_uri
):
    """redis-py lets the querystring beat the keyword arguments.

    Measured on redis-py 7.4.1: a URL ``socket_timeout=30`` leaves 30 in
    effect over the code's 0.25, on the limits storage as well, and either
    retry flag lifts retries 0 to 1, doubling the bound again. The call runs
    on the event loop, so that bound is not the operator's to widen.
    """
    monkeypatch.setattr(
        settings,
        "redis_url",
        "redis://valkey/0?socket_timeout=30&socket_connect_timeout=30"
        "&retry_on_timeout=true&retry_on_error=ConnectionError&db=2",
    )

    with structlog.testing.capture_logs() as captured:
        resolved = shared_storage_uri()
        emit_startup_notices()

    assert resolved == "redis://valkey/0?db=2"
    overrides = [
        e
        for e in captured
        if e["event"] == "rate_limit_storage_call_duration_override_ignored"
    ]
    assert len(overrides) == 1, captured
    assert overrides[0]["parameters"] == [
        "retry_on_error",
        "retry_on_timeout",
        "socket_connect_timeout",
        "socket_timeout",
    ]


def test_a_url_without_timeout_overrides_is_passed_through_untouched(
    monkeypatch: pytest.MonkeyPatch, uncached_storage_uri
):
    """Only the case being fixed is rewritten; nothing else is re-encoded."""
    url = "redis://valkey/0?db=2&client_name=geolens%2Fapi"
    monkeypatch.setattr(settings, "redis_url", url)

    assert shared_storage_uri() == url


@pytest.mark.parametrize("url", ["redis://valkey:6379/0", "rediss://valkey:6379/1"])
def test_a_redis_url_becomes_the_storage_uri_unchanged(
    monkeypatch: pytest.MonkeyPatch, uncached_storage_uri, url: str
):
    """The storage URL is derived from REDIS_URL, never a second copy of it."""
    monkeypatch.setattr(settings, "redis_url", url)
    assert shared_storage_uri() == url
    assert ratelimit_claims._build_store() is not None


def test_a_scheme_the_limiter_cannot_use_is_refused_not_raised(
    monkeypatch: pytest.MonkeyPatch, uncached_storage_uri
):
    """``limits`` raises ConfigurationError on an unknown scheme.

    That would be raised while building the module-level limiter, so an
    otherwise-working deployment could not boot. Refusing the scheme keeps
    per-process counting and says so once.
    """
    monkeypatch.setattr(settings, "redis_url", "unix:///run/valkey/valkey.sock")

    with structlog.testing.capture_logs() as captured:
        assert shared_storage_uri() is None
        emit_startup_notices()

    refusals = [
        e for e in captured if e["event"] == "rate_limit_storage_scheme_unsupported"
    ]
    assert len(refusals) == 1, captured
    assert refusals[0]["scheme"] == "unix"


def test_the_configured_url_never_reaches_the_log(
    monkeypatch: pytest.MonkeyPatch, uncached_storage_uri
):
    """REDIS_URL routinely carries a password in its userinfo.

    ``redact_url_credentials`` rewrites http(s) only, so a redis:// URL would
    pass through it unchanged; the refusal names the scheme instead.
    """
    monkeypatch.setattr(
        settings,
        "redis_url",
        "unix://storeuser:redaction-sentinel@valkey-host/valkey.sock",
    )

    with structlog.testing.capture_logs() as captured:
        assert shared_storage_uri() is None
        emit_startup_notices()

    refusal = [
        e for e in captured if e["event"] == "rate_limit_storage_scheme_unsupported"
    ][0]
    assert refusal["scheme"] == "unix"
    for value in refusal.values():
        assert "redaction-sentinel" not in str(value)
        assert "storeuser" not in str(value)


def test_the_limiter_keeps_its_strategy_key_function_and_style():
    """#2018 changes where the counters live, nothing about how they are keyed."""
    from slowapi.util import get_remote_address

    assert isinstance(limiter, _FallbackAnnouncingLimiter)
    assert limiter._key_func is get_remote_address
    assert limiter._key_style == "endpoint"
    assert limiter._strategy is None
    assert type(limiter._limiter).__name__ == "FixedWindowRateLimiter"


def test_an_outage_falls_back_to_per_process_limiting_not_to_none():
    """The fallback limiter exists and re-evaluates the SAME limits.

    ``in_memory_fallback`` is deliberately empty: slowapi swaps only the
    storage, so a store outage keeps every configured cap and merely stops
    sharing it, which is the pre-#2018 behaviour rather than no limit.
    """
    assert limiter._in_memory_fallback_enabled is True
    assert limiter._fallback_limiter is not None
    assert limiter._fallback_limiter is not limiter._limiter
    assert limiter._in_memory_fallback == []


def test_two_workers_on_one_store_count_into_one_bucket(
    monkeypatch: pytest.MonkeyPatch,
):
    """The subject of #2018, pinned behaviourally rather than structurally.

    Two limiters built the way the app builds its own stand in for two
    uvicorn workers. The second arm is the bug: with a store each, the
    second worker gets a whole fresh budget for the same caller. The first
    arm also guards a hazard this PR introduces, since an always-present
    in-memory fallback storage must never become the counting path while the
    shared store is healthy.
    """
    item = RateLimitItemPerMinute(2)
    key = f"sec-2018-bucket-{uuid.uuid4().hex}"

    def _two_workers(*, shared: bool) -> list[_FallbackAnnouncingLimiter]:
        one = MemoryStorage()
        monkeypatch.setattr(
            slowapi.extension,
            "storage_from_string",
            lambda _uri, **_options: one if shared else MemoryStorage(),
        )
        return [
            _FallbackAnnouncingLimiter(
                key_func=get_remote_address,
                default_limits=[_global_rate_limit],
                key_style="endpoint",
                storage_uri="redis://stand-in",
                in_memory_fallback_enabled=True,
            )
            for _ in range(2)
        ]

    worker_a, worker_b = _two_workers(shared=True)
    assert [
        worker_a.limiter.hit(item, key),
        worker_b.limiter.hit(item, key),
        worker_b.limiter.hit(item, key),
    ] == [True, True, False], "two workers on one store must share one budget of 2"

    worker_c, worker_d = _two_workers(shared=False)
    assert [
        worker_c.limiter.hit(item, key),
        worker_d.limiter.hit(item, key),
        worker_d.limiter.hit(item, key),
    ] == [True, True, True], "a store each is the pre-#2018 bug: 2 per worker"


@pytest.mark.parametrize("endpoint", [search_datasets_endpoint, search_facets_endpoint])
def test_the_claim_gate_stays_a_synchronous_callable(endpoint):
    """An async ``exempt_when`` returns a truthy coroutine for every request.

    slowapi calls it without awaiting, so the limit would be skipped
    unconditionally. #2018 puts a store round trip behind this callable,
    which is the change most likely to tempt someone into making it async.
    """
    key = f"{endpoint.__module__}.{endpoint.__name__}"
    groups = limiter._dynamic_route_limits[key]
    assert groups
    for group in groups:
        assert group.exempt_when is not None
        assert not inspect.iscoroutinefunction(group.exempt_when)


def test_the_app_drains_the_queue_after_it_configures_logging():
    """Queueing the notices is only worth anything if something flushes them.

    Deferring them and never draining would trade a badly formatted line for
    no line at all, which is the silent disable the queue exists to avoid.
    """
    import app.api.main as api_main

    source = pathlib.Path(api_main.__file__).read_text()

    assert "emit_startup_notices()" in source, (
        "nothing drains the queued rate-limit storage notices"
    )
    assert source.index("setup_logging(") < source.index("emit_startup_notices()"), (
        "the flush must come after logging is configured, not before"
    )


async def test_a_dead_store_degrades_the_request_and_both_edges_are_announced(
    client: AsyncClient,
):
    """A store that fails every call must not 500, and must not log per request.

    Both edges are driven through slowapi's own writes to ``_storage_dead``
    rather than assigned here, so a rename in slowapi leaves this test
    failing instead of quietly passing against a property nothing calls.
    """

    def _unreachable(*_args, **_kwargs):
        raise ConnectionError("rate-limit store unreachable")

    live_hit = limiter._limiter.hit
    live_check = limiter._storage.check
    limiter._limiter.hit = _unreachable
    limiter._storage.check = lambda: False
    limiter._fallback_storage.reset()
    limiter.enabled = True
    try:
        with structlog.testing.capture_logs() as outage:
            statuses = [
                (
                    await client.get(f"/search/datasets/?q=sec-2018-outage-{i}")
                ).status_code
                for i in range(3)
            ]

        assert statuses == [200, 200, 200], statuses
        assert [
            e["event"] for e in outage if e["event"].startswith("rate_limit_storage_")
        ] == ["rate_limit_storage_unreachable"]

        limiter._limiter.hit = live_hit
        limiter._storage.check = live_check
        # slowapi probes the backend on an exponential delay; zeroing the last
        # probe time lets the next request take the recovery branch now.
        limiter._Limiter__last_check_backend = 0.0

        with structlog.testing.capture_logs() as recovery:
            healed = await client.get("/search/datasets/?q=sec-2018-healed")

        assert healed.status_code == 200, healed.status_code
        assert [
            e["event"] for e in recovery if e["event"].startswith("rate_limit_storage_")
        ] == ["rate_limit_storage_recovered"]
    finally:
        limiter._limiter.hit = live_hit
        limiter._storage.check = live_check
        limiter.enabled = False
        limiter._storage_dead = False

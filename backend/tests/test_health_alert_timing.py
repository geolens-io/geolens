"""Timing cases for the fleet-wide degraded-health alert.

``/health`` claims a shared cache key before it alerts, so one replica sends
per incident, and releases it on recovery. These tests cover the orderings
that could hide an alert: a claim write that commits after its timeout, a
recovery still waiting on the cache when a newer degraded result lands, and a
delivery that fails. A "replica" here is a second copy of the per-process
alert state sharing the same cache.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
import structlog

import app.api.main as main_mod
from app.observability.health import service as health_svc
from app.platform.cache import get_cache, provider
from app.platform.cache.memory import InMemoryCacheProvider
from app.platform.cache.redis import RedisCacheProvider
from app.platform.notifications import NotificationResult
from app.platform.notifications import events as events_mod

pytestmark = pytest.mark.anyio

DEGRADED = {"status": "degraded", "providers": {"database": {"status": "error"}}}
HEALTHY = {"status": "healthy", "providers": {}}
CACHE_DOWN = {"status": "degraded", "providers": {"cache": {"status": "error"}}}
DELIVERED = NotificationResult(attempted=1, delivered=1)
UNDELIVERED = NotificationResult(
    attempted=1, delivered=0, errors=["E"], failed_channels=frozenset({"smtp"})
)
PARTLY_DELIVERED = NotificationResult(
    attempted=1, delivered=1, failed_channels=frozenset({"webhook"})
)


class _SharedMemoryCache(InMemoryCacheProvider):
    """One store that every simulated replica reads, standing in for Redis."""

    shared = True


_PROCESS_STATE = {
    (health_svc, "_last_health_alert_at"): None,
    (health_svc, "_last_health_status"): "healthy",
    (health_svc, "_health_probe_seq"): 0,
    (health_svc, "_health_applied_seq"): 0,
    (health_svc, "_alert_claim_token"): None,
    (health_svc, "_health_incident_started_at"): 0.0,
}
_PROCESS_LOCKS = ("_health_state_lock", "_alert_claim_lock")


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    from app.platform.ratelimit import limiter

    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(provider, "_cache_provider", _SharedMemoryCache())
    monkeypatch.setattr("app.core.config.settings.notify_on_health_alert", True)
    for (module, name), value in _PROCESS_STATE.items():
        monkeypatch.setattr(module, name, value)
    # A lock binds to the event loop it is first contended on; each test has its own.
    for name in _PROCESS_LOCKS:
        monkeypatch.setattr(health_svc, name, asyncio.Lock())


@pytest.fixture
def sent(monkeypatch):
    """Every notification handed to ``notify``, answered by *answers* in turn."""
    calls: list = []
    answers: list[NotificationResult] = []

    async def _notify(notification):
        calls.append(notification)
        return answers.pop(0) if answers else DELIVERED

    monkeypatch.setattr(events_mod, "notify", _notify)
    return calls, answers


def _checks(monkeypatch, *results):
    monkeypatch.setattr(health_svc, "check_health", AsyncMock(side_effect=results))


@contextmanager
def _replica(state: dict):
    """Run as another process: its own alert state and locks, the same cache."""
    current = {key: getattr(*key) for key in _PROCESS_STATE}
    locks = {name: getattr(health_svc, name) for name in _PROCESS_LOCKS}
    for key, default in _PROCESS_STATE.items():
        setattr(*key, state.get(key, default))
    for name in _PROCESS_LOCKS:
        setattr(health_svc, name, state.setdefault(name, asyncio.Lock()))
    try:
        yield
    finally:
        for key in _PROCESS_STATE:
            state[key] = getattr(*key)
            setattr(*key, current[key])
        for name, lock in locks.items():
            setattr(health_svc, name, lock)


async def _poll(run_background: bool = True):
    request = MagicMock()
    request.client.host = "127.0.0.1"
    response = await main_mod.health(request)
    if run_background and response.background is not None:
        await response.background()
    return response


async def test_a_claim_that_commits_after_its_timeout_is_released_on_recovery(
    monkeypatch, sent
):
    """``SET NX`` stored the key but its reply never came back in time."""
    calls, _ = sent

    class _CommitsThenStalls(_SharedMemoryCache):
        async def set_if_absent(self, key, value, ttl=300, *, security=False):
            await super().set_if_absent(key, value, ttl, security=security)
            await asyncio.Event().wait()

    monkeypatch.setattr(provider, "_cache_provider", _CommitsThenStalls())
    monkeypatch.setattr(health_svc, "HEALTH_TIMEOUT", 0.05)
    _checks(monkeypatch, DEGRADED, HEALTHY)

    await _poll()
    assert len(calls) == 1
    await _poll()

    assert await get_cache().get(health_svc._HEALTH_ALERT_KEY) is None


async def test_a_newer_degraded_result_waits_for_the_recovery_ahead_of_it(
    monkeypatch, sent
):
    """Probe 1 is still claiming, probe 2 (healthy) waits behind it, and probe
    3 (degraded again) is a new incident that must alert."""
    calls, _ = sent
    entered, proceed = asyncio.Event(), asyncio.Event()

    class _SlowFirstClaim(_SharedMemoryCache):
        async def set_if_absent(self, key, value, ttl=300, *, security=False):
            if not entered.is_set():
                entered.set()
                await proceed.wait()
            return await super().set_if_absent(key, value, ttl, security=security)

    monkeypatch.setattr(provider, "_cache_provider", _SlowFirstClaim())
    _checks(monkeypatch, DEGRADED, HEALTHY, DEGRADED)

    first = asyncio.create_task(_poll())
    await entered.wait()
    recovery = asyncio.create_task(_poll())
    for _ in range(5):
        await asyncio.sleep(0)
    newest = asyncio.create_task(_poll())
    for _ in range(5):
        await asyncio.sleep(0)
    proceed.set()
    await asyncio.gather(first, recovery, newest)

    assert len(calls) == 2
    assert health_svc._last_health_status == "degraded"


async def test_a_failed_delivery_is_retried_by_another_replica_after_the_backoff(
    monkeypatch, sent
):
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, DEGRADED, DEGRADED, DEGRADED)
    other: dict = {}

    # This replica claims; its delivery is still in flight when the other
    # replica polls, finds the claim held, and stands down.
    claimed = await _poll(run_background=False)
    with _replica(other):
        await _poll()
    answers.append(UNDELIVERED)
    await claimed.background()
    assert len(calls) == 1

    # Inside the backoff the claim still holds, so nobody re-sends yet.
    with _replica(other):
        await _poll()
    assert len(calls) == 1

    await asyncio.sleep(0.1)
    with _replica(other):
        await _poll()
    assert len(calls) == 2


async def test_a_slow_failed_delivery_leaves_a_newer_incidents_claim_alone(
    monkeypatch, sent
):
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, HEALTHY, DEGRADED, DEGRADED)

    slow = await _poll(run_background=False)
    await _poll()  # recovery releases the first incident's claim
    await _poll()  # a new incident claims and alerts
    assert len(calls) == 1
    newer = health_svc._alert_claim_token

    answers.append(UNDELIVERED)
    await slow.background()
    await asyncio.sleep(0.1)

    assert await get_cache().get(health_svc._HEALTH_ALERT_KEY) == newer
    await _poll()
    assert len(calls) == 2
    with _replica({}):
        assert await health_svc.claim_health_alert(["database"]) is None


async def test_a_slow_failed_delivery_leaves_a_newer_alerts_cooldown_alone(
    monkeypatch, sent
):
    """With the cache down nothing shared throttles, only the local cooldown."""
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, HEALTHY, CACHE_DOWN, CACHE_DOWN)

    slow = await _poll(run_background=False)
    await _poll()
    await _poll()
    assert len(calls) == 1

    answers.append(UNDELIVERED)
    await slow.background()
    await asyncio.sleep(0.1)
    await _poll()

    assert len(calls) == 2


async def test_attempts_are_spaced_out_while_the_channel_stays_down(monkeypatch, sent):
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, *[DEGRADED] * 6)
    answers.extend([UNDELIVERED] * 6)

    for _ in range(5):
        await _poll()
    assert len(calls) == 1

    await asyncio.sleep(0.1)
    await _poll()
    assert len(calls) == 2


async def test_a_partly_failed_alert_is_retried_to_every_channel_by_another_replica(
    monkeypatch, sent
):
    """SMTP delivered and the webhook failed: after the backoff another replica
    sends the alert again, SMTP included."""
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, DEGRADED, DEGRADED)
    other: dict = {}

    claimed = await _poll(run_background=False)
    with _replica(other):
        await _poll()
    answers.append(PARTLY_DELIVERED)
    await claimed.background()
    await asyncio.sleep(0.1)
    with _replica(other):
        await _poll()

    assert len(calls) == 2


async def test_early_retries_stop_after_the_incidents_first_cooldown(monkeypatch, sent):
    """A channel that stays down gets one attempt per backoff only during the
    incident's first cooldown; after that, one per cooldown."""
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, *[DEGRADED] * 5)
    answers.extend([PARTLY_DELIVERED] * 5)
    other: dict = {}

    await _poll()
    await asyncio.sleep(0.1)
    await _poll()
    assert len(calls) == 2

    health_svc._health_incident_started_at -= health_svc.HEALTH_ALERT_COOLDOWN_SECS
    await asyncio.sleep(0.1)
    await _poll()
    assert len(calls) == 3
    await asyncio.sleep(0.1)
    await _poll()
    with _replica(other):
        await _poll()

    assert len(calls) == 3


@pytest.mark.parametrize(
    ("incident_age", "retried"),
    [
        (health_svc.HEALTH_ALERT_COOLDOWN_SECS - 5, True),
        (health_svc.HEALTH_ALERT_COOLDOWN_SECS, False),
    ],
)
async def test_a_failed_send_gets_the_backoff_only_inside_the_first_cooldown(
    monkeypatch, sent, incident_age, retried
):
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    monkeypatch.setattr(health_svc, "_last_health_status", "degraded")
    monkeypatch.setattr(
        health_svc, "_health_incident_started_at", time.monotonic() - incident_age
    )
    _checks(monkeypatch, DEGRADED, DEGRADED)
    answers.append(PARTLY_DELIVERED)

    await _poll()
    await asyncio.sleep(0.1)
    with _replica({}):
        await _poll()

    assert len(calls) == (2 if retried else 1)


async def test_a_written_back_claim_delays_the_next_incident_by_one_backoff(
    monkeypatch, sent
):
    """A failed send reads its claim, another replica's recovery deletes it,
    then the send writes it back. The next incident alerts once that backoff
    runs out."""
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    other: dict = {}

    class _RecoveryBetweenReadAndWrite(_SharedMemoryCache):
        armed = False

        async def get(self, key, *, security=False):
            value = await super().get(key, security=security)
            if self.armed and key == health_svc._HEALTH_ALERT_KEY:
                self.armed = False
                with _replica(other):
                    await _poll()
            return value

    cache = _RecoveryBetweenReadAndWrite()
    monkeypatch.setattr(provider, "_cache_provider", cache)
    _checks(monkeypatch, DEGRADED, DEGRADED, HEALTHY, DEGRADED, DEGRADED)

    claimed = await _poll(run_background=False)
    token = health_svc._alert_claim_token
    with _replica(other):
        await _poll()
    answers.append(PARTLY_DELIVERED)
    cache.armed = True
    await claimed.background()
    assert await cache.get(health_svc._HEALTH_ALERT_KEY) == token
    with _replica(other):
        await _poll()
    await asyncio.sleep(0.1)
    with _replica(other):
        await _poll()

    assert len(calls) == 2


async def test_with_the_cache_down_a_partly_failed_alert_waits_out_the_cooldown(
    monkeypatch, sent
):
    """No shared key spaces out retries across replicas, so a channel that
    worked must not get the alert again every backoff from every replica."""
    calls, answers = sent
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, *[CACHE_DOWN] * 3)
    answers.extend([PARTLY_DELIVERED] * 3)

    for _ in range(3):
        await _poll()
        await asyncio.sleep(0.1)

    assert len(calls) == 1


class _ClaimRaises(_SharedMemoryCache):
    async def set_if_absent(self, key, value, ttl=300, *, security=False):
        raise ConnectionError("cache unreachable")


class _ClaimWriteFails(_SharedMemoryCache):
    """The write is refused and no key is stored, as when Redis drops it."""

    async def set_if_absent(self, key, value, ttl=300, *, security=False):
        return False


@pytest.mark.parametrize("cache", [_ClaimRaises, _ClaimWriteFails])
async def test_an_alert_sent_without_holding_the_key_waits_out_the_cooldown(
    monkeypatch, sent, cache
):
    """Without the key no other replica is held back, so an early retry here
    would repeat on every replica."""
    calls, answers = sent
    monkeypatch.setattr(provider, "_cache_provider", cache())
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, DEGRADED)
    answers.append(PARTLY_DELIVERED)

    await _poll()
    await asyncio.sleep(0.1)
    await _poll()

    assert len(calls) == 1


def _redis_with_open_circuit() -> RedisCacheProvider:
    cache = _fake_redis_cache()
    cache._failure_count = cache._max_failures
    cache._circuit_open_until = time.monotonic() + 30
    return cache


@pytest.mark.parametrize(
    "cache",
    [InMemoryCacheProvider, _redis_with_open_circuit],
    ids=["in-memory", "redis-circuit-open"],
)
async def test_a_claim_held_in_process_memory_gets_no_early_retry(
    monkeypatch, sent, cache
):
    """Each API worker has its own memory, so every worker would win the key
    and resend after each backoff."""
    calls, answers = sent
    monkeypatch.setattr(provider, "_cache_provider", cache())
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, DEGRADED)
    answers.append(PARTLY_DELIVERED)

    await _poll()
    await asyncio.sleep(0.1)
    await _poll()

    assert len(calls) == 1


async def test_a_failing_sink_beside_an_env_sink_with_nothing_to_send_is_retried(
    monkeypatch,
):
    """The env sink counts as delivered with no channel configured, so
    "someone was reached" can't be what decides a retry."""
    from app.platform import notifications as notifications_pkg
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    pages: list = []

    class _PagerSink:
        async def deliver(self, notification):
            pages.append(notification)
            raise RuntimeError("pager down")

    monkeypatch.setattr(
        notifications_pkg,
        "get_notification_sinks",
        lambda: [EnvConfiguredNotificationSink(), _PagerSink()],
    )
    monkeypatch.setattr("app.core.config.settings.notifications_enabled", False)
    monkeypatch.setattr(health_svc, "HEALTH_ALERT_RETRY_SECS", 0.05)
    _checks(monkeypatch, DEGRADED, DEGRADED)

    await _poll()
    await asyncio.sleep(0.1)
    await _poll()

    assert len(pages) == 2


def _fake_redis_cache() -> RedisCacheProvider:
    """The real provider over fakeredis, built the way its own tests build it."""
    cache = RedisCacheProvider.__new__(RedisCacheProvider)
    cache._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache._max_failures = 3
    cache._cooldown_seconds = 30
    cache._failure_count = 0
    cache._circuit_open_until = 0.0
    cache._fallback = InMemoryCacheProvider()
    cache._pending_authoritative = OrderedDict()
    cache._replay_lock = asyncio.Lock()
    return cache


async def test_the_retry_runs_on_the_redis_provider(monkeypatch, sent):
    """Integer TTLs and JSON values, which the in-memory cache never checks."""
    calls, answers = sent
    cache = _fake_redis_cache()
    monkeypatch.setattr(provider, "_cache_provider", cache)
    _checks(monkeypatch, DEGRADED, DEGRADED, DEGRADED)
    other: dict = {}

    claimed = await _poll(run_background=False)
    answers.append(PARTLY_DELIVERED)
    await claimed.background()
    with _replica(other):
        await _poll()

    ttl = await cache._client.ttl(health_svc._HEALTH_ALERT_KEY)
    assert 0 < ttl <= health_svc.HEALTH_ALERT_RETRY_SECS
    # Stands in for the backoff running out.
    await cache._client.delete(health_svc._HEALTH_ALERT_KEY)
    with _replica(other):
        await _poll()

    assert len(calls) == 2


async def test_a_probe_queued_behind_a_stuck_one_still_answers(monkeypatch, sent):
    calls, _ = sent
    monkeypatch.setattr(health_svc, "HEALTH_TIMEOUT", 0.05)
    _checks(monkeypatch, DEGRADED)

    with structlog.testing.capture_logs() as logs:
        async with health_svc._health_state_lock:
            response = await asyncio.wait_for(_poll(), timeout=2)

    assert response.status_code == 503
    assert calls == []
    assert "health_probe_result_dropped" in [log["event"] for log in logs]

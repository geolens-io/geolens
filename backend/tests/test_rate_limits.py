"""Tests for SEC-S10 and SEC-S11 per-route rate limiting.

Phase 1062 Plan 02: per-route @limiter.limit decorators on:
  - /search/datasets/   (SEC-S11, caps OpenAI embedding cost-DoS)
  - /search/facets/     (SEC-S11, one bucket shared with /search/datasets/)
  - /datasets/{id}/related/  (SEC-S11, same embedding cost surface)
  - /settings/basemaps/      (SEC-S10, caps commercial-tier basemap key replay)

The conftest.py `client` fixture globally disables the limiter
(``limiter.enabled = False``) to keep all other tests fast. Rate-limit
tests MUST re-enable the limiter within the test, reset its storage
afterwards, and then disable it again to avoid leaking state.

Per-test pattern:
    1. Set the rate-limit counter directly in _sync_rate_limit_cache
       (monkeypatching the low-level sync cache is cleaner than patching
       the PersistentConfig — it does not require an async DB round-trip).
    2. Enable the limiter.
    3. Fire N+1 requests; the last N-threshold should be 429.
    4. Re-disable the limiter and reset storage.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.persistent_config import (
    _sync_rate_limit_cache,
    get_cached_semantic_search_rate_limit,
    get_cached_basemap_proxy_rate_limit,
)
from app.platform.ratelimit import limiter

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Task 1: Default value tests (no HTTP required)
# ---------------------------------------------------------------------------


def test_default_semantic_search_limit_is_30():
    """get_cached_semantic_search_rate_limit() returns 30 when cache is empty.

    Clears the cache entry before calling to avoid interference from other
    tests that may have set a low monkeypatched value.
    """
    _sync_rate_limit_cache.pop("semantic_search_rate_limit", None)
    assert get_cached_semantic_search_rate_limit() == 30


def test_default_basemap_proxy_limit_is_120():
    """get_cached_basemap_proxy_rate_limit() returns 120 when cache is empty."""
    _sync_rate_limit_cache.pop("basemap_proxy_rate_limit", None)
    assert get_cached_basemap_proxy_rate_limit() == 120


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_cache_limit(key: str, value: int) -> None:
    """Inject a low limit into the sync cache so the slowapi callable picks it up."""
    import time

    _sync_rate_limit_cache[key] = (value, time.monotonic())


def _clear_cache_limit(key: str) -> None:
    _sync_rate_limit_cache.pop(key, None)


def _reset_limiter_storage() -> None:
    """Reset slowapi in-memory storage to clear counters from prior test runs.

    limiter._storage.reset() is a synchronous call on MemoryStorage.
    """
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()


# ---------------------------------------------------------------------------
# Task 2: /search/datasets/ and /search/facets/ rate limiting (SEC-S11)
# ---------------------------------------------------------------------------


async def test_semantic_search_rate_limit_returns_429(client: AsyncClient):
    """GET /search/datasets/?q=<unique-N> returns 429 after threshold is exceeded.

    Uses a monkeypatched low limit (5/min) to keep the test fast.
    Sends 7 unique queries; at least 2 must be 429.

    Note: slowapi storage is process-wide. We re-enable/reset/disable the
    limiter within this test to avoid contaminating other tests.
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for i in range(7):
            resp = await client.get(
                f"/search/datasets/?q=sec-ratelimit-test-unique-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 2, (
            f"Expected >= 2 rate-limited responses with threshold=5/7 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


async def test_search_facets_rate_limited(client: AsyncClient):
    """GET /search/facets/?q=<unique-N> returns 429 after threshold is exceeded.

    fix(#1855): facets embed the query to count over the same candidate set as
    /search/datasets/, so an unlimited /search/facets/ would be a way around
    the SEC-S11 embedding-cost cap. The endpoint carries the same limit.
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for i in range(7):
            resp = await client.get(
                f"/search/facets/?q=sec-facets-ratelimit-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 2, (
            f"Expected >= 2 rate-limited responses with threshold=5/7 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


@pytest.mark.parametrize("first", ["/search/datasets/", "/search/facets/"])
async def test_search_datasets_and_facets_share_one_bucket(
    client: AsyncClient, first: str
):
    """Alternating the two search routes cannot embed twice the advertised cap.

    fix(#1855): both routes embed a novel ``q``, and slowapi scopes a plain
    ``@limiter.limit`` to the handler, so two buckets let a caller alternate
    them for 2x the limit. With one shared bucket the (limit + 1)th call is a
    429 whichever route it lands on, and the same 429 starting from either.
    """
    routes = ["/search/datasets/", "/search/facets/"]
    if first != routes[0]:
        routes.reverse()
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for i in range(6):
            resp = await client.get(
                f"{routes[i % 2]}?q=sec-shared-bucket-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)
        assert statuses == [200] * 5 + [429], (
            f"one shared 5/min bucket must 429 the sixth call across both routes "
            f"(starting from {first}); got {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


# ---------------------------------------------------------------------------
# Task 3: /datasets/{id}/related/ rate limiting (SEC-S11)
# ---------------------------------------------------------------------------


async def test_related_datasets_rate_limit_returns_429(client: AsyncClient):
    """GET /datasets/{id}/related/ returns 429 after threshold is exceeded.

    Uses a random UUID for the dataset ID — the rate limiter fires before the
    handler body reads from the DB, so a 404 from an unknown dataset ID means
    the limiter did not fire (count < threshold). Once the limiter fires, the
    response is 429 regardless of whether the dataset exists.
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    dataset_id = uuid.uuid4()
    try:
        statuses = []
        for _ in range(7):
            resp = await client.get(f"/datasets/{dataset_id}/related/")
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 2, (
            f"Expected >= 2 rate-limited responses with threshold=5/7 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


# ---------------------------------------------------------------------------
# Task 4: /settings/basemaps/ rate limiting (SEC-S10)
# ---------------------------------------------------------------------------


async def test_basemap_proxy_rate_limit_returns_429(client: AsyncClient):
    """GET /settings/basemaps/ returns 429 after threshold is exceeded.

    /settings/basemaps/ is unauthenticated by design (frontend SPA boot path).
    The rate limiter fires before the handler reads from DB, so an empty basemap
    list (in test environment) still triggers 429 once threshold is exceeded.

    Sends 10 requests with threshold=5; at least 5 must be 429.
    """
    _set_cache_limit("basemap_proxy_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for _ in range(10):
            resp = await client.get("/settings/basemaps/")
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 5, (
            f"Expected >= 5 rate-limited responses with threshold=5/10 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("basemap_proxy_rate_limit")
        _reset_limiter_storage()

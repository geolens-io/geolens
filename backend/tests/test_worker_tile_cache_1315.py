"""fix(#1315): the Procrastinate worker gets a live MVT tile cache.

``invalidate_tile_cache_for_table()`` resolves its provider through the
``get_tile_cache()`` singleton, and that singleton used to be set only by the
API lifespan.  The worker is a separate process, so ``get_tile_cache()``
returned ``None`` there and every post-swap MVT purge -- both reupload paths
and the PostGIS refresh -- was a silent no-op.  Stale tiles kept being served
for up to ``tile_cache_ttl`` after every re-upload, which is exactly what
fix(#394) B-019/VT-01 added the purge to prevent.

The fix moves ``init_tile_cache()`` into the shared ``bootstrap()`` so both
entrypoints take it from one place.  The worker deliberately does NOT take the
PERF-01 in-memory fallback: it never reads tiles, so a per-process LRU there
holds nothing, and purging it would evict nothing while logging that it had
succeeded -- the current no-op with extra steps.  With ``REDIS_URL`` unset the
worker leaves the singleton unset and says why at boot.

The live-provider half of this file needs a reachable Redis/Valkey.  Start one
with::

    docker run -d --rm --name w6-valkey -p 16379:6379 valkey/valkey

Override the endpoint with ``GEOLENS_TEST_REDIS_URL``.  Those tests skip when
nothing is listening; they cannot pass vacuously, because each asserts the
tile is readable BEFORE the purge, and ``TileCacheProvider`` swallows backend
errors into cache misses.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import socket
import uuid
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
import structlog

LIVE_REDIS_URL = os.environ.get("GEOLENS_TEST_REDIS_URL", "redis://localhost:16379/0")


def _redis_reachable(url: str) -> bool:
    """True when something accepts TCP at ``url``'s host/port."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


requires_live_redis = pytest.mark.skipif(
    not _redis_reachable(LIVE_REDIS_URL),
    reason=(
        f"no Redis/Valkey listening at {LIVE_REDIS_URL} -- start one with "
        "`docker run -d --rm --name w6-valkey -p 16379:6379 valkey/valkey`"
    ),
)


def _table() -> str:
    """A fresh `data.*`-shaped table name, so runs cannot collide in Valkey."""
    return f"w6_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def restore_tile_cache():
    """Restore the tile-cache singleton so a test cannot leak its provider."""
    from app.platform.cache import provider as cache_provider

    saved = cache_provider._tile_cache
    yield
    cache_provider._tile_cache = saved


# ---------------------------------------------------------------------------
# bootstrap() wiring -- the bug itself
# ---------------------------------------------------------------------------


def _reset_registry():
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._routers.clear()
    ext_mod._loaded = False
    ext_mod._slot_owners.clear()


def _reset_edition():
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture
def bootstrappable():
    """Run ``bootstrap()`` with its heavy steps stubbed out.

    Mirrors ``test_worker_bootstrap_parity._clean_state``: storage, the JSON
    cache and the tenancy RLS pass are patched, entry points are emptied.
    ``init_tile_cache`` is deliberately NOT patched -- it is under test.
    """
    _reset_registry()
    _reset_edition()
    with (
        patch("app.platform.extensions.entry_points", return_value=[]),
        patch("app.platform.extensions.bootstrap.init_storage"),
        patch("app.platform.extensions.bootstrap.init_cache"),
        patch("app.core.db.rls.apply_tenancy_rls_from_engine"),
    ):
        yield
    _reset_registry()
    _reset_edition()


def test_worker_bootstrap_initializes_redis_backed_tile_cache(
    bootstrappable, restore_tile_cache, monkeypatch
):
    """bootstrap(app=None) must leave a Redis-backed tile cache behind.

    This is the #1315 regression: with no tile cache in the worker process,
    ``invalidate_tile_cache_for_table`` found ``None`` and returned without
    evicting anything.
    """
    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import TileCacheProvider
    from app.platform.extensions.bootstrap import bootstrap

    monkeypatch.setattr(cfg.settings, "redis_url", "redis://localhost:6379/0")
    cache_provider._tile_cache = None

    asyncio.run(bootstrap(app=None))

    assert isinstance(cache_provider.get_tile_cache(), TileCacheProvider), (
        "fix(#1315): the worker must end bootstrap with the Redis-backed tile "
        "cache live, or every post-swap MVT purge is a silent no-op."
    )


def test_api_bootstrap_initializes_redis_backed_tile_cache(
    bootstrappable, restore_tile_cache, monkeypatch
):
    """The API keeps the provider it always had -- now via the shared path."""
    from fastapi import FastAPI

    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import TileCacheProvider
    from app.platform.extensions.bootstrap import bootstrap

    monkeypatch.setattr(cfg.settings, "redis_url", "redis://localhost:6379/0")
    cache_provider._tile_cache = None

    asyncio.run(bootstrap(app=FastAPI()))

    assert isinstance(cache_provider.get_tile_cache(), TileCacheProvider)


def test_api_bootstrap_keeps_in_memory_fallback_without_redis(
    bootstrappable, restore_tile_cache, monkeypatch
):
    """PERF-01 is unchanged for the API: no REDIS_URL still gets the LRU.

    The API both writes and reads tiles in one process, so a process-local
    cache is a real cache there.
    """
    from fastapi import FastAPI

    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import InMemoryTileCacheProvider
    from app.platform.extensions.bootstrap import bootstrap

    monkeypatch.setattr(cfg.settings, "redis_url", None)
    cache_provider._tile_cache = None

    asyncio.run(bootstrap(app=FastAPI()))

    assert isinstance(cache_provider.get_tile_cache(), InMemoryTileCacheProvider)


def test_worker_bootstrap_refuses_in_memory_fallback_without_redis(
    bootstrappable, restore_tile_cache, monkeypatch
):
    """No REDIS_URL in the worker leaves the singleton unset, on purpose.

    The worker never reads tiles, so an LRU here would hold nothing and
    purging it would evict nothing -- while logging that it had succeeded.
    Leaving it unset keeps the honest answer honest.
    """
    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.extensions.bootstrap import bootstrap

    monkeypatch.setattr(cfg.settings, "redis_url", None)
    cache_provider._tile_cache = None

    asyncio.run(bootstrap(app=None))

    assert cache_provider.get_tile_cache() is None


def test_worker_bootstrap_without_redis_logs_why_purges_cannot_land(
    bootstrappable, restore_tile_cache, monkeypatch
):
    """The unset-REDIS_URL worker states the consequence at boot.

    Acceptance (b): a stated behaviour rather than a silent no-op.
    """
    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.extensions.bootstrap import bootstrap

    monkeypatch.setattr(cfg.settings, "redis_url", None)
    cache_provider._tile_cache = None

    with structlog.testing.capture_logs() as captured:
        asyncio.run(bootstrap(app=None))

    events = [
        record
        for record in captured
        if record.get("event") == "tile_cache_unavailable_in_worker"
    ]
    assert len(events) == 1, (
        "Expected one tile_cache_unavailable_in_worker warning at worker boot; "
        f"got: {captured}"
    )
    assert events[0]["log_level"] == "warning"


def test_in_memory_fallback_flag_is_the_only_difference(
    monkeypatch, restore_tile_cache
):
    """init_tile_cache's worker mode still takes Redis when Redis is configured.

    The suppression is scoped to the fallback, not to the whole provider --
    otherwise the fix would disable the very cache it exists to reach.
    """
    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import TileCacheProvider

    monkeypatch.setattr(cfg.settings, "redis_url", "redis://localhost:6379/0")
    cache_provider._tile_cache = None

    cache_provider.init_tile_cache(in_memory_fallback=False)

    assert isinstance(cache_provider.get_tile_cache(), TileCacheProvider)


# ---------------------------------------------------------------------------
# Cross-process eviction -- acceptance (a)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["fakeredis", "live"])
def two_process_providers(request):
    """Yield a factory of tile providers sharing one backend.

    ``fakeredis`` keeps this covered in CI (one ``FakeServer``, two clients);
    ``live`` is the honest proof against a real Valkey and skips when none is
    running.
    """
    from app.platform.cache.tile_cache import TileCacheProvider

    if request.param == "fakeredis":
        import fakeredis
        import fakeredis.aioredis

        server = fakeredis.FakeServer()

        def make() -> TileCacheProvider:
            provider = TileCacheProvider(url="redis://unused:6379/0")
            provider._client = fakeredis.aioredis.FakeRedis(
                server=server, decode_responses=False
            )
            return provider

        yield make
        return

    if not _redis_reachable(LIVE_REDIS_URL):
        pytest.skip(f"no Redis/Valkey listening at {LIVE_REDIS_URL}")

    def make() -> TileCacheProvider:
        return TileCacheProvider(url=LIVE_REDIS_URL)

    yield make


@pytest.mark.asyncio
async def test_worker_purge_evicts_tiles_another_process_cached(
    two_process_providers, restore_tile_cache, monkeypatch
):
    """The worker's purge evicts entries the API process wrote.

    Acceptance (a).  Two provider instances stand in for the two processes;
    only a shared backend can carry the eviction between them.  The pre-purge
    read is a control: ``TileCacheProvider`` turns every backend error into a
    cache miss, so without it an unreachable backend would make this pass
    while proving nothing.
    """
    from app.platform.cache import provider as cache_provider
    from app.processing.ingest.tasks_common import invalidate_tile_cache_for_table

    swapped, untouched = _table(), _table()
    api_cache = two_process_providers()
    worker_cache = two_process_providers()
    monkeypatch.setattr(cache_provider, "_tile_cache", worker_cache)

    await api_cache.set(swapped, 3, 1, 2, b"pre-swap-mvt", ttl=300)
    await api_cache.set(untouched, 3, 1, 2, b"other-dataset-mvt", ttl=300)
    assert await api_cache.get(swapped, 3, 1, 2) == b"pre-swap-mvt", (
        "control: the tile must be readable before the purge, else this test "
        "cannot distinguish an eviction from an unreachable cache backend"
    )

    await invalidate_tile_cache_for_table(swapped)

    assert await api_cache.get(swapped, 3, 1, 2) is None, (
        "fix(#1315): the worker's post-swap purge must evict the tiles the API "
        "process cached for the swapped table"
    )
    assert await api_cache.get(untouched, 3, 1, 2) == b"other-dataset-mvt", (
        "the purge is scoped to one table; it must not flush the whole cache"
    )


@requires_live_redis
@pytest.mark.asyncio
async def test_worker_bootstrap_provider_evicts_api_tiles_live(
    restore_tile_cache, monkeypatch
):
    """End to end against a real Valkey, through the worker's own wiring.

    The provider doing the evicting is the one the worker's bootstrap decision
    builds (``in_memory_fallback=False``), not a hand-made instance.
    """
    from app.core import config as cfg
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import TileCacheProvider
    from app.processing.ingest.tasks_common import invalidate_tile_cache_for_table

    swapped = _table()
    api_cache = TileCacheProvider(url=LIVE_REDIS_URL)
    await api_cache.set(swapped, 6, 17, 24, b"pre-swap-mvt", ttl=300)
    assert await api_cache.get(swapped, 6, 17, 24) == b"pre-swap-mvt", (
        "control: live Valkey must actually hold the tile before the purge"
    )

    monkeypatch.setattr(cfg.settings, "redis_url", LIVE_REDIS_URL)
    cache_provider._tile_cache = None
    cache_provider.init_tile_cache(in_memory_fallback=False)
    assert isinstance(cache_provider.get_tile_cache(), TileCacheProvider)

    await invalidate_tile_cache_for_table(swapped)

    assert await api_cache.get(swapped, 6, 17, 24) is None


@requires_live_redis
@pytest.mark.asyncio
async def test_in_memory_worker_cache_would_not_have_evicted_anything(
    restore_tile_cache, monkeypatch
):
    """Why the worker refuses the LRU fallback, asserted rather than argued.

    Same scenario with an ``InMemoryTileCacheProvider`` as the worker's
    singleton: the purge reports success and the API's tile survives.  That is
    the failure mode #1315 declined to ship.
    """
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import (
        InMemoryTileCacheProvider,
        TileCacheProvider,
    )
    from app.processing.ingest.tasks_common import invalidate_tile_cache_for_table

    swapped = _table()
    api_cache = TileCacheProvider(url=LIVE_REDIS_URL)
    await api_cache.set(swapped, 6, 17, 24, b"pre-swap-mvt", ttl=300)
    assert await api_cache.get(swapped, 6, 17, 24) == b"pre-swap-mvt"

    monkeypatch.setattr(cache_provider, "_tile_cache", InMemoryTileCacheProvider())
    await invalidate_tile_cache_for_table(swapped)

    assert await api_cache.get(swapped, 6, 17, 24) == b"pre-swap-mvt", (
        "a per-process LRU in the worker cannot reach the API's cache -- if "
        "this ever evicts, the fallback suppression is no longer needed"
    )
    await api_cache.invalidate_table(swapped)


# ---------------------------------------------------------------------------
# Call-site coverage -- acceptance (c)
# ---------------------------------------------------------------------------


def test_every_worker_swap_path_purges_the_tile_cache():
    """All three post-swap paths call the purge (acceptance (c)).

    A fourth swap path added without a purge, or one of these three losing it,
    fails here rather than in production tiles.

    ``test_mvt_audit_fixes.test_reupload_tasks_invalidate_tile_cache_after_commit``
    overlaps on the two reupload sites. It is left alone deliberately: that one
    is fix(#394)'s guard over its own two call sites, this one is #1315's over
    the set that has to reach a live provider, and the PostGIS site only exists
    in the second.
    """
    from app.processing.ingest import (
        tasks_postgis_refresh,
        tasks_reupload,
    )

    call = "await invalidate_tile_cache_for_table(live_table_name)"
    counts = {
        "tasks_reupload": inspect.getsource(tasks_reupload).count(call),
        "tasks_postgis_refresh": inspect.getsource(tasks_postgis_refresh).count(call),
    }
    assert counts == {"tasks_reupload": 2, "tasks_postgis_refresh": 1}, (
        f"fix(#1315) acceptance (c): expected the three post-swap purge call "
        f"sites (reupload_file, reupload_service, refresh_postgis); got {counts}"
    )


# ---------------------------------------------------------------------------
# Drift guards -- bootstrap owns the tile cache for both entrypoints
# ---------------------------------------------------------------------------


def test_bootstrap_initializes_the_tile_cache():
    """bootstrap() is where the tile cache comes from now."""
    from app.platform.extensions import bootstrap as bootstrap_module

    assert "init_tile_cache(" in inspect.getsource(bootstrap_module.bootstrap), (
        "fix(#1315): bootstrap() must own init_tile_cache() so the API and the "
        "worker cannot drift into different tile-cache states again."
    )


def test_api_lifespan_does_not_init_the_tile_cache_directly():
    """The lifespan must not re-inline what bootstrap() owns.

    Mirrors the existing init_storage()/init_cache() drift guards in
    test_worker_bootstrap_parity.py: a second call site here is how the API
    and the worker diverged in the first place.
    """
    from app.api import main as main_module

    assert "init_tile_cache(" not in inspect.getsource(main_module.lifespan), (
        "WORK-01 / fix(#1315): the lifespan must not call init_tile_cache() "
        "directly -- bootstrap() is the single source of truth."
    )

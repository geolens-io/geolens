"""A reused table name must never let one dataset read another's tiles (#1429).

`generate_table_name` collided only against LIVE catalog rows and LIVE
relations, so a vector delete freed its table name for immediate reuse.
Every tile cache key used to be that name alone, which made the cache a
cross-dataset channel: delete private "Roads" (table ``roads``), upload a
public "Roads" that draws ``roads`` again, and the tile endpoint authorized
against the NEW dataset while serving the OLD dataset's bytes.

#1427 added a purge on delete, which removed the durable window but not the
class — an in-flight writer could restore bytes after the purge, and a purge
from one uvicorn worker never reached another worker's in-memory LRU.

The fix is a generation dimension: the dataset UUID, which is never reissued,
goes into the key after the table segment. The successor reads a different key
space, so it cannot see the predecessor's entries whether or not the purge ran,
whether or not it reached this process, and whether or not the TTL expired.
Position matters — after the table segment, so `tile:{table}:*` invalidation
still matches every key for a table.

GH-1443 has since retired freed names outright, so the reuse this file is
about can no longer happen at all. The generation key stays and stays tested:
it is what makes a name safe independently of how names are generated.
"""

import gzip
import uuid
from contextlib import asynccontextmanager

import fakeredis.aioredis
import pytest

from app.platform.cache.tile_cache import (
    InMemoryTileCacheProvider,
    TileCacheProvider,
    _safe_label,
    tile_cache_hits,
)
from app.processing.tiles.router import (
    _cluster_cache_table_key,
    _generation_table_key,
)

TABLE = "roads"
TILE = (5, 10, 15)

# Both providers implement the same get/set/invalidate_table contract, and the
# reuse hazard is a property of the KEY, so every case runs against both.
PROVIDER_KINDS = ["redis", "in_memory"]


@asynccontextmanager
async def _provider(kind: str):
    """Yield a tile cache provider, closing the fake Redis client afterwards.

    The client owns a connection pool; leaving one open per test leaks
    event-loop resources into the rest of the session.
    """
    if kind == "in_memory":
        yield InMemoryTileCacheProvider()
        return

    provider = TileCacheProvider.__new__(TileCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield provider
    finally:
        await provider._client.aclose()


def _cluster_key(table: str, dataset_id: uuid.UUID) -> str:
    return _cluster_cache_table_key(
        table, dataset_id=dataset_id, cluster_radius=50, cluster_max_zoom=12
    )


# ---------------------------------------------------------------------------
# The reuse scenario — the reason this key shape exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_successor_cannot_read_predecessor_tiles(kind):
    """Dataset B, drawing A's freed table name, never reads A's cached bytes.

    Deliberately performs NO purge between the two datasets. That models the
    two windows #1427 could not close: an in-flight writer restoring bytes
    after the purge, and a second uvicorn worker whose LRU the purge never
    reached. Under the old table-only key both would hand B the bytes A wrote.
    """
    async with _provider(kind) as provider:
        dataset_a, dataset_b = uuid.uuid4(), uuid.uuid4()

        key_a = _generation_table_key(TABLE, dataset_a)
        await provider.set(key_a, *TILE, gzip.compress(b"A private geometry"), ttl=300)
        assert await provider.get(key_a, *TILE) is not None

        key_b = _generation_table_key(TABLE, dataset_b)
        assert await provider.get(key_b, *TILE) is None, (
            "the successor of a reused table name read the deleted dataset's tile"
        )


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_successor_cannot_read_predecessor_cluster_tiles(kind):
    """Same for clustered tiles, which hang extra segments off the table key."""
    async with _provider(kind) as provider:
        dataset_a, dataset_b = uuid.uuid4(), uuid.uuid4()

        await provider.set(
            _cluster_key(TABLE, dataset_a), *TILE, gzip.compress(b"A"), ttl=300
        )

        assert await provider.get(_cluster_key(TABLE, dataset_b), *TILE) is None


def test_generation_key_places_the_id_after_the_table_segment():
    """Position is what keeps `tile:{table}:*` invalidation working."""
    dataset_id = uuid.uuid4()
    key = _generation_table_key(TABLE, dataset_id)

    assert key.startswith(f"{TABLE}:"), (
        "the dataset id must follow the table segment — a leading id would "
        "make every invalidate_table pattern miss"
    )
    assert dataset_id.hex in key
    assert _cluster_key(TABLE, dataset_id).startswith(f"{TABLE}:")


# ---------------------------------------------------------------------------
# Invalidation still reaches every key shape for a table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_invalidate_table_still_purges_every_generation(kind):
    """A per-table purge hits all key shapes, for every dataset that held the name.

    Invalidation callers pass a bare table name and know nothing about
    generations, so a purge must not become generation-scoped by accident.
    """
    async with _provider(kind) as provider:
        older, newer = uuid.uuid4(), uuid.uuid4()

        await provider.set(_generation_table_key(TABLE, older), *TILE, b"old", ttl=300)
        await provider.set(_generation_table_key(TABLE, newer), *TILE, b"new", ttl=300)
        await provider.set(_cluster_key(TABLE, newer), *TILE, b"clustered", ttl=300)
        await provider.set(
            _generation_table_key(TABLE, newer), *TILE, b"cols", ttl=300, cols_key="a,b"
        )

        await provider.invalidate_table(TABLE)

        assert await provider.get(_generation_table_key(TABLE, older), *TILE) is None
        assert await provider.get(_generation_table_key(TABLE, newer), *TILE) is None
        assert await provider.get(_cluster_key(TABLE, newer), *TILE) is None
        assert (
            await provider.get(
                _generation_table_key(TABLE, newer), *TILE, cols_key="a,b"
            )
            is None
        )


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_invalidate_table_does_not_purge_a_prefix_sibling(kind):
    """`roads` must not evict `roads_2` — the suffix generate_table_name hands out."""
    async with _provider(kind) as provider:
        dataset_id = uuid.uuid4()
        sibling = _generation_table_key("roads_2", dataset_id)

        await provider.set(sibling, *TILE, b"x", ttl=300)

        await provider.invalidate_table("roads")

        assert await provider.get(sibling, *TILE) == b"x"


# ---------------------------------------------------------------------------
# PERF-11 label (fix #1429 restores it for composite keys)
# ---------------------------------------------------------------------------


def _hits(label: str) -> float:
    return tile_cache_hits.labels(table_name=label)._value.get()


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_explicit_label_survives_a_composite_key(kind):
    """A generation/tenant/cluster key must still report its bare table name.

    Derived from the key string it collapses to `_other`, which is what the
    multi-tenant and clustered paths already did before this change.
    """
    async with _provider(kind) as provider:
        label = "label_probe"
        tile_cache_hits.labels(table_name=label)._value.set(0)
        other_before = _hits("_other")

        composite = f"{uuid.uuid4()}:{_cluster_key(label, uuid.uuid4())}"
        assert _safe_label(composite) == "_other", (
            "precondition: the router's key is not label-shaped"
        )

        await provider.set(composite, *TILE, b"tile", ttl=300)
        assert await provider.get(composite, *TILE, label=label) == b"tile"

        assert _hits(label) == 1
        assert _hits("_other") == other_before


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_explicit_label_is_still_cardinality_bounded(kind):
    """An unexpected explicit label collapses to `_other` like a derived one."""
    async with _provider(kind) as provider:
        other_before = _hits("_other")

        key = _generation_table_key(TABLE, uuid.uuid4())
        await provider.set(key, *TILE, b"tile", ttl=300)
        await provider.get(key, *TILE, label="Robert'); DROP TABLE--")

        assert _hits("_other") == other_before + 1


# ---------------------------------------------------------------------------
# Dataset-metadata cache eviction (the authorization half)
# ---------------------------------------------------------------------------


def test_delete_evicts_cached_dataset_meta_for_the_freed_name():
    """The table_name -> meta map must forget a deleted name.

    That map decides visibility, so a stale entry would let a successor
    drawing the same table name be served under the DELETED dataset's
    authorization — a window no cache key can close, because the stale entry
    is what picks the dataset before any key is built.
    """
    from app.platform.cache.provider import notify_table_invalidated
    from app.processing.tiles import router as tiles_router

    tenant = uuid.uuid4()
    sibling = "roads_2"
    # The map is module state shared with the rest of the session — seed it,
    # then put back exactly what was there.
    with tiles_router._dataset_cache_lock:
        before = dict(tiles_router._dataset_cache)
        tiles_router._dataset_cache[TABLE] = (0.0, "single-tenant entry")
        tiles_router._dataset_cache[f"{tenant}:{TABLE}"] = (0.0, "tenant entry")
        tiles_router._dataset_cache[sibling] = (0.0, "unrelated table")

    try:
        notify_table_invalidated(TABLE)

        assert TABLE not in tiles_router._dataset_cache
        assert f"{tenant}:{TABLE}" not in tiles_router._dataset_cache
        assert sibling in tiles_router._dataset_cache, (
            "eviction must not take out a table whose name merely shares a prefix"
        )
    finally:
        with tiles_router._dataset_cache_lock:
            tiles_router._dataset_cache.clear()
            tiles_router._dataset_cache.update(before)


async def test_meta_eviction_happens_after_commit_not_inside_delete_dataset():
    """`delete_dataset` must NOT evict; the endpoints must, after they commit.

    The map is built from `catalog.datasets`, which the DROP does not lock, so
    an eviction inside the still-open transaction is undone by any concurrent
    tile request — it reads the not-yet-deleted row and re-caches it. This
    pins the placement, since the ordering is invisible in a single-threaded
    test and only shows up under concurrency.
    """
    import inspect

    from app.modules.catalog.datasets.api import router as datasets_router
    from app.modules.catalog.datasets.domain import service_lifecycle

    assert "notify_table_invalidated(" not in inspect.getsource(
        service_lifecycle.delete_dataset
    ), (
        "delete_dataset does not commit, so evicting there races any concurrent "
        "tile request; the endpoints evict after their commit instead"
    )

    for handler in (
        datasets_router.delete_dataset_endpoint,
        datasets_router.bulk_delete_datasets_endpoint,
    ):
        source = inspect.getsource(handler)
        assert "notify_table_invalidated(" in source, (
            f"{handler.__name__} must evict the tile router's metadata map"
        )
        assert source.index("await db.commit()") < source.index(
            "notify_table_invalidated("
        ), f"{handler.__name__} must evict AFTER its commit, not before"


def test_notify_table_invalidated_never_raises():
    """A listener failure must not fail the delete that triggered it."""
    from app.platform.cache import provider as cache_provider

    def _explode(_table_name: str) -> None:
        raise RuntimeError("listener is broken")

    cache_provider.register_table_invalidation_listener(_explode)
    try:
        cache_provider.notify_table_invalidated(TABLE)
    finally:
        cache_provider._table_invalidation_listeners.remove(_explode)

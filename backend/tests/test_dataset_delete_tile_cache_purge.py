"""Deleting a vector dataset must purge that table's MVT tile cache.

The tile cache key was ``tile:{table}:{z}:{x}:{y}`` — no dataset id, no
content version — and ``generate_table_name`` only collided against LIVE
rows and relations, so a table name freed by a delete was immediately
reusable. Without a purge on delete, the next dataset that landed on the
freed name was authorized on its OWN visibility while being served the
deleted dataset's cached bytes for up to ``tile_cache_ttl`` (default 300s,
tunable to 86400). Delete a private dataset, re-upload a public one that
draws the same table name, and the deleted private geometry reached
anonymous callers.

Two later changes each close that independently: #1429 put the dataset id in
the cache key, and GH-1443 retires a freed name so it is never redrawn. The
purge remains the first line — the orphaned entries are dead weight until
their TTL — and these tests keep it honest.

Every other write path that changes what a table's tiles should show
already purges: metadata edits (``datasets/api/router.py``), feature edits
(``features/router.py``), reupload and PostGIS refresh
(``processing/ingest/``). Delete was the gap.

The purge closes the durable window only. An in-flight tile request can
still write pre-delete bytes back after it, and a per-worker in-memory
cache is out of its reach; both need a generation dimension in the cache
key (#1429) and are deliberately not asserted here.
"""

import gzip
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.platform.cache import provider as cache_provider
from app.platform.cache.tile_cache import TileCacheProvider

TABLE_NAME = "test_table"


class _MockStorage:
    """Storage stand-in: delete_dataset reaps originals/ and vectors/."""

    async def list(self, prefix: str) -> list[str]:
        return []

    async def delete(self, key: str) -> None:  # pragma: no cover - nothing listed
        raise AssertionError("no keys were listed")


def _mock_dataset(record_type: str, title: str) -> MagicMock:
    ds = MagicMock()
    ds.id = uuid.uuid4()
    ds.table_name = TABLE_NAME
    ds.record = MagicMock()
    ds.record.title = title
    ds.record.record_type = record_type
    return ds


@pytest.fixture
def tile_cache(monkeypatch):
    """Install a fakeredis-backed tile cache as the process singleton."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(cache_provider, "_tile_cache", provider)
    return provider


async def _seed(provider: TileCacheProvider, table: str) -> None:
    """Seed the two cache-key shapes the tile router writes for a table."""
    await provider.set(table, 5, 10, 15, gzip.compress(b"private roads"), ttl=300)
    # Clustered tiles hang extra segments off the table key
    # (_cluster_cache_table_key in processing/tiles/router.py).
    await provider.set(
        f"{table}:cluster:v3:r50:z12", 5, 10, 15, gzip.compress(b"clustered"), ttl=300
    )


async def _run_delete(dataset: MagicMock) -> str:
    from app.modules.catalog.datasets.domain.service import delete_dataset

    session = AsyncMock()
    # AsyncSession.add is synchronous — leaving it an AsyncMock makes
    # delete_dataset's retired-name write (#1443) leak an un-awaited
    # coroutine instead of recording anything.
    session.add = MagicMock()
    no_dependents = MagicMock()
    no_dependents.all.return_value = []
    session.execute = AsyncMock(return_value=no_dependents)

    with (
        patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=dataset),
        ),
        patch("app.platform.storage.provider.get_storage", return_value=_MockStorage()),
    ):
        # fix(#1847): delete_dataset returns a DatasetDeletion now; these
        # tests are about the tile purge, so hand back the table name.
        deletion = await delete_dataset(session, dataset.id, dataset.record.title)
        return deletion.table_name


@pytest.mark.asyncio
async def test_vector_delete_purges_tile_cache(tile_cache):
    """Deleting a vector dataset evicts every cached tile for its table."""
    await _seed(tile_cache, TABLE_NAME)
    assert await tile_cache.get(TABLE_NAME, 5, 10, 15) is not None

    dataset = _mock_dataset("vector_dataset", "Roads")
    assert await _run_delete(dataset) == TABLE_NAME

    assert await tile_cache.get(TABLE_NAME, 5, 10, 15) is None, (
        "a table name freed by delete is immediately reusable — leaving its "
        "tiles cached serves the deleted dataset's bytes to whoever gets the "
        "name next"
    )
    assert await tile_cache.get(f"{TABLE_NAME}:cluster:v3:r50:z12", 5, 10, 15) is None


@pytest.mark.asyncio
async def test_delete_leaves_other_tables_cached(tile_cache):
    """Purge is scoped to the deleted table, not the whole tile cache."""
    await _seed(tile_cache, TABLE_NAME)
    await _seed(tile_cache, "other_table")

    await _run_delete(_mock_dataset("vector_dataset", "Roads"))

    assert await tile_cache.get("other_table", 5, 10, 15) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("record_type", ["raster_dataset", "vrt_dataset"])
async def test_raster_delete_does_not_purge_mvt_cache(tile_cache, record_type):
    """Raster tiles come from Titiler, never from the table-keyed MVT cache.

    The raster branch also drops no table, so there is no freed name for a
    later dataset to inherit.
    """
    await _seed(tile_cache, TABLE_NAME)

    await _run_delete(_mock_dataset(record_type, "My Raster"))

    assert await tile_cache.get(TABLE_NAME, 5, 10, 15) is not None


@pytest.mark.asyncio
async def test_delete_succeeds_when_tile_cache_is_unavailable(monkeypatch):
    """No tile cache in this process (get_tile_cache() -> None) must not break delete."""
    monkeypatch.setattr(cache_provider, "_tile_cache", None)

    dataset = _mock_dataset("vector_dataset", "Roads")
    assert await _run_delete(dataset) == TABLE_NAME


@pytest.mark.asyncio
async def test_delete_survives_a_tile_cache_backend_failure(monkeypatch):
    """A purge that cannot reach its backend must not roll back the delete."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    failing_client = AsyncMock()
    failing_client.scan.side_effect = ConnectionError("Redis unavailable")
    provider._client = failing_client
    monkeypatch.setattr(cache_provider, "_tile_cache", provider)

    dataset = _mock_dataset("vector_dataset", "Roads")
    assert await _run_delete(dataset) == TABLE_NAME

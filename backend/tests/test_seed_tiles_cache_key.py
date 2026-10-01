"""A tile the seeder caches is the entry the tile route reads, and goes stale with it."""

import sys
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.platform.cache.tile_cache import InMemoryTileCacheProvider
from app.processing.tiles import pool as pool_module
from app.processing.tiles import router as tile_router
from app.processing.tiles.cache_key import tile_cache_key
from app.processing.tiles.service import get_tile
from scripts import seed_tiles
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

_COLUMNS = [{"name": "name", "type": "character varying"}]


async def _public_point_dataset(session):
    table = f"seedkey_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        column_info=_COLUMNS,
        spatial_extent_wkt="POLYGON((-75 40, -73 40, -73 41, -75 41, -75 40))",
    )
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), name text)"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO "data"."{table}" (geom, geom_4326, name) VALUES '
            "(ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), "
            "ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), 'New York')"
        )
    )
    await session.commit()
    return dataset


async def _run_seeder(monkeypatch, cache, table: str) -> None:
    monkeypatch.setattr(settings, "redis_url", "redis://seeder.invalid:6379/0")
    monkeypatch.setattr(
        pool_module,
        "init_tile_pool",
        AsyncMock(return_value=pool_module.get_tile_pool()),
    )
    monkeypatch.setattr(pool_module, "close_tile_pool", AsyncMock())
    monkeypatch.setattr(
        "app.platform.cache.tile_cache.TileCacheProvider", lambda url: cache
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_tiles.py", "--dataset", table, "--min-zoom", "0", "--max-zoom", "0"],
    )
    await seed_tiles.main()


async def _drop_table(session, table: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


async def test_a_seeded_tile_is_served_without_rendering(
    client: AsyncClient, test_db_session, monkeypatch
):
    dataset = await _public_point_dataset(test_db_session)
    table = dataset.table_name
    cache = InMemoryTileCacheProvider()
    renderer = AsyncMock(side_effect=AssertionError("the tile route rendered"))
    try:
        await _run_seeder(monkeypatch, cache, table)
        rendered = await get_tile(pool_module.get_tile_pool(), table, 0, 0, 0, _COLUMNS)
        assert rendered is not None

        with (
            patch.object(tile_router, "get_tile_cache", return_value=cache),
            patch.object(tile_router, "get_tile", renderer),
        ):
            served = await client.get(f"/tiles/data.{table}/0/0/0.pbf")

        assert served.status_code == 200, served.text
        assert served.content == rendered
        renderer.assert_not_awaited()
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


async def test_a_seeded_tile_is_not_served_after_the_publication_changes(
    client: AsyncClient, test_db_session, monkeypatch
):
    dataset = await _public_point_dataset(test_db_session)
    table = dataset.table_name
    cache = InMemoryTileCacheProvider()
    renderer = AsyncMock(return_value=b"rendered after the transition")
    try:
        await _run_seeder(monkeypatch, cache, table)
        await test_db_session.execute(
            text(
                "UPDATE catalog.datasets SET publication_version = "
                "publication_version + 1 WHERE id = :id"
            ),
            {"id": dataset.id},
        )
        await test_db_session.commit()
        tile_router._evict_dataset_meta(table)

        with (
            patch.object(tile_router, "get_tile_cache", return_value=cache),
            patch.object(tile_router, "get_tile", renderer),
        ):
            served = await client.get(f"/tiles/data.{table}/0/0/0.pbf")

        assert served.status_code == 200, served.text
        assert served.content == b"rendered after the transition"
        renderer.assert_awaited_once()
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


async def _seed_tiles(cache, dataset, tiles):
    return await seed_tiles._seed_dataset(
        pool=pool_module.get_tile_pool(),
        cache=cache,
        dataset_id=dataset.id,
        table_name=dataset.table_name,
        publication_version=0,
        tile_cache_version=1,
        columns=_COLUMNS,
        tile_columns=None,
        cache_ttl=60,
        all_tiles=tiles,
        concurrency=1,
        dry_run=False,
    )


async def test_a_dataset_deleted_during_seeding_gets_no_cache_entry(
    test_db_session,
):
    dataset = await _public_point_dataset(test_db_session)
    table = dataset.table_name
    cache = InMemoryTileCacheProvider()
    key = tile_cache_key(table, dataset.id, 0, 1, None)
    try:
        await test_db_session.execute(
            text("DELETE FROM catalog.datasets WHERE id = :id"), {"id": dataset.id}
        )
        await test_db_session.commit()

        seeded, errors = await _seed_tiles(cache, dataset, [(0, 0, 0)])

        assert (seeded, errors) == (0, 1)
        assert await cache.get(key, 0, 0, 0) is None
    finally:
        await _drop_table(test_db_session, table)


@pytest.mark.parametrize("column", ["tile_cache_version", "publication_version"])
async def test_seeding_stops_when_the_dataset_changes_generation(
    test_db_session, capsys, column
):
    dataset = await _public_point_dataset(test_db_session)
    table = dataset.table_name
    key = tile_cache_key(table, dataset.id, 0, 1, None)
    tiles = [(1, 0, 0), (1, 1, 0), (1, 0, 1), (1, 1, 1), (0, 0, 0)]

    class _ChangesTheDatasetAfterTwoWrites(InMemoryTileCacheProvider):
        writes = 0

        async def set(self, *args, **kwargs):
            await super().set(*args, **kwargs)
            self.writes += 1
            if self.writes == 2:
                await test_db_session.execute(
                    text(
                        f"UPDATE catalog.datasets SET {column} = {column} + 1 "
                        "WHERE id = :id"
                    ),
                    {"id": dataset.id},
                )
                await test_db_session.commit()

    cache = _ChangesTheDatasetAfterTwoWrites()
    try:
        seeded, errors = await _seed_tiles(cache, dataset, tiles)

        assert (seeded, errors) == (2, 3)
        assert cache.writes == 2
        for z, x, y in tiles[2:]:
            assert await cache.get(key, z, x, y) is None
        assert "Stopped" in capsys.readouterr().out
    finally:
        await _drop_table(test_db_session, table)

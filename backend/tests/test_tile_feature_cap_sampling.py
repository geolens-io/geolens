"""A tile past the feature cap keeps a sample spread across it and says so."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.cache.tile_cache import InMemoryTileCacheProvider
from app.processing.tiles import router as tile_router
from app.processing.tiles import service as tile_service
from app.processing.tiles.pool import get_tile_pool
from app.processing.tiles.responses import TILE_SAMPLED_HEADER
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

_CAP = 10
# Twice the cap in each half of tile 0/0/0, the west half loaded first, so every
# gid a gid-ordered cap would keep lies west of lon 0.
_PER_HALF = 2 * _CAP
_GEOMETRY = {
    "Point": "ST_SetSRID(ST_MakePoint(lon, 10), 4326)",
    "Polygon": "ST_MakeEnvelope(lon, 10, lon + 1, 11, 4326)",
}


async def _create_west_first_table(session, geometry_type: str) -> str:
    table = f"tilecap_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            f"geom_4326 geometry({geometry_type}, 4326))"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO "data"."{table}" (geom_4326) '
            f"SELECT {_GEOMETRY[geometry_type]} FROM generate_series(0, :n - 1) AS i, "
            "LATERAL (SELECT CASE WHEN i < :half THEN -170 + i * 4 "
            "ELSE 10 + (i - :half) * 4 END AS lon) AS p ORDER BY i"
        ),
        {"n": 2 * _PER_HALF, "half": _PER_HALF},
    )
    await session.commit()
    return table


async def _drop_table(session, table: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


async def _kept_tile_x(table: str) -> list[float]:
    """Tile x of each feature the shipped query keeps in 0/0/0 (2048 = lon 0)."""
    query = tile_service._build_tile_query(table, [])
    head, sep, _tail = query.rpartition("SELECT\n    ST_AsMVT")
    assert sep, "tile query tail changed; update this test's split point"
    rows = await get_tile_pool().fetch(
        head + "SELECT $4::text AS layer, ST_X(ST_Centroid(geom)) AS x "
        "FROM mvtgeom WHERE geom IS NOT NULL",
        0,
        0,
        0,
        f"data.{table}",
    )
    return [row["x"] for row in rows]


@pytest.mark.parametrize("geometry_type", ["Point", "Polygon"])
async def test_a_capped_tile_keeps_features_across_the_tile(
    test_db_session, monkeypatch, geometry_type
):
    monkeypatch.setattr(tile_service, "_TILE_FEATURE_LIMIT", _CAP)
    table = await _create_west_first_table(test_db_session, geometry_type)
    try:
        xs = await _kept_tile_x(table)
        tile = await tile_service.get_tile(get_tile_pool(), table, 0, 0, 0, [])
    finally:
        await _drop_table(test_db_session, table)

    assert len(xs) == _CAP
    assert any(x < 2048 for x in xs) and any(x > 2048 for x in xs), xs
    assert tile is not None and tile.sampled


async def test_a_tile_under_the_cap_is_not_sampled(test_db_session):
    table = await _create_west_first_table(test_db_session, "Point")
    try:
        xs = await _kept_tile_x(table)
        tile = await tile_service.get_tile(get_tile_pool(), table, 0, 0, 0, [])
    finally:
        await _drop_table(test_db_session, table)

    assert len(xs) == 2 * _PER_HALF
    assert tile is not None and not tile.sampled


async def _public_layer(session) -> str:
    table = await _create_west_first_table(session, "Point")
    await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=2 * _PER_HALF,
        column_info=[],
        spatial_extent_wkt="POLYGON((-170 10, 90 10, 90 11, -170 11, -170 10))",
    )
    return table


async def test_the_sampled_header_survives_the_cache_and_revalidation(
    client: AsyncClient, test_db_session, monkeypatch
):
    monkeypatch.setattr(tile_service, "_TILE_FEATURE_LIMIT", _CAP)
    table = await _public_layer(test_db_session)
    url = f"/tiles/data.{table}/0/0/0.pbf"
    render = AsyncMock(side_effect=tile_service.get_tile)
    try:
        with (
            patch.object(
                tile_router, "get_tile_cache", return_value=InMemoryTileCacheProvider()
            ),
            patch.object(tile_router, "get_tile", render),
        ):
            rendered = await client.get(url)
            cached = await client.get(url)
            revalidated = await client.get(
                url, headers={"If-None-Match": rendered.headers["etag"]}
            )
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)

    assert rendered.status_code == 200, rendered.text
    assert render.await_count == 1
    for response in (rendered, cached, revalidated):
        assert response.headers.get(TILE_SAMPLED_HEADER) == "true"
        assert TILE_SAMPLED_HEADER in response.headers["access-control-expose-headers"]
    assert cached.content == rendered.content
    assert revalidated.status_code == 304


async def test_a_tile_under_the_cap_has_no_sampled_header(
    client: AsyncClient, test_db_session
):
    table = await _public_layer(test_db_session)
    url = f"/tiles/data.{table}/0/0/0.pbf"
    try:
        with patch.object(
            tile_router, "get_tile_cache", return_value=InMemoryTileCacheProvider()
        ):
            rendered = await client.get(url)
            cached = await client.get(url)
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)

    assert rendered.status_code == 200, rendered.text
    assert cached.status_code == 200
    assert TILE_SAMPLED_HEADER not in rendered.headers
    assert TILE_SAMPLED_HEADER not in cached.headers

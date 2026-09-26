"""A feature edit's response must carry the version its tile reload needs.

The tile routes treat a request's ``_v`` as a freshness signal only when it
is a stored ``tile_cache_version`` or a record ``updated_at`` timestamp
(``app.processing.tiles.router._client_saw_newer_state``). Without
``REDIS_URL``, each API worker keeps its own process-local dataset snapshot
cache (``_dataset_cache``) and its own tile-bytes cache, so a write handled
by one worker never reaches another's. Only a request whose ``_v`` names a
newer state forces that other worker to re-read the row.

Every feature mutation response now carries the dataset's
``tile_cache_version`` after its write committed -- create, replace and
patch in the JSON body, delete on the ``X-GeoLens-Tile-Cache-Version``
header since a 204 has no body -- so the editor's post-edit tile reload can
send a spelling the routes actually recognise.
"""

import uuid
from unittest.mock import patch

import pytest
from cachetools import LRUCache
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.features.schemas import TILE_CACHE_VERSION_HEADER
from app.platform.cache.tile_cache import InMemoryTileCacheProvider
from app.processing.tiles import router as tile_router

from tests.factories import create_dataset, get_user_id

NEW_YORK = {"type": "Point", "coordinates": [-74.0, 40.7]}
PARIS = {"type": "Point", "coordinates": [2.35, 48.85]}
LONDON = {"type": "Point", "coordinates": [-0.13, 51.51]}


async def _seed_point_dataset(session):
    """A public point dataset holding one feature (New York)."""
    admin_id = await get_user_id(session, "admin")
    table = f"edit2310_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        column_info=[{"name": "name", "type": "character varying"}],
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


async def _drop_table(session, table_name: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table_name}"'))
    await session.commit()


async def _row_tile_cache_version(session, dataset_id) -> int:
    return await session.scalar(
        text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
        {"id": dataset_id},
    )


async def test_each_mutation_response_carries_the_version_the_tile_route_will_see(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Create, replace, patch and delete each return the row's post-commit version.

    A real DB round trip for every one of the four responses: the value
    (create/replace/patch in the JSON body, delete on a response header
    since its 204 has no body) must match what a fresh read of the dataset
    row shows immediately after the same request committed.
    """
    dataset = await _seed_point_dataset(test_db_session)
    try:
        create_resp = await client.post(
            f"/datasets/{dataset.id}/features/",
            json={"geometry": PARIS, "properties": {"name": "Paris"}},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201, create_resp.text
        gid = create_resp.json()["id"]
        assert create_resp.json()["tile_cache_version"] == (
            await _row_tile_cache_version(test_db_session, dataset.id)
        )

        put_resp = await client.put(
            f"/datasets/{dataset.id}/features/{gid}",
            json={"geometry": LONDON, "properties": {"name": "London"}},
            headers=admin_auth_header,
        )
        assert put_resp.status_code == 200, put_resp.text
        assert put_resp.json()["tile_cache_version"] == (
            await _row_tile_cache_version(test_db_session, dataset.id)
        )

        patch_resp = await client.patch(
            f"/datasets/{dataset.id}/features/{gid}",
            json={"properties": {"name": "London, again"}},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 200, patch_resp.text
        assert patch_resp.json()["tile_cache_version"] == (
            await _row_tile_cache_version(test_db_session, dataset.id)
        )

        delete_resp = await client.delete(
            f"/datasets/{dataset.id}/features/{gid}",
            headers=admin_auth_header,
        )
        assert delete_resp.status_code == 204, delete_resp.text
        delete_version = int(delete_resp.headers[TILE_CACHE_VERSION_HEADER])
        assert delete_version == (
            await _row_tile_cache_version(test_db_session, dataset.id)
        )

        # Every write bumped the counter by exactly one, so the four
        # responses pin four consecutive versions rather than a value that
        # happened to match by coincidence (e.g. always echoing the same row).
        versions = [
            create_resp.json()["tile_cache_version"],
            put_resp.json()["tile_cache_version"],
            patch_resp.json()["tile_cache_version"],
            delete_version,
        ]
        assert versions == list(range(versions[0], versions[0] + 4))
    finally:
        await _drop_table(test_db_session, dataset.table_name)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
async def test_a_stale_worker_serves_the_edit_once_a_tile_request_carries_its_version(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Two API workers share nothing without REDIS_URL -- the edit's own
    response is the only way the one that DIDN'T handle it learns to re-read.

    Worker B stands for a second uvicorn process: its own dataset-snapshot
    cache and its own tile-bytes cache, both primed by serving this
    dataset's tiles once, before the edit. The edit itself runs as worker A
    would -- through the feature router, which never touches worker B's
    cache objects, exactly as a second OS process couldn't either. Worker
    B's snapshot stays stale until a request's `_v` names a newer version
    than the one it cached.
    """
    dataset = await _seed_point_dataset(test_db_session)
    table = dataset.table_name
    url = f"/tiles/data.{table}/0/0/0.pbf"

    worker_b_dataset_cache: LRUCache = LRUCache(maxsize=256)
    worker_b_tile_cache = InMemoryTileCacheProvider()
    try:
        with (
            patch.object(tile_router, "_dataset_cache", worker_b_dataset_cache),
            patch.object(
                tile_router, "get_tile_cache", return_value=worker_b_tile_cache
            ),
        ):
            before = await client.get(url)
            assert before.status_code == 200, before.text

        # Worker A handles the edit.
        create_resp = await client.post(
            f"/datasets/{dataset.id}/features/",
            json={"geometry": PARIS, "properties": {"name": "Paris"}},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201, create_resp.text
        tile_version = create_resp.json()["tile_cache_version"]
        assert isinstance(tile_version, int)

        with (
            patch.object(tile_router, "_dataset_cache", worker_b_dataset_cache),
            patch.object(
                tile_router, "get_tile_cache", return_value=worker_b_tile_cache
            ),
        ):
            # No `_v`: worker B's cached snapshot and tile bytes are both
            # still the pre-edit state -- the bug this fix closes.
            stale = await client.get(url)
            assert stale.content == before.content

            # The version the edit committed forces worker B to re-read.
            fresh = await client.get(url, params={"_v": str(tile_version)})
        assert fresh.status_code == 200, fresh.text
        assert fresh.content != before.content
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)

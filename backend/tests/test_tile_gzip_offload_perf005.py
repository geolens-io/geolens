"""PERF-005 regression — MVT gzip compression must be offloaded off the event loop.

`backend/app/processing/tiles/router.py` compressed each freshly-rendered MVT
tile inline in the async handler with ``gzip.compress(tile_data, compresslevel=6)``
on every cache MISS. gzip level-6 is CPU-bound; wide low-zoom tiles (up to the
50K-feature LIMIT) can be hundreds of KB, so the synchronous compress stalled the
single event-loop thread and serialized concurrent tile responses under load.

The fix dispatches the compression to a worker thread via ``asyncio.to_thread``
(the convention used across the processing modules — see
``processing/ingest/tasks_raster.py`` etc.). These tests pin that structural
change: a cache-MISS tile response must route ``gzip.compress`` through
``asyncio.to_thread`` rather than calling it inline on the loop.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied

Verify fail-before: revert the two ``await asyncio.to_thread(gzip.compress, ...)``
edits in router.py back to ``gzip.compress(tile_data, compresslevel=6)`` and both
tests FAIL (gzip.compress is never seen by the to_thread spy).
"""

import asyncio
import gzip
import uuid
from unittest.mock import patch

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.conftest import _run_with_too_many_clients_retry
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers (mirror test_tiles.py)
# ---------------------------------------------------------------------------


async def _create_tile_test_dataset(session, *, created_by, table_name):
    record = Record(
        title="PERF-005 gzip-offload dataset",
        summary="Dataset for the gzip-offload regression",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="test.geojson",
        column_info=[{"name": "gid", "type": "integer"}],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_point_data_table(session, table_name: str) -> None:
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom GEOMETRY(Point, 3857),"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_4326 "
            f"ON data.{table_name} USING GIST (geom_4326)"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES ("
            f"  'p', ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            f")"
        )
    )
    await session.commit()


async def _cleanup_data_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


@pytest.fixture
async def _init_tile_pool_for_tests():
    """Create a real asyncpg pool for tile rendering (lifespan does not run under ASGITransport)."""
    import app.processing.tiles.pool as pool_module

    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await _run_with_too_many_clients_retry(
        lambda: asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)
    )
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = None


def _make_to_thread_spy():
    """Return (spy, gzip_calls): a to_thread wrapper that records gzip.compress dispatches.

    Delegates every call to the real ``asyncio.to_thread`` so tile bytes are
    unchanged; only records when ``gzip.compress`` is the offloaded callable.
    """
    real_to_thread = asyncio.to_thread
    gzip_calls: list[tuple] = []

    async def _spy(func, /, *args, **kwargs):
        if func is gzip.compress:
            gzip_calls.append((args, kwargs))
        return await real_to_thread(func, *args, **kwargs)

    return _spy, gzip_calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileGzipOffload:
    async def test_vector_tile_miss_offloads_gzip_to_thread(
        self, client: AsyncClient, test_db_session
    ):
        """A cache-MISS vector tile must compress via asyncio.to_thread(gzip.compress)."""
        table_name = f"perf005_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_point_data_table(test_db_session, table_name)

        spy, gzip_calls = _make_to_thread_spy()
        try:
            with patch("app.processing.tiles.router.asyncio.to_thread", spy):
                resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")

            assert resp.status_code == 200
            assert resp.headers["content-encoding"] == "gzip"
            # The compression must have been dispatched to a thread, not run inline.
            assert gzip_calls, (
                "gzip.compress was not offloaded via asyncio.to_thread on the "
                "vector-tile cache-MISS path (PERF-005 regression)"
            )
            # compresslevel 6 is forwarded as the positional second arg.
            args, _kwargs = gzip_calls[0]
            assert args[1] == 6
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_cluster_tile_miss_offloads_gzip_to_thread(
        self, client: AsyncClient, test_db_session
    ):
        """A cache-MISS cluster tile must compress via asyncio.to_thread(gzip.compress)."""
        table_name = f"perf005c_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        await _create_point_data_table(test_db_session, table_name)

        spy, gzip_calls = _make_to_thread_spy()
        try:
            with patch("app.processing.tiles.router.asyncio.to_thread", spy):
                resp = await client.get(f"/tiles/clusters/data.{table_name}/0/0/0.pbf")

            assert resp.status_code == 200
            assert resp.headers["content-encoding"] == "gzip"
            assert gzip_calls, (
                "gzip.compress was not offloaded via asyncio.to_thread on the "
                "cluster-tile cache-MISS path (PERF-005 regression)"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

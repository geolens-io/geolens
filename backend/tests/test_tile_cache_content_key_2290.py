"""A worker-side table swap reaches an API tile cache the worker cannot purge.

With ``REDIS_URL`` unset the worker has no tile cache, so the purge a re-upload
runs after its swap never reaches the API process's in-memory LRU. A vector
tile key that stayed the same across the swap kept serving the pre-swap bytes
for the whole ``tile_cache_ttl``. The vector and cluster keys now carry the
dataset's ``tile_cache_version``, which the swap rolls, so the API stops
reading the old entries once it re-reads the dataset row.
"""

import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.cache import provider as cache_provider
from app.platform.cache.tile_cache import InMemoryTileCacheProvider
from app.platform.jobs.models import IngestJob
from app.processing.tiles import router as tile_router
from app.processing.tiles.router import _generation_table_key

from tests.factories import create_dataset, get_user_id
from tests.test_tile_cache_generation_key_1429 import PROVIDER_KINDS, _provider

TILE_ROUTES = [
    "/tiles/data.{table}/0/0/0.pbf",
    "/tiles/clusters/data.{table}/0/0/0.pbf",
]


async def _seed(session, tmp_path):
    """A public point dataset holding New York, and a queued re-upload of it."""
    from app.platform.refresh.service import create_pending_run

    admin_id = await get_user_id(session, "admin")
    table = f"swap2290_{uuid.uuid4().hex[:10]}"
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

    source = tmp_path / "update.geojson"
    source.write_text('{"type":"FeatureCollection","features":[]}')
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="update.geojson",
        file_path=str(source),
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.flush()
    await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    await session.refresh(job)
    return admin_id, dataset, job


async def _stage_three_cities(file_path, staging_tn, db_conn_str, **kwargs):
    """Stands in for the GDAL subprocess: stages the replacement rows for real."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "data"."{staging_tn}" '
                "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "data"."{staging_tn}" (geom, name) VALUES '
                "(ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), 'Paris'), "
                "(ST_SetSRID(ST_MakePoint(-0.13, 51.51), 4326), 'London'), "
                "(ST_SetSRID(ST_MakePoint(13.40, 52.52), 4326), 'Berlin')"
            )
        )
        await session.commit()


async def _reupload_in_the_worker(admin_id, dataset, job, monkeypatch) -> None:
    """Run the worker's file re-upload the way a ``REDIS_URL``-less boot leaves it.

    ``init_tile_cache(in_memory_fallback=False)`` leaves the worker's singleton
    unset, so the swap's own purge finds no cache to purge.
    """
    from app.processing.ingest.tasks import reupload_file

    monkeypatch.setattr(cache_provider, "_tile_cache", None)
    ogrinfo = {
        "srid": 4326,
        "geometry_type": "Point",
        "layer_name": "update",
        "feature_count": 3,
        "columns": [{"name": "name", "type": "String"}],
    }
    storage = AsyncMock()
    with contextlib.ExitStack() as stack:
        for target, replacement in (
            (
                "app.processing.ingest.service.resolve_file_path",
                AsyncMock(side_effect=lambda path, job_id: path),
            ),
            (
                "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
                AsyncMock(),
            ),
            ("app.processing.ingest.ogr.run_ogrinfo", AsyncMock(return_value=ogrinfo)),
            (
                "app.processing.ingest.ogr.run_ogr2ogr",
                AsyncMock(side_effect=_stage_three_cities),
            ),
            # A real grant would put this module in the tenancy test group.
            ("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
            ("app.processing.ingest.tasks_staging.get_storage", lambda: storage),
        ):
            stack.enter_context(patch(target, new=replacement))
        await reupload_file(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            file_path=job.file_path,
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
        )


async def _swap_landed(session, dataset_id, job_id) -> tuple[str, int]:
    job_status = await session.scalar(
        text("SELECT status FROM catalog.ingest_jobs WHERE id = :id"), {"id": job_id}
    )
    version = await session.scalar(
        text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
        {"id": dataset_id},
    )
    return job_status, version


def _age_metadata_snapshot(table_name: str) -> None:
    """Put the table's cached snapshot past its TTL, leaving the tile cache alone."""
    with tile_router._dataset_cache_lock:
        cached_at, meta = tile_router._dataset_cache[table_name]
        tile_router._dataset_cache[table_name] = (
            cached_at - tile_router._DATASET_CACHE_TTL,
            meta,
        )


async def _drop_table(session, table_name: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table_name}"'))
    await session.commit()


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize("route", TILE_ROUTES)
async def test_a_swap_the_worker_cannot_purge_is_served_once_the_row_is_re_read(
    client: AsyncClient, test_db_session, tmp_path, monkeypatch, route: str
):
    admin_id, dataset, job = await _seed(test_db_session, tmp_path)
    table = dataset.table_name
    url = route.format(table=table)
    api_cache = InMemoryTileCacheProvider()
    try:
        with patch.object(tile_router, "get_tile_cache", return_value=api_cache):
            before = await client.get(url)
            assert before.status_code == 200, before.text

            await _reupload_in_the_worker(admin_id, dataset, job, monkeypatch)
            assert await _swap_landed(test_db_session, dataset.id, job.id) == (
                "complete",
                2,
            )

            # The stale read: nothing reached this process's cache.
            within_snapshot = await client.get(url)
            assert within_snapshot.content == before.content

            _age_metadata_snapshot(table)
            after = await client.get(url)

        with patch.object(tile_router, "get_tile_cache", return_value=None):
            tile_router._evict_dataset_meta(table)
            uncached = await client.get(url)

        assert after.status_code == 200, after.text
        assert after.content != before.content, (
            "the API served the pre-swap tile after re-reading the dataset row"
        )
        assert after.content == uncached.content
    finally:
        tile_router._evict_dataset_meta(table)
        await _drop_table(test_db_session, table)


def test_the_content_version_is_its_own_key_after_the_table_segment():
    dataset_id = uuid.uuid4()
    before = _generation_table_key("roads", dataset_id, 0, 1)
    after = _generation_table_key("roads", dataset_id, 0, 2)

    assert before != after
    assert before.startswith("roads:") and after.startswith("roads:")


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
async def test_invalidate_table_purges_every_content_version(kind):
    """A purge that can reach the cache still takes out every version's entries."""
    async with _provider(kind) as provider:
        dataset_id = uuid.uuid4()
        keys = [_generation_table_key("roads", dataset_id, 0, v) for v in (1, 2)]
        for key in keys:
            await provider.set(key, 5, 10, 15, b"tile", ttl=300)

        await provider.invalidate_table("roads")

        for key in keys:
            assert await provider.get(key, 5, 10, 15) is None

"""Each worker swap publishes N+2 behind an edit that published N+1 (#1911)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

import app.core.db as db_module
from app.modules.catalog.datasets.domain.models import Dataset
from app.processing.ingest.tasks_common import _apply_reupload_swap
from app.processing.ingest.tasks_raster_replace import reupload_raster
from app.processing.raster.models import RasterAsset
from tests import test_feature_lock_order_1847 as lock_order
from tests.factories import get_user_id
from tests.test_feature_lock_order_1847 import (
    _await_waiter_on,
    _published_version,
    _seed_dataset,
)
from tests.test_raster_replace_1221 import (
    _geotiff_bytes,
    _make_live_raster,
    _purge,
    _queue_replace_job,
)
from tests.test_raster_replace_1221 import raster_storage as raster_storage

_SWAP_METADATA = {
    "srid": 4326,
    "geometry_type": "Point",
    "feature_count": 1,
    "extent_wkt": None,
    "column_info": [{"name": "name", "type": "character varying"}],
}

# Complete, because the row outlives the swap on the shared per-worker
# database and a partial detail fails response validation elsewhere.
_QUALITY = {
    "overall": 90.0,
    "metadata_completeness": 90.0,
    "geometry_validity": 100.0,
    "attribute_completeness": 90.0,
    "crs_defined": 100.0,
}


async def _parked_statement(probe, holder_xid: str) -> str:
    """The statement of whichever backend is queued behind *holder_xid*."""
    query = await probe.scalar(
        text(
            "SELECT string_agg(query, ' | ') FROM pg_stat_activity WHERE pid IN ("
            "SELECT pid FROM pg_locks WHERE NOT granted "
            "AND locktype = 'transactionid' AND transactionid::text = :xid)"
        ),
        {"xid": holder_xid},
    )
    await probe.rollback()
    return query or ""


async def _overlap(holder, probe, dataset_id, swap_coro):
    """Hold the row, park the swap on its acquisition, bump, commit, finish.

    FOR NO KEY UPDATE, so the job-row KEY SHARE does not release the barrier.
    """
    before = await holder.scalar(
        select(Dataset.tile_cache_version)
        .where(Dataset.id == dataset_id)
        .with_for_update(key_share=True)
    )
    holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))
    task = asyncio.create_task(swap_coro)
    try:
        await _await_waiter_on(probe, holder_xid)
        parked = await _parked_statement(probe, holder_xid)
        assert "FOR UPDATE" in parked and "catalog.datasets" in parked, (
            f"the barrier released on {parked!r}, not on the swap's catalog acquisition"
        )
        first = await holder.scalar(
            text(
                "UPDATE catalog.datasets SET tile_cache_version = "
                "tile_cache_version + 1 WHERE id = :d RETURNING tile_cache_version"
            ),
            {"d": dataset_id},
        )
        await holder.commit()
    except BaseException:
        await holder.rollback()
        task.cancel()
        raise
    result = await task
    assert first == before + 1
    return before, result


def _message(before: int, published: int) -> str:
    return (
        f"the swap published {published}. The edit committed {before + 1} while "
        f"the swap was parked, so the swap must publish {before + 2}: an "
        "absolute write from the instance loaded before the wait re-publishes "
        "the edit's version."
    )


@pytest.fixture
async def vector_dataset(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    seeded = await _seed_dataset(test_db_session, created_by=admin_id)
    yield seeded, admin_id
    for suffix in ("", "_staging", "_old"):
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{seeded.table_name}{suffix}")
        )
    await test_db_session.commit()
    await _purge(test_db_session, dataset_id=seeded.id, record_id=seeded.record_id)


class TestTheReuploadSwapPublishesTheNextVersion:
    async def test_behind_a_committed_edit(self, vector_dataset, test_db_session):
        seeded, admin_id = vector_dataset
        dataset = (
            await test_db_session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == seeded.id)
            )
        ).scalar_one()
        staging = f"{dataset.table_name}_staging"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{staging} ("
                "gid SERIAL PRIMARY KEY, "
                "geom geometry(Point, 4326), "
                "geom_4326 geometry(Geometry, 4326), "
                "name TEXT)"
            )
        )
        await test_db_session.commit()

        with (
            patch(
                "app.processing.ingest.metadata.refresh_attribute_metadata",
                new_callable=AsyncMock,
            ),
            patch(
                "app.processing.ingest.metadata.compute_quality_score",
                new_callable=AsyncMock,
            ) as mock_quality,
        ):
            mock_quality.return_value = _QUALITY
            async with (
                db_module.async_session() as holder,
                db_module.async_session() as probe,
            ):
                before, _version = await _overlap(
                    holder,
                    probe,
                    dataset.id,
                    _apply_reupload_swap(
                        test_db_session,
                        dataset=dataset,
                        staging_table=staging,
                        metadata=_SWAP_METADATA,
                        sample_values={"name": ["A"]},
                        user_id=str(admin_id),
                        source_filename="again.geojson",
                        source_format="geojson",
                        original_srid=4326,
                    ),
                )
            await test_db_session.commit()

        published = await _published_version(dataset.id)
        assert published == before + 2, _message(before, published)
        assert dataset.tile_cache_version == published


class TestTheRasterReplacePublishesTheNextVersion:
    async def test_behind_a_committed_edit(
        self, test_db_session, raster_storage, tmp_path, monkeypatch
    ):
        # The conversion runs before the swap reaches its lock wait.
        monkeypatch.setattr(lock_order, "_BARRIER_POLLS", 3000)
        admin_id = await get_user_id(test_db_session, "admin")
        live = await _make_live_raster(
            test_db_session, raster_storage, created_by=admin_id
        )
        dataset_id = live.dataset.id
        record_id = live.dataset.record_id
        old_cog_key = live.cog_key
        source = tmp_path / "replacement.tif"
        source.write_bytes(_geotiff_bytes(seed=1911))
        job = await _queue_replace_job(
            test_db_session,
            dataset_id=dataset_id,
            user_id=admin_id,
            file_path=str(source),
        )
        try:
            async with (
                db_module.async_session() as holder,
                db_module.async_session() as probe,
            ):
                before, _ = await _overlap(
                    holder,
                    probe,
                    dataset_id,
                    reupload_raster.func(
                        job_id=str(job.id),
                        dataset_id=str(dataset_id),
                        file_path=str(source),
                        user_id=str(admin_id),
                        attempt_id=str(job.attempt_id),
                    ),
                )

            published = await _published_version(dataset_id)
            assert published == before + 2, _message(before, published)
            test_db_session.expire_all()
            asset = (
                await test_db_session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
                )
            ).scalar_one()
            assert asset.asset_uri != old_cog_key, "the replace did not swap"
        finally:
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)


class TestNoWorkerSwapWritesAnAbsoluteTileVersion:
    """The two swap doors call the atomic spelling, not the instance method."""

    def test_the_swap_modules_call_the_atomic_bump(self):
        import ast
        import inspect

        from app.processing.ingest import (
            tasks_common,
            tasks_raster_replace,
            tasks_raster_swap,
        )

        scan = lock_order.TestNoCatalogModuleWritesAnAbsoluteTileVersion
        for module in (tasks_common, tasks_raster_replace, tasks_raster_swap):
            tree = ast.parse(inspect.getsource(module))
            assert not scan._calls_named(tree, scan.ABSOLUTE), (
                f"{module.__name__} writes an absolute tile_cache_version"
            )
        for module in (tasks_common, tasks_raster_replace):
            tree = ast.parse(inspect.getsource(module))
            assert len(scan._calls_named(tree, scan.ATOMIC)) == 1, module.__name__

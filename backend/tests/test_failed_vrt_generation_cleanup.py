"""A failed VRT regeneration's objects stay owed until a sweep deletes them."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.core.db as db_module
from app.platform.jobs.models import UNPUBLISHED_STORAGE_KEYS_FIELD, IngestJob
from app.platform.jobs.sweep import fail_stale_jobs
from tests.test_raster_replace_1221 import _purge_vrt
from tests.test_raster_replace_1221 import raster_storage as raster_storage
from tests.test_superseded_vrt_generation import (
    _left,
    _live_keys,
    _queue_regeneration,
    _regenerate,
    _vrt_with_quicklooks,
)

pytestmark = pytest.mark.anyio


async def _job(job_id) -> tuple[str, dict]:
    async with db_module.async_session() as session:
        row = (
            await session.execute(
                select(IngestJob.status, IngestJob.user_metadata).where(
                    IngestJob.id == job_id
                )
            )
        ).one()
    return row[0], row[1] or {}


async def test_a_failed_regeneration_whose_cleanup_failed_is_reaped_by_the_sweep(
    test_db_session, raster_storage, monkeypatch
) -> None:
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    generation_vrt = f"rasters/{ids[0]}/generations/{generation_id}/source.vrt"
    real_put, real_delete = raster_storage.put, raster_storage.delete

    async def _put_lands_then_reports_failure(key, data):
        await real_put(key, data)
        if key == generation_vrt:
            raise OSError("the object store dropped the response")

    async def _delete_fails(key):
        raise OSError("the object store timed out")

    monkeypatch.setattr(raster_storage, "put", _put_lands_then_reports_failure)
    monkeypatch.setattr(raster_storage, "delete", _delete_fails)
    try:
        with pytest.raises(OSError):
            await _regenerate(job, generation_id, ids[0])

        status, metadata = await _job(job.id)
        assert status == "failed"
        assert await _left(raster_storage, [generation_vrt]) == [generation_vrt]
        assert generation_vrt in metadata[UNPUBLISHED_STORAGE_KEYS_FIELD]

        monkeypatch.setattr(raster_storage, "delete", real_delete)
        await fail_stale_jobs(test_db_session)

        assert await _left(raster_storage, [generation_vrt]) == []
        assert UNPUBLISHED_STORAGE_KEYS_FIELD not in (await _job(job.id))[1]
        assert await _live_keys(ids[0]) == prior
        assert await _left(raster_storage, prior) == list(prior)
    finally:
        await _purge_vrt(test_db_session, ids=ids)

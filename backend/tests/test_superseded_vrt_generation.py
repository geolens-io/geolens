"""A VRT regeneration's superseded generation goes once its publish shows.

The regeneration records what it superseded with its publish's follow-ups, so
they delete it after an acknowledged commit, after a lost acknowledgement the
probe reads as landed, and, when the outcome is unknown, from the stale-job
sweep once the job row reads complete. A publish that rolled back records
nothing and deletes nothing.
"""

from __future__ import annotations

import io
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from sqlalchemy import select, text

import app.core.db as db_module
from app.modules.auth.models import User
from app.platform.jobs.models import PUBLISH_FOLLOWUPS_FIELD, IngestJob
from app.processing.ingest import tasks_vrt
from app.processing.ingest.publish_followups import run_owed_publish_followups
from app.processing.ingest.tasks_raster_common import PublishObservation
from app.processing.raster.models import RasterAsset, VrtGeneration
from tests.test_publish_followups import _make_due
from tests.test_raster_replace_1221 import (
    _make_live_raster,
    _make_vrt_parent,
    _purge_vrt,
)
from tests.test_raster_replace_1221 import raster_storage as raster_storage
from tests.test_replacement_post_commit import (
    _IndeterminatePublish,
    _LostAcknowledgement,
)

pytestmark = pytest.mark.anyio


async def _admin_id(session) -> uuid.UUID:
    return (
        await session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()


async def _vrt_with_quicklooks(session, storage):
    """A published VRT over one member, with quicklooks of its own; returns its ids and keys."""
    admin_id = await _admin_id(session)
    member = await _make_live_raster(session, storage, created_by=admin_id)
    parent = await _make_vrt_parent(
        session, storage, created_by=admin_id, member=member
    )
    base = parent.cog_key.rsplit("/", 1)[0]
    quicklooks = (f"{base}/quicklook_256.png", f"{base}/quicklook_512.png")
    await session.execute(
        text(
            "UPDATE catalog.raster_assets SET quicklook_256_uri = :ql256, "
            "quicklook_512_uri = :ql512 WHERE dataset_id = :id"
        ),
        {"ql256": quicklooks[0], "ql512": quicklooks[1], "id": parent.dataset.id},
    )
    await session.commit()
    for key in quicklooks:
        await storage.put(key, io.BytesIO(b"old quicklook"))
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    return admin_id, ids, (parent.cog_key, *quicklooks)


async def _queue_regeneration(
    session, *, vrt_id, user_id
) -> tuple[IngestJob, uuid.UUID]:
    generation_id = uuid.uuid4()
    job = IngestJob(
        dataset_id=vrt_id,
        source_filename="regen",
        created_by=user_id,
        status="pending",
        user_metadata={"vrt_regenerate": True},
    )
    session.add(job)
    session.add(
        VrtGeneration(
            id=generation_id,
            vrt_dataset_id=vrt_id,
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
    )
    await session.execute(
        text(
            "UPDATE catalog.raster_assets "
            "SET current_generation_id = :gen, status = 'regenerating' "
            "WHERE dataset_id = :id"
        ),
        {"gen": generation_id, "id": vrt_id},
    )
    await session.commit()
    await session.refresh(job)
    return job, generation_id


async def _regenerate(job: IngestJob, generation_id: uuid.UUID, vrt_id) -> None:
    await tasks_vrt.regenerate_vrt.func(
        job_id=str(job.id),
        vrt_dataset_id=str(vrt_id),
        attempt_id=str(job.attempt_id),
        generation_id=str(generation_id),
    )


async def _left(storage, keys) -> list[str]:
    return [key for key in keys if await storage.exists(key)]


async def _live_keys(vrt_id) -> tuple[str, str | None, str | None]:
    async with db_module.async_session() as session:
        return tuple(
            (
                await session.execute(
                    select(
                        RasterAsset.asset_uri,
                        RasterAsset.quicklook_256_uri,
                        RasterAsset.quicklook_512_uri,
                    ).where(RasterAsset.dataset_id == vrt_id)
                )
            ).one()
        )


async def _owed(job_id) -> dict | None:
    async with db_module.async_session() as session:
        metadata = await session.scalar(
            select(IngestJob.user_metadata).where(IngestJob.id == job_id)
        )
    return (metadata or {}).get(PUBLISH_FOLLOWUPS_FIELD)


def _observed(observation: PublishObservation):
    return patch.object(
        tasks_vrt, "observe_publish_commit", AsyncMock(return_value=observation)
    )


@pytest.mark.parametrize("publish", ["acknowledged", "observed"])
async def test_a_confirmed_regeneration_deletes_what_it_superseded(
    test_db_session, raster_storage, publish: str
) -> None:
    """The follow-ups delete the prior generation right after a publish the task can see."""
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    lost = _LostAcknowledgement(job.id, ConnectionResetError("dropped"))
    try:
        with ExitStack() as stack:
            logs = stack.enter_context(structlog.testing.capture_logs())
            if publish == "observed":
                stack.enter_context(lost.installed())
                stack.enter_context(_observed(PublishObservation.LANDED))
            await _regenerate(job, generation_id, ids[0])

        assert lost.fired == (publish == "observed")
        assert "publish_followups_unknown_task" not in {e["event"] for e in logs}
        live = await _live_keys(ids[0])
        assert set(live).isdisjoint(prior)
        assert await _left(raster_storage, prior) == []
        assert await _left(raster_storage, live) == list(live)
        assert await _owed(job.id) is None
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_landed_lost_ack_still_purges_the_cache_and_refreshes_the_embedding(
    test_db_session, raster_storage
) -> None:
    """The stand-down for a lost ack the probe reads as landed still runs the
    cache purge and embedding refresh nothing else retries, not just the
    follow-ups the sweep would retry on its own."""
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    lost = _LostAcknowledgement(job.id, ConnectionResetError("dropped"))
    purge, embed = AsyncMock(), AsyncMock()
    try:
        with (
            lost.installed(),
            _observed(PublishObservation.LANDED),
            patch.object(tasks_vrt, "invalidate_catalog_cache", purge),
            patch.object(tasks_vrt, "defer_embedding", embed),
        ):
            await _regenerate(job, generation_id, ids[0])

        assert lost.fired == 1
        assert purge.await_count == 1
        assert embed.await_count == 1
        assert await _left(raster_storage, prior) == []
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_regeneration_that_landed_unseen_leaves_the_prior_generation_to_the_sweep(
    test_db_session, raster_storage
) -> None:
    """With the outcome unknown the task keeps the prior generation; the sweep deletes it."""
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    lost = _LostAcknowledgement(job.id, ConnectionResetError("dropped"))
    try:
        with lost.installed(), _observed(PublishObservation.UNKNOWN):
            await _regenerate(job, generation_id, ids[0])

        assert lost.fired == 1
        live = await _live_keys(ids[0])
        assert set(live).isdisjoint(prior), "the publish didn't land"
        assert await _left(raster_storage, prior) == list(prior)
        assert (await _owed(job.id))["superseded_keys"] == list(prior)

        await run_owed_publish_followups()

        assert await _left(raster_storage, prior) == []
        assert await _left(raster_storage, live) == list(live)
        assert await _owed(job.id) is None
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_regeneration_that_rolled_back_keeps_the_live_generation(
    test_db_session, raster_storage
) -> None:
    """A publish that never landed records nothing, so neither the task nor the sweep deletes."""
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    indeterminate = _IndeterminatePublish(job.id)
    try:
        with indeterminate.installed():
            await _regenerate(job, generation_id, ids[0])

        assert indeterminate.commit_failed
        assert await _live_keys(ids[0]) == prior
        assert await _left(raster_storage, prior) == list(prior)
        assert await _owed(job.id) is None

        await run_owed_publish_followups()

        assert await _left(raster_storage, prior) == list(prior)
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_superseded_delete_that_fails_is_retried_once_due(
    test_db_session, raster_storage, monkeypatch
) -> None:
    """A prior generation object whose delete fails stays owed, and the retry deletes it."""
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    real_delete = raster_storage.delete
    failures: list[str] = []

    async def _fails_once(key):
        if key == prior[0] and not failures:
            failures.append(key)
            raise OSError("the object store timed out")
        await real_delete(key)

    monkeypatch.setattr(raster_storage, "delete", _fails_once)
    try:
        await _regenerate(job, generation_id, ids[0])

        assert failures, "the delete never ran"
        assert await _left(raster_storage, prior) == [prior[0]]
        assert (await _owed(job.id))["superseded_keys"] == [prior[0]]

        await _make_due(job.id)
        await run_owed_publish_followups()

        assert await _left(raster_storage, prior) == []
        assert await _owed(job.id) is None
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_followups_failure_still_purges_the_cache_and_refreshes_the_embedding(
    test_db_session, raster_storage
) -> None:
    """The follow-ups failing after the publish skips neither step the sweep can't redo.

    The job stays complete, and the sweep deletes the prior generation later.
    """
    admin_id, ids, prior = await _vrt_with_quicklooks(test_db_session, raster_storage)
    job, generation_id = await _queue_regeneration(
        test_db_session, vrt_id=ids[0], user_id=admin_id
    )
    purge, embed = AsyncMock(), AsyncMock()
    try:
        with (
            patch.object(
                tasks_vrt,
                "run_publish_followups",
                AsyncMock(side_effect=ConnectionResetError("the session dropped")),
            ),
            patch.object(tasks_vrt, "invalidate_catalog_cache", purge),
            patch.object(tasks_vrt, "defer_embedding", embed),
        ):
            await _regenerate(job, generation_id, ids[0])

        assert purge.await_count == 1
        assert embed.await_count == 1
        async with db_module.async_session() as session:
            status = await session.scalar(
                select(IngestJob.status).where(IngestJob.id == job.id)
            )
        assert status == "complete"
        assert await _left(raster_storage, prior) == list(prior)

        await run_owed_publish_followups()

        assert await _left(raster_storage, prior) == []
    finally:
        await _purge_vrt(test_db_session, ids=ids)

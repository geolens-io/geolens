"""A first ingest's follow-ups run once its publish has landed, and only once."""

from __future__ import annotations

import asyncio
import json as _json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

import app.core.db as db_module
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.processing.ingest.publish_followups import (
    PUBLISH_FOLLOWUPS_FIELD,
    run_owed_publish_followups,
    run_publish_followups,
)
from tests.factories import create_dataset, get_user_id
from tests.test_raster_replace_1221 import (
    _ack_lost_on_publish,
    _geotiff_bytes,
    _make_live_raster,
    _publish_commit_lost,
    _purge,
)
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

_RASTER = [
    ("notice", "ingest_complete"),
    ("cache",),
    ("embed",),
    ("bill", "ingest_jobs"),
]


class _Ran(list):
    """The follow-ups a publish ran, in order, with the usage events' ids."""

    def __init__(self) -> None:
        super().__init__()
        self.billing: list[str | None] = []


@pytest.fixture
def followups(monkeypatch) -> _Ran:
    """Each follow-up a publish runs, in order."""
    ran = _Ran()

    async def _notice(*, event_key, build):
        ran.append(("notice", event_key))

    async def _cache():
        ran.append(("cache",))

    async def _embed(dataset):
        ran.append(("embed",))

    async def _bill(tenant_id, dimension, value=1, *, event_id=None, table_name=None):
        ran.append(("bill", dimension))
        ran.billing.append(event_id)

    monkeypatch.setattr("app.platform.notifications.events.emit_event_safe", _notice)
    monkeypatch.setattr(
        "app.processing.ingest.publish_followups.invalidate_catalog_cache", _cache
    )
    monkeypatch.setattr("app.processing.embeddings.helpers.defer_embedding", _embed)
    monkeypatch.setattr(
        "app.processing.ingest.publish_followups._emit_billing_event", _bill
    )
    return ran


async def _owed_job(
    session, *, status: str = "complete", task: str = "ingest_raster"
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A job owing ``task``'s follow-ups for a fresh dataset: (job, dataset, record)."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status=status,
        created_by=admin_id,
        user_metadata={PUBLISH_FOLLOWUPS_FIELD: task},
    )
    session.add(job)
    await session.commit()
    return job.id, dataset.id, dataset.record_id


async def _drop(session, job_id, record_id) -> None:
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    await session.execute(delete(Record).where(Record.id == record_id))
    await session.commit()


async def _owes(job_id) -> bool:
    async with db_module.async_session() as session:
        metadata = await session.scalar(
            select(IngestJob.user_metadata).where(IngestJob.id == job_id)
        )
    return PUBLISH_FOLLOWUPS_FIELD in (metadata or {})


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("ingest_raster", _RASTER),
        ("ingest_tileset", _RASTER),
        ("ingest_vrt", [("cache",), ("embed",)]),
    ],
)
async def test_owed_followups_run_once(
    test_db_session, followups, task, expected
) -> None:
    """A claim runs the task's follow-ups and clears the record, so a second claim runs none."""
    job_id, _, record_id = await _owed_job(test_db_session, task=task)
    try:
        assert await run_publish_followups(job_id) is True
        assert followups == expected
        assert not await _owes(job_id)

        assert await run_publish_followups(job_id) is False
        assert followups == expected
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_the_sweep_runs_every_owed_followup(test_db_session, followups) -> None:
    """The sweep's pass claims each complete job that still owes its follow-ups."""
    first = await _owed_job(test_db_session)
    second = await _owed_job(test_db_session, task="ingest_vrt")
    try:
        assert await run_owed_publish_followups() >= 2
        assert followups.count(("embed",)) == 2
        assert not await _owes(first[0]) and not await _owes(second[0])
    finally:
        await _drop(test_db_session, first[0], first[2])
        await _drop(test_db_session, second[0], second[2])


async def test_a_deleted_dataset_clears_the_record_and_runs_nothing(
    test_db_session, followups
) -> None:
    """The sweep clears a record whose dataset is gone, runs nothing, and never retries it."""
    job_id, dataset_id, record_id = await _owed_job(test_db_session)
    try:
        await test_db_session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await test_db_session.execute(delete(Record).where(Record.id == record_id))
        await test_db_session.commit()

        assert await run_owed_publish_followups() >= 1
        assert followups == []
        assert not await _owes(job_id)
        assert await run_publish_followups(job_id) is False
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_job_that_is_not_complete_owes_nothing_yet(
    test_db_session, followups
) -> None:
    """Only a complete job's follow-ups are claimed."""
    job_id, _, record_id = await _owed_job(test_db_session, status="running")
    try:
        assert await run_publish_followups(job_id) is False
        assert followups == []
        assert await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_claim_another_caller_holds_is_skipped_without_waiting(
    test_db_session, followups
) -> None:
    """A row another caller has locked is left to it, and the claim returns at once."""
    job_id, _, record_id = await _owed_job(test_db_session)
    try:
        async with db_module.async_session() as holder:
            await holder.execute(
                select(IngestJob.id).where(IngestJob.id == job_id).with_for_update()
            )
            try:
                claimed = await asyncio.wait_for(run_publish_followups(job_id), 5)
            finally:
                await holder.rollback()
        assert claimed is False
        assert followups == []
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_retention_keeps_a_job_that_still_owes_its_followups(
    test_db_session, followups, monkeypatch
) -> None:
    """The purge keeps a job still owing its follow-ups, and the same pass claims them."""
    from app.core.config import settings
    from app.platform.jobs.sweep import fail_stale_jobs

    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 1)
    admin_id = await get_user_id(test_db_session, "admin")
    long_ago = datetime.now(timezone.utc) - timedelta(days=10)
    job = IngestJob(
        status="complete",
        created_by=admin_id,
        created_at=long_ago,
        completed_at=long_ago,
        user_metadata={PUBLISH_FOLLOWUPS_FIELD: "ingest_raster"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    try:
        async with db_module.async_session() as sweep:
            await fail_stale_jobs(sweep)
        async with db_module.async_session() as reader:
            assert await reader.get(IngestJob, job_id) is not None
        assert not await _owes(job_id)
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()


async def test_worker_recovery_runs_owed_followups(test_db_session, followups) -> None:
    """A worker's startup recovery claims the follow-ups a landed publish still owes."""
    from app.platform.jobs.worker import _recover_stale_jobs_for_current_scope

    job_id, _, record_id = await _owed_job(test_db_session)
    try:
        await _recover_stale_jobs_for_current_scope()
        assert followups == _RASTER
        assert not await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_an_admin_cleanup_runs_owed_followups(
    client, admin_auth_header, test_db_session, followups
) -> None:
    """The admin cleanup, which commits the sweep itself, still runs the owed follow-ups once."""
    job_id, _, record_id = await _owed_job(test_db_session)
    try:
        response = await client.post("/jobs/cleanup/stale/", headers=admin_auth_header)
        assert response.status_code == 200, response.text
        assert followups == _RASTER
        assert not await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_the_job_status_response_never_shows_the_record(
    client, admin_auth_header, test_db_session
) -> None:
    """GET /jobs/{id} carries nothing of the follow-up record."""
    job_id, _, record_id = await _owed_job(test_db_session)
    try:
        response = await client.get(f"/jobs/{job_id}", headers=admin_auth_header)
        assert response.status_code == 200, response.text
        assert PUBLISH_FOLLOWUPS_FIELD not in response.text
    finally:
        await _drop(test_db_session, job_id, record_id)


# --- Through the real tasks ------------------------------------------------


async def _raster_job(session, tmp_path: Path, seed: int) -> tuple[IngestJob, Path]:
    admin_id = await get_user_id(session, "admin")
    source = tmp_path / "first.tif"
    source.write_bytes(_geotiff_bytes(seed=seed))
    job = IngestJob(
        source_filename="first.tif",
        file_path=str(source),
        created_by=admin_id,
        status="pending",
        user_metadata={"file_type": "raster", "title": "Follow-up raster"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job, source


async def _run_raster(job: IngestJob, source: Path) -> None:
    from app.processing.ingest.tasks_raster import ingest_raster

    await ingest_raster.func(
        job_id=str(job.id),
        file_path=str(source),
        user_id=str(job.created_by),
        attempt_id=str(job.attempt_id),
    )


async def _purge_raster_job(session, job_id) -> None:
    session.expire_all()
    dataset_id = await session.scalar(
        select(IngestJob.dataset_id).where(IngestJob.id == job_id)
    )
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    await session.commit()
    if dataset_id is not None:
        record_id = await session.scalar(
            select(Dataset.record_id).where(Dataset.id == dataset_id)
        )
        await _purge(session, dataset_id=dataset_id, record_id=record_id)


async def test_a_first_ingest_runs_its_followups_once(
    test_db_session,
    raster_storage,
    tmp_path,
    followups,
) -> None:
    """An acknowledged publish runs the follow-ups once, and the sweep then owes nothing."""
    job, source = await _raster_job(test_db_session, tmp_path, seed=101)
    try:
        await _run_raster(job, source)
        assert followups == _RASTER
        assert followups.billing == [str(job.id)]
        assert not await _owes(job.id)

        await run_owed_publish_followups()
        assert followups == _RASTER
    finally:
        await _purge_raster_job(test_db_session, job.id)


async def test_a_lost_acknowledgement_that_landed_still_runs_the_followups(
    test_db_session,
    raster_storage,
    tmp_path,
    followups,
) -> None:
    """A publish observed after its acknowledgement was lost runs the follow-ups once."""
    job, source = await _raster_job(test_db_session, tmp_path, seed=102)
    try:
        with _ack_lost_on_publish(
            job.id, failure=ConnectionResetError("dropped")
        ) as fired:
            await _run_raster(job, source)
        assert fired["count"] == 1, "the publishing commit never fired"
        assert followups == _RASTER
        assert not await _owes(job.id)
    finally:
        await _purge_raster_job(test_db_session, job.id)


async def test_followups_a_first_ingest_cannot_claim_are_run_by_the_sweep(
    test_db_session,
    raster_storage,
    tmp_path,
    followups,
    monkeypatch,
) -> None:
    """A landed publish whose own claim fails leaves the record, and the sweep runs them once."""

    async def _unreachable(job_uuid):
        raise ConnectionResetError("the database is gone")

    monkeypatch.setattr(
        "app.processing.ingest.tasks_raster.run_publish_followups", _unreachable
    )
    job, source = await _raster_job(test_db_session, tmp_path, seed=103)
    try:
        with _ack_lost_on_publish(job.id, failure=ConnectionResetError("dropped")):
            await _run_raster(job, source)
        assert followups == []
        assert await _owes(job.id)

        await run_owed_publish_followups()
        assert followups == _RASTER
        await run_owed_publish_followups()
        assert followups == _RASTER
    finally:
        await _purge_raster_job(test_db_session, job.id)


async def test_a_publish_that_never_lands_owes_no_followups(
    test_db_session,
    raster_storage,
    tmp_path,
    followups,
) -> None:
    """A commit still in progress that then rolls back leaves no record and runs nothing."""
    job, source = await _raster_job(test_db_session, tmp_path, seed=104)
    try:
        with _publish_commit_lost(job.id) as fired:
            await _run_raster(job, source)
        assert fired["count"] == 1, "the publishing commit never fired"
        assert not await _owes(job.id)
        await run_owed_publish_followups()
        assert followups == []
    finally:
        await _purge_raster_job(test_db_session, job.id)


async def test_a_vrt_build_whose_acknowledgement_is_lost_runs_its_followups(
    test_db_session,
    raster_storage,
    followups,
) -> None:
    """A VRT build observed after its acknowledgement was lost purges the cache and embeds."""
    from app.processing.ingest.tasks_vrt import ingest_vrt, resolve_vrt_source_path

    admin_id = await get_user_id(test_db_session, "admin")
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    member_path = Path(resolve_vrt_source_path(member.asset.asset_uri, tenant_id=None))
    member_path.parent.mkdir(parents=True, exist_ok=True)
    member_path.write_bytes(_geotiff_bytes(seed=1))
    member_ds, member_rec = member.dataset.id, member.dataset.record_id
    job = IngestJob(
        source_filename="mosaic.vrt",
        created_by=admin_id,
        status="pending",
        user_metadata={"title": "Follow-up mosaic", "visibility": "public"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)
    job_id = job.id
    try:
        with _ack_lost_on_publish(
            job_id, failure=ConnectionResetError("dropped")
        ) as fired:
            await ingest_vrt.func(
                job_id=str(job_id),
                source_dataset_ids=_json.dumps([str(member_ds)]),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
                vrt_type="mosaic",
                resolution_strategy="finest",
            )
        assert fired["count"] == 1, "the publishing commit never fired"
        assert followups == [("cache",), ("embed",)]
        assert not await _owes(job_id)
    finally:
        test_db_session.expire_all()
        vrt_ds = await test_db_session.scalar(
            select(IngestJob.dataset_id).where(IngestJob.id == job_id)
        )
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()
        if vrt_ds is not None:
            vrt_rec = await test_db_session.scalar(
                select(Dataset.record_id).where(Dataset.id == vrt_ds)
            )
            await test_db_session.execute(
                text("DELETE FROM catalog.vrt_source_links WHERE vrt_dataset_id = :id"),
                {"id": vrt_ds},
            )
            await test_db_session.commit()
            await _purge(test_db_session, dataset_id=vrt_ds, record_id=vrt_rec)
        await _purge(test_db_session, dataset_id=member_ds, record_id=member_rec)

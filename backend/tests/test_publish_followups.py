"""A first ingest's follow-ups run once its publish has landed, and only once."""

from __future__ import annotations

import asyncio
import contextlib
import json as _json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import structlog
from sqlalchemy import delete, select, text

import app.core.db as db_module
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.processing.ingest.publish_followups import (
    PUBLISH_FOLLOWUPS_FIELD,
    run_owed_publish_followups,
    run_publish_followups,
)
from app.processing.ingest.tasks_raster_common import PublishObservation
from tests.factories import create_dataset, get_user_id
from tests.test_raster_replace_1221 import (
    _ack_lost_on_publish,
    _geotiff_bytes,
    _make_live_raster,
    _publish_commit_lost,
    _purge,
    _storage_calls,
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
    session,
    *,
    status: str = "complete",
    task: str = "ingest_raster",
    error_message: str | None = None,
    reaps_staged_upload: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A job owing ``task``'s follow-ups for a fresh dataset: (job, dataset, record)."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status=status,
        created_by=admin_id,
        error_message=error_message,
    )
    session.add(job)
    await session.flush()
    job.user_metadata = _owed(task, job.attempt_id, reaps_staged_upload)
    await session.commit()
    return job.id, dataset.id, dataset.record_id


def _owed(task: str, attempt_id, reaps_staged_upload: bool = False) -> dict:
    record = {"task": task, "attempt_id": str(attempt_id)}
    if reaps_staged_upload:
        record["reaps_staged_upload"] = True
    return {PUBLISH_FOLLOWUPS_FIELD: record}


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
        ("ingest_pointcloud", _RASTER),
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


async def test_a_failed_job_owes_only_its_failure_notice(
    test_db_session, followups, monkeypatch
) -> None:
    """A failed job's claim mails ingest_failed once, with its stored reason, and nothing else."""
    sent: list = []

    async def _notice(*, event_key, build):
        sent.append((event_key, build().data["reason"]))

    monkeypatch.setattr("app.platform.notifications.events.emit_event_safe", _notice)
    job_id, _, record_id = await _owed_job(
        test_db_session,
        status="failed",
        task="reupload_file",
        error_message="The refresh was rejected.",
    )
    try:
        assert await run_publish_followups(job_id) is True
        assert sent == [("ingest_failed", "The refresh was rejected.")]
        assert followups == []
        assert not await _owes(job_id)
        assert await run_publish_followups(job_id) is False
        assert len(sent) == 1
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_completed_job_carrying_a_failure_record_sends_nothing(
    test_db_session, followups
) -> None:
    """A complete job whose record names a replacement task is cleared and runs nothing."""
    job_id, _, record_id = await _owed_job(test_db_session, task="reupload_file")
    try:
        assert await run_publish_followups(job_id) is True
        assert followups == []
        assert not await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_record_an_earlier_attempt_wrote_is_cleared_and_runs_nothing(
    test_db_session, followups
) -> None:
    """A record whose attempt no longer owns the job, as after a retry, sends nothing."""
    job_id, _, record_id = await _owed_job(test_db_session)
    try:
        async with db_module.async_session() as session:
            await session.execute(
                text(
                    "UPDATE catalog.ingest_jobs SET attempt_id = gen_random_uuid() "
                    "WHERE id = :id"
                ),
                {"id": job_id},
            )
            await session.commit()

        assert await run_publish_followups(job_id) is True
        assert followups == []
        assert not await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_job_that_has_not_ended_owes_nothing_yet(
    test_db_session, followups
) -> None:
    """Only a complete or failed job's follow-ups are claimed."""
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
        user_metadata=_owed("ingest_raster", uuid.uuid4()),
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


# --- The staged upload a publish consumed ----------------------------------


async def _point_job_at(job_id, *, file_path: str | None, **metadata) -> None:
    """Bind ``job_id`` to ``file_path``, merging ``metadata`` into its record-bearing metadata."""
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, job_id)
        job.file_path = file_path
        job.user_metadata = {**job.user_metadata, **metadata}
        await session.commit()


async def _stage_upload(storage, job_id, where: str):
    """Stage ``job_id``'s upload on disk or in ``storage``; returns what is left of it."""
    if where == "local":
        path = Path(settings.upload_staging_dir) / f"{job_id}_upload.tif"
        path.write_bytes(b"staged")
        await _point_job_at(job_id, file_path=str(path))

        async def _local_left() -> list:
            return [path] if path.exists() else []

        return _local_left
    # Where a presigned completion leaves it: the frozen copy the job is bound
    # to, and the client's key, which a late PUT can recreate.
    frozen = f"staging/{job_id}/frozen/upload.tif"
    client_key = f"staging/{job_id}/upload.tif"
    for key in (frozen, client_key):
        await storage.put(key, b"staged")
    await _point_job_at(job_id, file_path=frozen, s3_key=client_key)

    async def _stored_left() -> list:
        return [key for key in (frozen, client_key) if await storage.exists(key)]

    return _stored_left


@pytest.mark.parametrize("where", ["local", "storage"])
async def test_a_claim_deletes_the_staged_upload_its_publish_consumed(
    test_db_session, raster_storage, followups, where
) -> None:
    """A complete job whose record asks for it loses its staged upload and runs the rest."""
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        left = await _stage_upload(raster_storage, job_id, where)
        assert await left(), "precondition: the upload is staged"

        assert await run_publish_followups(job_id) is True
        assert await left() == []
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("where", ["local", "storage"])
@pytest.mark.parametrize(
    ("status", "reaps_staged_upload", "earlier_attempt"),
    [("complete", False, False), ("failed", True, False), ("complete", True, True)],
    ids=["not-asked", "failed", "earlier-attempt"],
)
async def test_a_claim_that_does_not_license_the_delete_keeps_the_upload(
    test_db_session,
    raster_storage,
    followups,
    where,
    status,
    reaps_staged_upload,
    earlier_attempt,
) -> None:
    """Only a complete job whose own attempt asked for it loses its staged upload."""
    job_id, _, record_id = await _owed_job(
        test_db_session, status=status, reaps_staged_upload=reaps_staged_upload
    )
    try:
        left = await _stage_upload(raster_storage, job_id, where)
        staged = await left()
        if earlier_attempt:
            async with db_module.async_session() as session:
                await session.execute(
                    text(
                        "UPDATE catalog.ingest_jobs SET attempt_id = gen_random_uuid() "
                        "WHERE id = :id"
                    ),
                    {"id": job_id},
                )
                await session.commit()

        assert await run_publish_followups(job_id) is True
        assert await left() == staged
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("via", ["path", "dot-dot", "symlink"])
async def test_a_local_upload_outside_the_staging_dir_is_never_deleted(
    test_db_session, tmp_path, followups, via
) -> None:
    """A row naming a file outside the staging directory deletes nothing and logs only the job."""
    staging = Path(settings.upload_staging_dir)
    outside = tmp_path / "elsewhere" / "keep.tif"
    outside.parent.mkdir()
    outside.write_bytes(b"not an upload")
    named = {
        "path": outside,
        "dot-dot": staging / ".." / "elsewhere" / "keep.tif",
        "symlink": staging / "link.tif",
    }[via]
    if via == "symlink":
        named.symlink_to(outside)
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        await _point_job_at(job_id, file_path=str(named))
        with structlog.testing.capture_logs() as logs:
            assert await run_publish_followups(job_id) is True

        assert outside.read_bytes() == b"not an upload"
        assert [
            e for e in logs if e["event"] == "staged_upload_outside_staging_dir"
        ] == [
            {
                "event": "staged_upload_outside_staging_dir",
                "job_id": str(job_id),
                "log_level": "warning",
            }
        ]
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize(
    ("file_path", "metadata"),
    [(None, {}), ("", {"s3_key": ""}), (None, {"s3_key": None})],
    ids=["missing", "empty", "null-key"],
)
async def test_a_record_asking_for_the_delete_of_no_upload_deletes_nothing(
    test_db_session, raster_storage, followups, file_path, metadata
) -> None:
    """A job that names no upload deletes nothing, raises nothing and runs the rest."""
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        await _point_job_at(job_id, file_path=file_path, **metadata)
        with _storage_calls(raster_storage) as calls:
            assert await run_publish_followups(job_id) is True
        assert calls["delete"] == []
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


# --- Through the real tasks ------------------------------------------------


async def _raster_job(session, seed: int, **metadata) -> IngestJob:
    """A pending first raster ingest of a GeoTIFF uploaded to the staging directory."""
    admin_id = await get_user_id(session, "admin")
    source = Path(settings.upload_staging_dir) / "first.tif"
    source.write_bytes(_geotiff_bytes(seed=seed))
    job = IngestJob(
        source_filename="first.tif",
        file_path=str(source),
        created_by=admin_id,
        status="pending",
        user_metadata={"file_type": "raster", "title": "Follow-up raster", **metadata},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _stage_in_storage(session, storage, job: IngestJob) -> tuple[str, str]:
    """Move ``job``'s upload to where a presigned completion leaves it: (frozen, client key)."""
    frozen = f"staging/{job.id}/frozen/first.tif"
    client_key = f"staging/{job.id}/first.tif"
    source = Path(job.file_path)
    for key in (frozen, client_key):
        await storage.put(key, source.read_bytes())
    source.unlink()
    job.file_path = frozen
    job.user_metadata = {**job.user_metadata, "s3_key": client_key}
    await session.commit()
    await session.refresh(job)
    return frozen, client_key


async def _run_raster(job: IngestJob) -> None:
    from app.processing.ingest.tasks_raster import ingest_raster

    await ingest_raster.func(
        job_id=str(job.id),
        file_path=job.file_path,
        user_id=str(job.created_by),
        attempt_id=str(job.attempt_id),
    )


async def _job_row(job_id) -> tuple[str, uuid.UUID | None]:
    """The job's (status, dataset_id), read on a fresh session."""
    async with db_module.async_session() as session:
        row = await session.execute(
            select(IngestJob.status, IngestJob.dataset_id).where(IngestJob.id == job_id)
        )
    return tuple(row.one())


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
    followups,
) -> None:
    """An acknowledged publish runs the follow-ups once, deletes its upload, and the sweep owes nothing."""
    job = await _raster_job(test_db_session, seed=101)
    source = Path(job.file_path)
    try:
        await _run_raster(job)
        assert followups == _RASTER
        assert followups.billing == [str(job.id)]
        assert not await _owes(job.id)
        assert not source.exists()

        await run_owed_publish_followups()
        assert followups == _RASTER
    finally:
        await _purge_raster_job(test_db_session, job.id)


async def test_a_lost_acknowledgement_that_landed_still_runs_the_followups(
    test_db_session,
    raster_storage,
    followups,
) -> None:
    """A publish observed after its acknowledgement was lost runs the follow-ups once and deletes its upload."""
    job = await _raster_job(test_db_session, seed=102)
    source = Path(job.file_path)
    try:
        with _ack_lost_on_publish(
            job.id, failure=ConnectionResetError("dropped")
        ) as fired:
            await _run_raster(job)
        assert fired["count"] == 1, "the publishing commit never fired"
        assert followups == _RASTER
        assert not await _owes(job.id)
        assert (await _job_row(job.id))[0] == "complete"
        assert not source.exists(), "the staged upload outlived a landed publish"
    finally:
        await _purge_raster_job(test_db_session, job.id)


@pytest.mark.parametrize("ack", ["acknowledged", "lost"])
async def test_a_first_ingest_staged_in_storage_leaves_no_staging_object(
    test_db_session, raster_storage, followups, ack
) -> None:
    """The frozen copy and the client's key both go once the publish lands, acknowledged or not."""
    job = await _raster_job(test_db_session, seed=105)
    keys = await _stage_in_storage(test_db_session, raster_storage, job)
    try:
        if ack == "lost":
            with _ack_lost_on_publish(
                job.id, failure=ConnectionResetError("dropped")
            ) as fired:
                await _run_raster(job)
            assert fired["count"] == 1, "the publishing commit never fired"
        else:
            await _run_raster(job)
        assert followups == _RASTER
        assert [key for key in keys if await raster_storage.exists(key)] == []
    finally:
        await _purge_raster_job(test_db_session, job.id)


@pytest.mark.parametrize("archived", [True, False], ids=["archived", "not-archived"])
async def test_a_lossy_first_ingest_loses_its_upload_only_once_it_is_archived(
    test_db_session, raster_storage, followups, monkeypatch, archived
) -> None:
    """After a lost acknowledgement, a lossy upload goes only when a durable copy holds it."""
    if not archived:

        async def _not_archived(*args, **kwargs):
            return False, None, 0, None

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster.archive_lossy_original", _not_archived
        )
    job = await _raster_job(test_db_session, seed=106, compression="JPEG")
    source = Path(job.file_path)
    try:
        with _ack_lost_on_publish(
            job.id, failure=ConnectionResetError("dropped")
        ) as fired:
            await _run_raster(job)
        assert fired["count"] == 1, "the publishing commit never fired"
        status, dataset_id = await _job_row(job.id)
        assert status == "complete"
        kept = await raster_storage.list(f"originals/{dataset_id}/")
        assert bool(kept) is archived
        assert source.exists() is not archived, (
            "the only faithful copy of a lossy upload was deleted"
            if not archived
            else "the staged upload outlived its archived copy"
        )
    finally:
        await _purge_raster_job(test_db_session, job.id)


@pytest.mark.parametrize(
    "observed",
    [PublishObservation.LANDED, PublishObservation.UNKNOWN],
    ids=["landed", "unknown"],
)
async def test_followups_a_first_ingest_cannot_claim_are_run_by_the_sweep(
    test_db_session,
    raster_storage,
    followups,
    monkeypatch,
    observed,
) -> None:
    """A publish whose own claim fails keeps its upload and record until the sweep runs them once."""

    async def _unreachable(job_uuid):
        raise ConnectionResetError("the database is gone")

    async def _observe(*args, **kwargs):
        return observed

    monkeypatch.setattr(
        "app.processing.ingest.tasks_raster.run_publish_followups", _unreachable
    )
    monkeypatch.setattr(
        "app.processing.ingest.tasks_raster_common.observe_publish_commit", _observe
    )
    job = await _raster_job(test_db_session, seed=103)
    source = Path(job.file_path)
    try:
        with _ack_lost_on_publish(job.id, failure=ConnectionResetError("dropped")):
            await _run_raster(job)
        assert followups == []
        assert await _owes(job.id)
        assert source.exists(), "the upload went before the publish was known"

        await run_owed_publish_followups()
        assert followups == _RASTER
        assert not source.exists(), "the sweep left the upload of a landed publish"
        await run_owed_publish_followups()
        assert followups == _RASTER
    finally:
        await _purge_raster_job(test_db_session, job.id)


@pytest.mark.parametrize("aborted", [False, True], ids=["in-progress", "aborted"])
async def test_a_publish_that_never_lands_owes_no_followups(
    test_db_session,
    raster_storage,
    followups,
    aborted,
) -> None:
    """A commit that rolls back leaves no record, runs no follow-ups and keeps the upload."""
    job = await _raster_job(test_db_session, seed=104)
    source = Path(job.file_path)
    try:
        with (
            _publish_commit_lost(job.id, aborted=aborted) as fired,
            pytest.raises(ConnectionResetError)
            if aborted
            else contextlib.nullcontext(),
        ):
            await _run_raster(job)
        assert fired["count"] == 1, "the publishing commit never fired"
        assert not await _owes(job.id)
        await run_owed_publish_followups()
        assert followups == ([("notice", "ingest_failed")] if aborted else [])
        assert await _job_row(job.id) == ("failed" if aborted else "running", None)
        assert source.exists(), "the upload went though its publish never landed"
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

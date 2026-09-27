"""A first ingest's follow-ups run once its publish has landed, and only once."""

from __future__ import annotations

import asyncio
import contextlib
import json as _json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import structlog
from sqlalchemy import delete, select, text, update

import app.core.db as db_module
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    IngestJob,
    holds_unarchived_original,
)
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.publish_followups import (
    PUBLISH_FOLLOWUPS_FIELD,
    owed_followups,
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


async def test_a_relative_upload_under_a_relative_staging_dir_is_deleted(
    test_db_session, tmp_path, monkeypatch, followups
) -> None:
    """With a relative staging directory, the relative path a direct upload records is unlinked."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "upload_staging_dir", "staging")
    storage = LocalStorageProvider("staging")
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    upload = Path("staging") / f"{job_id}_upload.tif"
    upload.write_bytes(b"staged")
    try:
        await _point_job_at(job_id, file_path=str(upload))

        assert await run_publish_followups(job_id) is True
        assert not (tmp_path / upload).exists()
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("local_copy", [False, True], ids=["key", "key-and-file"])
async def test_a_staging_key_leaves_storage_where_it_also_reads_as_a_local_path(
    test_db_session, raster_storage, tmp_path, monkeypatch, followups, local_copy
) -> None:
    """A ``staging/`` key the working directory places inside the staging dir is still deleted from storage."""
    # As in the containers: /app/staging is both the staging dir and what
    # the key spells relative to /app.
    monkeypatch.chdir(tmp_path)
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        left = await _stage_upload(raster_storage, job_id, "storage")
        as_local = tmp_path / f"staging/{job_id}/frozen/upload.tif"
        assert as_local.is_relative_to(Path(settings.upload_staging_dir))
        if local_copy:
            as_local.parent.mkdir(parents=True)
            as_local.write_bytes(b"staged")

        assert await run_publish_followups(job_id) is True
        assert await left() == []
        assert not as_local.exists()
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_hosted_staging_key_never_reads_as_a_local_file(
    test_db_session, raster_storage, tmp_path, monkeypatch, followups
) -> None:
    """On a multi-tenant install a relative path is the tenant's storage key, never a local file."""
    from app.core.db.tenant_session import current_tenant_var

    monkeypatch.chdir(tmp_path)
    tenant = str(uuid.uuid4())
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    frozen = f"staging/{job_id}/frozen/upload.tif"
    local = tmp_path / frozen
    local.parent.mkdir(parents=True)
    local.write_bytes(b"not this tenant's upload")
    await raster_storage.put(f"tenants/{tenant}/{frozen}", b"staged")
    try:
        await _point_job_at(job_id, file_path=frozen)
        token = current_tenant_var.set(tenant)
        try:
            with patch("app.core.tenancy.is_multi_tenant", return_value=True):
                assert await run_publish_followups(job_id) is True
        finally:
            current_tenant_var.reset(token)

        assert local.read_bytes() == b"not this tenant's upload"
        assert not await raster_storage.exists(f"tenants/{tenant}/{frozen}")
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_delete_cut_short_leaves_the_record_for_the_next_run(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    """A run stopped inside the upload's delete keeps the record, and the next run deletes the upload."""
    import app.processing.ingest.publish_followups as publish_followups

    real_reap = publish_followups.reap_presigned_staging_object
    reaps = {"count": 0}

    async def _stopped_once(*args, **kwargs):
        reaps["count"] += 1
        if reaps["count"] == 1:
            raise asyncio.CancelledError
        return await real_reap(*args, **kwargs)

    monkeypatch.setattr(
        publish_followups, "reap_presigned_staging_object", _stopped_once
    )
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        left = await _stage_upload(raster_storage, job_id, "local")
        with pytest.raises(asyncio.CancelledError):
            await run_publish_followups(job_id)
        assert await _owes(job_id), "the record went before the upload did"
        assert await left(), "precondition: the delete stopped before the unlink"

        await run_owed_publish_followups()
        assert await left() == []
        assert not await _owes(job_id)
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _owe_archive(job_id, dataset_id, name: str) -> str:
    """Name the key the job's record archives the upload's original under."""
    key = f"originals/{dataset_id}/{name}"
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, job_id)
        owed = {**job.user_metadata[PUBLISH_FOLLOWUPS_FIELD], "archive_key": key}
        job.user_metadata = {**job.user_metadata, PUBLISH_FOLLOWUPS_FIELD: owed}
        await session.commit()
    return key


@pytest.mark.parametrize("task", ["reupload_file", "reupload_raster"])
async def test_a_replacement_owes_only_the_deletion_of_its_upload(
    test_db_session, raster_storage, followups, task
) -> None:
    """A replacement's record deletes the upload and runs nothing else, as a task it knows."""
    job_id, _, record_id = await _owed_job(
        test_db_session, task=task, reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, "local")
        with structlog.testing.capture_logs() as logs:
            assert await run_publish_followups(job_id) is True

        assert await left() == []
        assert followups == []
        assert "publish_followups_unknown_task" not in [e["event"] for e in logs]
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_an_archive_already_made_is_not_made_again(
    test_db_session, raster_storage, followups
) -> None:
    """An upload whose original is already archived is deleted without a second copy."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        await raster_storage.put(key, b"staged")
        with _storage_calls(raster_storage) as calls:
            assert await run_publish_followups(job_id) is True

        assert calls["put"] == []
        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("where", ["local", "storage"])
async def test_a_missing_archive_is_made_from_the_upload_before_it_goes(
    test_db_session, raster_storage, followups, where
) -> None:
    """The claim archives an upload's original from the upload itself, then deletes the upload."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, where)
        key = await _owe_archive(job_id, dataset_id, "upload.tif")

        assert await run_publish_followups(job_id) is True
        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("found", [False, True], ids=["made", "found"])
async def test_an_archive_in_place_clears_an_earlier_archive_failure(
    test_db_session, raster_storage, followups, found
) -> None:
    """A job flagged for a failed archive loses the flag, and its upload, once its archive is in place."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=None, archive_failed=True, archive_error="refused"
        )
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        if found:
            await raster_storage.put(key, b"staged")

        assert await run_publish_followups(job_id) is True
        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
        async with db_module.async_session() as session:
            metadata = await session.scalar(
                select(IngestJob.user_metadata).where(IngestJob.id == job_id)
            )
        assert not {"archive_failed", "archive_error"} & metadata.keys()
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _stored_metadata(job_id) -> dict:
    async with db_module.async_session() as session:
        return await session.scalar(
            select(IngestJob.user_metadata).where(IngestJob.id == job_id)
        )


@pytest.mark.parametrize(
    "archive_key", [None, "originals/d/upload.tif"], ids=["no-archive", "archive"]
)
async def test_a_record_marks_the_archive_pending_only_when_it_names_one(
    test_db_session, archive_key
) -> None:
    """The UPDATE that records the follow-ups marks an archive pending only with its key."""
    job_id, _, record_id = await _owed_job(test_db_session, task="reupload_file")
    try:
        async with db_module.async_session() as session:
            attempt_id = await session.scalar(
                select(IngestJob.attempt_id).where(IngestJob.id == job_id)
            )
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(
                    user_metadata=owed_followups(
                        attempt_id,
                        "reupload_file",
                        reaps_staged_upload=True,
                        archive_key=archive_key,
                    )
                )
            )
            await session.commit()

        metadata = await _stored_metadata(job_id)
        assert (ARCHIVE_PENDING_METADATA_KEY in metadata) is (archive_key is not None)
        assert metadata[PUBLISH_FOLLOWUPS_FIELD]["reaps_staged_upload"] is True
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("found", [False, True], ids=["made", "found"])
async def test_a_confirmed_archive_takes_the_pending_mark_off(
    test_db_session, raster_storage, followups, found
) -> None:
    """The mark goes once the archive exists, and the upload with it."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=None, **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        if found:
            await raster_storage.put(key, b"staged")

        assert await run_publish_followups(job_id) is True
        assert await left() == []
        assert ARCHIVE_PENDING_METADATA_KEY not in await _stored_metadata(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_failed_archive_keeps_the_pending_mark_and_the_upload(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=None, **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        real_put = raster_storage.put

        async def _refused(written, data):
            if written == key:
                raise RuntimeError("the object store refused the write")
            await real_put(written, data)

        monkeypatch.setattr(raster_storage, "put", _refused)

        assert await run_publish_followups(job_id) is True
        assert await left() == [f"staging/{job_id}/frozen/upload.tif"]
        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_PENDING_METADATA_KEY] is True
        assert metadata["archive_failed"] is True
        owed = metadata[PUBLISH_FOLLOWUPS_FIELD]
        assert (owed["archive_key"], owed["attempts"], owed["claimed"]) == (
            key,
            1,
            True,
        )
        assert "next_attempt_at" in owed
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _make_due(job_id) -> None:
    """Bring the job's next follow-up attempt forward to a minute ago."""
    async with db_module.async_session() as session:
        await session.execute(
            text(
                "UPDATE catalog.ingest_jobs SET user_metadata = jsonb_set("
                "user_metadata, '{publish_followups,next_attempt_at}', "
                "to_jsonb(now() - interval '1 minute')) WHERE id = :id"
            ),
            {"id": job_id},
        )
        await session.commit()


async def test_a_failed_archive_is_made_by_a_later_sweep(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    """The write that failed is tried again once due; then the mark and the upload go."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=None, **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        real_put = raster_storage.put
        refused: list[str] = []

        async def _refused_once(written, data):
            if written == key and not refused:
                refused.append(written)
                raise RuntimeError("the object store refused the write")
            await real_put(written, data)

        monkeypatch.setattr(raster_storage, "put", _refused_once)
        assert await run_publish_followups(job_id) is True
        await _make_due(job_id)

        await run_owed_publish_followups()

        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
        metadata = await _stored_metadata(job_id)
        assert (
            not {
                ARCHIVE_PENDING_METADATA_KEY,
                "archive_failed",
                PUBLISH_FOLLOWUPS_FIELD,
            }
            & metadata.keys()
        )
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _sweep_selections(monkeypatch) -> list:
    """Record, in order, the jobs the sweep hands to the follow-ups, and run none."""
    import app.processing.ingest.publish_followups as publish_followups

    selected: list = []

    async def _selected(job_uuid, **kwargs):
        selected.append(job_uuid)
        return False

    monkeypatch.setattr(publish_followups, "run_publish_followups", _selected)
    return selected


async def test_a_record_not_yet_due_is_left_by_the_sweep(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        async with db_module.async_session() as session:
            job = await session.get(IngestJob, job_id)
            owed = {
                **job.user_metadata[PUBLISH_FOLLOWUPS_FIELD],
                "attempts": 2,
                "claimed": True,
                "next_attempt_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
            }
            job.user_metadata = {**job.user_metadata, PUBLISH_FOLLOWUPS_FIELD: owed}
            await session.commit()

        with monkeypatch.context() as spied:
            selected = await _sweep_selections(spied)
            await run_owed_publish_followups()
        assert job_id not in selected
        assert await run_publish_followups(job_id) is False

        assert not await raster_storage.exists(key)
        assert len(await left()) == 2
        assert (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD] == owed
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_records_that_keep_failing_do_not_crowd_out_a_fresh_one(
    test_db_session, raster_storage, tmp_path, followups
) -> None:
    """More failing records than one sweep takes still leave room for a fresh record."""
    outside = tmp_path / "keep.tif"
    outside.write_bytes(b"not an upload")
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    failing = [
        IngestJob(
            dataset_id=dataset.id,
            status="complete",
            created_by=admin_id,
            file_path=str(outside),
            user_metadata={
                PUBLISH_FOLLOWUPS_FIELD: {
                    "task": "reupload_file",
                    "archive_key": f"originals/{dataset.id}/keep-{n}.tif",
                    "attempts": 3,
                    "claimed": True,
                    "next_attempt_at": later,
                }
            },
        )
        for n in range(55)
    ]
    test_db_session.add_all(failing)
    await test_db_session.flush()
    for job in failing:
        job.user_metadata = {
            PUBLISH_FOLLOWUPS_FIELD: {
                **job.user_metadata[PUBLISH_FOLLOWUPS_FIELD],
                "attempt_id": str(job.attempt_id),
            }
        }
    await test_db_session.commit()
    failing_ids = [job.id for job in failing]
    fresh_id, _, fresh_record = await _owed_job(
        test_db_session, status="failed", error_message="refused"
    )
    try:
        await run_owed_publish_followups()

        assert not await _owes(fresh_id)
    finally:
        await _drop(test_db_session, fresh_id, fresh_record)
        await test_db_session.execute(
            delete(IngestJob).where(IngestJob.id.in_(failing_ids))
        )
        await test_db_session.commit()


async def test_the_sweep_takes_records_never_attempted_first_then_the_longest_due(
    test_db_session, monkeypatch
) -> None:
    """Records that keep failing, due longer than a fresh one, don't hold it back."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    # Inserted newest due first, so the table's own order is no help.
    failing = [
        IngestJob(
            dataset_id=dataset.id,
            status="complete",
            created_by=admin_id,
            user_metadata={
                PUBLISH_FOLLOWUPS_FIELD: {
                    "task": "reupload_file",
                    "archive_key": f"originals/{dataset.id}/keep-{n}.tif",
                    "attempts": 3,
                    "claimed": True,
                    "next_attempt_at": (since + timedelta(minutes=n)).isoformat(),
                }
            },
        )
        for n in reversed(range(55))
    ]
    test_db_session.add_all(failing)
    await test_db_session.flush()
    failing_ids = [job.id for job in reversed(failing)]
    await test_db_session.commit()
    fresh_id, _, fresh_record = await _owed_job(
        test_db_session, status="failed", error_message="refused"
    )
    try:
        selected = await _sweep_selections(monkeypatch)
        await run_owed_publish_followups()

        ours = [job for job in selected if job in {fresh_id, *failing_ids}]
        assert ours[0] == fresh_id
        assert ours[1:] == failing_ids[: len(ours) - 1]
        assert len(ours) > 1
    finally:
        await _drop(test_db_session, fresh_id, fresh_record)
        await test_db_session.execute(
            delete(IngestJob).where(IngestJob.id.in_(failing_ids))
        )
        await test_db_session.commit()


async def test_a_direct_call_runs_the_items_whatever_the_workers_clock_says(
    test_db_session, raster_storage, followups
) -> None:
    """A job ended by a worker whose clock runs ahead still has its items run at once."""
    job_id, _, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, "local")
        async with db_module.async_session() as session:
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(completed_at=datetime.now(timezone.utc) + timedelta(hours=1))
            )
            await session.commit()

        assert await run_publish_followups(job_id) is True

        assert await left() == []
        assert not await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_record_with_an_unreadable_next_attempt_counts_as_due(
    test_db_session, followups
) -> None:
    """A ``next_attempt_at`` that isn't a time neither stops the sweep nor holds the record."""
    job_id, _, record_id = await _owed_job(
        test_db_session, status="failed", error_message="refused"
    )
    try:
        async with db_module.async_session() as session:
            job = await session.get(IngestJob, job_id)
            owed = {
                **job.user_metadata[PUBLISH_FOLLOWUPS_FIELD],
                "next_attempt_at": "not a time",
            }
            job.user_metadata = {PUBLISH_FOLLOWUPS_FIELD: owed}
            await session.commit()

        await run_owed_publish_followups()

        assert not await _owes(job_id)
        assert ("notice", "ingest_failed") in followups
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_followup_records_do_not_crowd_the_artifact_reap(test_db_session) -> None:
    """A batch's worth of rows owing only follow-ups still leaves an artifact to reap."""
    from app.platform.jobs.sweep import (
        StaleCleanupOutcome,
        collect_unreaped_artifacts,
    )

    admin_id = await get_user_id(test_db_session, "admin")
    owing = [
        IngestJob(
            status="complete",
            created_by=admin_id,
            user_metadata={
                PUBLISH_FOLLOWUPS_FIELD: {
                    "task": "ingest_file",
                    "attempt_id": str(uuid.uuid4()),
                    "archive_key": f"originals/{uuid.uuid4()}/upload.csv",
                }
            },
        )
        for _ in range(500)
    ]
    key = f"rasters/{uuid.uuid4()}/source.cog.tif"
    naming = IngestJob(
        status="failed",
        created_by=admin_id,
        user_metadata={"unpublished_storage_keys": [key]},
    )
    test_db_session.add_all([*owing, naming])
    await test_db_session.flush()
    ids = [job.id for job in (*owing, naming)]
    await test_db_session.commit()
    try:
        outcome = await collect_unreaped_artifacts(
            test_db_session, StaleCleanupOutcome(*([0] * 10))
        )

        assert key in outcome._unpublished_storage_keys
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id.in_(ids)))
        await test_db_session.commit()


async def test_an_owed_archive_is_retried_at_the_cap_until_storage_recovers(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    """However long storage refuses, the archive stays owed and the upload held."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=None, **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        real_put = raster_storage.put
        outage = [True]

        async def _refused(written, data):
            if written == key and outage:
                raise RuntimeError("the object store refused the write")
            await real_put(written, data)

        async def _still_owed(attempts: int) -> None:
            metadata = await _stored_metadata(job_id)
            owed = metadata[PUBLISH_FOLLOWUPS_FIELD]
            assert (owed["archive_key"], owed["attempts"]) == (key, attempts)
            assert metadata[ARCHIVE_PENDING_METADATA_KEY] is True
            assert metadata["archive_failed"] is True
            assert await left() == [f"staging/{job_id}/frozen/upload.tif"]
            async with db_module.async_session() as session:
                wait = await session.scalar(
                    text(
                        "SELECT (user_metadata #>> "
                        "'{publish_followups,next_attempt_at}')::timestamptz - now() "
                        "FROM catalog.ingest_jobs WHERE id = :id"
                    ),
                    {"id": job_id},
                )
                held = await session.scalar(
                    select(IngestJob.id).where(
                        IngestJob.id == job_id, holds_unarchived_original()
                    )
                )
            assert timedelta(hours=3, minutes=55) < wait <= timedelta(hours=4)
            assert held == job_id

        monkeypatch.setattr(raster_storage, "put", _refused)
        for _ in range(9):
            await _make_due(job_id)
            await run_owed_publish_followups()
        await _still_owed(9)

        async with db_module.async_session() as session:
            await session.execute(
                text(
                    "UPDATE catalog.ingest_jobs SET user_metadata = jsonb_set("
                    "user_metadata, '{publish_followups,attempts}', '1000') "
                    "WHERE id = :id"
                ),
                {"id": job_id},
            )
            await session.commit()
        await _make_due(job_id)
        await run_owed_publish_followups()
        await _still_owed(1001)

        outage.clear()
        await _make_due(job_id)
        await run_owed_publish_followups()

        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
        metadata = await _stored_metadata(job_id)
        assert (
            not {
                ARCHIVE_PENDING_METADATA_KEY,
                "archive_failed",
                PUBLISH_FOLLOWUPS_FIELD,
            }
            & metadata.keys()
        )
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _refuse_once(monkeypatch, storage, method: str, refused_key: str) -> list:
    """Make ``storage.method`` fail the first call for ``refused_key``; returns the refusals."""
    real = getattr(storage, method)
    refused: list[str] = []

    async def _refused_once(key, *args, **kwargs):
        if key == refused_key and not refused:
            refused.append(key)
            raise RuntimeError("the object store refused the call")
        return await real(key, *args, **kwargs)

    monkeypatch.setattr(storage, method, _refused_once)
    return refused


@pytest.mark.parametrize(
    ("task", "owed", "expected"),
    [("ingest_raster", "delete", _RASTER), ("reupload_file", "archive", [])],
    ids=["first-ingest-delete", "replacement-archive"],
)
async def test_the_rest_runs_once_without_waiting_on_an_owed_item(
    test_db_session, raster_storage, followups, monkeypatch, task, owed, expected
) -> None:
    """The first claim runs the rest while an item is owed; the sweep that lands it runs nothing again."""
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task=task, reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, "storage")
        if owed == "delete":
            frozen = f"staging/{job_id}/frozen/upload.tif"
            refused = await _refuse_once(monkeypatch, raster_storage, "delete", frozen)
        else:
            key = await _owe_archive(job_id, dataset_id, "upload.tif")
            refused = await _refuse_once(monkeypatch, raster_storage, "put", key)

        assert await run_publish_followups(job_id) is True
        assert refused and followups == expected
        assert await left() == [f"staging/{job_id}/frozen/upload.tif"]
        assert (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD]["claimed"]

        await _make_due(job_id)
        assert await run_owed_publish_followups() == 0

        assert followups == expected
        assert await left() == []
        assert not await _owes(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_local_unlink_that_fails_stays_owed_until_a_later_sweep(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        left = await _stage_upload(raster_storage, job_id, "local")
        [staged] = await left()
        real_unlink = Path.unlink
        refused: list[Path] = []

        def _refused_once(self, missing_ok=False):
            if self == staged.resolve() and not refused:
                refused.append(self)
                raise PermissionError("the staging mount refused the unlink")
            return real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", _refused_once)

        assert await run_publish_followups(job_id) is True
        assert refused and await left() == [staged]
        owed = (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD]
        assert (owed["reaps_staged_upload"], owed["attempts"]) == (True, 1)

        await _make_due(job_id)
        await run_owed_publish_followups()

        assert await left() == []
        assert not await _owes(job_id)
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_presigned_delete_that_fails_stays_owed_until_a_later_sweep(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        left = await _stage_upload(raster_storage, job_id, "storage")
        client_key = f"staging/{job_id}/upload.tif"
        refused = await _refuse_once(monkeypatch, raster_storage, "delete", client_key)

        assert await run_publish_followups(job_id) is True
        assert refused and await left() == [client_key]
        owed = (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD]
        assert (owed["reaps_staged_upload"], owed["attempts"]) == (True, 1)

        await _make_due(job_id)
        await run_owed_publish_followups()

        assert await left() == []
        assert not await _owes(job_id)
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("where", ["local", "storage"])
async def test_an_upload_already_gone_confirms_its_delete_at_once(
    test_db_session, raster_storage, followups, where
) -> None:
    job_id, _, record_id = await _owed_job(test_db_session, reaps_staged_upload=True)
    try:
        left = await _stage_upload(raster_storage, job_id, where)
        for gone in await left():
            if where == "local":
                gone.unlink()
            else:
                await raster_storage.delete(gone)

        assert await run_publish_followups(job_id) is True
        assert not await _owes(job_id)
        assert followups == _RASTER
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize(
    "item", ["archive_key", "reaps_staged_upload"], ids=["archive", "delete"]
)
async def test_confirming_one_item_leaves_every_other_owed(
    test_db_session, item
) -> None:
    """An item comes off the record alone, and only for the attempt that wrote it."""
    from app.processing.ingest.publish_followups import _confirm_owed_item

    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _owe_archive(job_id, dataset_id, "upload.tif")
        before = (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD]
        before = {**before, "attempts": 2, "claimed": True}
        await _point_job_at(job_id, file_path=None, **{PUBLISH_FOLLOWUPS_FIELD: before})

        await _confirm_owed_item(job_id, str(uuid.uuid4()), item)
        assert (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD] == before

        await _confirm_owed_item(job_id, before["attempt_id"], item)

        after = (await _stored_metadata(job_id))[PUBLISH_FOLLOWUPS_FIELD]
        assert after == {key: value for key, value in before.items() if key != item}
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("race", ["read-lost", "write-timed-out", "check-flaked"])
async def test_an_archive_found_after_a_failure_counts_as_made(
    test_db_session, raster_storage, followups, monkeypatch, race
) -> None:
    """A run that fails but then finds the archive in place flags nothing and deletes the upload.

    Another run can archive and delete the upload while this one reads it, a
    write can land though its call fails, and a store can refuse one
    existence check and answer the next.
    """
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        if race == "read-lost":

            async def _read_lost(src, dest):
                await raster_storage.put(key, b"staged")
                await raster_storage.delete(src)
                raise RuntimeError("the staged object is gone")

            monkeypatch.setattr(raster_storage, "get_to_file", _read_lost)
        elif race == "write-timed-out":
            real_put = raster_storage.put

            async def _put_timed_out(written, data):
                await real_put(written, data)
                if written == key:
                    raise RuntimeError("the object store timed out")

            monkeypatch.setattr(raster_storage, "put", _put_timed_out)
        else:
            await raster_storage.put(key, b"staged")
            real_exists = raster_storage.exists
            refused: list[str] = []

            async def _flaky_exists(checked):
                if checked == key and not refused:
                    refused.append(checked)
                    raise RuntimeError("the object store timed out")
                return await real_exists(checked)

            monkeypatch.setattr(raster_storage, "exists", _flaky_exists)

        assert await run_publish_followups(job_id) is True
        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
        async with db_module.async_session() as session:
            metadata = await session.scalar(
                select(IngestJob.user_metadata).where(IngestJob.id == job_id)
            )
        assert "archive_failed" not in metadata
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("fails_in", ["put", "read"])
async def test_a_failure_racing_a_confirmed_archive_restores_nothing(
    test_db_session, raster_storage, followups, monkeypatch, fails_in
) -> None:
    """A run whose archive fails after another run confirmed it leaves the job settled.

    The losing run's store then can't tell it the archive exists, so only the
    guards on its failure write keep the settled record, mark and flag away.
    """
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=None, **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        left = await _stage_upload(raster_storage, job_id, "storage")
        key = await _owe_archive(job_id, dataset_id, "upload.tif")
        method, raced = {
            "put": ("put", key),
            "read": ("get_to_file", f"staging/{job_id}/frozen/upload.tif"),
        }[fails_in]
        real, real_exists = getattr(raster_storage, method), raster_storage.exists
        race: dict = {"running": False, "won": None}

        async def _loses_the_race(first, *args):
            if race["running"] or race["won"] is not None or first != raced:
                return await real(first, *args)
            race["running"] = True
            race["won"] = await run_publish_followups(job_id)
            raise RuntimeError("the object store refused the call")

        async def _unsure_once_lost(checked):
            if race["won"] is not None and checked == key:
                raise RuntimeError("the object store timed out")
            return await real_exists(checked)

        monkeypatch.setattr(raster_storage, method, _loses_the_race)
        monkeypatch.setattr(raster_storage, "exists", _unsure_once_lost)

        await run_publish_followups(job_id)

        assert race["won"] is True
        assert await raster_storage.get(key) == b"staged"
        assert await left() == []
        metadata = await _stored_metadata(job_id)
        assert (
            not {
                PUBLISH_FOLLOWUPS_FIELD,
                ARCHIVE_PENDING_METADATA_KEY,
                "archive_failed",
                "archive_error",
            }
            & metadata.keys()
        )
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_an_archive_failure_lands_only_for_the_attempt_that_owns_the_job(
    test_db_session,
) -> None:
    from app.processing.ingest.publish_followups import _note_archive_outcome

    job_id, _, record_id = await _owed_job(test_db_session, task="reupload_file")
    try:
        await _point_job_at(
            job_id, file_path=None, **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        async with db_module.async_session() as session:
            attempt_id = str(
                await session.scalar(
                    select(IngestJob.attempt_id).where(IngestJob.id == job_id)
                )
            )

        await _note_archive_outcome(job_id, str(uuid.uuid4()), "the store refused")
        assert "archive_failed" not in await _stored_metadata(job_id)

        await _note_archive_outcome(job_id, attempt_id, "the store refused")
        assert (await _stored_metadata(job_id))["archive_failed"] is True
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_an_upload_outside_the_staging_dir_is_never_archived(
    test_db_session, raster_storage, tmp_path, followups
) -> None:
    """A replacement naming a file outside the staging directory neither archives nor deletes it."""
    outside = tmp_path / "keep.tif"
    outside.write_bytes(b"not an upload")
    job_id, dataset_id, record_id = await _owed_job(
        test_db_session, task="reupload_file", reaps_staged_upload=True
    )
    try:
        await _point_job_at(
            job_id, file_path=str(outside), **{ARCHIVE_PENDING_METADATA_KEY: True}
        )
        key = await _owe_archive(job_id, dataset_id, "keep.tif")

        assert await run_publish_followups(job_id) is True
        assert not await raster_storage.exists(key)
        assert outside.read_bytes() == b"not an upload"
        metadata = await _stored_metadata(job_id)
        assert metadata["archive_failed"] is True
        assert metadata[PUBLISH_FOLLOWUPS_FIELD]["archive_key"] == key
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

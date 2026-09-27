"""The archive flags on a published job clear only once the job provably owes no archive."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import structlog
from sqlalchemy import delete, select, text

import app.core.db as db_module
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    ARCHIVE_REVIEW_METADATA_KEY,
    IngestJob,
    holds_unarchived_original,
)
from app.processing.ingest.publish_followups import (
    PUBLISH_FOLLOWUPS_FIELD,
    run_owed_publish_followups,
)
from tests.factories import create_dataset, get_user_id
from tests.test_publish_followups import _make_due, _stored_metadata
from tests.test_publish_followups import followups as followups
from tests.test_raster_replace_1221 import _storage_calls
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

_FLAGS = {"archive_failed", "archive_error", ARCHIVE_PENDING_METADATA_KEY}


@pytest.fixture
def staging(tmp_path, monkeypatch) -> Path:
    """An upload staging directory of this test's own."""
    root = tmp_path / "staging"
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "upload_staging_dir", str(root))
    return root


def _archive_flags(failed: bool) -> dict:
    """A failed archive's flags, or a pending one's."""
    if failed:
        return {"archive_failed": True, "archive_error": "the store refused the write"}
    return {ARCHIVE_PENDING_METADATA_KEY: True}


async def _flagged_job(
    session,
    *,
    file_path: str | None = None,
    ended_ago=timedelta(days=2),
    failed: bool = True,
    **metadata,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A complete job of a live dataset whose archive failed, or was pending, before archives were owed.

    Returns (job, dataset, record).
    """
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    ended = datetime.now(timezone.utc) - ended_ago
    job = IngestJob(
        dataset_id=dataset.id,
        status="complete",
        created_by=admin_id,
        created_at=ended,
        completed_at=ended,
        file_path=file_path,
        user_metadata={**_archive_flags(failed), **metadata},
    )
    session.add(job)
    await session.commit()
    return job.id, dataset.id, dataset.record_id


async def _set_path(job_id, file_path: str | None) -> None:
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, job_id)
        job.file_path = file_path
        await session.commit()


def _stage(staging: Path, owner) -> Path:
    upload = staging / f"{owner}_roads.gpkg"
    upload.write_bytes(b"original")
    return upload


async def _held(job_id) -> bool:
    async with db_module.async_session() as session:
        return (
            await session.scalar(
                select(IngestJob.id).where(
                    IngestJob.id == job_id, holds_unarchived_original()
                )
            )
        ) is not None


async def _drop(session, job_id, record_id) -> None:
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    await session.execute(delete(Record).where(Record.id == record_id))
    await session.commit()


async def _delete_dataset(dataset_id, record_id) -> None:
    async with db_module.async_session() as session:
        await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await session.execute(delete(Record).where(Record.id == record_id))
        await session.commit()


def _touched(calls, *ids) -> list[str]:
    """The keys among ``calls`` that name any of ``ids``; other tests share the database."""
    return [
        key for key in calls["put"] + calls["delete"] if any(str(i) in key for i in ids)
    ]


async def _adopt_and_run() -> None:
    """One sweep owes a flagged job's archive again, and the next runs it."""
    await run_owed_publish_followups()
    await run_owed_publish_followups()


def _review_logs(logs) -> list:
    return [entry for entry in logs if entry["event"] == "archive_needs_review"]


# --- An owed archive -------------------------------------------------------


async def _owing_archive(
    session, *, file_path: str | None, failed: bool = True
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    """A published job owing its upload's archive, flagged as failed unless ``failed`` is False; also returns the key."""
    job_id, dataset_id, record_id = await _flagged_job(
        session, file_path=file_path, failed=failed
    )
    key = f"originals/{dataset_id}/{job_id}_roads.gpkg"
    async with db_module.async_session() as writer:
        job = await writer.get(IngestJob, job_id)
        job.user_metadata = {
            **job.user_metadata,
            ARCHIVE_PENDING_METADATA_KEY: True,
            PUBLISH_FOLLOWUPS_FIELD: {
                "task": "reupload_file",
                "attempt_id": str(job.attempt_id),
                "archive_key": key,
            },
        }
        await writer.commit()
    return job_id, dataset_id, record_id, key


async def test_a_deleted_datasets_owed_archive_takes_its_flags_with_it(
    test_db_session, raster_storage, followups
) -> None:
    """With the dataset gone nothing is owed, so the item and every archive flag go."""
    job_id, dataset_id, record_id, key = await _owing_archive(
        test_db_session, file_path=None
    )
    try:
        await _delete_dataset(dataset_id, record_id)

        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await raster_storage.exists(key)
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("file_path", [None, ""], ids=["null", "empty"])
async def test_an_owed_archive_with_no_upload_is_held_and_marked_for_review_once(
    test_db_session, raster_storage, followups, file_path
) -> None:
    """A missing path is no proof of an archive, and no retry can make one."""
    job_id, dataset_id, record_id, key = await _owing_archive(
        test_db_session, file_path=file_path
    )
    try:
        with structlog.testing.capture_logs() as logs:
            with _storage_calls(raster_storage) as calls:
                await run_owed_publish_followups()
                await run_owed_publish_followups()

        assert _touched(calls, job_id, dataset_id) == []
        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "original_missing"
        assert metadata["archive_failed"] is True
        assert metadata[ARCHIVE_PENDING_METADATA_KEY] is True
        assert PUBLISH_FOLLOWUPS_FIELD not in metadata, "it would hold a sweep slot"
        assert await _held(job_id)
        assert [(e["job_id"], e["reason"]) for e in _review_logs(logs)] == [
            (str(job_id), "original_missing")
        ]
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("failed", [False, True], ids=["pending", "failed"])
async def test_an_owed_archive_with_no_upload_counts_an_archive_in_storage_only_if_none_failed(
    test_db_session, raster_storage, followups, failed
) -> None:
    """A failed write may have left the object there truncated, so it confirms nothing."""
    job_id, _, record_id, key = await _owing_archive(
        test_db_session, file_path=None, failed=failed
    )
    try:
        await raster_storage.put(key, b"orig")

        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert PUBLISH_FOLLOWUPS_FIELD not in metadata
        if failed:
            assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "archive_unverified"
            assert metadata["archive_failed"] is True
            assert await _held(job_id)
        else:
            assert not (_FLAGS | {ARCHIVE_REVIEW_METADATA_KEY}) & metadata.keys()
            assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_an_owed_archive_with_no_upload_backs_off_while_the_store_cannot_answer(
    test_db_session, raster_storage, followups, monkeypatch
) -> None:
    """An unreadable store decides nothing, and the job waits out the capped delay."""
    job_id, _, record_id, key = await _owing_archive(test_db_session, file_path=None)
    try:
        real_exists = raster_storage.exists
        outage = [True]
        checks: list[str] = []

        async def _unreadable(checked):
            checks.append(checked)
            if outage:
                raise RuntimeError("the object store timed out")
            return await real_exists(checked)

        monkeypatch.setattr(raster_storage, "exists", _unreadable)
        await run_owed_publish_followups()
        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        owed = metadata[PUBLISH_FOLLOWUPS_FIELD]
        assert (owed["archive_key"], owed["attempts"]) == (key, 1)
        assert ARCHIVE_REVIEW_METADATA_KEY not in metadata
        assert checks.count(key) == 1, "a job not yet due took a second sweep slot"
        async with db_module.async_session() as session:
            wait = await session.scalar(
                text(
                    "SELECT (user_metadata #>> "
                    "'{publish_followups,next_attempt_at}')::timestamptz - now() "
                    "FROM catalog.ingest_jobs WHERE id = :id"
                ),
                {"id": job_id},
            )
        assert timedelta(minutes=4) < wait <= timedelta(minutes=5)

        outage.clear()
        await _make_due(job_id)
        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "original_missing"
        assert PUBLISH_FOLLOWUPS_FIELD not in metadata
        assert await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("upload", ["local", "storage"])
async def test_an_archive_in_place_confirms_a_pending_job_without_reading_its_upload(
    test_db_session, raster_storage, followups, staging, monkeypatch, upload
) -> None:
    """No attempt failed, so the object is whole; reading a vanished upload costs retries."""
    job_id, _, record_id, key = await _owing_archive(
        test_db_session, file_path=None, failed=False
    )
    try:
        if upload == "local":
            await _set_path(job_id, str(staging / f"{job_id}_roads.gpkg"))
        else:
            await _set_path(job_id, f"staging/{job_id}/frozen/roads.gpkg")
        await raster_storage.put(key, b"original")
        import app.processing.ingest.service as service

        real_read = service.resolve_file_path
        reads: list[str] = []

        async def _read(file_path, reader=None):
            if str(job_id) not in file_path:
                return await real_read(file_path, reader)
            reads.append(file_path)
            raise AssertionError("the upload was read")

        monkeypatch.setattr(service, "resolve_file_path", _read)
        await run_owed_publish_followups()

        assert reads == []
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("upload", ["vanished", "outside-staging"])
async def test_an_unreadable_upload_does_not_vouch_for_an_object_after_a_failure(
    test_db_session, raster_storage, followups, staging, tmp_path, upload
) -> None:
    """With nothing to measure it against, an object left after a failed attempt may be truncated."""
    job_id, _, record_id, key = await _owing_archive(test_db_session, file_path=None)
    try:
        if upload == "vanished":
            path = staging / f"{job_id}_roads.gpkg"
        else:
            path = tmp_path / f"{job_id}_roads.gpkg"
            path.write_bytes(b"original")
        await _set_path(job_id, str(path))
        await raster_storage.put(key, b"orig")

        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert metadata[PUBLISH_FOLLOWUPS_FIELD]["archive_key"] == key
        assert metadata["archive_failed"] is True
        assert metadata[ARCHIVE_PENDING_METADATA_KEY] is True
        assert await _held(job_id)
        assert await raster_storage.get(key) == b"orig"
    finally:
        await _drop(test_db_session, job_id, record_id)


# --- A flag nothing owes ---------------------------------------------------


@pytest.mark.parametrize("owner", ["job", "fan-out parent"])
async def test_a_flagged_local_upload_is_archived_and_released(
    test_db_session, raster_storage, followups, staging, owner
) -> None:
    """The row names the upload and its archive, so the archive is owed again and made."""
    parent_id = str(uuid.uuid4())
    extra = {"fan_out_parent_id": parent_id} if owner != "job" else {}
    job_id, dataset_id, record_id = await _flagged_job(test_db_session, **extra)
    try:
        upload = _stage(staging, parent_id if extra else job_id)
        await _set_path(job_id, str(upload))

        await _adopt_and_run()

        key = f"originals/{dataset_id}/{upload.name}"
        assert await raster_storage.get(key) == b"original"
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await _held(job_id)
        assert followups == []
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_job_that_ended_recently_is_left_to_its_own_followups(
    test_db_session, raster_storage, followups, staging
) -> None:
    """Its own archive or cleanup may still be in flight, so the sweep neither owes nor marks it."""
    job_id, dataset_id, record_id = await _flagged_job(
        test_db_session, ended_ago=timedelta(hours=1)
    )
    try:
        upload = _stage(staging, job_id)
        await _set_path(job_id, str(upload))

        with structlog.testing.capture_logs() as logs:
            await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert not {PUBLISH_FOLLOWUPS_FIELD, ARCHIVE_REVIEW_METADATA_KEY} & (
            metadata.keys()
        )
        assert metadata["archive_failed"] is True
        assert not await raster_storage.exists(f"originals/{dataset_id}/{upload.name}")
        assert await _held(job_id)
        assert _review_logs(logs) == []
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_flagged_upload_whose_full_archive_is_in_place_is_released_without_a_copy(
    test_db_session, raster_storage, followups, staging
) -> None:
    job_id, dataset_id, record_id = await _flagged_job(test_db_session)
    try:
        upload = _stage(staging, job_id)
        await _set_path(job_id, str(upload))
        key = f"originals/{dataset_id}/{upload.name}"
        await raster_storage.put(key, b"original")

        with _storage_calls(raster_storage) as calls:
            await _adopt_and_run()

        assert _touched(calls, job_id, dataset_id) == []
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("refused_once", [False, True], ids=["written", "refused-once"])
async def test_a_truncated_archive_is_written_again_before_it_counts(
    test_db_session, raster_storage, followups, staging, monkeypatch, refused_once
) -> None:
    """An object shorter than the upload is no archive: it is replaced, and only then confirmed."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session)
    try:
        upload = _stage(staging, job_id)
        await _set_path(job_id, str(upload))
        key = f"originals/{dataset_id}/{upload.name}"
        await raster_storage.put(key, b"orig")
        real_put = raster_storage.put
        outage = [True] if refused_once else []

        async def _refused(written, data):
            if written == key and outage:
                raise RuntimeError("the object store refused the write")
            await real_put(written, data)

        monkeypatch.setattr(raster_storage, "put", _refused)
        await _adopt_and_run()
        if refused_once:
            assert await raster_storage.get(key) == b"orig"
            metadata = await _stored_metadata(job_id)
            assert metadata[PUBLISH_FOLLOWUPS_FIELD]["archive_key"] == key
            assert metadata["archive_failed"] is True
            assert await _held(job_id)
            outage.clear()
            await _make_due(job_id)
            await run_owed_publish_followups()

        assert await raster_storage.get(key) == b"original"
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_pending_archive_in_place_without_its_upload_is_released(
    test_db_session, raster_storage, followups, staging
) -> None:
    """No attempt failed, so the object there was written whole."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session, failed=False)
    try:
        await _set_path(job_id, str(staging / f"{job_id}_roads.gpkg"))
        await raster_storage.put(
            f"originals/{dataset_id}/{job_id}_roads.gpkg", b"original"
        )

        await _adopt_and_run()

        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_failed_archive_in_place_without_its_upload_is_kept_for_review(
    test_db_session, raster_storage, followups, staging
) -> None:
    """With nothing to measure it against, an object left by a failed write may be truncated."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session)
    try:
        await _set_path(job_id, str(staging / f"{job_id}_roads.gpkg"))
        key = f"originals/{dataset_id}/{job_id}_roads.gpkg"
        await raster_storage.put(key, b"orig")

        with structlog.testing.capture_logs() as logs:
            await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "archive_unverified"
        assert metadata["archive_failed"] is True
        assert PUBLISH_FOLLOWUPS_FIELD not in metadata
        assert await _held(job_id)
        assert await raster_storage.get(key) == b"orig"
        assert [e["reason"] for e in _review_logs(logs)] == ["archive_unverified"]
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("upload", ["present", "gone"])
async def test_a_key_storage_would_refuse_is_kept_for_review(
    test_db_session, raster_storage, followups, staging, upload
) -> None:
    """The row can't name an archive storage would accept, so no pass could settle it."""
    job_id, _, record_id = await _flagged_job(test_db_session)
    try:
        path = staging / f"{job_id}_roads..v2.gpkg"
        if upload == "present":
            path.write_bytes(b"original")
        await _set_path(job_id, str(path))

        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "archive_unknown"
        assert metadata["archive_failed"] is True
        assert PUBLISH_FOLLOWUPS_FIELD not in metadata
        assert await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _place(case: str, staging: Path, tmp_path: Path, storage, job_id) -> None:
    """Bind the job to an upload whose archive its row can't name."""
    if case == "staging-key":
        key = f"staging/{job_id}/frozen/roads.gpkg"
        await storage.put(key, b"original")
        await _set_path(job_id, key)
    elif case == "unprefixed":
        await _set_path(job_id, str(_stage(staging, "survey")))
    elif case == "outside-staging":
        outside = tmp_path / f"{job_id}_roads.gpkg"
        outside.write_bytes(b"original")
        await _set_path(job_id, str(outside))
    elif case == "no-attempt":
        await _set_path(job_id, str(_stage(staging, job_id)))
        async with db_module.async_session() as session:
            await session.execute(
                text("UPDATE catalog.ingest_jobs SET attempt_id = NULL WHERE id = :id"),
                {"id": job_id},
            )
            await session.commit()


@pytest.mark.parametrize(
    "case", ["staging-key", "unprefixed", "outside-staging", "no-path", "no-attempt"]
)
async def test_a_flag_whose_archive_the_row_cannot_name_is_kept_for_review(
    test_db_session, raster_storage, followups, staging, tmp_path, case
) -> None:
    """Nothing is archived or released; the job is marked and reported once, however often the sweep runs."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session)
    try:
        await _place(case, staging, tmp_path, raster_storage, job_id)

        with structlog.testing.capture_logs() as logs:
            with _storage_calls(raster_storage) as calls:
                await run_owed_publish_followups()
                await run_owed_publish_followups()

        assert _touched(calls, job_id, dataset_id) == []
        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "archive_unknown"
        assert metadata["archive_failed"] is True
        assert PUBLISH_FOLLOWUPS_FIELD not in metadata
        assert await _held(job_id)
        assert [(e["job_id"], e["reason"]) for e in _review_logs(logs)] == [
            (str(job_id), "archive_unknown")
        ]
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_flag_whose_upload_and_archive_are_both_gone_is_kept_for_review(
    test_db_session, raster_storage, followups, staging
) -> None:
    job_id, _, record_id = await _flagged_job(test_db_session)
    try:
        await _set_path(job_id, str(staging / f"{job_id}_roads.gpkg"))

        with structlog.testing.capture_logs() as logs:
            await run_owed_publish_followups()
            await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert metadata[ARCHIVE_REVIEW_METADATA_KEY] == "original_missing"
        assert metadata["archive_failed"] is True
        assert await _held(job_id)
        assert len(_review_logs(logs)) == 1
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_store_that_cannot_answer_decides_nothing_until_it_can(
    test_db_session, raster_storage, followups, staging, monkeypatch
) -> None:
    """An unreadable store neither marks the job nor releases it; a later pass does."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session, failed=False)
    try:
        await _set_path(job_id, str(staging / f"{job_id}_roads.gpkg"))
        key = f"originals/{dataset_id}/{job_id}_roads.gpkg"
        await raster_storage.put(key, b"original")
        real_exists = raster_storage.exists
        outage = [True]

        async def _unreadable(checked):
            if outage:
                raise RuntimeError("the object store timed out")
            return await real_exists(checked)

        monkeypatch.setattr(raster_storage, "exists", _unreadable)
        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert not {ARCHIVE_REVIEW_METADATA_KEY, PUBLISH_FOLLOWUPS_FIELD} & (
            metadata.keys()
        )
        assert await _held(job_id)

        outage.clear()
        await _adopt_and_run()

        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {ARCHIVE_REVIEW_METADATA_KEY}) & metadata.keys()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_job_the_store_cannot_decide_leaves_room_for_the_others(
    test_db_session, raster_storage, followups, staging, monkeypatch
) -> None:
    """Even with one job a batch and the undecidable job first by id, the other is reached."""
    import app.processing.ingest.publish_followups as publish_followups

    (stuck_id, stuck_dataset, stuck_record), (ready_id, _, ready_record) = sorted(
        [await _flagged_job(test_db_session), await _flagged_job(test_db_session)]
    )
    try:
        await _set_path(stuck_id, str(staging / f"{stuck_id}_roads.gpkg"))
        await _set_path(ready_id, str(_stage(staging, ready_id)))
        stuck_key = f"originals/{stuck_dataset}/{stuck_id}_roads.gpkg"
        real_exists = raster_storage.exists

        async def _undecided(checked):
            if checked == stuck_key:
                raise RuntimeError("the object store timed out")
            return await real_exists(checked)

        monkeypatch.setattr(raster_storage, "exists", _undecided)
        monkeypatch.setattr(publish_followups, "_SWEEP_BATCH", 1)

        async def _ready_reached() -> bool:
            metadata = await _stored_metadata(ready_id)
            return PUBLISH_FOLLOWUPS_FIELD in metadata or not await _held(ready_id)

        for _ in range(20):
            await run_owed_publish_followups()
            if await _ready_reached():
                break

        assert await _ready_reached()
        stuck = await _stored_metadata(stuck_id)
        assert not {PUBLISH_FOLLOWUPS_FIELD, ARCHIVE_REVIEW_METADATA_KEY} & stuck.keys()
        assert await _held(stuck_id)
    finally:
        await _drop(test_db_session, stuck_id, stuck_record)
        await _drop(test_db_session, ready_id, ready_record)


async def test_an_archive_the_store_refuses_is_retried_until_it_lands(
    test_db_session, raster_storage, followups, staging, monkeypatch
) -> None:
    job_id, dataset_id, record_id = await _flagged_job(test_db_session)
    try:
        upload = _stage(staging, job_id)
        await _set_path(job_id, str(upload))
        key = f"originals/{dataset_id}/{upload.name}"
        real_put = raster_storage.put
        outage = [True]

        async def _refused(written, data):
            if written == key and outage:
                raise RuntimeError("the object store refused the write")
            await real_put(written, data)

        monkeypatch.setattr(raster_storage, "put", _refused)
        await _adopt_and_run()

        metadata = await _stored_metadata(job_id)
        assert metadata[PUBLISH_FOLLOWUPS_FIELD]["archive_key"] == key
        assert metadata["archive_failed"] is True
        assert await _held(job_id)
        assert upload.exists()

        outage.clear()
        await _make_due(job_id)
        await run_owed_publish_followups()

        assert await raster_storage.get(key) == b"original"
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_concurrent_sweeps_settle_each_flag_once(
    test_db_session, raster_storage, followups, staging, monkeypatch
) -> None:
    """Sweeps that all read a job before any writes archive the one, and mark and report the other once."""
    import app.processing.ingest.publish_followups as publish_followups

    owed_id, owed_dataset, owed_record = await _flagged_job(test_db_session)
    unknown_id, _, unknown_record = await _flagged_job(test_db_session)
    sweeps = 3
    real_reason = publish_followups._review_reason
    arrived: list = []
    all_read = asyncio.Event()

    async def _once_every_sweep_has_read(row, key):
        arrived.append(row.id)
        if len(arrived) >= sweeps:
            all_read.set()
        await asyncio.wait_for(all_read.wait(), timeout=30)
        return await real_reason(row, key)

    monkeypatch.setattr(publish_followups, "_review_reason", _once_every_sweep_has_read)
    try:
        upload = _stage(staging, owed_id)
        await _set_path(owed_id, str(upload))
        await _set_path(unknown_id, f"staging/{unknown_id}/frozen/roads.gpkg")

        with structlog.testing.capture_logs() as logs:
            await asyncio.gather(*(run_owed_publish_followups() for _ in range(sweeps)))
        await run_owed_publish_followups()

        key = f"originals/{owed_dataset}/{upload.name}"
        assert await raster_storage.get(key) == b"original"
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & (
            (await _stored_metadata(owed_id)).keys()
        )
        unknown = await _stored_metadata(unknown_id)
        assert unknown[ARCHIVE_REVIEW_METADATA_KEY] == "archive_unknown"
        assert PUBLISH_FOLLOWUPS_FIELD not in unknown
        assert [e["job_id"] for e in _review_logs(logs)] == [str(unknown_id)]
    finally:
        await _drop(test_db_session, owed_id, owed_record)
        await _drop(test_db_session, unknown_id, unknown_record)


@pytest.mark.parametrize("failed", [False, True], ids=["pending", "failed"])
async def test_a_dataset_deleted_while_its_flag_is_decided_owes_nothing(
    test_db_session, raster_storage, followups, staging, monkeypatch, failed
) -> None:
    """The write that owes the archive again, or marks it, lands only while the dataset is live."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session, failed=failed)
    try:
        await _set_path(job_id, str(staging / f"{job_id}_roads.gpkg"))
        await raster_storage.put(
            f"originals/{dataset_id}/{job_id}_roads.gpkg", b"original"
        )
        real_exists = raster_storage.exists

        async def _deleted_meanwhile(checked):
            await _delete_dataset(dataset_id, record_id)
            return await real_exists(checked)

        monkeypatch.setattr(raster_storage, "exists", _deleted_meanwhile)
        await run_owed_publish_followups()

        metadata = await _stored_metadata(job_id)
        assert not {PUBLISH_FOLLOWUPS_FIELD, ARCHIVE_REVIEW_METADATA_KEY} & (
            metadata.keys()
        )
        assert _archive_flags(failed).items() <= metadata.items()
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _delete_as_the_api_does(dataset_id, record_id, storage) -> None:
    """Delete a dataset in the order its route does: lock its jobs, delete, commit, then reap originals/."""
    from app.platform.catalog_locks import lock_ingest_jobs

    async with db_module.async_session() as session:
        await lock_ingest_jobs(session, job_cls=IngestJob, dataset_id=dataset_id)
        await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await session.execute(delete(Record).where(Record.id == record_id))
        await session.commit()
    for key in await storage.list(f"originals/{dataset_id}/"):
        await storage.delete(key)


async def test_a_dataset_deleted_before_its_archive_is_written_gets_none(
    test_db_session, raster_storage, followups, staging, monkeypatch
) -> None:
    """A delete that commits and reaps after the job was read leaves no archive behind it."""
    upload_name = "roads.gpkg"
    job_id, dataset_id, record_id, key = await _owing_archive(
        test_db_session, file_path=None, failed=False
    )
    try:
        upload = staging / f"{job_id}_{upload_name}"
        upload.write_bytes(b"original")
        await _set_path(job_id, str(upload))
        real_exists = raster_storage.exists
        deleted: list[bool] = []

        async def _deleted_after_the_read(checked):
            if checked == key and not deleted:
                deleted.append(True)
                await _delete_as_the_api_does(dataset_id, record_id, raster_storage)
            return await real_exists(checked)

        monkeypatch.setattr(raster_storage, "exists", _deleted_after_the_read)
        await run_owed_publish_followups()

        assert deleted
        assert not await real_exists(key)
        await _make_due(job_id)
        await run_owed_publish_followups()
        assert not await real_exists(key)
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_dataset_delete_waits_for_an_archive_being_written_then_reaps_it(
    test_db_session, raster_storage, followups, staging, monkeypatch
) -> None:
    """The delete takes the job's row only once the write is done, so its reap removes the archive."""
    job_id, dataset_id, record_id, key = await _owing_archive(
        test_db_session, file_path=None, failed=False
    )
    try:
        upload = staging / f"{job_id}_roads.gpkg"
        upload.write_bytes(b"original")
        await _set_path(job_id, str(upload))
        real_put = raster_storage.put
        deletion: list[asyncio.Task] = []
        finished_before_the_write: list[bool] = []

        async def _deleted_during_the_write(written, data):
            if written == key and not deletion:
                deletion.append(
                    asyncio.create_task(
                        _delete_as_the_api_does(dataset_id, record_id, raster_storage)
                    )
                )
                await asyncio.sleep(0.5)
                finished_before_the_write.append(deletion[0].done())
            await real_put(written, data)

        monkeypatch.setattr(raster_storage, "put", _deleted_during_the_write)
        await run_owed_publish_followups()
        await deletion[0]

        assert finished_before_the_write == [False]
        assert not await raster_storage.exists(key)
        metadata = await _stored_metadata(job_id)
        assert not (_FLAGS | {PUBLISH_FOLLOWUPS_FIELD}) & metadata.keys()
    finally:
        await _drop(test_db_session, job_id, record_id)


async def _owed_notices(session, count: int) -> list[uuid.UUID]:
    """``count`` failed jobs owing their failure notice, due before anything a test leaves behind."""
    long_ago = datetime(2000, 1, 1, tzinfo=timezone.utc)
    jobs = [
        IngestJob(status="failed", created_at=long_ago, completed_at=long_ago)
        for _ in range(count)
    ]
    session.add_all(jobs)
    await session.flush()
    for job in jobs:
        job.user_metadata = {
            PUBLISH_FOLLOWUPS_FIELD: {
                "task": "reupload_file",
                "attempt_id": str(job.attempt_id),
            }
        }
    await session.commit()
    return [job.id for job in jobs]


@pytest.mark.parametrize("owed", [3, 2], ids=["batch-full", "room-left"])
async def test_flagged_jobs_are_owed_again_only_with_the_room_owed_followups_leave(
    test_db_session, raster_storage, followups, staging, monkeypatch, owed
) -> None:
    """Follow-ups already owed take the batch first; flagged jobs get only what is left."""
    import app.processing.ingest.publish_followups as publish_followups

    monkeypatch.setattr(publish_followups, "_SWEEP_BATCH", 3)
    notices = await _owed_notices(test_db_session, owed)
    flagged = [await _flagged_job(test_db_session) for _ in range(2)]
    try:
        for job_id, _, _ in flagged:
            await _set_path(job_id, str(_stage(staging, job_id)))

        await run_owed_publish_followups()

        for job_id in notices:
            assert PUBLISH_FOLLOWUPS_FIELD not in (await _stored_metadata(job_id) or {})
        adopted = [
            job_id
            for job_id, _, _ in flagged
            if PUBLISH_FOLLOWUPS_FIELD in await _stored_metadata(job_id)
            or not await _held(job_id)
        ]
        assert len(adopted) == 3 - owed
    finally:
        async with db_module.async_session() as session:
            await session.execute(delete(IngestJob).where(IngestJob.id.in_(notices)))
            await session.commit()
        for job_id, _, record_id in flagged:
            await _drop(test_db_session, job_id, record_id)


async def test_an_admin_cleanup_releases_a_flagged_local_upload(
    client, admin_auth_header, test_db_session, raster_storage, followups
) -> None:
    """The operator's stale-job cleanup runs the same repair."""
    job_id, dataset_id, record_id = await _flagged_job(test_db_session)
    try:
        upload = _stage(Path(settings.upload_staging_dir), job_id)
        await _set_path(job_id, str(upload))

        for _ in range(2):
            response = await client.post(
                "/jobs/cleanup/stale/", headers=admin_auth_header
            )

        assert response.status_code == 200, response.text
        key = f"originals/{dataset_id}/{upload.name}"
        assert await raster_storage.get(key) == b"original"
        assert not await _held(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)

"""Publish follow-ups outlive a worker that dies after the claim or the publish commit."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import structlog
from sqlalchemy import delete, select, text, update

import app.core.db as db_module
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Record
from app.platform.jobs.models import PUBLISH_FOLLOWUPS_FIELD, IngestJob
from app.processing.ingest.publish_followups import (
    owed_followups,
    run_owed_publish_followups,
    run_publish_followups,
)
from tests.factories import create_dataset, get_user_id
from tests.test_publish_followups import _make_due
from tests.test_replacement_post_commit import _archived, _upload_left
from tests.test_replacement_post_commit import replace as replace
from tests.test_replacement_post_commit import storage as storage
from tests.test_vector_archive_dataset_delete import _Import
from tests.test_vector_archive_dataset_delete import store as store

pytestmark = pytest.mark.anyio

_RASTER = [("cache",), ("embed",), ("notice", "ingest_complete"), ("bill",)]


class _Ran(list):
    """The run-once items that ran, in order, and the notices' payloads."""

    def __init__(self) -> None:
        super().__init__()
        self.notices: list[dict] = []
        self.dies: dict[str, str] = {}

    def die(self, step: str, *, when: str = "before") -> None:
        """Make ``step`` cancel the worker once, ``before`` it lands or ``after``."""
        self.dies[step] = when

    def step(self, step: tuple, payload: dict | None = None) -> None:
        when = self.dies.pop(step[0], None)
        if when == "before":
            raise asyncio.CancelledError
        self.append(step)
        if payload is not None:
            self.notices.append(payload)
        if when == "after":
            raise asyncio.CancelledError


@pytest.fixture
def ran(monkeypatch) -> _Ran:
    """Doubles on every run-once item's runner, recording what each ran."""
    ran = _Ran()

    async def _notice(*, event_key, build):
        ran.step(("notice", event_key), build().data)

    async def _cache():
        ran.step(("cache",))
        return True

    async def _tiles(table):
        ran.step(("tiles", table))
        return True

    async def _quicklook(session, dataset_id, table):
        ran.step(("quicklook", table))

    async def _embed(dataset):
        ran.step(("embed",))
        return True

    async def _bill(tenant_id, dimension, value=1, *, event_id=None, table_name=None):
        ran.step(("bill",))

    prefix = "app.processing.ingest.publish_followups"
    monkeypatch.setattr("app.platform.notifications.events.emit_event_safe", _notice)
    monkeypatch.setattr(f"{prefix}.invalidate_catalog_cache", _cache)
    monkeypatch.setattr(f"{prefix}.invalidate_tile_cache_for_table", _tiles)
    monkeypatch.setattr(f"{prefix}._generate_quicklook", _quicklook)
    monkeypatch.setattr("app.processing.embeddings.helpers.defer_embedding", _embed)
    monkeypatch.setattr(f"{prefix}._emit_billing_event", _bill)
    return ran


async def _job(
    session,
    *,
    task: str,
    status: str = "complete",
    error_message: str | None = None,
    **record,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A job whose record, shaped as an older worker wrote it, owes ``task``: (job, attempt, record)."""
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
    job.user_metadata = {
        PUBLISH_FOLLOWUPS_FIELD: {
            "task": task,
            "attempt_id": str(job.attempt_id),
            **record,
        }
    }
    await session.commit()
    return job.id, job.attempt_id, dataset.record_id


async def _drop(session, job_id, record_id) -> None:
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    await session.execute(delete(Record).where(Record.id == record_id))
    await session.commit()


async def _record(job_id) -> dict | None:
    async with db_module.async_session() as session:
        metadata = await session.scalar(
            select(IngestJob.user_metadata).where(IngestJob.id == job_id)
        )
    return (metadata or {}).get(PUBLISH_FOLLOWUPS_FIELD)


async def _leased(job_id) -> bool:
    """Whether the job's record is held off the sweep until a time still to come."""
    async with db_module.async_session() as session:
        return await session.scalar(
            text(
                "SELECT (user_metadata #>> '{publish_followups,next_attempt_at}')"
                "::timestamptz > now() FROM catalog.ingest_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )


@pytest.mark.parametrize(
    ("task", "items", "expected"),
    [
        ("ingest_raster", {"catalog_cache", "embedding", "notice", "usage"}, _RASTER),
        ("regenerate_vrt", {"catalog_cache", "embedding"}, [("cache",), ("embed",)]),
    ],
)
async def test_a_worker_dying_after_the_claim_leaves_the_rest_to_the_sweep(
    test_db_session, ran, task, items, expected
) -> None:
    """The claim records its run-once items, so the sweep runs each once after the lease."""
    job_id, _, record_id = await _job(test_db_session, task=task)
    try:
        ran.die("cache")
        with pytest.raises(asyncio.CancelledError):
            await run_publish_followups(job_id)

        record = await _record(job_id)
        assert items <= record.keys()
        assert record["claimed"] is True
        assert await _leased(job_id)
        await run_owed_publish_followups()
        assert ran == []

        await _make_due(job_id)
        await run_owed_publish_followups()
        assert ran == expected
        assert await _record(job_id) is None
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_replacement_dying_after_its_commit_leaves_its_steps_to_the_sweep(
    replace, storage, ran
) -> None:
    """A file replacement cancelled as its commit returns owes its purges, quicklook and embedding."""
    from app.processing.ingest import publication

    replacement = await replace("file")
    real_commit = publication.commit_publication

    async def _dies_after(session, **kwargs):
        await real_commit(session, **kwargs)
        raise asyncio.CancelledError

    with (
        patch.object(publication, "commit_publication", _dies_after),
        pytest.raises(asyncio.CancelledError),
    ):
        await replacement.run()

    table = replacement.live_table
    record = await _record(replacement.job_id)
    assert {
        key: record[key]
        for key in ("catalog_cache", "tile_cache", "quicklook", "embedding")
    } == {
        "catalog_cache": True,
        "tile_cache": table,
        "quicklook": table,
        "embedding": True,
    }
    assert await _leased(replacement.job_id)
    uploaded = replacement.upload.read_bytes()

    await _make_due(replacement.job_id)
    await run_owed_publish_followups()

    assert ran == [("cache",), ("tiles", table), ("quicklook", table), ("embed",)]
    assert await _record(replacement.job_id) is None
    assert await _upload_left(replacement, storage) == []
    assert await _archived(replacement, storage) == [uploaded]


async def test_a_failure_notice_sent_before_the_worker_died_is_sent_again_with_its_id(
    test_db_session, ran
) -> None:
    """A notice whose confirmation never landed goes again with the same notification id."""
    job_id, attempt_id, record_id = await _job(
        test_db_session,
        task="reupload_file",
        status="failed",
        error_message="The refresh was rejected.",
    )
    try:
        ran.die("notice", when="after")
        with pytest.raises(asyncio.CancelledError):
            await run_publish_followups(job_id)
        assert (await _record(job_id))["notice"] == "ingest_failed"

        await _make_due(job_id)
        await run_owed_publish_followups()

        assert ran == [("notice", "ingest_failed")] * 2
        ids = {notice["notification_id"] for notice in ran.notices}
        assert ids == {f"{job_id}:{attempt_id}:ingest_failed"}
        assert await _record(job_id) is None
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_the_sweep_leaves_a_record_to_the_writer_running_it(
    test_db_session, ran
) -> None:
    """A leased record is the writer's alone: a sweep before or during its run sends nothing more."""
    job_id, attempt_id, record_id = await _job(test_db_session, task="ingest_raster")
    swept: list[bool] = []
    try:
        async with db_module.async_session() as session:
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(
                    user_metadata=owed_followups(
                        attempt_id,
                        "ingest_raster",
                        catalog_cache=True,
                        embedding=True,
                        notice="ingest_complete",
                    )
                )
            )
            await session.commit()
        await run_owed_publish_followups()
        assert await run_publish_followups(job_id) is False
        assert ran == []

        async def _sweep_during(*, event_key, build):
            await run_owed_publish_followups()
            swept.append(True)
            ran.step(("notice", event_key), build().data)

        with patch("app.platform.notifications.events.emit_event_safe", _sweep_during):
            await run_publish_followups(job_id, attempt_id=attempt_id)

        assert swept == [True]
        assert ran == [("cache",), ("embed",), ("notice", "ingest_complete")]
        assert await _record(job_id) is None
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize(("attempts", "dropped"), [(6, False), (7, True)])
async def test_run_once_items_are_dropped_after_eight_attempts_and_storage_items_stay(
    test_db_session, ran, monkeypatch, attempts, dropped
) -> None:
    """The attempt that counts eight drops the run-once items still owed and keeps retrying storage."""
    key = f"rasters/{uuid.uuid4()}/superseded.tif"
    job_id, _, record_id = await _job(
        test_db_session,
        task="reupload_raster",
        claimed=True,
        attempts=attempts,
        embedding=True,
        superseded_keys=[key],
    )

    async def _still_owed(job_uuid, dataset_id, keys):
        return list(keys)

    async def _not_deferred(dataset):
        return False

    monkeypatch.setattr(
        "app.processing.ingest.publish_followups._reap_superseded", _still_owed
    )
    monkeypatch.setattr(
        "app.processing.embeddings.helpers.defer_embedding", _not_deferred
    )
    try:
        with structlog.testing.capture_logs() as logs:
            await run_owed_publish_followups()

        record = await _record(job_id)
        assert record["attempts"] == attempts + 1
        assert record["superseded_keys"] == [key]
        assert ("embedding" in record) is not dropped
        abandoned = [e for e in logs if e["event"] == "publish_followup_abandoned"]
        assert [e["items"] for e in abandoned] == ([["embedding"]] if dropped else [])
        assert await _leased(job_id)
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize(
    ("task", "status", "expected"),
    [
        ("ingest_raster", "complete", _RASTER),
        ("ingest_vrt", "complete", [("cache",), ("embed",)]),
        ("reupload_file", "failed", [("notice", "ingest_failed")]),
        ("ingest_file", "complete", []),
    ],
)
async def test_a_record_an_older_worker_wrote_gets_its_items_at_the_claim(
    test_db_session, ran, task, status, expected
) -> None:
    """A record naming a task and no item, unclaimed, runs what its task and status imply."""
    job_id, _, record_id = await _job(
        test_db_session, task=task, status=status, error_message="refused"
    )
    try:
        await run_owed_publish_followups()

        assert ran == expected
        assert await _record(job_id) is None
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_first_vector_import_dying_after_its_commit_leaves_its_steps_to_the_sweep(
    client, admin_auth_header, test_db_session, tmp_path, store, ran, monkeypatch
) -> None:
    """The import's notice and quicklook stay owed past a death after the commit, and the sweep sends them."""
    ingest = _Import(test_db_session, tmp_path)

    async def _dies(dataset) -> None:
        raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            await ingest.run(after_publish=_dies)
        assert ran == []
        record = await _record(ingest.job_id)
        assert record["notice"] == "ingest_complete"
        assert await _leased(ingest.job_id)

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        await _make_due(ingest.job_id)
        await run_owed_publish_followups()

        table = record["quicklook"]
        assert ran == [
            ("cache",),
            ("quicklook", table),
            ("embed",),
            ("notice", "ingest_complete"),
        ]
        assert ran.notices[0]["dataset"] == table
        assert await _record(ingest.job_id) is None
        archived = await store.list(f"originals/{ingest.dataset_id}/")
        assert [Path(key).name for key in archived] == ["points.geojson"]
        assert not ingest.source.exists()
    finally:
        await ingest.clean_up(client, admin_auth_header)

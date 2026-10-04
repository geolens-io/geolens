"""Publish follow-ups outlive a worker that dies after the claim or the publish commit."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
from tests.test_publish_followups import (
    _only_this_tests_followups as _only_this_tests_followups,
)
from tests.test_replacement_post_commit import _archived, _upload_left
from tests.test_replacement_post_commit import replace as replace
from tests.test_replacement_post_commit import storage as storage
from tests.test_service_reupload_3d import _BASE, _source
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
    table_name: str | None = None,
    **record,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A job whose record, shaped as an older worker wrote it, owes ``task``: (job, attempt, record)."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        **({"table_name": table_name} if table_name else {}),
    )
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
            ("bill",),
        ]
        assert ran.notices[0]["dataset"] == table
        assert await _record(ingest.job_id) is None
        archived = await store.list(f"originals/{ingest.dataset_id}/")
        assert [Path(key).name for key in archived] == ["points.geojson"]
        assert not ingest.source.exists()
    finally:
        await ingest.clean_up(client, admin_auth_header)


# --- Transient failures beneath the runners ----------------------------------


async def _retried_once_due(job_id, item: str) -> None:
    """The record still owes ``item`` after one attempt, under its retry delay."""
    record = await _record(job_id)
    assert (item in record, record["attempts"]) == (True, 1)
    assert await _leased(job_id)


async def test_a_notice_every_sink_failed_to_deliver_is_sent_again_once_due(
    test_db_session, monkeypatch
) -> None:
    """A webhook that is down leaves the failure notice owed, and the retry delivers it."""
    from app.platform.notifications import env_sink

    posted: list[str] = []
    down = {"webhook": True}

    async def _post(notification) -> None:
        if down["webhook"]:
            raise ConnectionError("the webhook is unreachable")
        posted.append(notification.data["notification_id"])

    monkeypatch.setattr(env_sink, "post_webhook", _post)
    monkeypatch.setattr(
        "app.platform.notifications.get_notification_sinks",
        lambda: [env_sink.EnvConfiguredNotificationSink()],
    )
    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "notify_on_ingest_failed", True)
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/geolens"
    )
    job_id, attempt_id, record_id = await _job(
        test_db_session, task="reupload_file", status="failed", error_message="no"
    )
    try:
        await run_publish_followups(job_id)
        await _retried_once_due(job_id, "notice")

        down["webhook"] = False
        await _make_due(job_id)
        await run_owed_publish_followups()

        assert posted == [f"{job_id}:{attempt_id}:ingest_failed"]
        assert await _record(job_id) is None
    finally:
        await _drop(test_db_session, job_id, record_id)


@pytest.mark.parametrize("cache", ["open-circuit", "in-memory"])
async def test_a_catalog_purge_redis_skipped_stays_owed_and_a_local_one_lands(
    test_db_session, monkeypatch, cache
) -> None:
    """A purge an open Redis circuit skips is retried once due; one with no Redis lands at once."""
    from app.platform.cache import provider
    from app.platform.cache.memory import InMemoryCacheProvider
    from app.platform.cache.redis import RedisCacheProvider

    redis = RedisCacheProvider(url="redis://127.0.0.1:1/0", max_failures=1)
    redis._record_failure()
    monkeypatch.setattr(
        provider,
        "_cache_provider",
        redis if cache == "open-circuit" else InMemoryCacheProvider(),
    )
    job_id, _, record_id = await _job(
        test_db_session, task="reupload_file", claimed=True, catalog_cache=True
    )
    try:
        await run_publish_followups(job_id)
        if cache == "open-circuit":
            await _retried_once_due(job_id, "catalog_cache")
            monkeypatch.setattr(provider, "_cache_provider", InMemoryCacheProvider())
            await _make_due(job_id)
            await run_owed_publish_followups()

        assert await _record(job_id) is None
    finally:
        await redis._client.aclose()
        await _drop(test_db_session, job_id, record_id)


async def test_a_usage_event_the_billing_extension_refused_is_emitted_once_due(
    test_db_session, monkeypatch
) -> None:
    """A billing extension that raises leaves the usage event owed, and the retry emits it."""

    class _Meter:
        def __init__(self) -> None:
            self.down = True
            self.events: list[str | None] = []

        async def on_usage_event(self, *, event_id=None, **_kwargs) -> None:
            if self.down:
                raise ConnectionError("the meter is unreachable")
            self.events.append(event_id)

    meter = _Meter()
    monkeypatch.setattr(
        "app.platform.extensions.get_billing_extensions", lambda: [meter]
    )
    monkeypatch.setattr(
        "app.processing.ingest.publish_followups._usage_tenant", lambda: "tenant-a"
    )
    job_id, _, record_id = await _job(
        test_db_session, task="ingest_raster", claimed=True, usage="ingest_jobs"
    )
    try:
        await run_publish_followups(job_id)
        await _retried_once_due(job_id, "usage")

        meter.down = False
        await _make_due(job_id)
        await run_owed_publish_followups()

        assert meter.events == [str(job_id)]
        assert await _record(job_id) is None
    finally:
        await _drop(test_db_session, job_id, record_id)


async def test_a_quicklook_whose_upload_failed_is_drawn_again_once_due(
    test_db_session, tmp_path, monkeypatch
) -> None:
    """A storage write that fails leaves the quicklook owed, and the retry draws and records it."""
    from app.platform.storage.local import LocalStorageProvider

    table = f"qlretry_{uuid.uuid4().hex[:10]}"
    async with db_module.async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "data"."{table}" '
                "(gid serial PRIMARY KEY, geom_4326 geometry(Point, 4326))"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "data"."{table}" (geom_4326) '
                "VALUES (ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326))"
            )
        )
        await session.commit()
    store = LocalStorageProvider(str(tmp_path / "objects"))
    real_put = store.put
    down = {"storage": True}

    async def _put(key, data):
        if down["storage"]:
            raise OSError("the object store refused the write")
        return await real_put(key, data)

    monkeypatch.setattr(store, "put", _put)
    monkeypatch.setattr("app.processing.ingest.tasks_common.get_storage", lambda: store)
    job_id, _, record_id = await _job(
        test_db_session,
        task="reupload_file",
        table_name=table,
        claimed=True,
        quicklook=table,
    )
    try:
        await run_publish_followups(job_id)
        await _retried_once_due(job_id, "quicklook")

        down["storage"] = False
        await _make_due(job_id)
        await run_owed_publish_followups()

        assert await _record(job_id) is None
        async with db_module.async_session() as session:
            dataset_id = await session.scalar(
                select(IngestJob.dataset_id).where(IngestJob.id == job_id)
            )
        key = f"vectors/{dataset_id}/quicklook_256.png"
        assert await store.exists(key)
    finally:
        await _drop(test_db_session, job_id, record_id)
        async with db_module.async_session() as session:
            await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
            await session.commit()


# --- The first vector import bills through its record ------------------------


class _Meter:
    """A billing extension that refuses usage events while ``down``."""

    def __init__(self, *, down: bool) -> None:
        self.down = down
        self.events: list[str | None] = []

    async def on_usage_event(self, *, event_id=None, **_kwargs) -> None:
        if self.down:
            raise ConnectionError("the meter is unreachable")
        self.events.append(event_id)


@pytest.fixture
def meter(monkeypatch) -> _Meter:
    """The one billing extension, billing a hosted tenant, up until a test takes it down."""
    meter = _Meter(down=False)
    monkeypatch.setattr(
        "app.platform.extensions.get_billing_extensions", lambda: [meter]
    )
    monkeypatch.setattr(
        "app.processing.ingest.publish_followups._usage_tenant", lambda: "tenant-a"
    )
    return meter


async def _dies_after_the_commit(monkeypatch) -> None:
    """Cancel the worker as the import's publish commit returns."""
    from app.processing.ingest import tasks_vector

    real = tasks_vector._finalize_ingest

    async def _dies(ctx):
        await real(ctx)
        raise asyncio.CancelledError

    monkeypatch.setattr(tasks_vector, "_finalize_ingest", _dies)


async def _vector_import(
    kind: str, session, tmp_path, monkeypatch, jobs: list[uuid.UUID]
) -> None:
    """Run a first vector import of ``kind`` by the admin, adding its job id to ``jobs`` first."""
    from app.processing.ingest import tasks_vector

    admin_id = await get_user_id(session, "admin")
    if kind == "file":
        source = tmp_path / "points.geojson"
        source.write_bytes(
            b'{"type":"FeatureCollection","features":[{"type":"Feature",'
            b'"properties":{"name":"a"},"geometry":{"type":"Point","coordinates":[1,2]}}]}'
        )
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        job = IngestJob(
            source_filename="points.geojson",
            file_path=str(source),
            created_by=admin_id,
            status="pending",
            user_metadata={"title": f"Billed {uuid.uuid4().hex[:8]}"},
        )
    else:
        job = IngestJob(
            source_filename="Wells",
            source_url=_BASE,
            source_layer="0",
            created_by=admin_id,
            status="pending",
            user_metadata={
                "title": f"Billed {uuid.uuid4().hex[:8]}",
                "service_type": "ArcGIS FeatureServer",
                "layer_id": "0",
                "geometry_type": "Point",
            },
        )
    session.add(job)
    await session.commit()
    jobs.append(job.id)
    if kind == "file":
        from tests.test_vector_archive_dataset_delete import _fake_ogr2ogr

        ogrinfo = {
            "srid": 4326,
            "geometry_type": "Point",
            "columns": [{"name": "name", "type": "String"}],
        }
        with (
            patch(
                "app.processing.ingest.ogr.run_ogrinfo", AsyncMock(return_value=ogrinfo)
            ),
            patch("app.processing.ingest.ogr.run_ogr2ogr", new=_fake_ogr2ogr),
        ):
            await tasks_vector.ingest_file.func(
                job_id=str(job.id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
    else:
        with _source(monkeypatch, [(1.0, 2.0, None)]):
            await tasks_vector.ingest_service.func(
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                source_url=_BASE,
                source_layer="0",
                user_id=str(admin_id),
            )


async def _drop_import(session, job_id) -> None:
    """Delete the job, its dataset and the dataset's table."""
    from app.modules.catalog.datasets.domain.models import Dataset

    session.expire_all()
    dataset = await session.scalar(
        select(Dataset)
        .join(IngestJob, IngestJob.dataset_id == Dataset.id)
        .where(IngestJob.id == job_id)
    )
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    if dataset is not None:
        table, record_id = dataset.table_name, dataset.record_id
        await session.execute(delete(Record).where(Record.id == record_id))
        await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


@pytest.mark.parametrize("kind", ["file", "service"])
async def test_a_vector_import_dying_after_its_commit_is_billed_once_by_the_sweep(
    test_db_session, tmp_path, monkeypatch, store, meter, kind
) -> None:
    """The import's usage event is owed past a death after the commit and billed once."""
    await _dies_after_the_commit(monkeypatch)
    monkeypatch.setattr(
        "app.processing.embeddings.helpers.defer_embedding",
        AsyncMock(return_value=True),
    )
    jobs: list[uuid.UUID] = []
    try:
        with pytest.raises(asyncio.CancelledError):
            await _vector_import(kind, test_db_session, tmp_path, monkeypatch, jobs)
        [job_id] = jobs
        assert (await _record(job_id))["usage"] == "ingest_jobs"
        assert meter.events == []

        await _make_due(job_id)
        await run_owed_publish_followups()
        await run_owed_publish_followups()

        assert meter.events == [str(job_id)]
        assert await _record(job_id) is None
    finally:
        for job_id in jobs:
            await _drop_import(test_db_session, job_id)


@pytest.mark.parametrize("kind", ["file", "service"])
async def test_a_vector_import_the_meter_refused_is_billed_once_when_it_recovers(
    test_db_session, tmp_path, monkeypatch, store, meter, kind
) -> None:
    """A billing extension that raises leaves only the usage event owed, and the retry bills it once."""
    monkeypatch.setattr(
        "app.processing.embeddings.helpers.defer_embedding",
        AsyncMock(return_value=True),
    )
    meter.down = True
    jobs: list[uuid.UUID] = []
    try:
        await _vector_import(kind, test_db_session, tmp_path, monkeypatch, jobs)
        [job_id] = jobs
        record = await _record(job_id)
        owed = {"catalog_cache", "quicklook", "embedding", "notice", "usage"}
        assert (owed & record.keys(), record["attempts"]) == ({"usage"}, 1)

        meter.down = False
        await _make_due(job_id)
        await run_owed_publish_followups()
        await run_owed_publish_followups()

        assert meter.events == [str(job_id)]
        assert await _record(job_id) is None
    finally:
        for job_id in jobs:
            await _drop_import(test_db_session, job_id)


async def test_a_usage_event_still_owed_when_its_dataset_goes_is_billed_once(
    test_db_session, tmp_path, monkeypatch, store, meter
) -> None:
    """Billing needs only the job and its tenant, so a deleted dataset still gets billed once."""
    from app.modules.catalog.datasets.domain.models import Dataset

    monkeypatch.setattr(
        "app.processing.embeddings.helpers.defer_embedding",
        AsyncMock(return_value=True),
    )
    meter.down = True
    jobs: list[uuid.UUID] = []
    try:
        await _vector_import("file", test_db_session, tmp_path, monkeypatch, jobs)
        [job_id] = jobs
        assert (await _record(job_id))["usage"] == "ingest_jobs"
        test_db_session.expire_all()
        dataset = await test_db_session.scalar(
            select(Dataset)
            .join(IngestJob, IngestJob.dataset_id == Dataset.id)
            .where(IngestJob.id == job_id)
        )
        table = dataset.table_name
        await test_db_session.execute(
            delete(Record).where(Record.id == dataset.record_id)
        )
        await test_db_session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
        await test_db_session.commit()

        meter.down = False
        await _make_due(job_id)
        await run_owed_publish_followups()
        await run_owed_publish_followups()

        assert meter.events == [str(job_id)]
        assert await _record(job_id) is None
    finally:
        for job_id in jobs:
            await _drop_import(test_db_session, job_id)

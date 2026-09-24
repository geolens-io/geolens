"""Each replacement task takes its job row, then its catalog rows, under one worker budget."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

import app.core.db as db_module
from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform import catalog_locks
from app.platform.catalog_locks import CATALOG_LOCK_CONFLICT_CODE, CatalogLockConflict
from app.platform.jobs.heartbeat import StaleIngestAttempt
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest import tasks_raster_replace
from app.processing.raster.models import RasterAsset
from tests.factories import get_user_id
from tests.test_replacement_post_commit import (
    _BUILDERS,
    _Replacement,
    _assert_settled_published,
    _fresh_scalar,
    _quiet_embedding,
    _stored_keys,
    replace as replace,
    storage as storage,
)

pytestmark = pytest.mark.anyio

# Long enough to probe the other rows while a task waits, short enough to keep
# seventeen contention cases quick.
_BUDGET = "2s"

# A task still waiting after this is not waiting on the worker budget.
_TIMEOUT = 20

# The rows each task locks, in the order it takes them.
_ROWS = {
    "file": ("job", "dataset", "record"),
    "service": ("job", "dataset", "record"),
    "raster": ("job", "raster", "dataset", "record"),
    "postgis": ("job", "dataset", "record"),
    "stac": ("job", "raster", "dataset", "record"),
}

_CASES = [(kind, row) for kind, rows in _ROWS.items() for row in rows]

# The per-user lock a storage reservation takes; a sibling first ingest holds
# it across its whole upload.
_QUOTA_LOCK = (
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('geolens:dataset_quota:' || :uid, 0))"
)


async def _row_selects(replacement: _Replacement) -> dict:
    record_id = await _fresh_scalar(
        select(Dataset.record_id).where(Dataset.id == replacement.dataset_id)
    )
    return {
        "job": select(IngestJob.id).where(IngestJob.id == replacement.job_id),
        "raster": select(RasterAsset.dataset_id).where(
            RasterAsset.dataset_id == replacement.dataset_id
        ),
        "dataset": select(Dataset.id).where(Dataset.id == replacement.dataset_id),
        "record": select(Record.id).where(Record.id == record_id),
    }


async def _live_state(replacement: _Replacement) -> tuple:
    """What an attempt that did not publish must leave as it found it."""
    async with db_module.async_session() as session:
        dataset = (
            await session.execute(
                select(
                    Dataset.tile_cache_version,
                    Dataset.current_version,
                    Dataset.feature_count,
                    Dataset.origin_uri,
                    Dataset.last_refreshed_at,
                ).where(Dataset.id == replacement.dataset_id)
            )
        ).one()
        asset = await session.scalar(
            select(RasterAsset.asset_uri).where(
                RasterAsset.dataset_id == replacement.dataset_id
            )
        )
        rows = None
        if replacement.live_table is not None:
            rows = await session.scalar(
                text(
                    "SELECT array_agg(name ORDER BY gid) "
                    f'FROM "data"."{replacement.live_table}"'
                )
            )
    return tuple(dataset), asset, rows


async def _waits_on(pid: int, task: asyncio.Task) -> bool:
    """Poll until a backend waits on ``pid``; False when ``task`` ends first."""
    async with db_module.async_session() as probe:
        while not task.done():
            waiting = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": pid},
            )
            await probe.rollback()
            if waiting:
                return True
            await asyncio.sleep(0.05)
    return False


async def _locked_by_another(statement) -> bool:
    """Whether another transaction holds this row against an update, without waiting."""
    async with db_module.async_session() as probe:
        try:
            await probe.execute(statement.with_for_update(key_share=True, nowait=True))
        except DBAPIError as exc:
            if sqlstate(exc) != "55P03":
                raise
            return True
        finally:
            await probe.rollback()
    return False


def _conflict_in(exc: BaseException | None) -> bool:
    while exc is not None:
        if isinstance(exc, CatalogLockConflict):
            return True
        exc = exc.__cause__
    return False


async def _settle(task: asyncio.Task) -> BaseException | None:
    try:
        await asyncio.wait_for(task, timeout=_TIMEOUT)
    except Exception as exc:  # broad: the test inspects whatever ended the task
        return exc
    return None


@pytest.mark.parametrize(("kind", "row"), _CASES, ids=[f"{k}-{r}" for k, r in _CASES])
async def test_a_held_row_fails_the_task_as_contention(
    replace, storage, monkeypatch, kind: str, row: str
) -> None:
    """A task waits its budget on a held row holding only the rows before it, then fails as contention."""
    replacement = await replace(kind)
    monkeypatch.setattr(catalog_locks, "WORKER_LOCK_TIMEOUT", _BUDGET)
    rows = await _row_selects(replacement)
    before = await _live_state(replacement)
    order = _ROWS[kind]

    async with db_module.async_session() as holder:
        # KEY SHARE conflicts with the task's FOR UPDATE and with nothing the
        # task writes before it, such as a foreign-key check.
        await holder.execute(rows[row].with_for_update(read=True, key_share=True))
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        with _quiet_embedding(), structlog.testing.capture_logs() as logs:
            task = asyncio.create_task(replacement.run())
            try:
                waited = await _waits_on(holder_pid, task)
                held = {
                    other: await _locked_by_another(rows[other])
                    for other in order
                    if other != row
                }
                still_waiting = await _waits_on(holder_pid, task)
            finally:
                failure = await _settle(task)
                await holder.rollback()

    assert waited, (
        f"{kind} never waited on the held {row} row; it ended with {failure!r}"
    )
    assert still_waiting, "the task stopped waiting before the probes finished"
    position = order.index(row)
    assert held == {
        other: index < position for index, other in enumerate(order) if other != row
    }, f"{kind} waiting on {row} holds {held}, not the rows before it in {order}"
    assert _conflict_in(failure), f"{kind} ended with {failure!r}, not contention"

    job = await _fresh_scalar(
        select(IngestJob).where(IngestJob.id == replacement.job_id)
    )
    assert job.status == "failed"
    assert "Another operation is updating" in (job.error_message or "")
    run = await _fresh_scalar(
        select(DatasetRefreshRun).where(
            DatasetRefreshRun.ingest_job_id == replacement.job_id
        )
    )
    assert (run.status, run.error_code) == ("failed", CATALOG_LOCK_CONFLICT_CODE)
    assert await _live_state(replacement) == before
    if kind == "raster":
        assert _stored_keys(storage, replacement.dataset_id) == set(
            replacement.prior_keys
        ), "the attempt's objects were kept, or the live ones were reaped"
        if row != "job":
            expired = [
                entry
                for entry in logs
                if entry.get("event") == "raster_replace_catalog_lock_timeout"
            ]
            assert [(e["budget"], e["sqlstate"]) for e in expired] == [
                (_BUDGET, "55P03")
            ]


async def _tile_version(dataset_id: uuid.UUID) -> int:
    return await _fresh_scalar(
        select(Dataset.tile_cache_version).where(Dataset.id == dataset_id)
    )


@pytest.mark.parametrize("kind", sorted(_BUILDERS))
async def test_a_publication_bumps_the_tile_version_once_atomically(
    replace, kind: str
) -> None:
    """A publication that changes tile content rolls the version by one, in SQL."""
    replacement = await replace(kind)
    before = await _tile_version(replacement.dataset_id)
    absolute = AssertionError("the ORM bump writes back a counter read earlier")
    with (
        _quiet_embedding(),
        patch.object(Dataset, "bump_tile_cache_version", side_effect=absolute),
    ):
        await replacement.run()

    await _assert_settled_published(replacement)
    assert await _tile_version(replacement.dataset_id) == before + 1


async def test_the_raster_quota_wait_outlasts_the_worker_budget(
    replace, monkeypatch, test_db_session
) -> None:
    """The budget ends with the catalog wait, so the quota reservation waits out a sibling upload."""
    replacement = await replace("raster")
    monkeypatch.setattr(catalog_locks, "WORKER_LOCK_TIMEOUT", "500ms")
    owner = await get_user_id(test_db_session, "admin")

    async with db_module.async_session() as sibling:
        await sibling.execute(text(_QUOTA_LOCK), {"uid": str(owner)})
        sibling_pid = await sibling.scalar(text("SELECT pg_backend_pid()"))
        with (
            _quiet_embedding(),
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new=AsyncMock(return_value=10**12),
            ),
        ):
            task = asyncio.create_task(replacement.run())
            try:
                reached = await _waits_on(sibling_pid, task)
                await asyncio.sleep(1.5)
                outlasted = not task.done()
            finally:
                await sibling.rollback()
                failure = await _settle(task)

    assert reached, f"the replace never waited on the quota lock: {failure!r}"
    assert outlasted, f"the quota wait ended within the worker budget: {failure!r}"
    assert failure is None
    await _assert_settled_published(replacement)


@pytest.fixture
async def running_job(test_db_session):
    job = IngestJob(
        status="running",
        created_by=await get_user_id(test_db_session, "admin"),
        started_at=datetime.now(timezone.utc),
    )
    test_db_session.add(job)
    await test_db_session.commit()
    ids = (job.id, job.attempt_id)
    yield ids
    await test_db_session.execute(
        text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": ids[0]}
    )
    await test_db_session.commit()


@pytest.mark.parametrize("moved", ["status", "attempt"])
async def test_a_job_the_attempt_no_longer_owns_is_not_held(
    running_job, moved: str
) -> None:
    """A job that left `running` or changed attempt raises, and nothing is written."""
    from app.processing.ingest.publication import hold_publishing_job

    job_id, attempt_id = running_job
    values = {"status": "failed"} if moved == "status" else {"attempt_id": uuid.uuid4()}
    async with db_module.async_session() as session:
        await session.execute(
            update(IngestJob).where(IngestJob.id == job_id).values(**values)
        )
        await session.commit()
    version = text("SELECT xmin::text FROM catalog.ingest_jobs WHERE id = :id")
    before = await _fresh_scalar(version.bindparams(id=job_id))

    async with db_module.async_session() as session:
        with pytest.raises(StaleIngestAttempt):
            await hold_publishing_job(session, job_id, attempt_id)
        await session.commit()

    assert await _fresh_scalar(version.bindparams(id=job_id)) == before


async def test_the_worker_budget_ends_with_its_block(
    test_db_session, monkeypatch
) -> None:
    """Waits in the block run on the worker budget; after it, the earlier budget is back."""
    monkeypatch.setattr(catalog_locks, "WORKER_LOCK_TIMEOUT", "1500ms")
    await test_db_session.execute(text("SET LOCAL lock_timeout = '7s'"))
    async with catalog_locks.worker_lock_budget(test_db_session):
        inside = await test_db_session.scalar(
            text("SELECT current_setting('lock_timeout')")
        )
    after = await test_db_session.scalar(text("SELECT current_setting('lock_timeout')"))
    await test_db_session.rollback()

    assert (inside, after) == ("1500ms", "7s")


async def test_a_raster_replace_that_lost_its_job_puts_nothing(
    replace, storage, monkeypatch
) -> None:
    """Phase 2 of a replace whose job the sweep failed writes no object."""
    replacement = await replace("raster")
    real_stamp = tasks_raster_replace._stamp_progress

    async def _swept_after_the_last_checkpoint(job_uuid, attempt_uuid, **kwargs):
        await real_stamp(job_uuid, attempt_uuid, **kwargs)
        if kwargs["phase"] == "progress_write_quicklook":
            async with db_module.async_session() as sweep:
                await sweep.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job_uuid)
                    .values(status="failed", error_message="swept")
                )
                await sweep.commit()

    monkeypatch.setattr(
        tasks_raster_replace, "_stamp_progress", _swept_after_the_last_checkpoint
    )
    puts = AsyncMock(side_effect=storage.put)
    monkeypatch.setattr(storage, "put", puts)
    before = await _live_state(replacement)

    await replacement.run()

    assert puts.await_count == 0
    job = await _fresh_scalar(
        select(IngestJob).where(IngestJob.id == replacement.job_id)
    )
    assert (job.status, job.error_message) == ("failed", "swept")
    assert await _live_state(replacement) == before
    assert _stored_keys(storage, replacement.dataset_id) == set(replacement.prior_keys)


@pytest.mark.parametrize("kind", ["file", "service"])
async def test_a_job_warning_recorded_before_the_hold_survives_it(
    replace, monkeypatch, kind: str
) -> None:
    """A warning appended to the job before its row is held is still on it after publication."""
    replacement = await replace(kind)
    monkeypatch.setattr(
        "app.processing.ingest.metadata.rename_reserved_columns",
        AsyncMock(return_value=[{"original": "fid", "renamed": "src_fid"}]),
    )
    with _quiet_embedding():
        await replacement.run()

    await _assert_settled_published(replacement)
    job = await _fresh_scalar(
        select(IngestJob).where(IngestJob.id == replacement.job_id)
    )
    warnings = (job.user_metadata or {}).get("warnings", [])
    assert [w["kind"] for w in warnings] == ["reserved_rename"]

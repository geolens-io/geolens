"""The settlement seam runs every replacement strategy's steps in one order."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform import catalog_locks
from app.platform.catalog_locks import CATALOG_LOCK_CONFLICT_CODE
from app.platform.jobs.heartbeat import StaleIngestAttempt, attempt_scoped_staging_table
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    create_pending_run,
    record_refresh_blocked,
    record_refresh_failure,
)
from app.processing.ingest.publication import (
    PUBLISH,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
)
from app.processing.raster.models import RasterAsset
from tests.factories import create_dataset, get_user_id
from tests.test_feature_lock_order_1847 import _published_version
from tests.test_worker_swap_bump_after_lock_1911 import _message, _overlap

pytestmark = pytest.mark.anyio

# Long enough to probe the other rows while the seam waits.
_BUDGET = "2s"

_ROWS = ("job", "raster", "dataset", "record")


@dataclass(frozen=True)
class _Seed:
    job_id: uuid.UUID
    attempt_id: uuid.UUID
    dataset_id: uuid.UUID
    record_id: uuid.UUID
    table: str

    def rows(self) -> dict:
        return {
            "job": select(IngestJob.id).where(IngestJob.id == self.job_id),
            "raster": select(RasterAsset.dataset_id).where(
                RasterAsset.dataset_id == self.dataset_id
            ),
            "dataset": select(Dataset.id).where(Dataset.id == self.dataset_id),
            "record": select(Record.id).where(Record.id == self.record_id),
        }


async def _held(seed: _Seed) -> dict[str, bool]:
    """Which of the seed's rows another transaction holds against an update."""
    held = {}
    for name, statement in seed.rows().items():
        async with db_module.async_session() as probe:
            try:
                await probe.execute(
                    statement.with_for_update(key_share=True, nowait=True)
                )
                held[name] = False
            except DBAPIError as exc:
                if sqlstate(exc) != "55P03":
                    raise
                held[name] = True
            finally:
                await probe.rollback()
    return held


class _Fake:
    """Stages a table, changes the live table on install and two catalog fields on write."""

    task = "fake_replacement"
    staging = True
    catalog_event = "fake_catalog"

    def __init__(
        self,
        seed: _Seed,
        *,
        raster_row: bool = False,
        verdict: Verdict = PUBLISH,
        fail_at: str | None = None,
        refused: bool = False,
        during: dict | None = None,
        failure: Failure | None = None,
    ) -> None:
        self.seed = seed
        self.raster_row = raster_row
        self.verdict = verdict
        self.fail_at = fail_at
        self.refused = refused
        self.failure = failure
        # A coroutine function to run at a step, after the step's probe.
        self.during = during or {}
        self.seen: dict[str, dict[str, bool]] = {}
        self.lock_timeouts: dict[str, str] = {}
        self.released: tuple | None = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        self.staging_table = staging_table

    async def fetch(self) -> None:
        await self._step("fetch")
        async with db_module.async_session() as session:
            await session.execute(
                text(f'CREATE TABLE data."{self.staging_table}" (name text)')
            )
            await session.commit()

    async def stage(self, session, job, dataset) -> Verdict:
        self.lock_timeouts["stage"] = await session.scalar(
            text("SELECT current_setting('lock_timeout')")
        )
        await self._step("stage")
        return self.verdict

    async def install(self, session, dataset) -> None:
        await session.execute(
            text(f"UPDATE data.\"{self.seed.table}\" SET name = 'after'")
        )
        await self._step("install")

    async def write(self, session, dataset) -> Published:
        self.lock_timeouts["write"] = await session.scalar(
            text("SELECT current_setting('lock_timeout')")
        )
        dataset.feature_count = 7
        dataset.record.title = "Replaced"
        await self._step("write")
        return Published(
            dataset_version_id=None,
            feature_count=7,
            schema_diff=None,
            contacted_origin=False,
            live_table=dataset.table_name,
        )

    def classify(self, exc: BaseException) -> Failure:
        if self.failure is not None:
            return self.failure
        return Failure(getattr(exc, "error_code", "fake_failed"), refused=self.refused)

    async def release(self, *, publication, failed: bool) -> None:
        self.released = (publication, failed)

    async def _step(self, name: str) -> None:
        self.seen[name] = await _held(self.seed)
        if name in self.during:
            await self.during[name]()
        if self.fail_at == name:
            raise RuntimeError(f"{name} failed")


@pytest.fixture
async def seed(test_db_session):
    """A dataset with a live table, a raster row, and a pending job with its run."""
    admin_id = await get_user_id(test_db_session, "admin")
    table = f"seam_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, table_name=table, feature_count=1
    )
    await test_db_session.execute(
        text(f'CREATE TABLE data."{table}" (gid serial PRIMARY KEY, name text)')
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.\"{table}\" (name) VALUES ('before')")
    )
    test_db_session.add(
        RasterAsset(dataset_id=dataset.id, asset_uri=f"rasters/{dataset.id}/a.tif")
    )
    job = IngestJob(dataset_id=dataset.id, status="pending", created_by=admin_id)
    test_db_session.add(job)
    await test_db_session.flush()
    await create_pending_run(
        test_db_session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await test_db_session.commit()
    await test_db_session.refresh(job)
    seeded = _Seed(job.id, job.attempt_id, dataset.id, dataset.record_id, table)
    yield seeded
    async with db_module.async_session() as cleanup:
        await cleanup.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job.id}
        )
        # Cascades to the dataset and its runs, so a run a test leaves running
        # never reaches a later test's unscoped sweep.
        await cleanup.execute(
            text("DELETE FROM catalog.records WHERE id = :id"),
            {"id": seeded.record_id},
        )
        await cleanup.execute(text(f'DROP TABLE IF EXISTS data."{table}" CASCADE'))
        await cleanup.commit()


async def _settle(strategy: _Fake) -> None:
    await settle_replacement(
        strategy,
        job_id=str(strategy.seed.job_id),
        dataset_id=str(strategy.seed.dataset_id),
        attempt_id=str(strategy.seed.attempt_id),
    )


async def _state(seed: _Seed) -> dict:
    async with db_module.async_session() as session:
        job = await session.get(IngestJob, seed.job_id)
        run = await session.scalar(
            select(DatasetRefreshRun).where(
                DatasetRefreshRun.ingest_job_id == seed.job_id
            )
        )
        dataset = await session.get(Dataset, seed.dataset_id)
        record = await session.get(Record, seed.record_id)
        live = await session.scalar(text(f'SELECT name FROM data."{seed.table}"'))
        staging_left = await session.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'data' AND table_name LIKE :prefix"
            ),
            {"prefix": f"{seed.table}_staging_%"},
        )
    return {
        "job": job.status,
        "run": (run.status, run.error_code),
        "catalog": (dataset.feature_count, record.title, dataset.tile_cache_version),
        "live": live,
        "staging_left": staging_left,
    }


@pytest.fixture(autouse=True)
def embedding():
    deferred = AsyncMock()
    with patch("app.processing.embeddings.helpers.defer_embedding", new=deferred):
        yield deferred


@pytest.fixture
def notifications():
    sent = AsyncMock()
    with patch("app.platform.notifications.events.emit_event_safe", new=sent):
        yield sent


def _events(notifications: AsyncMock) -> list[str]:
    return [call.kwargs["event_key"] for call in notifications.await_args_list]


async def test_the_job_row_comes_before_the_catalog_rows_and_every_fetch_before_both(
    seed,
) -> None:
    """Fetch and stage hold nothing; install holds only the job row; write holds all four."""
    fake = _Fake(seed, raster_row=True)
    await _settle(fake)

    none = {row: False for row in _ROWS}
    assert fake.seen["fetch"] == none
    assert fake.seen["stage"] == none
    assert fake.seen["install"] == {**none, "job": True}
    assert fake.seen["write"] == {row: True for row in _ROWS}


@pytest.mark.parametrize("row", ["raster", "dataset", "record"])
async def test_the_seam_waits_on_a_catalog_row_holding_only_the_rows_before_it(
    seed, monkeypatch, row: str
) -> None:
    """The wait runs on the worker budget with the earlier rows held, then fails as contention."""
    monkeypatch.setattr(catalog_locks, "WORKER_LOCK_TIMEOUT", _BUDGET)
    fake = _Fake(seed, raster_row=True)
    order = _ROWS
    async with db_module.async_session() as holder:
        # KEY SHARE conflicts with the seam's FOR UPDATE and with nothing the
        # strategy writes before it.
        await holder.execute(
            seed.rows()[row].with_for_update(read=True, key_share=True)
        )
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(_settle(fake))
        try:
            waited_at = await _waits_on(holder_pid, task)
            held = await _held(seed)
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(catalog_locks.CatalogLockConflict):
                await asyncio.wait_for(task, timeout=20)
            waited = loop.time() - started
        finally:
            await holder.rollback()

    assert waited_at
    position = order.index(row)
    assert {r: held[r] for r in order if r != row} == {
        r: i < position for i, r in enumerate(order) if r != row
    }
    assert waited < 5, f"the wait outlasted the worker budget: {waited:.1f}s"
    assert (await _state(seed))["run"] == ("failed", CATALOG_LOCK_CONFLICT_CODE)


async def _waits_on(pid: int, task: asyncio.Task) -> bool:
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


async def test_the_budget_ends_with_the_catalog_wait(seed, monkeypatch) -> None:
    """The strategy's writes run on the budget the transaction arrived with."""
    monkeypatch.setattr(catalog_locks, "WORKER_LOCK_TIMEOUT", "1500ms")
    fake = _Fake(seed)
    await _settle(fake)

    assert fake.lock_timeouts["write"] == fake.lock_timeouts["stage"] != "1500ms"


async def test_the_run_is_claimed_and_committed_before_the_fetch(seed) -> None:
    """The fetch runs with the job and run already running and neither row locked."""
    seen: dict = {}

    async def _look() -> None:
        async with db_module.async_session() as probe:
            seen["job"] = await probe.scalar(
                select(IngestJob.status).where(IngestJob.id == seed.job_id)
            )
            seen["run"] = await probe.scalar(
                select(DatasetRefreshRun.status)
                .where(DatasetRefreshRun.ingest_job_id == seed.job_id)
                .with_for_update(nowait=True)
            )
            await probe.rollback()

    await _settle(_Fake(seed, during={"fetch": _look}))

    assert seen == {"job": "running", "run": "running"}


async def test_the_job_run_and_catalog_writes_commit_together(seed, embedding) -> None:
    """A published replacement lands the job, its run and the catalog writes at once."""
    fake = _Fake(seed)
    await _settle(fake)

    state = await _state(seed)
    assert state["job"] == "complete"
    assert state["run"] == ("succeeded", None)
    assert state["catalog"] == (7, "Replaced", 2)
    assert state["live"] == "after"
    assert state["staging_left"] == 0
    assert fake.released == (PublicationCommit.ACKNOWLEDGED, False)
    embedding.assert_awaited_once()


async def _cancel(seed: _Seed) -> None:
    async with db_module.async_session() as session:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == seed.job_id)
            .values(status="cancelled", error_message="Cancelled by user")
        )
        await session.commit()


class _FailingCommit:
    """Fail the publishing commit before it lands; the probe then reads it as not landed."""

    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        self.failed = False

    def installed(self):
        real_commit = AsyncSession.commit
        own_status = select(IngestJob.status).where(IngestJob.id == self.job_id)
        outer = self

        async def _commit(session, *args, **kwargs):
            if not outer.failed:
                if (await session.execute(own_status)).scalar() == "complete":
                    outer.failed = True
                    raise ConnectionResetError("the connection dropped before COMMIT")
            return await real_commit(session, *args, **kwargs)

        return patch.object(AsyncSession, "commit", _commit)


class _LostAcknowledgement:
    """Make the commit that ends the job ``ended`` raise after it has applied."""

    def __init__(self, job_id: uuid.UUID, ended: str, failure: BaseException) -> None:
        self.job_id = job_id
        self.ended = ended
        self.failure = failure
        self.fired = 0

    def installed(self):
        real_commit = AsyncSession.commit
        own_status = select(IngestJob.status).where(IngestJob.id == self.job_id)
        outer = self

        async def _commit(session, *args, **kwargs):
            await real_commit(session, *args, **kwargs)
            if outer.fired:
                return
            async with db_module.async_session() as probe:
                status = await probe.scalar(own_status)
            if status == outer.ended:
                outer.fired += 1
                raise outer.failure

        return patch.object(AsyncSession, "commit", _commit)


@pytest.mark.parametrize("fail_at", ["fetch", "stage", "install", "write", "commit"])
async def test_a_failure_before_the_commit_leaves_live_data_as_it_was(
    seed, notifications, fail_at: str
) -> None:
    """The job and run end failed once, and neither the live table nor the catalog moved."""
    fake = _Fake(seed, fail_at=None if fail_at == "commit" else fail_at)
    commit = _FailingCommit(seed.job_id)
    with pytest.raises((RuntimeError, ConnectionResetError)):
        if fail_at == "commit":
            with commit.installed():
                await _settle(fake)
        else:
            await _settle(fake)

    state = await _state(seed)
    assert state["job"] == "failed"
    assert state["run"] == ("failed", "fake_failed")
    assert state["catalog"] == (1, "Test Dataset", 1)
    assert state["live"] == "before"
    assert state["staging_left"] == 0
    assert fake.released == (None, True)
    assert _events(notifications) == ["ingest_failed"]


async def test_a_cancel_that_wins_rolls_the_publication_back_and_writes_nothing(
    seed, notifications
) -> None:
    """A cancel landing before the job's end leaves it cancelled and the data untouched."""
    fake = _Fake(seed, during={"stage": lambda: _cancel(seed)})
    with pytest.raises(Exception, match="no longer owns"):
        await _settle(fake)

    state = await _state(seed)
    assert state["job"] == "cancelled"
    assert state["catalog"] == (1, "Test Dataset", 1)
    assert state["live"] == "before"
    assert _events(notifications) == []


@pytest.mark.parametrize("step", ["catalog cache", "tile cache", "embedding"])
async def test_a_failure_after_the_commit_is_logged_and_the_job_stays_complete(
    seed, step: str
) -> None:
    """A post-commit step that raises leaves the publication complete and the task returns."""
    target = {
        "catalog cache": "app.processing.ingest.publication.invalidate_catalog_cache",
        "tile cache": "app.processing.ingest.publication.invalidate_tile_cache_for_table",
        "embedding": "app.processing.ingest.publication._defer_embedding",
    }[step]
    fake = _Fake(seed)
    with (
        patch(target, new=AsyncMock(side_effect=RuntimeError(f"{step} down"))),
        structlog.testing.capture_logs() as logs,
    ):
        await _settle(fake)

    state = await _state(seed)
    assert (state["job"], state["run"][0]) == ("complete", "succeeded")
    assert state["catalog"] == (7, "Replaced", 2)
    assert [e["step"] for e in logs if e["event"] == "ingest_cleanup_step_failed"] == [
        f"fake_replacement {step}"
    ]


def _rejection(seed: _Seed) -> Verdict:
    async def _settle_rejected(session) -> None:
        await record_refresh_failure(
            session,
            ingest_job_id=seed.job_id,
            error_code="refresh_rejected",
            error_message="rejected",
        )

    return Verdict(
        publish=False,
        reason="The refresh was rejected.",
        settle=_settle_rejected,
        notify=True,
    )


async def test_a_rejected_verdict_ends_the_job_failed_and_notifies(
    seed, notifications
) -> None:
    """A rejection ends the job and settles its run in one transaction, and sends ingest_failed."""
    fake = _Fake(seed, verdict=_rejection(seed))
    await _settle(fake)

    state = await _state(seed)
    assert state["job"] == "failed"
    assert state["run"] == ("failed", "refresh_rejected")
    assert state["catalog"] == (1, "Test Dataset", 1)
    assert state["live"] == "before"
    assert "install" not in fake.seen
    assert _events(notifications) == ["ingest_failed"]


async def test_a_blocked_verdict_waits_for_review_without_notifying(
    seed, notifications, embedding
) -> None:
    """A verdict held for review ends the job but sends nothing and embeds nothing."""

    async def _settle_blocked(session) -> None:
        await record_refresh_blocked(
            session,
            ingest_job_id=seed.job_id,
            feature_count_after=None,
            schema_diff=None,
            verification=None,
        )

    fake = _Fake(
        seed,
        verdict=Verdict(publish=False, reason="Review it.", settle=_settle_blocked),
    )
    await _settle(fake)

    state = await _state(seed)
    assert (state["job"], state["run"][0]) == ("failed", "blocked")
    assert state["catalog"] == (1, "Test Dataset", 1)
    assert _events(notifications) == []
    embedding.assert_not_awaited()


async def test_a_refused_input_is_recorded_and_the_task_returns(
    seed, notifications
) -> None:
    """A refusal ends the job failed and notifies, without raising."""
    fake = _Fake(seed, fail_at="fetch", refused=True)
    await _settle(fake)

    assert (await _state(seed))["job"] == "failed"
    assert _events(notifications) == ["ingest_failed"]


async def test_a_failure_write_that_expires_leaves_the_tasks_own_failure(
    seed, monkeypatch, notifications
) -> None:
    """An expired failure write is logged, and the task still raises its own error."""
    monkeypatch.setattr("app.platform.jobs.heartbeat.JOB_ERROR_WRITE_TIMEOUT_MS", 400)
    holder = db_module.async_session()

    async def _hold_the_job_row() -> None:
        await holder.execute(seed.rows()["job"].with_for_update())

    fake = _Fake(seed, fail_at="fetch", during={"fetch": _hold_the_job_row})
    try:
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(RuntimeError, match="fetch failed"):
                await asyncio.wait_for(_settle(fake), timeout=20)
    finally:
        await holder.rollback()
        await holder.close()

    assert (await _state(seed))["job"] == "running"
    assert [e["event"] for e in logs if e["event"].startswith("job_error_write")] == [
        "job_error_write_timeout"
    ]
    assert fake.released == (None, True)
    assert _events(notifications) == []


async def test_a_lost_catalog_wait_ends_the_job_without_waiting_on_the_held_row(
    seed, monkeypatch, notifications
) -> None:
    """The failure write skips the contact stamp on a held dataset row and still lands."""
    monkeypatch.setattr(catalog_locks, "WORKER_LOCK_TIMEOUT", "1s")
    monkeypatch.setattr("app.platform.jobs.heartbeat.JOB_ERROR_WRITE_TIMEOUT_MS", 1500)
    async with db_module.async_session() as reader:
        dataset = await reader.get(Dataset, seed.dataset_id)
        bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
        checked = dataset.last_checked_at
    fake = _Fake(seed, failure=Failure(CATALOG_LOCK_CONFLICT_CODE, contacted=bound))
    async with db_module.async_session() as holder:
        await holder.execute(seed.rows()["dataset"].with_for_update())
        try:
            with pytest.raises(catalog_locks.CatalogLockConflict):
                await asyncio.wait_for(_settle(fake), timeout=20)
        finally:
            await holder.rollback()

    state = await _state(seed)
    assert state["job"] == "failed"
    assert state["run"] == ("failed", CATALOG_LOCK_CONFLICT_CODE)
    assert _events(notifications) == ["ingest_failed"]
    async with db_module.async_session() as reader:
        assert (await reader.get(Dataset, seed.dataset_id)).last_checked_at == checked


async def _missing(seed: _Seed) -> Failure:
    """A failure that established the origin is missing, contacted as the seed is bound."""
    async with db_module.async_session() as reader:
        dataset = await reader.get(Dataset, seed.dataset_id)
        bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
    return Failure("source_missing", contacted=bound, health=("missing", "not_found"))


async def _origin(seed: _Seed) -> tuple:
    async with db_module.async_session() as reader:
        dataset = await reader.get(Dataset, seed.dataset_id)
        return (
            dataset.source_health,
            dataset.source_health_detail,
            dataset.last_checked_at,
        )


async def test_a_failure_verdict_lands_once_a_brief_hold_on_the_dataset_row_ends(
    seed, notifications
) -> None:
    """A failure's origin verdict waits out an edit's short hold on the dataset row."""
    fake = _Fake(seed, fail_at="fetch", failure=await _missing(seed))
    async with db_module.async_session() as holder:
        # The lock an edit's UPDATE of the row takes.
        await holder.execute(seed.rows()["dataset"].with_for_update(key_share=True))
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(_settle(fake))
        try:
            waited = await _waits_on(holder_pid, task)
        finally:
            await holder.rollback()
        with pytest.raises(RuntimeError, match="fetch failed"):
            await asyncio.wait_for(task, timeout=20)

    assert waited, "the verdict was stamped or skipped without waiting for the row"
    state = await _state(seed)
    assert (state["job"], state["run"]) == ("failed", ("failed", "source_missing"))
    health, detail, checked = await _origin(seed)
    assert (health, detail) == ("missing", "not_found")
    assert checked is not None
    assert _events(notifications) == ["ingest_failed"]


async def test_a_failure_verdict_behind_a_long_hold_is_dropped_and_the_failure_lands(
    seed, notifications
) -> None:
    """A verdict whose dataset row stays held past its short wait is dropped, and the job and run still fail."""
    before = await _origin(seed)
    fake = _Fake(seed, fail_at="fetch", failure=await _missing(seed))
    async with db_module.async_session() as holder:
        await holder.execute(seed.rows()["dataset"].with_for_update(key_share=True))
        try:
            with pytest.raises(RuntimeError, match="fetch failed"):
                await asyncio.wait_for(_settle(fake), timeout=20)
        finally:
            await holder.rollback()

    state = await _state(seed)
    assert (state["job"], state["run"]) == ("failed", ("failed", "source_missing"))
    assert await _origin(seed) == before
    assert _events(notifications) == ["ingest_failed"]


async def test_an_attempt_rotated_during_the_fetch_is_stale_and_writes_nothing(
    seed, notifications
) -> None:
    """A job handed to a newer attempt mid-fetch raises StaleIngestAttempt and is left to that attempt."""

    async def _rotate() -> None:
        async with db_module.async_session() as session:
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == seed.job_id)
                .values(attempt_id=uuid.uuid4())
            )
            await session.commit()

    fake = _Fake(seed, during={"fetch": _rotate})
    with pytest.raises(StaleIngestAttempt):
        await _settle(fake)

    state = await _state(seed)
    assert state["job"] == "running"
    assert state["catalog"] == (1, "Test Dataset", 1)
    assert state["live"] == "before"
    assert state["staging_left"] == 0
    assert "stage" not in fake.seen
    assert _events(notifications) == []


async def test_a_held_back_verdict_without_a_settle_step_is_refused() -> None:
    """A verdict that holds the candidate back must say how its run ends."""
    with pytest.raises(ValueError, match="settle step"):
        Verdict(publish=False, reason="Held back.")


@pytest.mark.parametrize("failure", [ConnectionResetError, asyncio.CancelledError])
async def test_a_rejection_that_loses_its_acknowledgement_still_notifies(
    seed, notifications, failure
) -> None:
    """A rejection that lands but loses its acknowledgement ends as rejected and sends ingest_failed."""
    fake = _Fake(seed, verdict=_rejection(seed))
    lost = _LostAcknowledgement(seed.job_id, "failed", failure("dropped"))
    with lost.installed():
        await _settle(fake)

    assert lost.fired == 1
    state = await _state(seed)
    assert state["job"] == "failed"
    assert state["run"] == ("failed", "refresh_rejected")
    assert _events(notifications) == ["ingest_failed"]


async def test_a_publication_parked_on_the_dataset_row_bumps_past_the_edit(
    seed,
) -> None:
    """The bump follows the catalog rows, so it publishes past an edit that held them."""
    async with (
        db_module.async_session() as holder,
        db_module.async_session() as probe,
    ):
        before, _ = await _overlap(holder, probe, seed.dataset_id, _settle(_Fake(seed)))

    published = await _published_version(seed.dataset_id)
    assert published == before + 2, _message(before, published)


async def test_a_lost_claim_drops_the_table_its_attempt_left_behind(seed) -> None:
    """A redelivery that finds its job already running still drops its attempt's table."""
    leftover = attempt_scoped_staging_table(seed.table, seed.attempt_id)
    async with db_module.async_session() as session:
        await session.execute(text(f'CREATE TABLE data."{leftover}" (name text)'))
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == seed.job_id)
            .values(status="running")
        )
        await session.commit()
    fake = _Fake(seed)
    await _settle(fake)

    assert "fetch" not in fake.seen
    state = await _state(seed)
    assert (state["job"], state["staging_left"]) == ("running", 0)


async def test_a_contact_stamp_matches_an_origin_ref_in_another_key_order(seed) -> None:
    """The stamp's binding guard compares origin_ref as JSON, so key order is no rebind."""
    from app.platform.dataset_origin import set_dataset_origin
    from app.processing.ingest.publication import _stamp_contact

    url = "https://services.example.test/wfs"
    async with db_module.async_session() as session:
        dataset = await session.get(Dataset, seed.dataset_id)
        set_dataset_origin(
            dataset, "service", uri=url, service_type="wfs", url=url, layer_id="roads"
        )
        reordered = dict(reversed(list(dataset.origin_ref.items())))
        binding = (dataset.origin_uri, reordered, dataset.source_format)
        await session.commit()

        stamped = await _stamp_contact(session, seed.dataset_id, binding)
        await session.commit()

    assert stamped

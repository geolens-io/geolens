"""The job ledger ends a job once, fenced, and settles its linked rows with it."""

from __future__ import annotations

import uuid

import anyio
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

import app.core.db as db_module
from app.modules.audit.models import AuditLog
from app.platform.jobs import ledger
from app.platform.jobs.heartbeat import claim_ingest_job_attempt
from app.platform.jobs.ledger import Outcome, abort, hold
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import claim_run_for_job
from app.processing.raster.models import RasterAsset, VrtGeneration
from tests.factories import get_user_id
from tests.test_embedding_backfill_queue_1542 import _release_slot
from tests.test_job_cancel_vrt import _seed_vrt_regeneration
from tests.test_refresh_dispatch_rollback import _committed_dispatch
from tests.test_stale_settlement_pass_2151 import _a_settler_waits_on_a_row_lock

pytestmark = pytest.mark.anyio

_STATUSES = ("pending", "running", "complete", "failed", "cancelled", "fanned_out")
_REASON = "Failed to queue ingest task (RuntimeError)"


@pytest.fixture(autouse=True)
async def _drop_ledger_jobs(test_db_session):
    """Keep this file's job rows out of the worker database's later sweeps."""
    yield
    await test_db_session.rollback()
    await test_db_session.execute(
        delete(IngestJob).where(IngestJob.source_filename == "ledger.geojson")
    )
    await test_db_session.commit()


async def _job(session, *, status: str = "pending", **columns) -> IngestJob:
    job = IngestJob(
        source_filename="ledger.geojson",
        status=status,
        attempt_id=uuid.uuid4(),
        **columns,
    )
    session.add(job)
    await session.commit()
    return job


async def _row(session, job_id: uuid.UUID) -> IngestJob:
    return await session.get(IngestJob, job_id, populate_existing=True)


async def _refresh_failed_events(session, dataset_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "refresh.failed",
            AuditLog.resource_id == dataset_id,
        )
    )


class TestHold:
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_returns_the_row_only_in_the_expected_state(
        self, test_db_session, status
    ):
        """hold returns a job in the state it expects, and None in any other."""
        job = await _job(test_db_session, status=status)
        job_id = job.id

        held = await hold(test_db_session, job_id, expect="pending")
        assert (held is not None) == (status == "pending")
        held_as_is = await hold(test_db_session, job_id, expect=status)
        assert held_as_is is not None and held_as_is.id == job_id
        await test_db_session.rollback()
        assert (await _row(test_db_session, job_id)).status == status

    async def test_misses_a_superseded_attempt(self, test_db_session):
        """hold returns None when another attempt owns the row."""
        job = await _job(test_db_session)

        assert (
            await hold(
                test_db_session, job.id, expect="pending", attempt_id=uuid.uuid4()
            )
            is None
        )
        assert (
            await hold(
                test_db_session, job.id, expect="pending", attempt_id=job.attempt_id
            )
            is not None
        )
        await test_db_session.rollback()

    async def test_locks_the_row_until_the_transaction_ends(self, test_db_session):
        """A held row refuses another transaction's lock."""
        job = await _job(test_db_session)
        job_id = job.id
        assert await hold(test_db_session, job_id, expect="pending") is not None

        async with db_module.async_session() as other:
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                await other.execute(
                    select(IngestJob.id)
                    .where(IngestJob.id == job_id)
                    .with_for_update(nowait=True)
                )
            await other.rollback()
        await test_db_session.rollback()


class TestAbort:
    @pytest.mark.parametrize("expect", ["pending", "running"])
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_fails_only_a_job_in_the_expected_state(
        self, test_db_session, status, expect
    ):
        """abort fails a job in the state it expects and writes nothing otherwise."""
        job = await _job(test_db_session, status=status)
        job_id = job.id

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON, expect=expect
        )
        if status == expect:
            assert outcome is Outcome.ENDED
            assert job.status == "failed", "the instance was not told"
        else:
            assert outcome is Outcome.MOVED
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        if status == expect:
            assert (row.status, row.error_message) == ("failed", _REASON)
            assert row.completed_at is not None
        else:
            assert (row.status, row.error_message, row.completed_at) == (
                status,
                None,
                None,
            )

    async def test_leaves_a_superseded_attempt_unwritten(self, test_db_session):
        """abort on an attempt a retry replaced reports it and writes nothing."""
        job = await _job(test_db_session)
        job_id = job.id
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(attempt_id=uuid.uuid4())
            .execution_options(synchronize_session=False)
        )
        await test_db_session.commit()

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON
        )
        await test_db_session.commit()

        assert outcome is Outcome.SUPERSEDED
        row = await _row(test_db_session, job_id)
        assert (row.status, row.error_message) == ("pending", None)

    async def test_reports_a_missing_job(self, test_db_session):
        """abort on a row that does not exist reports it missing."""
        absent = IngestJob(id=uuid.uuid4(), attempt_id=uuid.uuid4(), status="pending")

        outcome = await abort(
            test_db_session, absent, code="dispatch_failed", reason=_REASON
        )

        assert outcome is Outcome.MISSING

    async def test_refuses_a_state_no_dispatch_leaves_a_job_in(self, test_db_session):
        """abort ends only a pending job, or a running URL import."""
        job = await _job(test_db_session, status="complete")

        with pytest.raises(ValueError):
            await abort(
                test_db_session,
                job,
                code="dispatch_failed",
                reason=_REASON,
                expect="complete",
            )

    async def test_stores_the_reason_redacted(self, test_db_session):
        """abort keeps credentials and library exception text out of the stored reason."""
        leaky = await _job(test_db_session)
        library = await _job(test_db_session)

        await abort(
            test_db_session,
            leaky,
            code="content_rejected",
            reason="Rejected https://reader:hunter2@example.test/data?token=abc",
        )
        await abort(
            test_db_session,
            library,
            code="dispatch_failed",
            reason=OSError("connection to 10.0.0.5 refused"),
        )
        await test_db_session.commit()

        stored = (await _row(test_db_session, leaky.id)).error_message
        assert "hunter2" not in stored and "abc" not in stored
        assert (
            await _row(test_db_session, library.id)
        ).error_message == "internal_error"


class TestTheRefreshRunHook:
    @pytest.mark.parametrize("claimed", [False, True], ids=["pending", "claimed"])
    async def test_fails_the_run_only_when_the_job_write_lands(
        self, test_db_session, clean_tables, claimed
    ):
        """The job's run fails with the abort's code and reason exactly when the abort lands."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, dataset_id = job.id, job.dataset_id
        if claimed:
            assert await claim_ingest_job_attempt(
                test_db_session, job_id, job.attempt_id
            )
            assert await claim_run_for_job(test_db_session, job_id) == run_id
            await test_db_session.commit()

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON
        )
        await test_db_session.commit()

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        if claimed:
            assert outcome is Outcome.MOVED
            assert (run.status, run.error_code, run.finished_at) == (
                "running",
                None,
                None,
            )
            assert await _refresh_failed_events(test_db_session, dataset_id) == 0
        else:
            assert outcome is Outcome.ENDED
            assert (run.status, run.error_code, run.error_message) == (
                "failed",
                "dispatch_failed",
                _REASON,
            )
            assert run.finished_at is not None
            assert await _refresh_failed_events(test_db_session, dataset_id) == 1


class TestTheBackfillTrailHook:
    @pytest.mark.parametrize("claimed", [False, True], ids=["pending", "claimed"])
    async def test_closes_the_trail_only_when_the_job_write_lands(
        self, test_db_session, claimed
    ):
        """A backfill's terminal entry names the requester and the request's IP, and only a landed abort writes it."""
        await _release_slot(test_db_session)
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _job(
            test_db_session,
            status="running" if claimed else "pending",
            created_by=admin_id,
            user_metadata={
                EMBEDDING_BACKFILL_METADATA_KEY: {
                    "force": True,
                    "operation_id": "op-ledger",
                }
            },
        )
        job_id = job.id
        try:
            outcome = await abort(
                test_db_session,
                job,
                code="dispatch_failed",
                reason=_REASON,
                ip_address="203.0.113.9",
            )
            await test_db_session.commit()

            entries = (
                await test_db_session.execute(
                    select(
                        AuditLog.user_id, AuditLog.ip_address, AuditLog.details
                    ).where(
                        AuditLog.action == "embedding.backfill",
                        AuditLog.details["job_id"].astext == str(job_id),
                    )
                )
            ).all()
            if claimed:
                assert outcome is Outcome.MOVED
                assert entries == []
            else:
                assert outcome is Outcome.ENDED
                assert len(entries) == 1
                user_id, ip_address, details = entries[0]
                assert (user_id, ip_address) == (admin_id, "203.0.113.9")
                assert details == {
                    "force": True,
                    "operation_id": "op-ledger",
                    "job_id": str(job_id),
                    "outcome": "failed",
                    "error_code": "dispatch_failed",
                }
        finally:
            await _release_slot(test_db_session)


class TestTheVrtHook:
    @pytest.mark.parametrize("claimed", [False, True], ids=["pending", "claimed"])
    async def test_releases_the_asset_only_when_the_job_write_lands(
        self, test_db_session, clean_tables, claimed
    ):
        """A VRT regeneration's generation fails and its asset is restored exactly when the abort lands."""
        _vrt, asset, generation, job = await _seed_vrt_regeneration(
            test_db_session, job_status="running" if claimed else "pending"
        )
        asset_id, generation_id = asset.id, generation.id

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON
        )
        await test_db_session.commit()

        generation = await test_db_session.get(
            VrtGeneration, generation_id, populate_existing=True
        )
        asset = await test_db_session.get(RasterAsset, asset_id, populate_existing=True)
        if claimed:
            assert outcome is Outcome.MOVED
            assert generation.status == "pending"
            assert (asset.status, asset.current_generation_id) == (
                "regenerating",
                generation_id,
            )
        else:
            assert outcome is Outcome.ENDED
            assert (generation.status, generation.error_message) == ("failed", _REASON)
            assert generation.completed_at is not None
            assert (asset.status, asset.current_generation_id) == ("ready", None)

    async def test_restores_by_the_ready_worthy_rule(
        self, test_db_session, clean_tables
    ):
        """An aborted regeneration of a VRT whose last attempt failed leaves it failed."""
        _vrt, asset, _generation, job = await _seed_vrt_regeneration(
            test_db_session, prior_failed_attempt=True
        )
        asset_id = asset.id

        assert (
            await abort(test_db_session, job, code="dispatch_failed", reason=_REASON)
            is Outcome.ENDED
        )
        await test_db_session.commit()

        asset = await test_db_session.get(RasterAsset, asset_id, populate_existing=True)
        assert (asset.status, asset.current_generation_id) == ("failed", None)


class TestHookContract:
    async def test_hooks_run_with_the_job_row_already_locked(
        self, test_db_session, monkeypatch
    ):
        """Every hook sees the job row locked before it touches a linked row."""
        job = await _job(test_db_session)
        job_id = job.id
        seen: list[bool] = []

        async def _probe(session, end) -> None:
            async with db_module.async_session() as other:
                try:
                    await other.execute(
                        select(IngestJob.id)
                        .where(IngestJob.id == end.job_id)
                        .with_for_update(nowait=True)
                    )
                    seen.append(False)
                except DBAPIError:
                    seen.append(True)
                await other.rollback()

        monkeypatch.setattr(ledger, "_END_HOOKS", (_probe,))
        assert (
            await abort(test_db_session, job, code="dispatch_failed", reason=_REASON)
            is Outcome.ENDED
        )
        await test_db_session.commit()

        assert seen == [True]
        assert (await _row(test_db_session, job_id)).status == "failed"

    async def test_a_raising_hook_rolls_back_the_job_and_every_linked_write(
        self, test_db_session, clean_tables, monkeypatch
    ):
        """A hook that raises leaves the job and the rows earlier hooks wrote as they were."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, dataset_id = job.id, job.dataset_id

        async def _raises(session, end) -> None:
            raise RuntimeError("linked row refused")

        monkeypatch.setattr(ledger, "_END_HOOKS", (ledger._fail_refresh_run, _raises))
        with pytest.raises(RuntimeError, match="linked row refused"):
            await abort(test_db_session, job, code="dispatch_failed", reason=_REASON)
        # A caller that commits after the error still commits nothing of the abort.
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert (row.status, row.error_message) == ("pending", None)
        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert run.status == "pending"
        assert await _refresh_failed_events(test_db_session, dataset_id) == 0


@pytest.mark.parametrize("first", ["claim", "abort"])
async def test_an_abort_racing_a_claim_ends_the_job_once(
    test_db_session, clean_tables, first
):
    """An abort and a worker's claim on one job end it once, with one set of run writes."""
    job, run_id = await _committed_dispatch(test_db_session)
    # Read up front: the lock watcher's rollbacks expire every loaded row.
    job_id, attempt_id, dataset_id = job.id, job.attempt_id, job.dataset_id
    results: dict[str, object] = {}

    async with (
        db_module.async_session() as worker,
        db_module.async_session() as dispatcher,
    ):
        dispatched = await dispatcher.get(IngestJob, job_id)
        await dispatcher.commit()

        async def _abort() -> None:
            results["abort"] = await abort(
                dispatcher, dispatched, code="dispatch_failed", reason=_REASON
            )

        async def _claim() -> None:
            results["claim"] = await claim_ingest_job_attempt(
                worker, job_id, attempt_id
            )
            if results["claim"]:
                assert await claim_run_for_job(worker, job_id) == run_id

        if first == "claim":
            holder, holding, waiter, waiting = _claim, worker, _abort, dispatcher
        else:
            holder, holding, waiter, waiting = _abort, dispatcher, _claim, worker

        # The holder's transaction stays open, so the waiter blocks on the job
        # row until the holder commits.
        await holder()
        async with anyio.create_task_group() as tg:
            tg.start_soon(waiter)
            with anyio.fail_after(30):
                while not await _a_settler_waits_on_a_row_lock(test_db_session):
                    await anyio.sleep(0.05)
            await holding.commit()
        await waiting.commit()

    row = await _row(test_db_session, job_id)
    run = await test_db_session.get(DatasetRefreshRun, run_id, populate_existing=True)
    failed_events = await _refresh_failed_events(test_db_session, dataset_id)
    if first == "claim":
        assert (results["claim"], results["abort"]) == (True, Outcome.MOVED)
        assert (row.status, run.status, failed_events) == ("running", "running", 0)
    else:
        assert (results["abort"], results["claim"]) == (Outcome.ENDED, False)
        assert (row.status, run.status, failed_events) == ("failed", "failed", 1)

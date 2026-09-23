"""Startup recovery and the lifespan sweep run one stale-job settlement pass."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs import sweep as sweep_module
from app.platform.jobs import worker as worker_module
from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY, IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS, stale_pending_cutoff_seconds
from tests.stale_settlers import STALE_SETTLERS

pytestmark = pytest.mark.anyio


def _ago(seconds: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _add(session: AsyncSession, **columns) -> IngestJob:
    job = IngestJob(source_filename="settle.geojson", **columns)
    session.add(job)
    await session.commit()
    return job


async def _stale_running(session: AsyncSession) -> IngestJob:
    return await _add(
        session, status="running", started_at=_ago(JOB_TIMEOUT_SECONDS + 60)
    )


async def _stale_pending(session: AsyncSession, *, bound: bool) -> IngestJob:
    age = stale_pending_cutoff_seconds(completion_bound=bound) + 60
    return await _add(
        session,
        status="pending",
        file_path="staging/settle/frozen/roads.geojson" if bound else "",
        created_at=_ago(age),
        user_metadata={COMMIT_ATTEMPTED_METADATA_KEY: _ago(age).isoformat()},
    )


@STALE_SETTLERS
async def test_a_running_job_with_a_fresh_heartbeat_is_left_alone(
    test_db_session, settle
) -> None:
    """A job whose worker still renews its lease stays running, however old."""
    job = await _add(
        test_db_session,
        status="running",
        started_at=_ago(JOB_TIMEOUT_SECONDS + 60),
        heartbeat_at=_ago(30),
    )

    await settle(test_db_session)

    await test_db_session.refresh(job)
    assert job.status == "running"
    assert job.completed_at is None


async def test_recovery_logs_each_job_it_settles(test_db_session) -> None:
    """Recovery names every job it settles in its own log line."""
    running = await _stale_running(test_db_session)
    pending = await _stale_pending(test_db_session, bound=False)

    with patch.object(worker_module, "log") as log:
        await worker_module.recover_stale_jobs()

    logged = {
        call.kwargs.get("job_id"): (call.args[0], call.kwargs.get("status"))
        for call in log.warning.call_args_list
    }
    assert logged[str(running.id)] == ("Recovered stale running job", None)
    assert logged[str(pending.id)] == ("Recovered orphaned pending job", "failed")


async def _a_settler_waits_on_a_row_lock(observer: AsyncSession) -> bool:
    waiting = await observer.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() "
            "AND state = 'active' "
            "AND wait_event_type = 'Lock' "
            "AND query ILIKE '%ingest_jobs%'"
        )
    )
    # Activity is snapshotted per transaction, so each poll needs a new one.
    await observer.rollback()
    return waiting > 0


def _settled_ids(outcome) -> set:
    return set(outcome._settled_running_ids) | {
        job_id for job_id, _status in outcome._settled_pending
    }


@pytest.mark.parametrize("first", ["recovery", "sweep"])
@pytest.mark.parametrize("stale", ["pending", "running"])
async def test_a_concurrent_sweep_and_recovery_settle_each_row_once(
    test_db_session, monkeypatch, first, stale
) -> None:
    """Recovery and the sweep running at once settle every stale row exactly once."""
    from app.core.db import async_session

    # Settle this database's leftovers first, so no other row is contended.
    await sweep_module.fail_stale_jobs(test_db_session)
    if stale == "pending":
        jobs = [
            await _stale_pending(test_db_session, bound=False),
            await _stale_pending(test_db_session, bound=True),
        ]
    else:
        jobs = [await _stale_running(test_db_session)]
    job_ids = {job.id for job in jobs}

    real_settle = sweep_module.settle_stale_jobs
    outcomes = []
    first_holds_its_rows = anyio.Event()
    release = anyio.Event()

    async def settle_and_hold_the_first_caller(db, now):
        outcome = await real_settle(db, now)
        outcomes.append(outcome)
        if len(outcomes) == 1:
            first_holds_its_rows.set()
            with anyio.fail_after(30):
                await release.wait()
        return outcome

    monkeypatch.setattr(
        sweep_module, "settle_stale_jobs", settle_and_hold_the_first_caller
    )

    async def lifespan_sweep() -> None:
        async with async_session() as session:
            await sweep_module.fail_stale_jobs(session)

    callers = {
        "recovery": worker_module.recover_stale_jobs,
        "sweep": lifespan_sweep,
    }
    second = "sweep" if first == "recovery" else "recovery"

    async with anyio.create_task_group() as tg:
        tg.start_soon(callers[first])
        with anyio.fail_after(30):
            await first_holds_its_rows.wait()
        tg.start_soon(callers[second])
        with anyio.fail_after(30):
            if stale == "pending":
                # The second caller's UPDATE blocks on a row the first holds.
                while not await _a_settler_waits_on_a_row_lock(test_db_session):
                    await anyio.sleep(0.05)
            else:
                # SKIP LOCKED: the second caller passes the held row by.
                while len(outcomes) < 2:
                    await anyio.sleep(0.05)
        release.set()

    held, other = outcomes
    assert job_ids <= _settled_ids(held)
    assert not job_ids & _settled_ids(other)
    for job in jobs:
        await test_db_session.refresh(job)
        assert job.status == "failed"

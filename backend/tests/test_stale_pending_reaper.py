"""fix(#724): the pending reaper must not fail jobs that are genuinely queued.

``fail_stale_jobs`` marked every ``pending`` IngestJob older than
``PENDING_TIMEOUT_SECONDS`` as failed with "never queued". That conflated two
different states, and since fix(#695) deferred analysis to priority -10 —
where waiting behind a steady upload stream is by design and unbounded — the
wrong one became reachable in normal operation.

DB-backed on purpose: the fix is a correlated EXISTS against
``catalog.procrastinate_jobs``, so mocking the session would assert nothing
about whether the SQL is even valid.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob
from app.platform.jobs.router import PENDING_TIMEOUT_SECONDS, fail_stale_jobs

pytestmark = pytest.mark.anyio


async def _stale_pending_job(session: AsyncSession) -> IngestJob:
    """A pending job old enough for the reaper to consider it."""
    job = IngestJob(source_filename="reaper-test", status="pending")
    session.add(job)
    await session.flush()
    old = datetime.now(timezone.utc) - timedelta(seconds=PENDING_TIMEOUT_SECONDS + 600)
    await session.execute(
        text(
            "UPDATE catalog.ingest_jobs SET created_at = :old WHERE id = :id"
        ).bindparams(old=old, id=job.id)
    )
    await session.commit()
    return job


async def _queue_procrastinate_job(
    session: AsyncSession, job_id: uuid.UUID, status: str
) -> None:
    # Procrastinate's insert trigger logs to procrastinate_events by unqualified
    # name, so the schema has to be on the search_path or a 'todo' insert fails
    # where a 'doing' one (no event) would succeed.
    await session.execute(text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        text(
            "INSERT INTO catalog.procrastinate_jobs"
            " (queue_name, task_name, args, status)"
            " VALUES ('default', 'app.processing.analysis.tasks.materialize_analysis',"
            " jsonb_build_object('job_id', :job_id), CAST(:status AS"
            " catalog.procrastinate_job_status))"
        ).bindparams(job_id=str(job_id), status=status)
    )
    await session.commit()


class TestStalePendingReaper:
    async def test_reaps_a_job_that_was_never_queued(
        self, test_db_session: AsyncSession
    ):
        """The genuine orphan: committed, then the defer never landed a row."""
        job = await _stale_pending_job(test_db_session)

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "never queued" in (job.error_message or "")

    @pytest.mark.parametrize("queue_status", ["todo", "doing"])
    async def test_spares_a_job_the_queue_still_holds(
        self, test_db_session: AsyncSession, queue_status: str
    ):
        """Starved, not orphaned — the task is right there in the queue.

        Reachable in normal operation: analysis defers at priority -10, so a
        steady upload stream keeps it in 'todo' indefinitely. Failing it here
        both lies to the user and races the worker, which later picks the task
        up against a row already marked failed.
        """
        job = await _stale_pending_job(test_db_session)
        await _queue_procrastinate_job(test_db_session, job.id, queue_status)

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "pending", job.error_message
        assert job.error_message is None

    @pytest.mark.parametrize("queue_status", ["failed", "cancelled", "succeeded"])
    async def test_reaps_a_job_whose_queue_entry_is_already_terminal(
        self, test_db_session: AsyncSession, queue_status: str
    ):
        """A terminal queue row cannot advance the job, so the row IS stale."""
        job = await _stale_pending_job(test_db_session)
        await _queue_procrastinate_job(test_db_session, job.id, queue_status)

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"

    async def test_leaves_a_recent_pending_job_alone(
        self, test_db_session: AsyncSession
    ):
        """The age test still applies — this guards against over-reaping."""
        job = IngestJob(source_filename="fresh", status="pending")
        test_db_session.add(job)
        await test_db_session.commit()

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "pending"

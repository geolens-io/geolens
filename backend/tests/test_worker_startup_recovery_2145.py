"""Worker startup recovery must not fail a running job the queue still holds.

The periodic sweep (``fail_stale_jobs``) exempts a running row from its lease
reap while a `todo` Procrastinate entry means no worker has adopted it yet
(``no_unclaimed_queue_entry``). The worker's own startup recovery pass ran
the same running-row query without that predicate, so a job still sitting in
a startup backlog could be failed by the very restart meant to recover it.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS
from app.platform.jobs.worker import recover_stale_jobs

pytestmark = pytest.mark.anyio


async def _stale_running_job(session: AsyncSession) -> IngestJob:
    """A running job whose lease looks expired by JOB_TIMEOUT_SECONDS."""
    expired = datetime.now(timezone.utc) - timedelta(seconds=JOB_TIMEOUT_SECONDS + 60)
    job = IngestJob(
        source_filename="backlog.geojson",
        status="running",
        started_at=expired,
        heartbeat_at=None,
    )
    session.add(job)
    await session.commit()
    return job


async def _queue_todo_entry(session: AsyncSession, job_id: UUID) -> None:
    # Procrastinate's insert trigger logs to procrastinate_events by
    # unqualified name, so the schema has to be on the search_path for a
    # 'todo' insert.
    await session.execute(text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        text(
            "INSERT INTO catalog.procrastinate_jobs"
            " (queue_name, task_name, args, status)"
            " VALUES ('download', 'fetch_url',"
            " jsonb_build_object('job_id', CAST(:job_id AS text)), 'todo')"
        ).bindparams(job_id=str(job_id))
    )
    await session.commit()


class TestStartupRecoverySparesAQueuedRunningJob:
    async def test_a_todo_queue_entry_survives_startup_recovery(
        self, test_db_session: AsyncSession
    ) -> None:
        """No worker has claimed the lease yet, so recovery must leave it.

        Counterfactual: without `no_unclaimed_queue_entry()` in the worker's
        own running-row query, this job is failed on the very restart meant
        to recover it.
        """
        job = await _stale_running_job(test_db_session)
        await _queue_todo_entry(test_db_session, job.id)

        await recover_stale_jobs()

        test_db_session.expire_all()
        await test_db_session.refresh(job)
        assert job.status == "running", job.error_message

    async def test_the_same_row_without_a_queue_entry_is_failed(
        self, test_db_session: AsyncSession
    ) -> None:
        """The exemption is for never-claimed work only."""
        job = await _stale_running_job(test_db_session)

        await recover_stale_jobs()

        test_db_session.expire_all()
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Stale: running" in (job.error_message or "")

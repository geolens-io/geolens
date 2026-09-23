"""Worker startup recovery applies the sweep's unclaimed-queue exemption."""

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
        """A stale running job whose queue entry is still todo stays running."""
        job = await _stale_running_job(test_db_session)
        await _queue_todo_entry(test_db_session, job.id)

        await recover_stale_jobs()

        test_db_session.expire_all()
        await test_db_session.refresh(job)
        assert job.status == "running", job.error_message

    async def test_the_same_row_without_a_queue_entry_is_failed(
        self, test_db_session: AsyncSession
    ) -> None:
        """The same stale job with no queue entry is failed."""
        job = await _stale_running_job(test_db_session)

        await recover_stale_jobs()

        test_db_session.expire_all()
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Stale: running" in (job.error_message or "")

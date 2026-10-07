"""Settling a lost worker's replacement frees its dataset for the next one in the same commit."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS
from app.platform.refresh.service import claim_run_for_job, create_pending_run
from tests.factories import create_dataset, get_user_id
from tests.stale_settlers import EVERY_SETTLER

pytestmark = pytest.mark.anyio


async def _doing_queue_entry(session: AsyncSession, job_id: uuid.UUID) -> None:
    """The queue row a killed worker leaves in ``doing``."""
    await session.execute(text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        text(
            "INSERT INTO catalog.procrastinate_jobs"
            " (queue_name, task_name, args, status)"
            " VALUES ('default', 'reupload',"
            " jsonb_build_object('job_id', CAST(:job_id AS text)), 'todo')"
        ).bindparams(job_id=str(job_id))
    )
    await session.execute(
        text(
            "UPDATE catalog.procrastinate_jobs SET status = 'doing'"
            " WHERE args->>'job_id' = :job_id"
        ).bindparams(job_id=str(job_id))
    )
    await session.commit()


async def _lost_replacement(session: AsyncSession):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=admin_id, name=f"lost-{uuid.uuid4().hex[:8]}"
    )
    job = IngestJob(
        status="running",
        source_filename="lost.geojson",
        dataset_id=dataset.id,
        created_by=admin_id,
        started_at=datetime.now(timezone.utc)
        - timedelta(seconds=JOB_TIMEOUT_SECONDS + 60),
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.flush()
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
    )
    await claim_run_for_job(session, job.id)
    await session.commit()
    await _doing_queue_entry(session, job.id)
    return dataset, job, run, admin_id


@EVERY_SETTLER
async def test_a_lost_workers_run_fails_with_the_job(test_db_session, settle) -> None:
    dataset, job, run, admin_id = await _lost_replacement(test_db_session)
    job_id, dataset_id = job.id, dataset.id
    try:
        await settle(test_db_session, job)

        await test_db_session.refresh(job)
        await test_db_session.refresh(run)
        assert (job.status, job.error_code) == ("failed", "worker_lost")
        assert (run.status, run.error_code) == ("failed", "worker_lost")
        await create_pending_run(
            test_db_session,
            dataset_id=dataset_id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=None,
            feature_count_before=None,
        )
        await test_db_session.rollback()
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(text("SET LOCAL search_path TO catalog, public"))
        await test_db_session.execute(
            text("DELETE FROM catalog.procrastinate_jobs WHERE args->>'job_id' = :id"),
            {"id": str(job_id)},
        )
        await test_db_session.commit()

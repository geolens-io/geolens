"""A failed dispatch's rollback fails a refresh run only when it failed the job too."""

from __future__ import annotations

import uuid

import pytest

from app.platform.jobs.defer_guard import (
    DeferFailed,
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.heartbeat import claim_ingest_job_attempt
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    claim_run_for_job,
    create_pending_run,
    make_refresh_run_failed_rollback,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _committed_dispatch(session) -> tuple[IngestJob, uuid.UUID]:
    """A pending job and its pending run, committed as a door leaves them."""
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=user_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.gpkg",
        file_path="staging/parcels.gpkg",
        created_by=user_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.flush()
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=user_id,
        ingest_job_id=job.id,
        feature_count_before=None,
    )
    run_id = run.id
    await session.commit()
    return job, run_id


async def _fail_the_defer(session, job: IngestJob, *, worker_claims_first: bool):
    """Dispatch through the orphan guard with a defer that raises."""
    import app.core.db as db_module

    job_id, attempt_id = job.id, job.attempt_id
    rollback = make_refresh_run_failed_rollback(
        make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue refresh task"
        ),
        db=session,
        ingest_job_id=job_id,
    )

    async def _defer() -> None:
        if worker_claims_first:
            async with db_module.async_session() as worker:
                assert await claim_ingest_job_attempt(worker, job_id, attempt_id)
                assert await claim_run_for_job(worker, job_id) is not None
                await worker.commit()
        raise RuntimeError("connection dropped after the insert")

    with pytest.raises(DeferFailed):
        await defer_with_orphan_guard(_defer, rollback=rollback, db=session, job=job)


class TestDispatchRollback:
    async def test_a_job_and_run_a_worker_claimed_are_left_to_it(
        self, test_db_session, clean_tables
    ):
        """A defer that raises after a worker claimed both rows changes neither."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, attempt_id = job.id, job.attempt_id

        await _fail_the_defer(test_db_session, job, worker_claims_first=True)

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert (run.status, run.error_code, run.finished_at) == ("running", None, None)
        claimed = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert (claimed.status, claimed.attempt_id, claimed.error_message) == (
            "running",
            attempt_id,
            None,
        )

    async def test_an_unclaimed_job_and_run_both_fail(
        self, test_db_session, clean_tables
    ):
        """With no worker in the way, the rollback fails the job and its run."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id = job.id

        await _fail_the_defer(test_db_session, job, worker_claims_first=False)

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert (run.status, run.error_code) == ("failed", "dispatch_failed")
        failed = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert failed.status == "failed"
        assert failed.error_message == "Failed to queue refresh task (RuntimeError)"

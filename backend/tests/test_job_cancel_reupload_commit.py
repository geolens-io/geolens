"""Cancel racing POST /datasets/{id}/reupload/{job_id}/commit.

``reupload_commit`` reads the job as pending, merges metadata, inserts the
``DatasetRefreshRun`` that takes the dataset's admission slot, and commits. A
cancel landing between that read and the commit would leave a pending run
bound to a cancelled job, holding ``uq_refresh_runs_one_active`` until the
stale-run sweep. So the request takes the ledger's hold on the job just before
it commits, in the transaction that flushes the run, and compares the held
row's attempt with the one it read. A committed cancel, or a new attempt, fails
that check, and the whole request, run row included, rolls back into a 409.
Once the commit lands, a cancel ends the job and its run together through
``cancel_active_run_for_job``.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    USER_CANCELLED_ERROR_CODE,
    create_pending_run,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _seed_committable_reupload(session):
    """Dataset + bound pending reupload job, exactly what the stage door
    commits before the user clicks commit."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.gpkg",
        file_path="/tmp/fake-reupload.gpkg",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return dataset, job


def _racing_create_pending_run(session_factory, **values):
    """Wrap the real create_pending_run: first commit ``values`` onto the
    pending job, by default the write a cancel makes, on a SEPARATE session,
    then proceed.

    The flip runs on its own connection and commits immediately —
    the concurrent cancel, made deterministic. It must run BEFORE the real
    helper, because the helper's flush writes the request's dirty job
    metadata and takes the job row lock; flipping after that on another
    connection would wait on the request's own lock forever.
    """

    async def _wrapped(session, **kwargs):
        async with session_factory() as side_session:
            await side_session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == kwargs["ingest_job_id"],
                    IngestJob.status == "pending",
                )
                .values(
                    **(
                        values
                        or {"status": "cancelled", "error_message": "Cancelled by user"}
                    )
                )
            )
            await side_session.commit()
        return await create_pending_run(session, **kwargs)

    return _wrapped


class TestCommitFenceLosesToCancel:
    async def test_lost_fence_rolls_back_the_run_and_409s(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Cancel commits between the pending read and the commit: the fence
        matches zero rows, the run insert rolls back with the request, and
        the dataset's admission index stays free."""
        from app.core.db import async_session

        dataset, job = await _seed_committable_reupload(test_db_session)

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.create_pending_run",
            side_effect=_racing_create_pending_run(async_session),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={},
                headers=admin_auth_header,
            )

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "job_conflict"
        assert detail["status"] == "cancelled"

        # The committed cancel stands; the run insert rolled back with the
        # request, so nothing holds uq_refresh_runs_one_active.
        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        runs = (
            (
                await test_db_session.execute(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.dataset_id == dataset.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert runs == []

        # The admission index is provably free: a new dispatch is admitted
        # immediately, which is the whole harm the fence exists to prevent.
        admin_id = await get_user_id(test_db_session, "admin")
        next_job = IngestJob(
            dataset_id=dataset.id,
            status="pending",
            attempt_id=uuid.uuid4(),
            source_filename="parcels.gpkg",
            file_path="/tmp/fake-reupload-2.gpkg",
            created_by=admin_id,
            user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
        )
        test_db_session.add(next_job)
        await test_db_session.commit()
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=next_job.id,
            feature_count_before=1,
        )
        await test_db_session.commit()
        assert run.status == "pending"

    async def test_a_new_attempt_on_the_job_also_409s(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A job that gains a new attempt while it stays pending fails the commit's attempt check."""
        from app.core.db import async_session

        dataset, job = await _seed_committable_reupload(test_db_session)

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.create_pending_run",
            side_effect=_racing_create_pending_run(
                async_session, attempt_id=uuid.uuid4()
            ),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={},
                headers=admin_auth_header,
            )

        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "job_conflict"
        assert detail["status"] == "pending"
        runs = (
            await test_db_session.execute(
                select(DatasetRefreshRun.id).where(
                    DatasetRefreshRun.dataset_id == dataset.id
                )
            )
        ).all()
        assert runs == []


class TestCommitWinsThenCancel:
    async def test_cancel_after_commit_finalizes_job_and_run_together(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The other serialization: the commit lands first (fence passes,
        run committed), then the cancel finalizes both rows in one
        transaction — no stranded reservation on this side either."""
        dataset, job = await _seed_committable_reupload(test_db_session)

        async def _noop(fn, rollback=None, db=None, job=None):
            pass

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.defer_with_orphan_guard",
            side_effect=_noop,
        ):
            commit_resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={},
                headers=admin_auth_header,
            )
        assert commit_resp.status_code == 202, commit_resp.text

        run_id = (
            await test_db_session.execute(
                select(DatasetRefreshRun.id).where(
                    DatasetRefreshRun.ingest_job_id == job.id
                )
            )
        ).scalar_one()

        cancel_resp = await client.post(
            f"/jobs/{job.id}/cancel", headers=admin_auth_header
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["run_id"] == str(run_id)

        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        run_row = (
            await test_db_session.execute(
                select(DatasetRefreshRun).where(DatasetRefreshRun.id == run_id)
            )
        ).scalar_one()
        assert run_row.status == "cancelled"
        assert run_row.error_code == USER_CANCELLED_ERROR_CODE

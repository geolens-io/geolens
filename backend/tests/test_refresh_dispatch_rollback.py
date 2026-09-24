"""A failed dispatch's rollback never takes back what a worker has claimed."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.platform.jobs.defer_guard import (
    DeferFailed,
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.heartbeat import claim_ingest_job_attempt
from app.platform.jobs.models import IngestJob
from app.platform.refresh import credentials as creds
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    cancel_active_run_for_job,
    claim_run_for_job,
    create_pending_run,
)
from tests.factories import create_dataset, get_user_id
from tests.test_import_token_lease_1676 import (
    _import_harness,
    _reupload_harness,
    _service_import_job,
    _service_reupload_job,
)
from tests.test_service_refresh_1220 import (  # noqa: F401
    _dispatch_harness as _service_harness,
    _service_dataset,
    credential_backend,
)
from tests.test_stac_refresh_1266 import (
    _dispatch_harness as _stac_harness,
    _stac_dataset,
)

pytestmark = pytest.mark.anyio

_CLAIMED = pytest.mark.parametrize(
    "claimed", [True, False], ids=["worker-claimed", "unclaimed"]
)


def _failing_defer(*, claimed: bool, claims_run: bool = True):
    """A defer that raises, after a worker took its task when ``claimed``."""
    import app.core.db as db_module

    async def _defer(**kwargs) -> None:
        if claimed:
            job_id = uuid.UUID(kwargs["job_id"])
            async with db_module.async_session() as worker:
                assert await claim_ingest_job_attempt(
                    worker, job_id, uuid.UUID(kwargs["attempt_id"])
                )
                if claims_run:
                    assert await claim_run_for_job(worker, job_id) is not None
                await worker.commit()
        raise RuntimeError("connection dropped after the insert")

    return _defer


def _cancelling_defer():
    """A defer that raises after a cancel settled its job and run."""
    import app.core.db as db_module

    async def _defer(**kwargs) -> None:
        job_id = uuid.UUID(kwargs["job_id"])
        async with db_module.async_session() as other:
            cancelled = await other.execute(
                update(IngestJob)
                .where(IngestJob.id == job_id, IngestJob.status == "pending")
                .values(status="cancelled", error_message="Cancelled by user")
            )
            assert cancelled.rowcount == 1
            assert await cancel_active_run_for_job(other, job_id) is not None
            await other.commit()
        raise RuntimeError("connection dropped after the insert")

    return _defer


async def _blocked_run(session, dataset_id: uuid.UUID) -> uuid.UUID:
    """A blocked service refresh the next dispatch can accept."""
    now = datetime.now(timezone.utc)
    run = DatasetRefreshRun(
        dataset_id=dataset_id,
        origin_kind="service",
        trigger="api",
        status="blocked",
        started_at=now,
        created_at=now,
        finished_at=now,
        error_code="review_required",
        verification={"review_fingerprint": "fp", "review_reasons": ["empty_result"]},
    )
    session.add(run)
    await session.commit()
    return run.id


async def _consumed_by(session, run_id: uuid.UUID) -> str | None:
    verification = await session.scalar(
        select(DatasetRefreshRun.verification).where(DatasetRefreshRun.id == run_id)
    )
    return (verification or {}).get("acceptance_consumed_by_run_id")


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


async def _fail_the_defer(session, job: IngestJob, *, claimed: bool) -> None:
    """Dispatch through the orphan guard with a defer that raises."""
    job_id, attempt_id = job.id, job.attempt_id
    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue refresh task"
    )
    defer = _failing_defer(claimed=claimed)

    with pytest.raises(DeferFailed):
        await defer_with_orphan_guard(
            lambda: defer(job_id=str(job_id), attempt_id=str(attempt_id)),
            rollback=rollback,
            db=session,
            job=job,
        )


class TestDispatchRollback:
    async def test_a_job_and_run_a_worker_claimed_are_left_to_it(
        self, test_db_session, clean_tables
    ):
        """A defer that raises after a worker claimed both rows changes neither."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, attempt_id = job.id, job.attempt_id

        await _fail_the_defer(test_db_session, job, claimed=True)

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

        await _fail_the_defer(test_db_session, job, claimed=False)

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert (run.status, run.error_code) == ("failed", "dispatch_failed")
        failed = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert failed.status == "failed"
        assert failed.error_message == "Failed to queue refresh task (RuntimeError)"


async def _assert_credential(ref: str | None, *, kept: bool) -> None:
    assert ref
    if kept:
        assert await creds.claim_service_credential(ref)
    else:
        with pytest.raises(creds.CredentialExpiredError):
            await creds.claim_service_credential(ref)


async def _statuses(session, job_id: uuid.UUID) -> tuple[str, str | None]:
    """The job's status and its run's, if it has one."""
    job_status = await session.scalar(
        select(IngestJob.status).where(IngestJob.id == job_id)
    )
    run_status = await session.scalar(
        select(DatasetRefreshRun.status).where(
            DatasetRefreshRun.ingest_job_id == job_id
        )
    )
    return job_status, run_status


class TestDoorCompensation:
    @pytest.mark.parametrize("scenario", ["worker-claimed", "cancelled", "unclaimed"])
    async def test_the_service_refresh_door(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        scenario: str,
    ):
        """The acceptance comes back unless a worker holds it, the credential only when unclaimed."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        blocked_id = await _blocked_run(test_db_session, dataset_id)
        defer = {
            "worker-claimed": _failing_defer(claimed=True),
            "cancelled": _cancelling_defer(),
            "unclaimed": _failing_defer(claimed=False),
        }[scenario]

        async with _service_harness() as task:
            task.defer_async.side_effect = defer
            resp = await client.post(
                f"/datasets/{dataset_id}/refresh",
                json={
                    "token": "tok-" + uuid.uuid4().hex,
                    "accept_blocked_run_id": str(blocked_id),
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        kwargs = task.defer_async.call_args.kwargs
        await _assert_credential(kwargs["credential_ref"], kept=scenario != "unclaimed")
        status = {
            "worker-claimed": "running",
            "cancelled": "cancelled",
            "unclaimed": "failed",
        }[scenario]
        job_id = uuid.UUID(kwargs["job_id"])
        assert await _statuses(test_db_session, job_id) == (status, status)

        released = scenario != "worker-claimed"
        assert (await _consumed_by(test_db_session, blocked_id) is None) is released
        async with _service_harness():
            again = await client.post(
                f"/datasets/{dataset_id}/refresh",
                json={"accept_blocked_run_id": str(blocked_id)},
                headers=admin_auth_header,
            )
        assert again.status_code == (202 if released else 422), again.text

    @_CLAIMED
    async def test_the_stac_refresh_door(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        claimed: bool,
    ):
        """Its staged credential is discarded only when the job was unclaimed."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _stac_dataset(test_db_session, created_by=admin_id)

        async with _stac_harness() as task:
            task.defer_async.side_effect = _failing_defer(claimed=claimed)
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"auth": {"method": "bearer", "token": "tok-" + uuid.uuid4().hex}},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        kwargs = task.defer_async.call_args.kwargs
        await _assert_credential(kwargs["credential_ref"], kept=claimed)
        status = "running" if claimed else "failed"
        job_id = uuid.UUID(kwargs["job_id"])
        assert await _statuses(test_db_session, job_id) == (status, status)

    @_CLAIMED
    async def test_the_reupload_commit_door(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        claimed: bool,
    ):
        """Its staged credential is discarded only when the job was unclaimed."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            feature_count=100,
            source_filename="original.geojson",
            source_url="https://old.example.test/source",
        )
        job = await _service_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )
        job_id = job.id

        async with _reupload_harness(
            defer_side_effect=_failing_defer(claimed=claimed)
        ) as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job_id}/commit",
                json={"token": "tok-" + uuid.uuid4().hex},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        await _assert_credential(
            task.defer_async.call_args.kwargs["credential_ref"], kept=claimed
        )
        status = "running" if claimed else "failed"
        assert await _statuses(test_db_session, job_id) == (status, status)

    @_CLAIMED
    async def test_the_import_door(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        claimed: bool,
    ):
        """Its staged credential is discarded only when the job was unclaimed."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _service_import_job(test_db_session, created_by=admin_id)
        job_id = job.id

        async with _import_harness(
            defer_side_effect=_failing_defer(claimed=claimed, claims_run=False)
        ) as task:
            resp = await client.post(
                f"/ingest/commit/{job_id}",
                json={"title": "Parcels", "token": "tok-" + uuid.uuid4().hex},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        await _assert_credential(
            task.defer_async.call_args.kwargs["credential_ref"], kept=claimed
        )
        status = "running" if claimed else "failed"
        assert await _statuses(test_db_session, job_id) == (status, None)

"""A replacement held for review is not a failed job in the admin job list."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.modules.admin.job_review import review_states
from app.modules.admin.service import AdminService
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _held_job(
    session, *, token: str, accepted_by: str | None = None
) -> IngestJob:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        status="failed",
        error_code="review_required",
        error_message="Review the detected changes before publication.",
        source_filename=f"{token}.gpkg",
        created_by=admin_id,
    )
    session.add(job)
    await session.flush()
    now = datetime.now(timezone.utc)
    verification = {"review_fingerprint": "fp"}
    if accepted_by is not None:
        accepting_id = uuid.uuid4()
        verification["acceptance_consumed_by_run_id"] = str(accepting_id)
        session.add(
            DatasetRefreshRun(
                id=accepting_id,
                dataset_id=dataset.id,
                origin_kind="upload",
                trigger="api",
                status=accepted_by,
                started_at=now,
                created_at=now,
            )
        )
    session.add(
        DatasetRefreshRun(
            dataset_id=dataset.id,
            ingest_job_id=job.id,
            origin_kind="upload",
            trigger="api",
            status="blocked",
            started_at=now,
            created_at=now,
            finished_at=now,
            error_code="review_required",
            verification=verification,
        )
    )
    await session.commit()
    return job


async def _failed_job(session, *, token: str) -> IngestJob:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        status="failed",
        error_code="ogr_failed",
        source_filename=f"{token}.gpkg",
        created_by=admin_id,
    )
    session.add(job)
    await session.commit()
    return job


async def _listed(svc: AdminService, token: str, status: str) -> set[uuid.UUID]:
    rows, total = await svc.list_jobs(search=token, status=status)
    assert total == len(rows)
    return {job.id for job, _username in rows}


async def test_a_held_replacement_is_awaiting_review_not_failed(test_db_session):
    token = f"held{uuid.uuid4().hex[:10]}"
    held = await _held_job(test_db_session, token=f"{token}a", accepted_by=None)
    broken = await _failed_job(test_db_session, token=f"{token}b")
    svc = AdminService(test_db_session)

    assert await _listed(svc, token, "failed") == {broken.id}
    assert await _listed(svc, token, "awaiting_review") == {held.id}
    assert await review_states(test_db_session, [held.id, broken.id]) == {
        held.id: "awaiting"
    }


async def test_an_accepted_replacement_is_neither_failed_nor_awaiting(test_db_session):
    token = f"held{uuid.uuid4().hex[:10]}"
    accepted = await _held_job(test_db_session, token=token, accepted_by="succeeded")
    svc = AdminService(test_db_session)

    assert await _listed(svc, token, "failed") == set()
    assert await _listed(svc, token, "awaiting_review") == set()
    assert await review_states(test_db_session, [accepted.id]) == {
        accepted.id: "resolved"
    }


async def test_an_acceptance_still_in_flight_keeps_the_review_awaiting(test_db_session):
    """A failed or cancelled accepting run gives the acceptance back."""
    token = f"held{uuid.uuid4().hex[:10]}"
    job = await _held_job(test_db_session, token=token, accepted_by="running")
    svc = AdminService(test_db_session)

    assert await _listed(svc, token, "awaiting_review") == {job.id}
    assert await review_states(test_db_session, [job.id]) == {job.id: "awaiting"}


async def test_an_accepting_run_that_was_held_again_resolves_the_review(
    test_db_session,
):
    token = f"held{uuid.uuid4().hex[:10]}"
    job = await _held_job(test_db_session, token=token, accepted_by="blocked")

    assert await review_states(test_db_session, [job.id]) == {job.id: "resolved"}


async def test_a_review_required_job_whose_run_is_gone_stays_a_failure(
    test_db_session,
):
    """Deleting the dataset removes the held run, and with it the claim to be held."""
    token = f"held{uuid.uuid4().hex[:10]}"
    job = await _held_job(test_db_session, token=token, accepted_by=None)
    await test_db_session.execute(
        delete(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job.id)
    )
    await test_db_session.commit()
    svc = AdminService(test_db_session)

    assert await _listed(svc, token, "failed") == {job.id}
    assert await review_states(test_db_session, [job.id]) == {}


async def test_the_job_list_reports_each_held_jobs_review_state(
    test_db_session, client, admin_auth_header
):
    token = f"held{uuid.uuid4().hex[:10]}"
    await _held_job(test_db_session, token=f"{token}a", accepted_by=None)
    await _held_job(test_db_session, token=f"{token}b", accepted_by="succeeded")
    await _failed_job(test_db_session, token=f"{token}c")

    resp = await client.get(
        "/admin/jobs/", params={"search": token}, headers=admin_auth_header
    )

    assert resp.status_code == 200
    states = {
        j["source_filename"][len(token)]: j["review_state"] for j in resp.json()["jobs"]
    }
    assert states == {"a": "awaiting", "b": "resolved", "c": None}

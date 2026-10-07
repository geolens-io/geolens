"""A replacement held for review is not a failed job in the admin job list."""

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.admin.job_review import awaiting_review_job_ids
from app.modules.admin.service import AdminService
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _held_job(session, *, token: str, consumed: bool) -> IngestJob:
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
    if consumed:
        verification["acceptance_consumed_by_run_id"] = str(uuid.uuid4())
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
    held = await _held_job(test_db_session, token=f"{token}a", consumed=False)
    broken = await _failed_job(test_db_session, token=f"{token}b")
    svc = AdminService(test_db_session)

    assert await _listed(svc, token, "failed") == {broken.id}
    assert await _listed(svc, token, "awaiting_review") == {held.id}
    assert await awaiting_review_job_ids(test_db_session, [held.id, broken.id]) == {
        held.id
    }


async def test_an_accepted_replacement_is_neither_failed_nor_awaiting(test_db_session):
    token = f"held{uuid.uuid4().hex[:10]}"
    accepted = await _held_job(test_db_session, token=token, consumed=True)
    svc = AdminService(test_db_session)

    assert await _listed(svc, token, "failed") == set()
    assert await _listed(svc, token, "awaiting_review") == set()
    assert await awaiting_review_job_ids(test_db_session, [accepted.id]) == set()


async def test_the_job_list_reports_each_held_jobs_review_state(
    test_db_session, client, admin_auth_header
):
    token = f"held{uuid.uuid4().hex[:10]}"
    await _held_job(test_db_session, token=f"{token}a", consumed=False)
    await _held_job(test_db_session, token=f"{token}b", consumed=True)
    await _failed_job(test_db_session, token=f"{token}c")

    resp = await client.get(
        "/admin/jobs/", params={"search": token}, headers=admin_auth_header
    )

    assert resp.status_code == 200
    states = {
        j["source_filename"][len(token)]: j["review_state"] for j in resp.json()["jobs"]
    }
    assert states == {"a": "awaiting", "b": "resolved", "c": None}

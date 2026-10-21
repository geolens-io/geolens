"""``POST /jobs/status``: many job statuses in one request."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from tests.conftest import get_auth_header
from tests.factories import create_dataset, create_user

pytestmark = pytest.mark.anyio

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()


async def _job(session, owner_id: str, **fields) -> IngestJob:
    job = IngestJob(
        status=fields.pop("status", "complete"),
        source_filename="batch.geojson",
        created_by=uuid.UUID(owner_id),
        **fields,
    )
    session.add(job)
    await session.commit()
    return job


async def _post(client, headers, ids):
    return await client.post(
        "/jobs/status/", json={"job_ids": [str(i) for i in ids]}, headers=headers
    )


async def test_other_users_job_is_indistinguishable_from_an_unknown_id(
    client, test_db_session, admin_auth_header
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    _, other_id = await create_user(client, admin_auth_header, "editor")
    mine = await _job(test_db_session, owner_id)
    theirs = await _job(test_db_session, other_id)
    unknown = uuid.uuid4()

    resp = await _post(client, owner_headers, [mine.id, theirs.id, unknown, theirs.id])
    assert resp.status_code == 200, resp.text
    entries = resp.json()["jobs"]

    assert [e["id"] for e in entries] == [str(mine.id), str(theirs.id), str(unknown)]
    assert entries[0]["status"] == "complete"
    denied = {k: v for k, v in entries[1].items() if k != "id"}
    missing = {k: v for k, v in entries[2].items() if k != "id"}
    assert denied == missing
    assert denied["status"] == "not_found"


async def test_refused_ids_are_logged_once_per_request(
    client, test_db_session, admin_auth_header, caplog
):
    owner_headers, _ = await create_user(client, admin_auth_header, "editor")
    _, other_id = await create_user(client, admin_auth_header, "editor")
    theirs = [await _job(test_db_session, other_id) for _ in range(2)]

    with caplog.at_level("WARNING"):
        await _post(client, owner_headers, [job.id for job in theirs])

    denials = [r for r in caplog.records if "permission_denied" in r.getMessage()]
    assert len(denials) == 1


async def test_a_stale_job_the_caller_cannot_read_is_left_alone(
    client, test_db_session, admin_auth_header
):
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    other_headers, _ = await create_user(client, admin_auth_header, "editor")
    long_ago = datetime.now(timezone.utc) - timedelta(days=2)
    job = await _job(
        test_db_session,
        owner_id,
        status="running",
        started_at=long_ago,
        heartbeat_at=long_ago,
    )

    job_id = job.id
    entry = (await _post(client, other_headers, [job_id])).json()["jobs"][0]
    assert entry["status"] == "not_found"
    test_db_session.expire_all()
    stored = await test_db_session.scalar(
        select(IngestJob.status).where(IngestJob.id == job_id)
    )
    assert stored == "running"

    # The owner's read settles the same job, so the check above is not vacuous.
    entry = (await _post(client, owner_headers, [job_id])).json()["jobs"][0]
    assert entry["status"] == "failed"


async def test_admin_reads_other_users_jobs(client, test_db_session, admin_auth_header):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    job = await _job(
        test_db_session, owner_id, status="failed", error_code="ogr_failed"
    )

    entry = (await _post(client, admin_auth_header, [job.id])).json()["jobs"][0]
    assert entry["status"] == "failed"
    assert entry["error_code"] == "ogr_failed"


@pytest.mark.parametrize("count", [0, 101])
async def test_id_count_outside_one_to_a_hundred_is_rejected(
    client, admin_auth_header, count
):
    resp = await _post(client, admin_auth_header, [uuid.uuid4() for _ in range(count)])
    assert resp.status_code == 422


async def test_requires_authentication(client):
    resp = await _post(client, {}, [uuid.uuid4()])
    assert resp.status_code == 401


async def test_held_replacement_reports_its_blocked_run(
    client, test_db_session, admin_auth_header
):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(test_db_session, created_by=uuid.UUID(owner_id))
    job = await _job(
        test_db_session,
        owner_id,
        status="failed",
        error_code="review_required",
        dataset_id=dataset.id,
    )
    now = datetime.now(timezone.utc)
    test_db_session.add(
        DatasetRefreshRun(
            dataset_id=dataset.id,
            ingest_job_id=job.id,
            origin_kind="upload",
            trigger="api",
            status="blocked",
            started_at=now,
            created_at=now,
            verification={"review_reasons": ["feature_count_drop"]},
        )
    )
    await test_db_session.commit()

    plain = await _job(test_db_session, owner_id)
    entries = (await _post(client, admin_auth_header, [job.id, plain.id])).json()[
        "jobs"
    ]
    entry = entries[0]
    assert entries[1]["refresh_run"] is None
    assert entry["refresh_run"]["status"] == "blocked"
    assert entry["refresh_run"]["review_reasons"] == ["feature_count_drop"]


async def test_read_only_key_can_poll(client, test_db_session, admin_auth_header):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    minted = await client.post(
        "/auth/api-keys/",
        json={"name": "Batch status", "scope": "read_only"},
        headers=headers,
    )
    assert minted.status_code == 201, minted.text
    try:
        job_id = uuid.uuid4()
        resp = await client.post(
            "/jobs/status/",
            json={"job_ids": [str(job_id)]},
            headers={"X-Api-Key": minted.json()["key"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["jobs"][0]["status"] == "not_found"
    finally:
        await client.delete(f"/auth/api-keys/{minted.json()['id']}", headers=headers)


async def test_the_newest_refresh_run_is_the_one_reported(
    client, test_db_session, admin_auth_header
):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(test_db_session, created_by=uuid.UUID(owner_id))
    job = await _job(test_db_session, owner_id, dataset_id=dataset.id)
    now = datetime.now(timezone.utc)
    for status, age in (("succeeded", timedelta(hours=1)), ("blocked", timedelta())):
        test_db_session.add(
            DatasetRefreshRun(
                dataset_id=dataset.id,
                ingest_job_id=job.id,
                origin_kind="upload",
                trigger="api",
                status=status,
                started_at=now - age,
                created_at=now - age,
            )
        )
        await test_db_session.commit()

    entry = (await _post(client, admin_auth_header, [job.id])).json()["jobs"][0]
    assert entry["refresh_run"]["status"] == "blocked"


async def test_a_readable_entry_has_exactly_the_documented_fields(
    client, test_db_session, admin_auth_header
):
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    job = await _job(test_db_session, owner_id)
    entry = (await _post(client, admin_auth_header, [job.id])).json()["jobs"][0]
    assert set(entry) == {
        "id",
        "status",
        "dataset_id",
        "progress",
        "current_step",
        "error_code",
        "warnings",
        "can_retry",
        "refresh_run",
    }


async def test_storage_probes_for_failed_jobs_run_concurrently(
    client, test_db_session, admin_auth_header, monkeypatch
):
    import asyncio

    from app.platform.jobs import router as jobs_router

    in_flight = 0
    peak = 0

    async def _slow_probe(_job):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return True, None

    monkeypatch.setattr(jobs_router, "staged_input_available", _slow_probe)
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    jobs = [
        await _job(test_db_session, owner_id, status="failed", file_path="/x/in.gpkg")
        for _ in range(4)
    ]

    resp = await _post(client, admin_auth_header, [job.id for job in jobs])
    assert [e["can_retry"] for e in resp.json()["jobs"]] == [True] * 4
    assert 1 < peak <= jobs_router._BATCH_STATUS_CONCURRENCY

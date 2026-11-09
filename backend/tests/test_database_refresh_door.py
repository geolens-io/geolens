"""The database refresh strategy at the door, and the copy's GDAL invocation."""

from __future__ import annotations

import secrets
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.config_database_sources import DatabaseConnection
from app.modules.catalog.datasets.api import router_refresh_database
from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.platform.refresh.verification import DATABASE_SINGLE_READ_POLICY
from app.processing.ingest.tasks_database import refresh_database
from tests.factories import create_dataset

pytestmark = pytest.mark.anyio

HOST = "gis-sql.corp.example"
USERNAME = "geolens_reader"
PASSWORD = secrets.token_hex(16)


def _connection() -> DatabaseConnection:
    return DatabaseConnection.model_validate(
        {
            "engine": "sqlserver",
            "host": HOST,
            "database": "GIS",
            "username": USERNAME,
            "password": PASSWORD,
        }
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})


@pytest.fixture
def deferred(monkeypatch) -> AsyncMock:
    defer = AsyncMock()
    monkeypatch.setattr(router_refresh_database, "defer_async_with_tenant", defer)
    return defer


async def _database_dataset(client, headers, session, *, table: str = "parcels"):
    owner = uuid.UUID((await client.get("/auth/me", headers=headers)).json()["id"])
    dataset = await create_dataset(
        session, created_by=owner, source_format="database", visibility="private"
    )
    restamp(
        dataset,
        SourceBinding.database("gis", schema="dbo", table=table),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await session.commit()
    return dataset


async def test_refresh_admits_a_database_run_and_defers_its_task(
    client: AsyncClient, editor_auth_header, configured, deferred, test_db_session
):
    dataset = await _database_dataset(client, editor_auth_header, test_db_session)

    resp = await client.post(
        f"/datasets/{dataset.id}/refresh", headers=editor_auth_header
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["origin_kind"] == "database"
    run = await test_db_session.get(DatasetRefreshRun, uuid.UUID(resp.json()["run_id"]))
    assert run.origin_kind == "database"
    assert run.verification_policy == DATABASE_SINGLE_READ_POLICY
    job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
    assert job.source_url is None
    assert job.source_filename == "dbo.parcels"
    assert job.user_metadata["refresh"] is True
    assert "database_source" not in job.user_metadata
    assert deferred.await_args.args[0] is refresh_database
    assert set(deferred.await_args.kwargs) == {
        "job_id",
        "attempt_id",
        "dataset_id",
        "user_id",
    }


async def test_refresh_through_a_connection_that_is_gone_names_it(
    client: AsyncClient,
    editor_auth_header,
    configured,
    deferred,
    test_db_session,
    monkeypatch,
):
    dataset = await _database_dataset(client, editor_auth_header, test_db_session)
    monkeypatch.setattr(settings, "database_sources", {})

    resp = await client.post(
        f"/datasets/{dataset.id}/refresh", headers=editor_auth_header
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "origin_unavailable"
    assert "'gis'" in detail["message"]
    deferred.assert_not_awaited()


async def test_a_credential_is_refused(
    client: AsyncClient, editor_auth_header, configured, deferred, test_db_session
):
    dataset = await _database_dataset(client, editor_auth_header, test_db_session)
    resp = await client.post(
        f"/datasets/{dataset.id}/refresh",
        json={"auth": {"type": "bearer", "token": secrets.token_urlsafe(16)}},
        headers=editor_auth_header,
    )
    assert resp.status_code == 422
    deferred.assert_not_awaited()


async def test_a_blocked_database_run_is_accepted_once(
    client: AsyncClient, editor_auth_header, configured, deferred, test_db_session
):
    dataset = await _database_dataset(client, editor_auth_header, test_db_session)
    owner = uuid.UUID(
        (await client.get("/auth/me", headers=editor_auth_header)).json()["id"]
    )
    blocked = await create_pending_run(
        test_db_session,
        dataset_id=dataset.id,
        origin_kind="database",
        trigger="api",
        triggered_by=owner,
        ingest_job_id=None,
        feature_count_before=dataset.feature_count,
    )
    blocked.status = "blocked"
    blocked.verification = {"review_fingerprint": "f" * 64}
    blocked_id = blocked.id
    await test_db_session.commit()

    resp = await client.post(
        f"/datasets/{dataset.id}/refresh",
        json={"accept_blocked_run_id": str(blocked_id)},
        headers=editor_auth_header,
    )

    assert resp.status_code == 202, resp.text
    job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
    assert job.user_metadata["accepted_refresh_fingerprint"] == "f" * 64
    assert job.user_metadata["accepted_refresh_run_id"] == str(blocked_id)
    test_db_session.expire_all()
    consumed = await test_db_session.scalar(
        select(DatasetRefreshRun.verification).where(DatasetRefreshRun.id == blocked_id)
    )
    assert consumed["acceptance_consumed_by_run_id"] == resp.json()["run_id"]


async def test_the_publication_fence_reads_a_database_fingerprint(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    from app.platform.refresh.verification import (
        canonical_database_source_binding_fingerprint,
    )
    from app.processing.ingest.tasks_reupload import (
        RefreshPublicationFenceError,
        _enforce_refresh_publication_fence,
    )

    dataset = await _database_dataset(client, editor_auth_header, test_db_session)
    owner = uuid.UUID(
        (await client.get("/auth/me", headers=editor_auth_header)).json()["id"]
    )
    job = IngestJob(created_by=owner, dataset_id=dataset.id, status="running")
    test_db_session.add(job)
    await test_db_session.flush()
    run = await create_pending_run(
        test_db_session,
        dataset_id=dataset.id,
        origin_kind="database",
        trigger="api",
        triggered_by=owner,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
        source_binding_fingerprint=canonical_database_source_binding_fingerprint(
            dataset.origin_ref
        ),
    )
    await test_db_session.flush()

    await _enforce_refresh_publication_fence(
        test_db_session, job_id=job.id, dataset=dataset, verification={}
    )

    run.source_binding_fingerprint = canonical_database_source_binding_fingerprint(
        {**dataset.origin_ref, "table": "elsewhere"}
    )
    await test_db_session.flush()
    with pytest.raises(RefreshPublicationFenceError) as raised:
        await _enforce_refresh_publication_fence(
            test_db_session, job_id=job.id, dataset=dataset, verification={}
        )
    assert raised.value.code == "source_changed"
    await test_db_session.rollback()

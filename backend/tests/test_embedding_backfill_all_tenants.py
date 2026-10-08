"""An all-tenant embedding backfill queues a run in every registered tenant.

The embedding width and model are deployment-wide, so changing either leaves
every tenant's semantic search to regenerate. A backfill queued from one
tenant's request covers only that tenant; ``?all_tenants=true`` reaches the
rest. Runs for other tenants are system runs (no user), because the database
refuses an ingest job or audit row whose user belongs to another tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import current_tenant_var
from app.modules.admin import backfill_jobs
from app.modules.audit.models import AuditLog
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob

from tests.factories import create_dataset, get_user_id

pytestmark = [pytest.mark.anyio, pytest.mark.xdist_group("tenancy_global_state")]

_URL = "/admin/backfill-embeddings/?all_tenants=true"


@dataclass
class _Tenants:
    caller: str
    with_records: str
    empty: str

    @property
    def all(self) -> tuple[str, str, str]:
        return (self.caller, self.with_records, self.empty)


class _FleetOperatorOnly:
    """Permission extension for a hosted operator holding only manage_tenants.

    ``manage_tenants`` cannot be stored on any role, so a hosted deployment
    grants it out of band; this is that grant, without manage_users.
    """

    async def check_permission(self, _db, _user, capability, **_kwargs) -> bool:
        return capability == "manage_tenants"


def _by_tenant(other_tenants: list[dict]) -> dict[str, tuple[str | None, str]]:
    return {run["tenant_id"]: (run["job_id"], run["status"]) for run in other_tenants}


async def _backfill_jobs_in(session: AsyncSession, tenant_ids) -> list[IngestJob]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(IngestJob).where(
                    IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
                    IngestJob.tenant_id.in_([uuid.UUID(t) for t in tenant_ids]),
                )
            )
        ).scalars()
    )


@pytest.fixture
async def tenants(test_db_session: AsyncSession) -> AsyncIterator[_Tenants]:
    """Three registered tenants: the caller's, one with a record, one empty.

    The admin user moves into the caller's tenant for the test, because the
    database ties a job's and an audit row's tenant to its user's.
    """
    seeded = _Tenants(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()))
    admin_id = await get_user_id(test_db_session, "admin")
    for tenant_id in seeded.all:
        await test_db_session.execute(
            text("INSERT INTO catalog.tenants (id, slug, name) VALUES (:id, :s, :n)"),
            {"id": tenant_id, "s": f"t-{tenant_id[:8]}", "n": "backfill probe"},
        )
    record_ids = []
    for tenant_id in (seeded.caller, seeded.with_records):
        dataset = await create_dataset(
            test_db_session, created_by=admin_id, name=f"probe {tenant_id[:8]}"
        )
        record_ids.append(dataset.record_id)
        await test_db_session.execute(
            text("UPDATE catalog.records SET tenant_id = :t WHERE id = :r"),
            {"t": tenant_id, "r": dataset.record_id},
        )
    await test_db_session.execute(
        text("UPDATE catalog.users SET tenant_id = :t WHERE id = :u"),
        {"t": seeded.caller, "u": admin_id},
    )
    await test_db_session.commit()
    try:
        yield seeded
    finally:
        await test_db_session.rollback()
        tenant_uuids = [uuid.UUID(t) for t in seeded.all]
        await test_db_session.execute(
            delete(AuditLog).where(AuditLog.tenant_id.in_(tenant_uuids))
        )
        await test_db_session.execute(
            delete(IngestJob).where(IngestJob.tenant_id.in_(tenant_uuids))
        )
        await test_db_session.execute(
            text("UPDATE catalog.users SET tenant_id = NULL WHERE id = :u"),
            {"u": admin_id},
        )
        await test_db_session.execute(
            text("UPDATE catalog.records SET tenant_id = NULL WHERE id = ANY(:ids)"),
            {"ids": record_ids},
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.tenants WHERE id = ANY(:ids)"),
            {"ids": tenant_uuids},
        )
        await test_db_session.commit()


@pytest.fixture
def hosted(monkeypatch):
    """Hosted mode below the request middleware, with the production GUC hook.

    Only ``app.core.tenancy.is_multi_tenant`` is patched, so the middleware
    (which bound the original at import) stays out of the way while the route,
    the session hook and the deferral all see a multi-tenant deployment. The
    caller's tenant is bound the way the middleware would bind it.
    """
    import app.core.db as core_db
    from app.core.db.tenant_session import install_tenant_session_hook

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    install_tenant_session_hook(core_db.engine)

    def _bind(tenant_id: str):
        return current_tenant_var.set(tenant_id)

    return _bind


@pytest.fixture
def deferred(monkeypatch) -> AsyncMock:
    """Stop the queue hop at the task, after the tenant id has been threaded in."""
    defer = AsyncMock()
    monkeypatch.setattr(backfill_jobs.run_embedding_backfill, "defer_async", defer)
    return defer


async def test_every_tenant_with_records_gets_its_own_run(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.auth.dependencies.get_permission_extension",
        lambda: _FleetOperatorOnly(),
    )
    token = hosted(tenants.caller)
    try:
        resp = await client.post(_URL, headers=admin_auth_header)
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    jobs = {
        str(job.tenant_id): job
        for job in await _backfill_jobs_in(test_db_session, tenants.all)
    }
    # The empty tenant gets a run too: finding out that it has no records would
    # cost a scan of the shared table per tenant.
    assert set(jobs) == set(tenants.all)

    caller_job = jobs[tenants.caller]
    assert body["job_id"] == str(caller_job.id)
    assert caller_job.created_by == await get_user_id(test_db_session, "admin")

    other_jobs = [jobs[tenants.with_records], jobs[tenants.empty]]
    assert all(job.created_by is None for job in other_jobs)
    assert _by_tenant(body["other_tenants"]) == {
        str(job.tenant_id): (str(job.id), "pending") for job in other_jobs
    }
    operation_ids = {
        job.user_metadata[EMBEDDING_BACKFILL_METADATA_KEY]["operation_id"]
        for job in jobs.values()
    }
    assert len(operation_ids) == 1

    queued = {
        call.kwargs["tenant_id"]: call.kwargs["job_id"]
        for call in deferred.await_args_list
    }
    assert queued == {tenant_id: str(job.id) for tenant_id, job in jobs.items()}


async def test_a_tenant_with_a_run_in_flight_is_reported_and_the_rest_proceed(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.auth.dependencies.get_permission_extension",
        lambda: _FleetOperatorOnly(),
    )
    token = hosted(tenants.with_records)
    try:
        test_db_session.add(
            IngestJob(
                source_filename="embedding-backfill",
                file_path="",
                status="running",
                user_metadata={
                    EMBEDDING_BACKFILL_METADATA_KEY: {
                        "force": False,
                        "operation_id": "seed",
                    }
                },
            )
        )
        await test_db_session.commit()
    finally:
        current_tenant_var.reset(token)
    in_flight = await _backfill_jobs_in(test_db_session, [tenants.with_records])
    assert len(in_flight) == 1

    token = hosted(tenants.caller)
    try:
        resp = await client.post(_URL, headers=admin_auth_header)
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 200, resp.text
    others = _by_tenant(resp.json()["other_tenants"])
    assert others[tenants.with_records] == (None, "already_running")
    assert others[tenants.empty][1] == "pending"
    assert len(await _backfill_jobs_in(test_db_session, [tenants.with_records])) == 1
    assert len(await _backfill_jobs_in(test_db_session, [tenants.caller])) == 1


async def test_a_run_in_flight_in_the_callers_tenant_does_not_stop_the_fleet(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.auth.dependencies.get_permission_extension",
        lambda: _FleetOperatorOnly(),
    )
    token = hosted(tenants.caller)
    try:
        in_flight = IngestJob(
            source_filename="embedding-backfill",
            file_path="",
            status="running",
            user_metadata={
                EMBEDDING_BACKFILL_METADATA_KEY: {
                    "force": False,
                    "operation_id": "seed",
                }
            },
        )
        test_db_session.add(in_flight)
        await test_db_session.commit()
        resp = await client.post(_URL, headers=admin_auth_header)
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == str(in_flight.id)
    assert body["status"] == "already_running"
    other_jobs = await _backfill_jobs_in(
        test_db_session, [tenants.with_records, tenants.empty]
    )
    assert _by_tenant(body["other_tenants"]) == {
        str(job.tenant_id): (str(job.id), "pending") for job in other_jobs
    }
    assert len(other_jobs) == 2
    assert len(await _backfill_jobs_in(test_db_session, [tenants.caller])) == 1


async def test_an_in_flight_run_the_caller_cannot_read_is_not_disclosed(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
    monkeypatch,
):
    for target in (
        "app.modules.auth.dependencies.get_permission_extension",
        "app.platform.jobs.router.get_permission_extension",
    ):
        monkeypatch.setattr(target, lambda: _FleetOperatorOnly())
    token = hosted(tenants.caller)
    try:
        test_db_session.add(
            IngestJob(
                source_filename="embedding-backfill",
                file_path="",
                status="running",
                user_metadata={
                    EMBEDDING_BACKFILL_METADATA_KEY: {
                        "force": False,
                        "operation_id": "seed",
                    }
                },
            )
        )
        await test_db_session.commit()
        resp = await client.post(_URL, headers=admin_auth_header)
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "already_running"
    assert body["job_id"] is None
    assert len(body["other_tenants"]) == 2


async def test_a_caller_run_that_ends_mid_request_does_not_stop_the_fleet(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.auth.dependencies.get_permission_extension",
        lambda: _FleetOperatorOnly(),
    )
    real_find = backfill_jobs.find_active_embedding_backfill
    calls = 0

    async def _ends_after_refusing(session):
        nonlocal calls
        calls += 1
        return await real_find(session) if calls == 1 else None

    monkeypatch.setattr(
        backfill_jobs, "find_active_embedding_backfill", _ends_after_refusing
    )
    token = hosted(tenants.caller)
    try:
        test_db_session.add(
            IngestJob(
                source_filename="embedding-backfill",
                file_path="",
                status="running",
                user_metadata={
                    EMBEDDING_BACKFILL_METADATA_KEY: {
                        "force": False,
                        "operation_id": "seed",
                    }
                },
            )
        )
        await test_db_session.commit()
        resp = await client.post(_URL, headers=admin_auth_header)
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["job_id"]) == ("already_running", None)
    assert {run["status"] for run in body["other_tenants"]} == {"pending"}
    assert len(body["other_tenants"]) == 2


async def test_all_tenants_needs_the_fleet_permission(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
):
    token = hosted(tenants.caller)
    try:
        resp = await client.post(_URL, headers=admin_auth_header)
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 403, resp.text
    assert await _backfill_jobs_in(test_db_session, tenants.all) == []
    deferred.assert_not_awaited()


async def test_a_tenant_scoped_backfill_still_needs_manage_users(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tenants: _Tenants,
    hosted,
    deferred: AsyncMock,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.auth.dependencies.get_permission_extension",
        lambda: _FleetOperatorOnly(),
    )
    token = hosted(tenants.caller)
    try:
        resp = await client.post(
            "/admin/backfill-embeddings/", headers=admin_auth_header
        )
    finally:
        current_tenant_var.reset(token)

    assert resp.status_code == 403, resp.text
    assert await _backfill_jobs_in(test_db_session, tenants.all) == []
    deferred.assert_not_awaited()


async def test_single_tenant_still_queues_one_run(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    deferred: AsyncMock,
):
    seeded_tenant = str(uuid.uuid4())
    await test_db_session.execute(
        text("INSERT INTO catalog.tenants (id, slug, name) VALUES (:id, :s, :n)"),
        {"id": seeded_tenant, "s": f"t-{seeded_tenant[:8]}", "n": "ignored"},
    )
    await test_db_session.commit()
    try:
        resp = await client.post(_URL, headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["other_tenants"] == []
        deferred.assert_awaited_once()
        assert "tenant_id" not in deferred.await_args.kwargs
        assert deferred.await_args.kwargs["job_id"] == body["job_id"]
    finally:
        # Free the instance-wide slot for the next test on this worker.
        await test_db_session.execute(
            update(IngestJob)
            .where(
                IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
                IngestJob.status.in_(("pending", "running")),
            )
            .values(status="failed")
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.tenants WHERE id = :id"),
            {"id": seeded_tenant},
        )
        await test_db_session.commit()

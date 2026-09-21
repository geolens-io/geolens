"""Claim and recovery contracts for core-neutral scheduled refresh runs."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import anyio
import pytest
from sqlalchemy import select

from app.platform.jobs.models import IngestJob
from app.platform.jobs.heartbeat import claim_ingest_job_attempt
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    claim_admitted_run_for_job,
    create_pending_run,
    expire_unclaimed_admitted_runs,
)
from app.platform.refresh.execution import (
    RefreshAdmissionRequest,
    execute_admitted_refresh,
    prepare_admitted_refresh,
    register_scheduled_refresh_task,
    reject_admitted_refresh,
)
from app.processing.ingest.tasks_reupload import require_scheduled_execution_claim
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _scheduled_run(session) -> tuple[DatasetRefreshRun, IngestJob]:
    actor_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=actor_id)
    job = IngestJob(
        dataset_id=dataset.id,
        created_by=actor_id,
        status="pending",
        source_filename="scheduled.geojson",
        user_metadata={"refresh": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.flush()
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="scheduled",
        triggered_by=actor_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
        scheduled_for=datetime.now(timezone.utc),
        occurrence_key=f"occurrence:{uuid.uuid4()}",
        execution_key=uuid.uuid4(),
        source_binding_fingerprint="a" * 64,
        verification_policy="arcgis_id_set_v1",
    )
    await session.commit()
    return run, job


async def test_scheduled_claim_is_exactly_once(test_db_session) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None

    first = await claim_admitted_run_for_job(
        test_db_session, job.id, execution_key=run.execution_key
    )
    await test_db_session.commit()
    second = await claim_admitted_run_for_job(
        test_db_session, job.id, execution_key=run.execution_key
    )

    assert first == run.id
    assert second is None
    persisted = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.id == run.id)
    )
    assert persisted is not None
    assert persisted.status == "running"


async def test_expired_unclaimed_scheduled_run_releases_active_reservation(
    test_db_session,
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    job_id = job.id
    run.claim_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    await test_db_session.commit()

    expired = await expire_unclaimed_admitted_runs(test_db_session)
    await test_db_session.commit()

    run_id = run.id
    assert expired == [run_id]
    test_db_session.expire_all()
    persisted = await test_db_session.get(DatasetRefreshRun, run_id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.error_code == "scheduled_claim_expired"
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_job is not None
    assert persisted_job.status == "failed"
    assert persisted_job.completed_at is not None

    assert (
        await claim_admitted_run_for_job(
            test_db_session, job_id, execution_key=run.execution_key
        )
        is None
    )


async def test_claimed_run_can_finish_after_its_queue_claim_deadline(
    test_db_session,
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    assert job.attempt_id is not None
    assert (
        await claim_admitted_run_for_job(
            test_db_session, job.id, execution_key=run.execution_key
        )
        == run.id
    )
    run.claim_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    await test_db_session.commit()
    called = False

    @require_scheduled_execution_claim
    async def execute(**_kwargs) -> None:
        nonlocal called
        called = True

    await execute(
        job_id=str(job.id),
        attempt_id=str(job.attempt_id),
        scheduled_execution_key=str(run.execution_key),
    )

    assert called


async def test_keyed_execution_has_a_wall_clock_timeout(
    test_db_session, monkeypatch
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    assert job.attempt_id is not None
    attempt_id = job.attempt_id
    await claim_admitted_run_for_job(
        test_db_session, job.id, execution_key=run.execution_key
    )
    assert await claim_ingest_job_attempt(test_db_session, job.id, attempt_id)
    await test_db_session.commit()
    monkeypatch.setattr(
        "app.processing.ingest.tasks_reupload._KEYED_REFRESH_EXECUTION_TIMEOUT_SECONDS",
        0.01,
    )
    published = False

    @require_scheduled_execution_claim
    async def execute(**_kwargs) -> None:
        nonlocal published
        await anyio.sleep(1)
        published = True

    with pytest.raises(TimeoutError):
        await execute(
            job_id=str(job.id),
            attempt_id=str(attempt_id),
            scheduled_execution_key=str(run.execution_key),
        )

    run_id = run.id
    job_id = job.id
    test_db_session.expire_all()
    persisted = await test_db_session.get(DatasetRefreshRun, run_id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.error_code == "scheduled_execution_timeout"
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_job is not None
    assert persisted_job.status == "failed"
    assert persisted_job.completed_at is not None
    assert published is False


async def test_keyed_timeout_does_not_settle_a_reclaimed_job_attempt(
    test_db_session, monkeypatch
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    assert job.attempt_id is not None
    assert await claim_admitted_run_for_job(
        test_db_session, job.id, execution_key=run.execution_key
    )
    assert await claim_ingest_job_attempt(test_db_session, job.id, job.attempt_id)
    await test_db_session.commit()
    monkeypatch.setattr(
        "app.processing.ingest.tasks_reupload._KEYED_REFRESH_EXECUTION_TIMEOUT_SECONDS",
        0.01,
    )

    @require_scheduled_execution_claim
    async def execute(**_kwargs) -> None:
        await anyio.sleep(1)

    with pytest.raises(TimeoutError):
        await execute(
            job_id=str(job.id),
            attempt_id=str(uuid.uuid4()),
            scheduled_execution_key=str(run.execution_key),
        )

    run_id, job_id = run.id, job.id
    test_db_session.expire_all()
    persisted_run = await test_db_session.get(DatasetRefreshRun, run_id)
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_run is not None
    assert persisted_run.status == "running"
    assert persisted_job is not None
    assert persisted_job.status == "running"


async def test_worker_expiry_sweep_commits_expired_ids() -> None:
    from app.platform.jobs.worker import _expire_unclaimed_scheduled_refreshes_safely

    run_id = uuid.uuid4()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.core.db.async_session", return_value=session),
        patch(
            "app.platform.refresh.service.expire_unclaimed_admitted_runs",
            new=AsyncMock(return_value=[run_id]),
        ) as expire,
    ):
        await _expire_unclaimed_scheduled_refreshes_safely()

    expire.assert_awaited_once_with(session)
    session.commit.assert_awaited_once()


async def test_manual_keyed_admission_claims_once_and_expires(test_db_session) -> None:
    actor_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=actor_id)
    job = IngestJob(
        dataset_id=dataset.id,
        created_by=actor_id,
        status="pending",
        source_filename="manual.geojson",
        user_metadata={"refresh": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.flush()
    run = await create_pending_run(
        test_db_session,
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="manual",
        triggered_by=actor_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
        occurrence_key=f"occurrence:{uuid.uuid4()}",
        execution_key=uuid.uuid4(),
        source_binding_fingerprint="b" * 64,
        verification_policy="arcgis_id_set_v1",
    )
    await test_db_session.commit()

    assert run.claim_deadline is not None
    assert (
        await claim_admitted_run_for_job(
            test_db_session, job.id, execution_key=run.execution_key
        )
        == run.id
    )
    await test_db_session.commit()
    assert (
        await claim_admitted_run_for_job(
            test_db_session, job.id, execution_key=run.execution_key
        )
        is None
    )


async def test_preclaim_rejection_terminalizes_the_pending_job_and_run(
    test_db_session,
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    run_id = run.id
    job_id = job.id

    rejected = await reject_admitted_refresh(
        test_db_session,
        job.id,
        str(run.execution_key),
        "authorization_changed",
    )
    await test_db_session.commit()

    assert rejected == run_id
    test_db_session.expire_all()
    persisted_run = await test_db_session.get(DatasetRefreshRun, run_id)
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_run is not None
    assert persisted_job is not None
    assert persisted_run.status == "failed"
    assert persisted_run.error_code == "authorization_changed"
    assert persisted_job.status == "failed"
    assert persisted_job.completed_at is not None


async def test_preclaim_rejection_leaves_claimed_work_untouched(
    test_db_session,
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    run_id = run.id
    job_id = job.id
    assert (
        await claim_admitted_run_for_job(
            test_db_session, job.id, execution_key=run.execution_key
        )
        == run.id
    )
    await test_db_session.commit()

    assert (
        await reject_admitted_refresh(
            test_db_session,
            job.id,
            str(run.execution_key),
            "authorization_changed",
        )
        is None
    )
    await test_db_session.commit()
    test_db_session.expire_all()
    persisted_run = await test_db_session.get(DatasetRefreshRun, run_id)
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_run is not None
    assert persisted_job is not None
    assert persisted_run.status == "running"
    assert persisted_job.status == "pending"


async def test_credential_resolution_failure_terminalizes_claimed_job_and_run(
    test_db_session,
) -> None:
    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    run.credential_reference = "credential-1"
    await test_db_session.commit()
    run_id = run.id
    job_id = job.id

    @asynccontextmanager
    async def test_session_factory():
        yield test_db_session

    async def credential_resolver(_reference: str, _version: str | None) -> str:
        raise RuntimeError("credential provider unavailable")

    with (
        patch("app.core.db.async_session", test_session_factory),
        patch("app.platform.extensions.get_catalog_port") as catalog_port,
    ):
        result = await execute_admitted_refresh(
            job_id,
            str(run.execution_key),
            credential_resolver=credential_resolver,
        )

    assert result.status == "rejected"
    assert result.run_id == run_id
    catalog_port.assert_not_called()
    test_db_session.expire_all()
    persisted_run = await test_db_session.get(DatasetRefreshRun, run_id)
    persisted_job = await test_db_session.get(IngestJob, job_id)
    assert persisted_run is not None
    assert persisted_run.status == "failed"
    assert persisted_run.error_code == "scheduled_credential_unavailable"
    assert (
        persisted_run.error_message
        == "Scheduled refresh credential resolution failed (RuntimeError)"
    )
    assert persisted_job is not None
    assert persisted_job.status == "failed"
    assert (
        persisted_job.error_message
        == "Scheduled refresh credential resolution failed (RuntimeError)"
    )
    assert persisted_job.completed_at is not None


@pytest.mark.parametrize(
    "actor",
    [None, SimpleNamespace(), SimpleNamespace(id="not-a-uuid")],
    ids=["missing", "missing-id", "invalid-id"],
)
async def test_admission_rejects_actorless_or_invalid_callers_before_writes(
    actor,
) -> None:
    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    request = RefreshAdmissionRequest(
        source_binding_fingerprint="a" * 64,
        local_edit_baseline=None,
        origin_kind="service",
    )

    with pytest.raises(ValueError, match="actor must expose a UUID id"):
        await prepare_admitted_refresh(
            session,  # type: ignore[arg-type]
            dataset=SimpleNamespace(id=uuid.uuid4()),
            actor=actor,
            request=request,
            trigger="manual",
        )

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_admitted_execution_forwards_tenant_to_the_real_task_wrapper(
    test_db_session, monkeypatch
) -> None:
    """The verified task's tenant wrapper receives the admitted run context."""
    import app.core.tenancy as tenancy
    from app.core.db.tenant_session import (
        current_tenant_var,
        tenant_job_context,
        tenant_task,
    )

    run, job = await _scheduled_run(test_db_session)
    assert run.execution_key is not None
    tenant_id = uuid.uuid4()
    run.tenant_id = tenant_id
    await test_db_session.commit()
    seen_tenants: list[str | None] = []

    @tenant_task
    async def verified_task(**_kwargs) -> None:
        seen_tenants.append(current_tenant_var.get())

    monkeypatch.setattr(tenancy, "is_multi_tenant", lambda: True)
    with pytest.raises(RuntimeError, match="missing tenant context"):
        await verified_task()

    task = SimpleNamespace(func=verified_task)
    with patch(
        "app.platform.extensions.get_catalog_port",
        return_value=SimpleNamespace(verified_refresh_service_task=lambda: task),
    ):
        with tenant_job_context(str(tenant_id)):
            result = await execute_admitted_refresh(job.id, str(run.execution_key))

    assert result.status == "rejected"
    assert seen_tenants == [str(tenant_id)]


async def test_core_registers_only_the_versioned_scheduled_task() -> None:
    registered: dict[str, object] = {}

    class TaskApp:
        def task(self, **kwargs):
            registered.update(kwargs)

            def decorate(fn):
                return fn

            return decorate

    executed: list[tuple[str, str, str | None]] = []

    async def execute(job_id: str, execution_key: str, tenant_id: str | None) -> None:
        executed.append((job_id, execution_key, tenant_id))

    task = register_scheduled_refresh_task(TaskApp(), execute=execute)
    await task("job-1", "key-1", "tenant-1")  # type: ignore[operator]

    assert registered == {
        "queue": "ingest",
        "retry": 0,
        "name": "scheduled-refresh-v1",
    }
    assert executed == [("job-1", "key-1", "tenant-1")]

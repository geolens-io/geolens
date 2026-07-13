"""Hosted stale-job recovery always enters an explicit tenant scope."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.db.tenant_session import current_tenant_var

pytestmark = pytest.mark.xdist_group("tenancy_global_state")


def _session_context(*, tenant_ids: list[uuid.UUID] | None = None) -> AsyncMock:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    if tenant_ids is not None:
        result = MagicMock()
        result.scalars.return_value = tenant_ids
        session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_api_sweeper_scopes_each_tenant_and_continues_after_failure():
    from app.api import main as main_module

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    registry_session = _session_context(tenant_ids=[tenant_a, tenant_b])
    tenant_a_session = _session_context()
    tenant_b_session = _session_context()
    session_factory = MagicMock(
        side_effect=[registry_session, tenant_a_session, tenant_b_session]
    )
    observed: list[tuple[str | None, object]] = []

    async def fake_fail_stale_jobs(session):
        tenant_id = current_tenant_var.get()
        observed.append((tenant_id, session))
        assert tenant_id is not None, "an IngestJob sweep ran without tenant scope"
        if tenant_id == str(tenant_a):
            raise RuntimeError("tenant A database fault")
        return 2, 3

    with (
        patch.object(main_module, "is_multi_tenant", return_value=True),
        patch("app.core.tenancy.is_multi_tenant", return_value=True),
        patch.object(main_module, "async_session", session_factory),
        patch(
            "app.platform.jobs.router.fail_stale_jobs",
            side_effect=fake_fail_stale_jobs,
        ),
        patch.object(main_module, "logger") as logger,
    ):
        assert await main_module.sweep_stale_jobs_once() == (2, 3)

    assert observed == [
        (str(tenant_a), tenant_a_session),
        (str(tenant_b), tenant_b_session),
    ]
    assert logger.warning.call_count == 1
    assert current_tenant_var.get() is None


@pytest.mark.asyncio
async def test_api_sweeper_preserves_single_tenant_one_shot():
    from app.api import main as main_module

    session = _session_context()
    session_factory = MagicMock(return_value=session)
    fail_stale_jobs = AsyncMock(return_value=(4, 5))

    with (
        patch.object(main_module, "is_multi_tenant", return_value=False),
        patch.object(main_module, "async_session", session_factory),
        patch("app.platform.jobs.router.fail_stale_jobs", fail_stale_jobs),
    ):
        assert await main_module.sweep_stale_jobs_once() == (4, 5)

    session_factory.assert_called_once_with()
    fail_stale_jobs.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_worker_recovery_scopes_each_tenant_and_continues_after_failure():
    from app.platform.jobs import worker as worker_module

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    observed: list[str | None] = []

    async def fake_recover_current_scope():
        tenant_id = current_tenant_var.get()
        observed.append(tenant_id)
        assert tenant_id is not None, "worker queried IngestJob without tenant scope"
        if tenant_id == tenant_a:
            raise RuntimeError("tenant A database fault")

    with (
        patch("app.core.tenancy.is_multi_tenant", return_value=True),
        patch.object(
            worker_module,
            "_registered_tenant_ids_for_recovery",
            AsyncMock(return_value=[tenant_a, tenant_b]),
        ),
        patch.object(
            worker_module,
            "_recover_stale_jobs_for_current_scope",
            side_effect=fake_recover_current_scope,
        ),
        patch.object(worker_module, "log") as logger,
    ):
        await worker_module.recover_stale_jobs()

    assert observed == [tenant_a, tenant_b]
    assert logger.warning.call_count == 1
    assert current_tenant_var.get() is None


@pytest.mark.asyncio
async def test_worker_recovery_preserves_single_tenant_one_shot():
    from app.platform.jobs import worker as worker_module

    recover_current_scope = AsyncMock()
    tenant_registry = AsyncMock()
    with (
        patch("app.core.tenancy.is_multi_tenant", return_value=False),
        patch.object(
            worker_module,
            "_recover_stale_jobs_for_current_scope",
            recover_current_scope,
        ),
        patch.object(
            worker_module,
            "_registered_tenant_ids_for_recovery",
            tenant_registry,
        ),
    ):
        await worker_module.recover_stale_jobs()

    recover_current_scope.assert_awaited_once_with()
    tenant_registry.assert_not_awaited()

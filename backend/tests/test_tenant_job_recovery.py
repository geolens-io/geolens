"""Hosted stale-job recovery always enters an explicit tenant scope."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

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
    # fix(#1746 codex r1): the fleet-level token purge opens the first session
    # of the pass, before any tenant scope is entered.
    session_factory = MagicMock(
        side_effect=[
            _session_context(),
            registry_session,
            tenant_a_session,
            tenant_b_session,
        ]
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
        # fix(#909): sweep_stale_jobs_once late-binds from app.core.db
        patch("app.core.db.async_session", session_factory),
        patch(
            "app.platform.jobs.router.fail_stale_jobs",
            side_effect=fake_fail_stale_jobs,
        ),
        # fix(#1746 codex r1): stubbed so this test keeps stating only the
        # per-tenant scoping it is about — the purge writes to a table that
        # has nothing to do with tenant scope, and has its own tests below.
        patch("app.platform.jobs.sweep.purge_terminal_job_tokens", AsyncMock()),
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
async def test_api_sweeper_aggregates_detailed_tenant_outcomes():
    from app.api import main as main_module
    from app.platform.jobs.router import StaleCleanupOutcome

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    registry_session = _session_context(tenant_ids=[tenant_a, tenant_b])
    tenant_a_session = _session_context()
    tenant_b_session = _session_context()
    # fix(#1746 codex r1): the purge's session comes first — see the test above.
    session_factory = MagicMock(
        side_effect=[
            _session_context(),
            registry_session,
            tenant_a_session,
            tenant_b_session,
        ]
    )
    outcomes = [
        StaleCleanupOutcome(
            pending_failed=1,
            running_failed=2,
            vrt_assets_recovered=3,
            vrt_generations_failed=4,
            terminal_jobs_purged=5,
            staged_paths_considered=6,
            local_files_reaped=7,
            storage_objects_reaped=8,
            staged_paths_skipped=9,
            staged_cleanup_failures=10,
        ),
        StaleCleanupOutcome(
            pending_failed=10,
            running_failed=20,
            vrt_assets_recovered=30,
            vrt_generations_failed=40,
            terminal_jobs_purged=50,
            staged_paths_considered=60,
            local_files_reaped=70,
            storage_objects_reaped=80,
            staged_paths_skipped=90,
            staged_cleanup_failures=100,
        ),
    ]
    cleanup = AsyncMock(side_effect=outcomes)

    with (
        patch.object(main_module, "is_multi_tenant", return_value=True),
        # fix(#909): sweep_stale_jobs_once late-binds from app.core.db
        patch("app.core.db.async_session", session_factory),
        patch("app.platform.jobs.router.fail_stale_jobs", cleanup),
        # fix(#1746 codex r1): see the note in the test above.
        patch("app.platform.jobs.sweep.purge_terminal_job_tokens", AsyncMock()),
    ):
        details = await main_module.sweep_stale_jobs_once(detailed=True)

    assert isinstance(details, dict)
    assert details == {
        key: outcomes[0].as_dict()[key] + outcomes[1].as_dict()[key]
        for key in outcomes[0].as_dict()
    }
    assert [awaited.kwargs for awaited in cleanup.await_args_list] == [
        {"detailed": True},
        {"detailed": True},
    ]
    assert current_tenant_var.get() is None


@pytest.mark.asyncio
async def test_api_sweeper_preserves_single_tenant_one_shot():
    from app.api import main as main_module

    session = _session_context()
    # fix(#1746 codex r1): two sessions per pass now — the fleet-level token
    # purge's, then the sweep's. The one-shot property this test is about is
    # `fail_stale_jobs` being awaited exactly once, asserted below.
    session_factory = MagicMock(side_effect=[_session_context(), session])
    fail_stale_jobs = AsyncMock(return_value=(4, 5))

    with (
        patch.object(main_module, "is_multi_tenant", return_value=False),
        # fix(#909): sweep_stale_jobs_once late-binds from app.core.db
        patch("app.core.db.async_session", session_factory),
        patch("app.platform.jobs.router.fail_stale_jobs", fail_stale_jobs),
        # fix(#1746 codex r1): see the note two tests above.
        patch("app.platform.jobs.sweep.purge_terminal_job_tokens", AsyncMock()),
    ):
        assert await main_module.sweep_stale_jobs_once() == (4, 5)

    assert session_factory.call_args_list == [call(), call()]
    fail_stale_jobs.assert_awaited_once_with(session)


class TestTheTokenPurgeBelongsToThePassNotTheTenant:
    """fix(#1746 codex r1): `catalog.procrastinate_jobs` has no tenant column.

    The purge started life inside ``fail_stale_jobs``, which hosted mode calls
    once per tenant — so one unscoped, unindexed UPDATE ran tenants-many times
    per pass, per API process, every cadence. It belongs to the pass.
    """

    @pytest.mark.asyncio
    async def test_three_tenants_still_purge_exactly_once(self):
        from app.api import main as main_module

        tenants = [uuid.uuid4() for _ in range(3)]
        registry_session = _session_context(tenant_ids=tenants)
        purge_session = _session_context()
        session_factory = MagicMock(
            side_effect=[
                purge_session,
                registry_session,
                *[_session_context() for _ in tenants],
            ]
        )
        purge = AsyncMock()

        with (
            patch.object(main_module, "is_multi_tenant", return_value=True),
            patch("app.core.tenancy.is_multi_tenant", return_value=True),
            patch("app.core.db.async_session", session_factory),
            patch(
                "app.platform.jobs.router.fail_stale_jobs",
                AsyncMock(return_value=(0, 0)),
            ),
            patch("app.platform.jobs.sweep.purge_terminal_job_tokens", purge),
        ):
            await main_module.sweep_stale_jobs_once()

        purge.assert_awaited_once_with(purge_session)
        assert current_tenant_var.get() is None

    @pytest.mark.asyncio
    async def test_single_tenant_purges_once_too(self):
        """The property is per `sweep_stale_jobs_once` call, in both modes."""
        from app.api import main as main_module

        purge_session = _session_context()
        sweep_session = _session_context()
        session_factory = MagicMock(side_effect=[purge_session, sweep_session])
        purge = AsyncMock()

        with (
            patch.object(main_module, "is_multi_tenant", return_value=False),
            patch("app.core.db.async_session", session_factory),
            patch(
                "app.platform.jobs.router.fail_stale_jobs",
                AsyncMock(return_value=(0, 0)),
            ),
            patch("app.platform.jobs.sweep.purge_terminal_job_tokens", purge),
        ):
            await main_module.sweep_stale_jobs_once()

        purge.assert_awaited_once_with(purge_session)

    @pytest.mark.asyncio
    async def test_a_failing_purge_does_not_cost_the_sweep(self):
        """Best-effort, like the per-tenant branch: warn and carry on."""
        from app.api import main as main_module

        session_factory = MagicMock(
            side_effect=[_session_context(), _session_context()]
        )
        fail_stale_jobs = AsyncMock(return_value=(4, 5))

        with (
            patch.object(main_module, "is_multi_tenant", return_value=False),
            patch("app.core.db.async_session", session_factory),
            patch("app.platform.jobs.router.fail_stale_jobs", fail_stale_jobs),
            patch(
                "app.platform.jobs.sweep.purge_terminal_job_tokens",
                AsyncMock(side_effect=RuntimeError("queue table unreachable")),
            ),
            patch.object(main_module, "logger") as logger,
        ):
            assert await main_module.sweep_stale_jobs_once() == (4, 5)

        assert logger.warning.call_count == 1
        fail_stale_jobs.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_cleanup_uses_fleet_sweeper_in_multi_tenant_mode():
    import app.modules.audit.service as audit_service
    from app.platform.jobs import router as jobs_router

    fleet_sweep = AsyncMock(
        return_value={
            "pending_failed": 4,
            "running_failed": 5,
            "total_cleaned": 9,
            "vrt_assets_recovered": 0,
            "vrt_generations_failed": 0,
            "terminal_jobs_purged": 0,
            "staged_paths_considered": 0,
            "local_files_reaped": 0,
            "storage_objects_reaped": 0,
            "staged_paths_skipped": 0,
            "staged_cleanup_failures": 0,
            "total_affected": 9,
        }
    )
    direct_sweep = AsyncMock()
    audit_emit = AsyncMock()
    audit_emit_durable = AsyncMock()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    user = SimpleNamespace(id=uuid.uuid4())

    with (
        patch("app.core.tenancy.is_multi_tenant", return_value=True),
        patch("app.api.main.sweep_stale_jobs_once", fleet_sweep),
        patch.object(jobs_router, "fail_stale_jobs", direct_sweep),
        patch.object(audit_service, "audit_emit", audit_emit),
        patch.object(audit_service, "audit_emit_durable", audit_emit_durable),
    ):
        response = await jobs_router.cleanup_stale_jobs(
            request=request,
            user=user,
            db=AsyncMock(),
        )

    fleet_sweep.assert_awaited_once_with(detailed=True)
    direct_sweep.assert_not_awaited()
    assert response.pending_failed == 4
    assert response.running_failed == 5
    assert response.total_cleaned == 9


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

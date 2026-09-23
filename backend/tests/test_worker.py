"""Tests for the standalone Procrastinate worker module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Worker health app tests
# ---------------------------------------------------------------------------


@pytest.fixture
def health_app():
    from app.observability.health.worker import app

    return app


@pytest.mark.asyncio
async def test_health_live_returns_ok(health_app):
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready_returns_200_when_db_reachable(health_app):
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.execute = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    with patch("app.observability.health.worker._get_engine", return_value=mock_engine):
        transport = ASGITransport(app=health_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"


@pytest.mark.asyncio
async def test_health_ready_returns_503_when_db_unreachable(health_app):
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("connection refused")

    with patch("app.observability.health.worker._get_engine", return_value=mock_engine):
        transport = ASGITransport(app=health_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert "error" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_output(health_app):
    with patch(
        "app.observability.health.worker.generate_latest",
        return_value=b"# HELP fake_metric\n",
    ):
        with patch(
            "app.observability.health.worker.CONTENT_TYPE_LATEST",
            "text/plain; version=0.0.4",
        ):
            transport = ASGITransport(app=health_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/metrics")

    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Worker module importability test
# ---------------------------------------------------------------------------


def test_worker_module_is_importable():
    """worker.py must be importable without side effects (no auto-run)."""
    import app.worker as worker_mod

    assert hasattr(worker_mod, "main")
    assert callable(worker_mod.main)


# ---------------------------------------------------------------------------
# Worker main() configuration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_bootstraps_before_recovering_stale_jobs():
    """Startup recovery must wait until bootstrap has applied tenancy RLS."""
    from app.platform.jobs.worker import main

    call_order: list[str] = []
    bootstrap = AsyncMock(side_effect=lambda **_kwargs: call_order.append("bootstrap"))
    recover = AsyncMock(side_effect=lambda: call_order.append("recover"))
    assert_ports = MagicMock(side_effect=lambda: call_order.append("assert_ports"))

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", recover),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        patch("app.platform.jobs.worker.sweep_orphaned_exports"),
        patch("app.platform.extensions.bootstrap.bootstrap", bootstrap),
        patch(
            "app.platform.extensions.bootstrap.assert_enterprise_ports_resolved",
            assert_ports,
        ),
        patch(
            "app.observability.metrics.jobs.update_job_metrics", new_callable=AsyncMock
        ),
        patch("app.platform.jobs.worker.run_health_server", new_callable=AsyncMock),
        patch("app.processing.ingest.tasks.task_app", mock_task_app),
    ):
        await main()

    assert call_order == ["bootstrap", "assert_ports", "recover"]


@pytest.mark.asyncio
async def test_main_skips_stale_recovery_when_bootstrap_fails():
    """A failed tenancy bootstrap must prevent an unscoped recovery sweep."""
    from app.platform.jobs.worker import main

    recover = AsyncMock()
    bootstrap = AsyncMock(side_effect=RuntimeError("tenancy bootstrap failed"))
    assert_ports = MagicMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", recover),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        patch("app.platform.jobs.worker.sweep_orphaned_exports"),
        patch("app.platform.extensions.bootstrap.bootstrap", bootstrap),
        patch(
            "app.platform.extensions.bootstrap.assert_enterprise_ports_resolved",
            assert_ports,
        ),
    ):
        with pytest.raises(RuntimeError, match="tenancy bootstrap failed"):
            await main()

    recover.assert_not_awaited()
    assert_ports.assert_not_called()


@pytest.mark.asyncio
async def test_main_uses_shutdown_graceful_timeout():
    """main() should pass shutdown_graceful_timeout from settings.worker_shutdown_timeout.

    CONF-03 (Phase 277): worker.py reads the timeout via the Settings model
    (`settings.worker_shutdown_timeout`) instead of `os.environ.get(...)`,
    so the test patches the Settings attribute directly.
    """
    from app.platform.jobs import worker as worker_module
    from app.platform.jobs.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        # WORK-01: storage/cache/edition init now lives inside the shared bootstrap()
        # helper that worker.main() delegates to — patch it (not the old inline calls).
        patch("app.platform.extensions.bootstrap.bootstrap", new_callable=AsyncMock),
        patch("app.platform.extensions.bootstrap.assert_enterprise_ports_resolved"),
        patch(
            "app.observability.metrics.jobs.update_job_metrics", new_callable=AsyncMock
        ),
        patch("app.platform.jobs.worker.run_health_server", new_callable=AsyncMock),
        patch("app.processing.ingest.tasks.task_app", mock_task_app),
        patch.object(worker_module.settings, "worker_shutdown_timeout", 45),
    ):
        await main()

    call_kwargs = mock_task_app.run_worker_async.call_args
    assert call_kwargs.kwargs.get("shutdown_graceful_timeout") == 45


@pytest.mark.asyncio
async def test_main_uses_default_shutdown_timeout():
    """Without an override, settings.worker_shutdown_timeout defaults to 30.

    CONF-03 (Phase 277): the default is built into the Settings field,
    not pulled from os.environ. Patching the attribute to 30 makes the
    expectation explicit even when the host process inherits a different
    value.
    """
    from app.platform.jobs import worker as worker_module
    from app.platform.jobs.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        # WORK-01: storage/cache/edition init now lives inside the shared bootstrap()
        # helper that worker.main() delegates to — patch it (not the old inline calls).
        patch("app.platform.extensions.bootstrap.bootstrap", new_callable=AsyncMock),
        patch("app.platform.extensions.bootstrap.assert_enterprise_ports_resolved"),
        patch(
            "app.observability.metrics.jobs.update_job_metrics", new_callable=AsyncMock
        ),
        patch("app.platform.jobs.worker.run_health_server", new_callable=AsyncMock),
        patch("app.processing.ingest.tasks.task_app", mock_task_app),
        patch.object(worker_module.settings, "worker_shutdown_timeout", 30),
    ):
        await main()

    call_kwargs = mock_task_app.run_worker_async.call_args
    assert call_kwargs.kwargs.get("shutdown_graceful_timeout") == 30


@pytest.mark.asyncio
async def test_main_warns_when_worker_queues_lacks_the_drain_queue():
    import structlog

    from app.platform.jobs import worker as worker_module
    from app.platform.jobs.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        patch("app.platform.extensions.bootstrap.bootstrap", new_callable=AsyncMock),
        patch("app.platform.extensions.bootstrap.assert_enterprise_ports_resolved"),
        patch(
            "app.observability.metrics.jobs.update_job_metrics", new_callable=AsyncMock
        ),
        patch("app.platform.jobs.worker.run_health_server", new_callable=AsyncMock),
        patch("app.processing.ingest.tasks.task_app", mock_task_app),
        patch.object(worker_module.settings, "worker_queues", "priority,ingest,raster"),
        structlog.testing.capture_logs() as captured,
    ):
        await main()

    warnings = [
        e for e in captured if e.get("event") == "worker_queue_missing_drain_queue"
    ]
    assert len(warnings) == 1
    assert warnings[0]["missing_queue"] == "ingest-auth-v2"
    assert warnings[0]["configured_queues"] == ["priority", "ingest", "raster"]
    assert warnings[0]["log_level"] == "warning"


@pytest.mark.asyncio
async def test_main_does_not_warn_when_worker_queues_lists_the_drain_queue():
    import structlog

    from app.platform.jobs import worker as worker_module
    from app.platform.jobs.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        patch("app.platform.extensions.bootstrap.bootstrap", new_callable=AsyncMock),
        patch("app.platform.extensions.bootstrap.assert_enterprise_ports_resolved"),
        patch(
            "app.observability.metrics.jobs.update_job_metrics", new_callable=AsyncMock
        ),
        patch("app.platform.jobs.worker.run_health_server", new_callable=AsyncMock),
        patch("app.processing.ingest.tasks.task_app", mock_task_app),
        patch.object(
            worker_module.settings,
            "worker_queues",
            "priority,ingest,raster,ingest-auth-v2",
        ),
        structlog.testing.capture_logs() as captured,
    ):
        await main()

    warnings = [
        e for e in captured if e.get("event") == "worker_queue_missing_drain_queue"
    ]
    assert warnings == []


@pytest.mark.asyncio
async def test_main_passes_install_signal_handlers_true():
    """main() should pass install_signal_handlers=True to run_worker_async."""
    from app.platform.jobs.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.platform.jobs.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.core.db.schema_skew.assert_schema_in_sync", new_callable=AsyncMock),
        patch("app.platform.jobs.worker.ensure_staging_ready"),
        # WORK-01: storage/cache/edition init now lives inside the shared bootstrap()
        # helper that worker.main() delegates to — patch it (not the old inline calls).
        patch("app.platform.extensions.bootstrap.bootstrap", new_callable=AsyncMock),
        patch("app.platform.extensions.bootstrap.assert_enterprise_ports_resolved"),
        patch(
            "app.observability.metrics.jobs.update_job_metrics", new_callable=AsyncMock
        ),
        patch("app.platform.jobs.worker.run_health_server", new_callable=AsyncMock),
        patch("app.processing.ingest.tasks.task_app", mock_task_app),
    ):
        await main()

    call_kwargs = mock_task_app.run_worker_async.call_args
    assert call_kwargs.kwargs.get("install_signal_handlers") is True

"""Tests for the standalone Procrastinate worker module."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Worker health app tests
# ---------------------------------------------------------------------------


@pytest.fixture
def health_app():
    from app.worker_health import app

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

    with patch("app.worker_health._get_engine", return_value=mock_engine):
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

    with patch("app.worker_health._get_engine", return_value=mock_engine):
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
        "app.worker_health.generate_latest", return_value=b"# HELP fake_metric\n"
    ):
        with patch(
            "app.worker_health.CONTENT_TYPE_LATEST", "text/plain; version=0.0.4"
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
    assert hasattr(worker_mod, "recover_stale_jobs")
    assert callable(worker_mod.main)


# ---------------------------------------------------------------------------
# Stale job recovery tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_stale_jobs_marks_running_as_failed():
    """recover_stale_jobs should mark all running IngestJobs as failed."""
    from app.worker import recover_stale_jobs

    fake_job = MagicMock()
    fake_job.id = uuid4()
    fake_job.status = "running"
    fake_job.error_message = None
    fake_job.completed_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value = [fake_job]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    with patch("app.database.async_session", return_value=mock_session):
        await recover_stale_jobs()

    assert fake_job.status == "failed"
    assert "Stale" in fake_job.error_message
    assert fake_job.completed_at is not None


@pytest.mark.asyncio
async def test_recover_stale_jobs_logs_individual_job_ids():
    """Each stale job should be logged with its individual job_id."""
    from app.worker import recover_stale_jobs

    job1 = MagicMock()
    job1.id = uuid4()
    job1.status = "running"
    job1.error_message = None
    job1.completed_at = None

    job2 = MagicMock()
    job2.id = uuid4()
    job2.status = "running"
    job2.error_message = None
    job2.completed_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value = [job1, job2]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    with patch("app.database.async_session", return_value=mock_session):
        with patch("app.worker.log") as mock_log:
            await recover_stale_jobs()

    # Should have individual log calls with job_id kwarg
    warning_calls = [c for c in mock_log.warning.call_args_list]
    assert len(warning_calls) == 2
    assert warning_calls[0].kwargs.get("job_id") == str(job1.id)
    assert warning_calls[1].kwargs.get("job_id") == str(job2.id)


# ---------------------------------------------------------------------------
# Worker main() configuration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_uses_shutdown_graceful_timeout():
    """main() should pass shutdown_graceful_timeout from WORKER_SHUTDOWN_TIMEOUT env."""
    from app.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.worker.ensure_staging_ready"),
        patch("app.storage.init_storage"),
        patch("app.cache.init_cache"),
        patch("app.metrics.jobs.update_job_metrics", new_callable=AsyncMock),
        patch("app.worker.run_health_server", new_callable=AsyncMock),
        patch("app.ingest.tasks.task_app", mock_task_app),
        patch.dict("os.environ", {"WORKER_SHUTDOWN_TIMEOUT": "45"}),
    ):
        await main()

    call_kwargs = mock_task_app.run_worker_async.call_args
    assert call_kwargs.kwargs.get("shutdown_graceful_timeout") == 45


@pytest.mark.asyncio
async def test_main_uses_default_shutdown_timeout():
    """Without WORKER_SHUTDOWN_TIMEOUT, default to 30 seconds."""
    from app.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.worker.ensure_staging_ready"),
        patch("app.storage.init_storage"),
        patch("app.cache.init_cache"),
        patch("app.metrics.jobs.update_job_metrics", new_callable=AsyncMock),
        patch("app.worker.run_health_server", new_callable=AsyncMock),
        patch("app.ingest.tasks.task_app", mock_task_app),
        patch.dict("os.environ", {}, clear=False),
    ):
        # Ensure WORKER_SHUTDOWN_TIMEOUT is not set
        import os

        os.environ.pop("WORKER_SHUTDOWN_TIMEOUT", None)
        await main()

    call_kwargs = mock_task_app.run_worker_async.call_args
    assert call_kwargs.kwargs.get("shutdown_graceful_timeout") == 30


@pytest.mark.asyncio
async def test_main_passes_install_signal_handlers_true():
    """main() should pass install_signal_handlers=True to run_worker_async."""
    from app.worker import main

    mock_task_app = MagicMock()
    mock_open = AsyncMock()
    mock_open.__aenter__ = AsyncMock()
    mock_open.__aexit__ = AsyncMock(return_value=False)
    mock_task_app.open_async.return_value = mock_open
    mock_task_app.run_worker_async = AsyncMock()

    with (
        patch("app.worker.recover_stale_jobs", new_callable=AsyncMock),
        patch("app.worker.ensure_staging_ready"),
        patch("app.storage.init_storage"),
        patch("app.cache.init_cache"),
        patch("app.metrics.jobs.update_job_metrics", new_callable=AsyncMock),
        patch("app.worker.run_health_server", new_callable=AsyncMock),
        patch("app.ingest.tasks.task_app", mock_task_app),
    ):
        await main()

    call_kwargs = mock_task_app.run_worker_async.call_args
    assert call_kwargs.kwargs.get("install_signal_handlers") is True

"""fix(#1778): terminal queue rows need a retention path.

Nothing in the repository ever deleted a failed, cancelled or aborted
``procrastinate_jobs`` row or its events. ``delete_old_jobs`` was never called,
there is no pg_cron, no CronJob, no scheduled workflow and no periodic
Procrastinate task, and ``POST /jobs/cleanup/stale/`` sweeps only the
``ingest_jobs`` mirror -- whose own 30-day retention deletes the row that
explains the queue row, leaving unattributable residue behind.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platform.jobs.worker import (
    TERMINAL_JOB_PURGE_INTERVAL_SECONDS,
    purge_expired_terminal_jobs,
)


def _task_app_with_manager():
    manager = MagicMock()
    manager.delete_old_jobs = AsyncMock(return_value=None)
    task_app = MagicMock()
    task_app.job_manager = manager
    return task_app, manager


@pytest.mark.asyncio
async def test_purge_covers_every_terminal_status_and_uses_the_mirror_window():
    task_app, manager = _task_app_with_manager()
    with patch("app.processing.ingest.tasks.task_app", task_app):
        with patch("app.core.config.settings.ingest_jobs_retention_days", 30):
            await purge_expired_terminal_jobs()

    manager.delete_old_jobs.assert_awaited_once()
    kwargs = manager.delete_old_jobs.await_args.kwargs
    # Procrastinate defaults every include_* to False, i.e. succeeded only --
    # and succeeded rows are the one status this deployment never stores.
    assert kwargs["include_failed"] is True
    assert kwargs["include_cancelled"] is True
    assert kwargs["include_aborted"] is True
    # Keyed to INGEST_JOBS_RETENTION_DAYS so queue row and mirror row age out
    # together.
    assert kwargs["nb_hours"] == 30 * 24


@pytest.mark.asyncio
async def test_a_zero_retention_setting_disables_the_purge():
    """0 means keep, matching the ingest_jobs mirror sweep."""
    task_app, manager = _task_app_with_manager()
    with patch("app.processing.ingest.tasks.task_app", task_app):
        with patch("app.core.config.settings.ingest_jobs_retention_days", 0):
            await purge_expired_terminal_jobs()

    manager.delete_old_jobs.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_purge_failure_never_kills_the_worker_loop():
    from app.platform.jobs.worker import _purge_terminal_jobs_safely

    task_app, manager = _task_app_with_manager()
    manager.delete_old_jobs = AsyncMock(side_effect=RuntimeError("pool closed"))
    with patch("app.processing.ingest.tasks.task_app", task_app):
        with patch("app.core.config.settings.ingest_jobs_retention_days", 30):
            await _purge_terminal_jobs_safely()


def test_the_worker_runs_the_purge_at_startup_and_on_an_interval():
    import inspect

    from app.platform.jobs import worker as worker_module

    src = inspect.getsource(worker_module.main)
    assert "await _purge_terminal_jobs_safely()" in src, (
        "the startup pass is what keeps the jobs-by-events join small"
    )
    assert "run_terminal_job_purges()" in src
    assert TERMINAL_JOB_PURGE_INTERVAL_SECONDS > 0

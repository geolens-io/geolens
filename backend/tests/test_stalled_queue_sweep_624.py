"""fix(#624): the stalled-queue sweep fails jobs whose worker died mid-job.

The procrastinate API contract these mocks stand in for (``get_stalled_jobs``
with a heartbeat window, ``finish_job_by_id_async``, ``prune_stalled_workers``)
was verified live against a real database before this test was written: a
``doing`` row pinned to a worker with a 5-day-old heartbeat flipped to
``failed``, its dead worker row was pruned, and the concurrently-heartbeating
live worker was left alone. What is asserted here is the sweep's decision logic
— fail rather than requeue, keep the row, skip unpersisted jobs.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from procrastinate.jobs import Status

from app.platform.jobs.worker import (
    STALLED_WORKER_SECONDS,
    fail_stalled_queue_jobs,
    run_stalled_queue_sweeps,
)


def _fake_task_app(stalled: list, pruned: list | None = None) -> SimpleNamespace:
    manager = SimpleNamespace(
        get_stalled_jobs=AsyncMock(return_value=stalled),
        finish_job_by_id_async=AsyncMock(),
        prune_stalled_workers=AsyncMock(return_value=pruned or []),
    )
    return SimpleNamespace(job_manager=manager)


@pytest.mark.anyio
async def test_stalled_jobs_are_failed_not_requeued():
    """A stalled job is transitioned to FAILED and its row is kept.

    Requeueing would re-run an ingest task that is not idempotency-audited, and
    failing matches the verdict the ingest_jobs reaper already gave the user.
    Keeping the row (delete_job=False) preserves the post-mortem trail.
    """
    job = SimpleNamespace(
        id=181, task_name="app.processing.ingest.tasks.ingest_service"
    )
    fake = _fake_task_app([job], pruned=[7])

    with patch("app.processing.ingest.tasks.task_app", fake):
        failed = await fail_stalled_queue_jobs()

    assert failed == 1
    fake.job_manager.get_stalled_jobs.assert_awaited_once_with(
        seconds_since_heartbeat=STALLED_WORKER_SECONDS
    )
    fake.job_manager.finish_job_by_id_async.assert_awaited_once_with(
        job_id=181, status=Status.FAILED, delete_job=False
    )
    fake.job_manager.prune_stalled_workers.assert_awaited_once_with(
        seconds_since_heartbeat=STALLED_WORKER_SECONDS
    )


@pytest.mark.anyio
async def test_no_stalled_jobs_touches_nothing():
    """A healthy queue transitions no jobs — the sweep must be a no-op."""
    fake = _fake_task_app([])

    with patch("app.processing.ingest.tasks.task_app", fake):
        failed = await fail_stalled_queue_jobs()

    assert failed == 0
    fake.job_manager.finish_job_by_id_async.assert_not_awaited()


@pytest.mark.anyio
async def test_unpersisted_job_is_skipped():
    """A Job with no id cannot be transitioned; skip it instead of crashing the
    sweep (which would strand every job behind it)."""
    jobs = [
        SimpleNamespace(id=None, task_name="unpersisted"),
        SimpleNamespace(id=42, task_name="real"),
    ]
    fake = _fake_task_app(jobs)

    with patch("app.processing.ingest.tasks.task_app", fake):
        await fail_stalled_queue_jobs()

    fake.job_manager.finish_job_by_id_async.assert_awaited_once_with(
        job_id=42, status=Status.FAILED, delete_job=False
    )


@pytest.mark.anyio
async def test_sweep_loop_keeps_running_after_a_failure():
    """fix(#624 codex P2): the sweep must repeat, and survive its own failures.

    A startup-only sweep is always one restart behind: under
    `restart: unless-stopped` the replacement worker is up seconds after the
    crash, while the dead worker's heartbeat is still fresh, so the startup pass
    skips the very row it exists to reap. The loop is what actually reaps it —
    which makes "one bad sweep kills the loop" a silent regression to the old
    behavior, hence the raising first call.
    """
    calls = []

    async def _flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient DB blip")

    with (
        patch("app.platform.jobs.worker.fail_stalled_queue_jobs", _flaky),
        patch("app.platform.jobs.worker.STALLED_QUEUE_SWEEP_INTERVAL_SECONDS", 0),
    ):
        task = asyncio.create_task(run_stalled_queue_sweeps())
        try:
            # Bounded: if the loop dies on the raising call this fails in 5s
            # instead of spinning forever.
            async with asyncio.timeout(5):
                while len(calls) < 3:
                    await asyncio.sleep(0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert len(calls) >= 3  # kept sweeping past the exception on call 1


def test_procrastinate_prune_window_matches_the_sweep_window():
    """fix(#624 codex P1): the two stalled-worker windows must not diverge.

    Procrastinate's own ``Worker.run()`` prunes workers silent longer than
    ``stalled_worker_timeout``. ``procrastinate_jobs.worker_id`` is ON DELETE SET
    NULL, and ``select_stalled_jobs_by_heartbeat`` treats a ``doing`` job with a
    NULL worker_id as stalled outright — there is no heartbeat left to compare
    against. At procrastinate's 30s default, a live worker that merely stalls
    gets pruned by another worker's startup and our 300s sweep then fails its
    in-flight work.

    Source-asserted because the call sits in ``main()`` behind bootstrap; what
    matters is that the kwarg is present and bound to the same constant, which a
    future "tidy up the redundant argument" edit would silently undo.
    """
    from pathlib import Path

    import app.platform.jobs.worker as worker_mod

    source = Path(worker_mod.__file__).read_text()
    assert "stalled_worker_timeout=STALLED_WORKER_SECONDS" in source, (
        "run_worker_async must pin procrastinate's prune window to "
        "STALLED_WORKER_SECONDS — see the comment at that call site"
    )

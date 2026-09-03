"""fix(#1778): both job counters must move, and only once the row is written.

``geolens_jobs_completed_total`` was derived from a ``SELECT status, COUNT(*)
... GROUP BY status`` over ``catalog.procrastinate_jobs``, but the worker runs
with ``delete_jobs="successful"``, which makes ``procrastinate_finish_job_v1``
DELETE the row while it is still ``doing``. No ``succeeded`` row is ever
written, so the 15s poll could never observe one, and the metric read a flat
zero -- along with the RUNBOOK entry that documents it and the "Job throughput"
Grafana panel whose first target is ``rate(geolens_jobs_completed_total[15m])``.
A healthy ingest burst looked exactly like a crashed worker.

fix(#1778 codex r1): ``geolens_jobs_failed_total`` moves here too. It used to
be a delta against a snapshot of a row count, which stops working the moment
rows can disappear -- and ``purge_expired_terminal_jobs`` makes them disappear.
``_prev_counts`` kept the pre-purge figure, so the next failure produced a
non-positive delta the counter never saw, taking ``GeoLensJobFailures`` with
it.

fix(#1778 codex r2): both increments hang off the JOB MANAGER rather than a
worker middleware. Procrastinate runs worker middleware inside
``Worker._process_job``'s ``try``, which is before ``_persist_job_status``, so
a middleware reported a completion for a job whose terminal row had not been
written and might never be. Wrapping ``job_manager.finish_job`` counts strictly
after the row lands, and takes Procrastinate's own status instead of
re-deriving it: a retry goes through ``retry_job`` and never arrives, an abort
arrives as ``Status.ABORTED`` and is counted as neither.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from procrastinate.jobs import Status

from app.observability.metrics.jobs import (
    _refresh_job_metrics,
    jobs_completed_total,
    jobs_failed_total,
)
from app.platform.jobs import worker as worker_module
from app.platform.jobs.worker import (
    count_failed_job,
    install_job_outcome_counters,
    purge_expired_terminal_jobs,
)


def _mock_engine_returning(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=result)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


def _job(queue: str):
    job = MagicMock()
    job.queue = queue
    job.id = 4242
    return job


def _task_app_with_finish(side_effect=None):
    """A stand-in app whose job manager records how finish_job was called."""
    manager = MagicMock()
    manager.finish_job = AsyncMock(side_effect=side_effect)
    task_app = MagicMock()
    task_app.job_manager = manager
    return task_app, manager


def _completed(queue: str) -> float:
    return jobs_completed_total.labels(queue=queue)._value.get()


def _failed(queue: str) -> float:
    return jobs_failed_total.labels(queue=queue)._value.get()


# ---------------------------------------------------------------------------
# Counting at terminal persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_persisted_success_advances_exactly_one_counter():
    queue = "q1778_ok"
    completed_before, failed_before = _completed(queue), _failed(queue)

    task_app, manager = _task_app_with_finish()
    inner = manager.finish_job  # the wrapper replaces the attribute
    install_job_outcome_counters(task_app)
    await task_app.job_manager.finish_job(
        job=_job(queue), status=Status.SUCCEEDED, delete_job=True
    )

    inner.assert_awaited_once()
    assert _completed(queue) == completed_before + 1
    assert _failed(queue) == failed_before


@pytest.mark.asyncio
async def test_a_persisted_failure_advances_exactly_one_counter():
    queue = "q1778_terminal"
    completed_before, failed_before = _completed(queue), _failed(queue)

    task_app, _ = _task_app_with_finish()
    install_job_outcome_counters(task_app)
    await task_app.job_manager.finish_job(
        job=_job(queue), status=Status.FAILED, delete_job=False
    )

    assert _failed(queue) == failed_before + 1
    assert _completed(queue) == completed_before


@pytest.mark.asyncio
async def test_a_persistence_failure_leaves_both_counters_unchanged():
    """fix(#1778 codex r2): the ordering a worker middleware could not give.

    A middleware runs before `_persist_job_status`, so it reported a completion
    for a job whose terminal row was never written.
    """
    queue = "q1778_persist_fail"
    completed_before, failed_before = _completed(queue), _failed(queue)

    task_app, _ = _task_app_with_finish(side_effect=RuntimeError("connection lost"))
    install_job_outcome_counters(task_app)

    for status in (Status.SUCCEEDED, Status.FAILED):
        with pytest.raises(RuntimeError):
            await task_app.job_manager.finish_job(
                job=_job(queue), status=status, delete_job=False
            )

    assert _completed(queue) == completed_before
    assert _failed(queue) == failed_before


@pytest.mark.asyncio
async def test_an_aborted_job_counts_as_neither():
    """`aborted` is its own status; a graceful shutdown must not page anyone."""
    queue = "q1778_abort"
    completed_before, failed_before = _completed(queue), _failed(queue)

    task_app, _ = _task_app_with_finish()
    install_job_outcome_counters(task_app)
    await task_app.job_manager.finish_job(
        job=_job(queue), status=Status.ABORTED, delete_job=False
    )

    assert _completed(queue) == completed_before
    assert _failed(queue) == failed_before


@pytest.mark.asyncio
async def test_a_retry_never_reaches_the_counters():
    """`_persist_job_status` calls retry_job instead of finish_job.

    A retried attempt is therefore not a failure. Counting it would turn one
    eventual failure into one per attempt, which the row count never did.
    """
    queue = "q1778_retry"
    completed_before, failed_before = _completed(queue), _failed(queue)

    task_app, manager = _task_app_with_finish()
    manager.retry_job = AsyncMock()
    install_job_outcome_counters(task_app)
    await task_app.job_manager.retry_job(job=_job(queue))

    assert _completed(queue) == completed_before
    assert _failed(queue) == failed_before


@pytest.mark.asyncio
async def test_installing_twice_does_not_double_count():
    queue = "q1778_idempotent"
    before = _completed(queue)

    task_app, _ = _task_app_with_finish()
    install_job_outcome_counters(task_app)
    install_job_outcome_counters(task_app)
    await task_app.job_manager.finish_job(
        job=_job(queue), status=Status.SUCCEEDED, delete_job=True
    )

    assert _completed(queue) == before + 1


@pytest.mark.asyncio
async def test_a_metrics_failure_never_changes_a_job_outcome():
    task_app, _ = _task_app_with_finish()
    install_job_outcome_counters(task_app)

    job = MagicMock()
    type(job).queue = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("registry down"))
    )
    # The wrapper must not raise: the terminal row is already written.
    await task_app.job_manager.finish_job(
        job=job, status=Status.SUCCEEDED, delete_job=True
    )


def test_the_worker_installs_the_wrapper_before_it_starts():
    """Both counters are dead again if main() stops installing it."""
    src = inspect.getsource(worker_module.main)
    assert "install_job_outcome_counters(task_app)" in src
    install_at = src.index("install_job_outcome_counters(task_app)")
    run_at = src.index("run_worker_async(")
    assert install_at < run_at, "no job may finish outside the wrapper"
    assert "worker_middleware=" not in src, (
        "a worker middleware runs before _persist_job_status and cannot see "
        "whether the terminal row was written"
    )


# ---------------------------------------------------------------------------
# The regression the purge introduced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failure_after_a_purge_still_advances_the_counter():
    """fix(#1778 codex r1): purge, then a failure, the counter advances by one.

    With the old snapshot delta this was the bug: the poll recorded the queue's
    failed row count, the purge deleted those rows, and the next burst came in
    below the remembered figure, so `delta > 0` was false and the counter never
    moved again.
    """
    queue = "q1778_after_purge"

    # A poll while failed rows exist. It must not touch the counter at all.
    before_poll = _failed(queue)
    with patch("app.core.db.engine", _mock_engine_returning([("failed", queue, 7)])):
        await _refresh_job_metrics()
    assert _failed(queue) == before_poll, (
        "the poll must not derive the failed counter from a row count"
    )

    # The purge removes those rows.
    manager = MagicMock()
    manager.delete_old_jobs = AsyncMock(return_value=None)
    purge_app = MagicMock()
    purge_app.job_manager = manager
    with patch("app.processing.ingest.tasks.task_app", purge_app):
        with patch("app.core.config.settings.ingest_jobs_retention_days", 30):
            await purge_expired_terminal_jobs()
    manager.delete_old_jobs.assert_awaited_once()

    # A poll that now sees no failed rows, then one new persisted failure.
    with patch("app.core.db.engine", _mock_engine_returning([])):
        await _refresh_job_metrics()

    before = _failed(queue)
    task_app, _ = _task_app_with_finish()
    install_job_outcome_counters(task_app)
    await task_app.job_manager.finish_job(
        job=_job(queue), status=Status.FAILED, delete_job=False
    )

    assert _failed(queue) == before + 1


@pytest.mark.asyncio
async def test_the_poll_no_longer_derives_either_counter_from_rows():
    """Feeding it a realistic row set for this deployment's delete_jobs setting."""
    queue = "q1778_poll"
    completed_before = _completed(queue)
    failed_before = _failed(queue)

    rows = [("todo", queue, 3), ("doing", queue, 1), ("failed", queue, 2)]
    with patch("app.core.db.engine", _mock_engine_returning(rows)):
        await _refresh_job_metrics()

    assert _completed(queue) == completed_before
    assert _failed(queue) == failed_before


@pytest.mark.asyncio
async def test_a_succeeded_row_is_not_a_source_for_the_counter():
    """The counterfactual for the old design, kept as a guard."""
    queue = "q1778_succeeded"
    before = _completed(queue)

    with patch(
        "app.core.db.engine", _mock_engine_returning([("succeeded", queue, 99)])
    ):
        await _refresh_job_metrics()

    assert _completed(queue) == before


# ---------------------------------------------------------------------------
# The other site that writes a failed row
# ---------------------------------------------------------------------------


def test_the_stalled_sweep_counts_its_own_failures_after_persisting():
    """It calls finish_job_by_id_async directly, so the wrapper never sees it."""
    src = inspect.getsource(worker_module.fail_stalled_queue_jobs)
    assert "count_failed_job(job.queue)" in src, (
        "failing a stalled job is a terminal transition the counter must see"
    )
    persist_at = src.index("finish_job_by_id_async(")
    count_at = src.index("count_failed_job(job.queue)")
    assert persist_at < count_at, "a persistence failure must count nothing"

    queue = "q1778_sweep"
    before = _failed(queue)
    count_failed_job(queue)
    assert _failed(queue) == before + 1

    # A queue-less job still lands somewhere countable.
    default_before = _failed("default")
    count_failed_job(None)
    assert _failed("default") == default_before + 1

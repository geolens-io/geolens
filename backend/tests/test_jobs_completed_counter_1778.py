"""fix(#1778): both job counters must move, and keep moving after a purge.

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
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from procrastinate import exceptions as procrastinate_exceptions

from app.observability.metrics.jobs import (
    _refresh_job_metrics,
    jobs_completed_total,
    jobs_failed_total,
)
from app.platform.jobs.worker import (
    _writes_a_failed_row,
    count_failed_job,
    count_job_outcome,
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


def _context_for(queue: str):
    context = MagicMock()
    context.job.queue = queue
    context.job.task_name = "app.tasks.ingest"
    return context


def _worker_with_retry(retry_decision):
    """A worker whose task declines (None) or grants a retry."""
    task = MagicMock()
    task.get_retry_exception = MagicMock(return_value=retry_decision)
    worker = MagicMock()
    worker.app.tasks = {"app.tasks.ingest": task}
    return worker


def _completed(queue: str) -> float:
    return jobs_completed_total.labels(queue=queue)._value.get()


def _failed(queue: str) -> float:
    return jobs_failed_total.labels(queue=queue)._value.get()


# ---------------------------------------------------------------------------
# Completions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_completed_job_increments_the_counter():
    queue = "q1778_ok"
    before = _completed(queue)

    async def call_next():
        return "task result"

    result = await count_job_outcome(
        call_next, _context_for(queue), _worker_with_retry(None)
    )

    assert result == "task result", "middleware must pass the task result through"
    assert _completed(queue) == before + 1


@pytest.mark.asyncio
async def test_a_failing_job_does_not_increment_the_completed_counter():
    queue = "q1778_fail"
    before = _completed(queue)

    async def call_next():
        raise RuntimeError("task blew up")

    with pytest.raises(RuntimeError):
        await count_job_outcome(
            call_next, _context_for(queue), _worker_with_retry(None)
        )

    assert _completed(queue) == before


@pytest.mark.asyncio
async def test_a_metrics_failure_never_fails_a_finished_job():
    async def call_next():
        return "done"

    context = MagicMock()
    type(context.job).queue = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("registry down"))
    )

    assert (
        await count_job_outcome(call_next, context, _worker_with_retry(None)) == "done"
    )


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_terminal_failure_increments_the_failed_counter():
    queue = "q1778_terminal"
    before = _failed(queue)

    async def call_next():
        raise RuntimeError("task blew up")

    with pytest.raises(RuntimeError):
        await count_job_outcome(
            call_next, _context_for(queue), _worker_with_retry(None)
        )

    assert _failed(queue) == before + 1


@pytest.mark.asyncio
async def test_a_retried_attempt_is_not_a_failure():
    """A retry goes back to `todo` and writes no failed row.

    Counting it would turn one eventual failure into one per attempt, which is
    not what the row count did.
    """
    queue = "q1778_retry"
    before = _failed(queue)

    async def call_next():
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError):
        await count_job_outcome(
            call_next,
            _context_for(queue),
            _worker_with_retry(MagicMock(name="JobRetry")),
        )

    assert _failed(queue) == before


@pytest.mark.asyncio
async def test_an_aborted_job_is_not_a_failure():
    """`aborted` is its own status; a graceful shutdown must not page anyone."""
    queue = "q1778_abort"
    before = _failed(queue)

    for exc in (
        procrastinate_exceptions.JobAborted("stop"),
        asyncio.CancelledError(),
    ):

        async def call_next(_exc=exc):
            raise _exc

        with pytest.raises(BaseException):
            await count_job_outcome(
                call_next, _context_for(queue), _worker_with_retry(None)
            )

    assert _failed(queue) == before


def test_writes_a_failed_row_mirrors_the_worker_decision():
    context = _context_for("q1778_decision")

    assert (
        _writes_a_failed_row(RuntimeError("x"), context, _worker_with_retry(None))
        is True
    )
    assert (
        _writes_a_failed_row(
            RuntimeError("x"), context, _worker_with_retry(MagicMock())
        )
        is False
    )
    assert (
        _writes_a_failed_row(
            procrastinate_exceptions.JobAborted("x"), context, _worker_with_retry(None)
        )
        is False
    )

    # An unregistered task cannot retry, so procrastinate records `failed`.
    worker = MagicMock()
    worker.app.tasks = {}
    assert _writes_a_failed_row(RuntimeError("x"), context, worker) is True


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
    task_app = MagicMock()
    task_app.job_manager = manager
    with patch("app.processing.ingest.tasks.task_app", task_app):
        with patch("app.core.config.settings.ingest_jobs_retention_days", 30):
            await purge_expired_terminal_jobs()
    manager.delete_old_jobs.assert_awaited_once()

    # A poll that now sees no failed rows, then one new failure.
    with patch("app.core.db.engine", _mock_engine_returning([])):
        await _refresh_job_metrics()

    before = _failed(queue)

    async def call_next():
        raise RuntimeError("post-purge failure")

    with pytest.raises(RuntimeError):
        await count_job_outcome(
            call_next, _context_for(queue), _worker_with_retry(None)
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


def test_the_stalled_sweep_counts_its_own_failures():
    """fix(#1778 codex r1): a transition count has to be told about this one."""
    from app.platform.jobs import worker as worker_module

    src = inspect.getsource(worker_module.fail_stalled_queue_jobs)
    assert "count_failed_job(job.queue)" in src, (
        "failing a stalled job is a terminal transition the counter must see"
    )

    queue = "q1778_sweep"
    before = _failed(queue)
    count_failed_job(queue)
    assert _failed(queue) == before + 1

    # A queue-less job still lands somewhere countable.
    default_before = _failed("default")
    count_failed_job(None)
    assert _failed("default") == default_before + 1


def test_the_worker_registers_the_middleware():
    """Both counters are dead again if run_worker_async stops carrying it."""
    from app.platform.jobs import worker as worker_module

    src = inspect.getsource(worker_module.main)
    assert "worker_middleware=[count_job_outcome]" in src

"""fix(#1778): geolens_jobs_completed_total must actually move.

The counter was derived from a ``SELECT status, COUNT(*) ... GROUP BY status``
over ``catalog.procrastinate_jobs``, but the worker runs with
``delete_jobs="successful"``, which makes ``procrastinate_finish_job_v1``
DELETE the row while it is still ``doing``. No ``succeeded`` row is ever
written, so the 15s poll could never observe one, and the metric has read a
flat zero since it was added -- along with the RUNBOOK entry that documents it
and the "Job throughput" Grafana panel whose first target is
``rate(geolens_jobs_completed_total[15m])``. A healthy ingest burst looked
exactly like a crashed worker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.observability.metrics.jobs import (
    _refresh_job_metrics,
    jobs_completed_total,
    jobs_failed_total,
)
from app.platform.jobs.worker import count_completed_job


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
    return context


@pytest.mark.asyncio
async def test_a_completed_job_increments_the_counter():
    queue = "q1778_ok"
    before = jobs_completed_total.labels(queue=queue)._value.get()

    async def call_next():
        return "task result"

    result = await count_completed_job(call_next, _context_for(queue), MagicMock())

    assert result == "task result", "middleware must pass the task result through"
    assert jobs_completed_total.labels(queue=queue)._value.get() == before + 1


@pytest.mark.asyncio
async def test_a_failing_job_does_not_increment_the_counter():
    """Any exception is a non-success for procrastinate, retries included."""
    queue = "q1778_fail"
    before = jobs_completed_total.labels(queue=queue)._value.get()

    async def call_next():
        raise RuntimeError("task blew up")

    with pytest.raises(RuntimeError):
        await count_completed_job(call_next, _context_for(queue), MagicMock())

    assert jobs_completed_total.labels(queue=queue)._value.get() == before


@pytest.mark.asyncio
async def test_a_metrics_failure_never_fails_a_finished_job():
    async def call_next():
        return "done"

    context = MagicMock()
    type(context.job).queue = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("registry down"))
    )

    assert await count_completed_job(call_next, context, MagicMock()) == "done"


@pytest.mark.asyncio
async def test_the_poll_no_longer_pretends_to_count_completions():
    """The row scan must not claim completions it cannot see.

    Feeding it a realistic row set for this deployment's delete_jobs setting:
    todo and doing rows exist, failed rows persist, succeeded rows never do.
    """
    queue = "q1778_poll"
    completed_before = jobs_completed_total.labels(queue=queue)._value.get()
    failed_before = jobs_failed_total.labels(queue=queue)._value.get()

    rows = [("todo", queue, 3), ("doing", queue, 1), ("failed", queue, 2)]
    with patch("app.core.db.engine", _mock_engine_returning(rows)):
        await _refresh_job_metrics()

    assert jobs_completed_total.labels(queue=queue)._value.get() == completed_before
    # The sibling branch still works, which is what GeoLensJobFailures needs.
    assert jobs_failed_total.labels(queue=queue)._value.get() == failed_before + 2


@pytest.mark.asyncio
async def test_a_succeeded_row_is_not_a_source_for_the_counter():
    """The counterfactual for the old design, kept as a guard.

    If someone reinstates the row-scan branch beside the middleware, a
    deployment that ever did persist succeeded rows would double count.
    """
    queue = "q1778_succeeded"
    before = jobs_completed_total.labels(queue=queue)._value.get()

    rows = [("succeeded", queue, 99)]
    with patch("app.core.db.engine", _mock_engine_returning(rows)):
        await _refresh_job_metrics()

    assert jobs_completed_total.labels(queue=queue)._value.get() == before


def test_the_worker_registers_the_middleware():
    """The counter is dead again if run_worker_async stops carrying it."""
    import inspect

    from app.platform.jobs import worker as worker_module

    src = inspect.getsource(worker_module.main)
    assert "worker_middleware=[count_completed_job]" in src

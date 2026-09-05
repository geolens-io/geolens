"""fix(#1755 item 11): a cleanup step must not eat the exception it runs past.

Every ingest task ends in a `finally:` block that stops its heartbeat, drops
its attempt staging table, unlinks local scratch files and reaps staging
objects. Each call used to be awaited bare, which gives a failing cleanup two
ways to destroy the diagnosis:

- it REPLACES whatever the `try`/`except` above was propagating, so the queue
  row and the caller's `except` record an unrelated cleanup error, and
- it SKIPS every remaining step in the same block, including the reaps and
  (through the raise leaving the task) anything the caller does after.

``cleanup_step`` (``processing/ingest/tasks_common.py``) is the one helper all
seven task modules now route those steps through.

structlog records are read with ``structlog.testing.capture_logs``; pytest's
``caplog`` sees zero of them in this repo.
"""

import asyncio

import pytest
import structlog

from app.processing.ingest.tasks_common import cleanup_step

pytestmark = pytest.mark.anyio


async def test_a_failing_step_is_logged_and_does_not_raise():
    with structlog.testing.capture_logs() as captured:
        async with cleanup_step("ingest_file heartbeat", job_id="job-77"):
            raise ValueError("cleanup boom")

    entries = [e for e in captured if e["event"] == "ingest_cleanup_step_failed"]
    assert len(entries) == 1
    assert entries[0]["step"] == "ingest_file heartbeat"
    assert entries[0]["job_id"] == "job-77"
    assert entries[0]["log_level"] == "error"
    assert "cleanup boom" in entries[0]["error"]


async def test_a_successful_step_logs_nothing():
    ran = False
    with structlog.testing.capture_logs() as captured:
        async with cleanup_step("ingest_file staging table", job_id="job-77"):
            ran = True

    assert ran is True
    assert [e for e in captured if e["event"] == "ingest_cleanup_step_failed"] == []


async def test_a_failing_step_neither_masks_the_exception_nor_skips_the_next():
    """The whole point, exercised in the shape the task tails use."""
    later_steps: list[str] = []

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(RuntimeError, match="the real ingest failure"):
            try:
                raise RuntimeError("the real ingest failure")
            finally:
                async with cleanup_step("heartbeat", job_id="job-77"):
                    raise ValueError("cleanup boom")
                async with cleanup_step("staging table", job_id="job-77"):
                    later_steps.append("staging table")
                async with cleanup_step("token purge", job_id="job-77"):
                    later_steps.append("token purge")

    assert later_steps == ["staging table", "token purge"]
    failed = [e["step"] for e in captured if e["event"] == "ingest_cleanup_step_failed"]
    assert failed == ["heartbeat"]


async def test_cancellation_is_not_swallowed():
    """A worker shutdown must still reach the task it is shutting down.

    ``CancelledError`` is a ``BaseException``, so the helper's ``except
    Exception`` has to let it through. Swallowing it would leave the worker
    waiting on a task that reported itself finished.
    """
    with pytest.raises(asyncio.CancelledError):
        async with cleanup_step("heartbeat", job_id="job-77"):
            raise asyncio.CancelledError()


async def test_the_logged_message_is_redacted():
    """A cleanup exception can carry a credentialed URL; the log must not."""
    token = "SECRETTOKEN123"
    url = f"https://services.example.com/svc/FeatureServer/0?f=json&token={token}"

    with structlog.testing.capture_logs() as captured:
        async with cleanup_step("downloaded source", job_id="job-77"):
            raise RuntimeError(f"Client error '401 Unauthorized' for url '{url}'")

    entry = next(e for e in captured if e["event"] == "ingest_cleanup_step_failed")
    assert token not in entry["error"]
    assert token not in repr(entry)

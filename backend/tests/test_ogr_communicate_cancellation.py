"""F11: client-disconnect cancellation must kill the ogr2ogr child.

``asyncio.wait_for`` re-raises ``CancelledError`` on outer-task cancellation
without touching the awaited subprocess, so `_communicate_with_timeout`'s
pre-fix code — which only caught `asyncio.TimeoutError` — let a cancelled
caller unwind while the child kept running with nothing left to reap it.
Three ``BaseHTTPMiddleware`` subclasses cancel the downstream task on
``http.disconnect``, so this is reachable from a real client disconnect
during export or ingest, not just a contrived test.
"""

import asyncio

import pytest

from app.processing.ingest.ogr import _communicate_with_timeout


@pytest.mark.asyncio
async def test_cancellation_kills_the_child_process():
    """Cancelling the task awaiting `_communicate_with_timeout` must kill the
    underlying subprocess and re-raise CancelledError, not leave the child
    running with the caller already unwound.
    """
    proc = await asyncio.create_subprocess_exec(
        "sleep",
        "30",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    task = asyncio.ensure_future(
        _communicate_with_timeout(proc, timeout=60, tool_name="test")
    )
    # Let the subprocess start and _communicate_with_timeout begin awaiting it.
    await asyncio.sleep(0.2)
    assert proc.returncode is None, "child should still be running before cancel"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The assertion that fails pre-fix: without the CancelledError branch,
    # the `sleep 30` child is still running and this wait_for times out.
    await asyncio.wait_for(proc.wait(), timeout=5)
    assert proc.returncode is not None


@pytest.mark.asyncio
async def test_timeout_still_kills_the_child_process():
    """Regression guard: the pre-existing timeout-kill path must survive the
    refactor into the shared `_kill_and_reap_subprocess` helper.
    """
    from app.processing.ingest.ogr import IngestionError

    proc = await asyncio.create_subprocess_exec(
        "sleep",
        "30",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    with pytest.raises(IngestionError):
        await _communicate_with_timeout(proc, timeout=0.1, tool_name="test")

    await asyncio.wait_for(proc.wait(), timeout=5)
    assert proc.returncode is not None

"""fix(#435 codex r2/r3/r4): threaded I/O must finish before cancellation returns.

`run_in_thread_draining` backs the local-storage copy, the manifest HTTP download, and
the shapefile export zip. `asyncio.to_thread` cannot stop a running thread, so returning
on cancellation while the thread still owns a file descriptor races the caller's
close/unlink and truncates the artifact. These tests pin the drain directly, so they
cover all three call sites.
"""

import asyncio
import time

import pytest

from app.core.async_io import run_in_thread_draining


async def test_returns_the_thread_result() -> None:
    assert await run_in_thread_draining(lambda: 21 * 2) == 42


async def test_propagates_the_thread_exception() -> None:
    def _boom() -> None:
        raise OSError("No space left on device")

    with pytest.raises(OSError, match="No space left"):
        await run_in_thread_draining(_boom)


async def test_single_cancellation_drains_the_thread() -> None:
    state = {"done": False}

    def _slow() -> None:
        time.sleep(0.1)
        state["done"] = True

    task = asyncio.create_task(run_in_thread_draining(_slow))
    await asyncio.sleep(0.02)  # let the thread start
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert state["done"], "returned before the thread finished"


async def test_repeated_cancellation_still_drains_the_thread() -> None:
    """A second cancel (shutdown after a timeout) must not abandon the thread."""
    state = {"done": False}

    def _slow() -> None:
        time.sleep(0.15)
        state["done"] = True

    task = asyncio.create_task(run_in_thread_draining(_slow))
    await asyncio.sleep(0.02)

    for _ in range(30):
        task.cancel()
        await asyncio.sleep(0.005)
        if task.done():
            break

    with pytest.raises(asyncio.CancelledError):
        await task

    assert state["done"], "hammered cancellation returned before the thread finished"


async def test_cancellation_does_not_leak_the_thread_exception() -> None:
    """If the drained thread raised, its exception is retrieved, not re-raised.

    The caller asked to cancel; that is what they get. A leaked exception would show up
    as an "exception was never retrieved" warning at GC.
    """

    def _slow_then_raise() -> None:
        time.sleep(0.08)
        raise OSError("write failed during shutdown")

    task = asyncio.create_task(run_in_thread_draining(_slow_then_raise))
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

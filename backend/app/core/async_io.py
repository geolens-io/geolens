"""Cancellation-safe threaded I/O (fix(#435 codex r2/r3/r4)).

`asyncio.to_thread` offloads a blocking call, but cancelling the awaiting task does
NOT stop the thread — it is already running. When that thread owns a file descriptor
(streaming a large upload to disk, zipping an export, copying a COG into storage), an
early return lets the caller's cleanup close or delete the file while the thread is
still writing to it: a truncated artifact, a fd race, or a thread exception nobody
retrieves. Worker shutdown and client disconnect both hit exactly this.

`run_in_thread_draining` waits for the thread to finish before propagating the
cancellation, and keeps waiting through repeated cancellations (a shutdown that
cancels again while we are draining), so the thread has always released the fd by the
time control returns to the caller.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

_T = TypeVar("_T")


async def await_draining(awaitable: Awaitable[_T]) -> _T:
    """Await async provider I/O to completion before propagating cancellation."""
    task = asyncio.ensure_future(awaitable)
    cancelled: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc
    if cancelled is not None:
        if not task.cancelled():
            task.exception()
        raise cancelled
    return task.result()


async def run_in_thread_draining(fn: Callable[..., _T], *args: Any) -> _T:
    """Run ``fn(*args)`` in a worker thread; on cancellation, drain it first.

    Returns the thread's result, or raises whatever the thread raised. On
    cancellation, waits for the thread to complete (absorbing further cancels) and
    then re-raises ``CancelledError`` — never returns while the thread is still live.
    """
    fut = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    # `asyncio.wait` waits on `fut` without cancelling it and without logging its
    # exception (unlike `asyncio.shield`, which logs a cancelled shield's inner
    # exception even after we retrieve it). The loop keeps waiting through repeated
    # cancellations, so a running thread is never abandoned.
    cancelled: asyncio.CancelledError | None = None
    while not fut.done():
        try:
            await asyncio.wait({fut})
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc

    if cancelled is not None:
        if not fut.cancelled():
            fut.exception()  # retrieve it so it is not flagged never-retrieved
        raise cancelled
    return fut.result()


async def run_in_thread_draining_capture_cancel(
    fn: Callable[..., _T], *args: Any
) -> tuple[_T, asyncio.CancelledError | None]:
    """Drain a thread and return its result plus any cancellation request.

    Resource-creating calls sometimes need the completed result (for example,
    an S3 multipart upload id) to undo the side effect before cancellation is
    propagated. Callers must perform that cleanup and then raise the returned
    ``CancelledError``.
    """
    fut = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    cancelled: asyncio.CancelledError | None = None
    while not fut.done():
        try:
            await asyncio.wait({fut})
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc
    return fut.result(), cancelled

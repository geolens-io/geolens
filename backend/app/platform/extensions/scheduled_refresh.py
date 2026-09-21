"""Lifecycle port for optional scheduled-refresh worker services.

Core starts this port only while the Procrastinate connection is open. The
community implementation intentionally does nothing and advertises no feature;
an overlay supplies a lifecycle only when it also supplies scheduled-sync work.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    from procrastinate import App


@runtime_checkable
class ScheduledRefreshLifecycle(Protocol):
    """Own optional scheduler/dispatcher tasks for one worker process."""

    async def start(self, *, task_app: "App") -> None:
        """Register and start lifecycle work after the queue connection opens."""

    async def stop(self) -> None:
        """Stop and join lifecycle work before the queue connection closes."""


class DefaultScheduledRefreshLifecycle:
    """Community default: no scheduler, dispatcher, or advertised capability."""

    async def start(self, *, task_app: "App") -> None:
        del task_app

    async def stop(self) -> None:
        return None


@asynccontextmanager
async def supervised_scheduled_refresh_lifecycle(
    lifecycle: ScheduledRefreshLifecycle, *, task_app: "App"
) -> AsyncIterator[None]:
    """Keep lifecycle shutdown inside the queue connector lifetime."""
    await lifecycle.start(task_app=task_app)
    try:
        yield
    finally:
        await lifecycle.stop()

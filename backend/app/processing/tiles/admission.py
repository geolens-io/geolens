"""Bound uncached vector and cluster work in each API process."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings
from app.processing.tiles.responses import tile_busy_error

# A cold map view requests dozens of tiles at once. A short queue absorbs that
# burst; the waiter cap rejects a larger flood instead of parking it.
_SLOT_WAIT_SECONDS = 2.0
_MAX_SLOT_WAITERS = 2 * settings.tile_pool_max_size

_render_slots = asyncio.BoundedSemaphore(settings.tile_pool_max_size)
_slot_waiters = 0


async def _acquire_render_slot() -> None:
    global _slot_waiters
    if not _render_slots.locked():
        await _render_slots.acquire()
        return
    if _slot_waiters >= _MAX_SLOT_WAITERS:
        raise tile_busy_error()
    _slot_waiters += 1
    try:
        await asyncio.wait_for(_render_slots.acquire(), _SLOT_WAIT_SECONDS)
    except TimeoutError:
        raise tile_busy_error()
    finally:
        _slot_waiters -= 1


@asynccontextmanager
async def tile_render_slot(tenant_sem: Any = None) -> AsyncIterator[None]:
    """Admit tenant work before reserving shared capacity; release on every exit.

    A full budget queues the request briefly, then answers 429.
    """
    if tenant_sem is not None:
        try:
            acquired = await asyncio.wait_for(tenant_sem.acquire(), timeout=10.0)
            if not acquired:
                raise TimeoutError
        except TimeoutError:
            raise tile_busy_error(
                "Tile concurrency limit reached for tenant, please retry"
            )
    try:
        await _acquire_render_slot()
        try:
            yield
        finally:
            _render_slots.release()
    finally:
        if tenant_sem is not None:
            tenant_sem.release()

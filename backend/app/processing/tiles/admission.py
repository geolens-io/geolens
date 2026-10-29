"""Bound uncached tile renders in each API process."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings
from app.processing.tiles.responses import tile_busy_error

# A cold map view requests dozens of tiles at once. A short queue absorbs that
# burst; the waiter cap rejects a larger flood instead of parking it.
_SLOT_WAIT_SECONDS = 2.0


class _RenderBudget:
    """Concurrent render slots behind a short, capped queue."""

    def __init__(self, size: int) -> None:
        self.slots = asyncio.BoundedSemaphore(size)
        self.max_waiters = 2 * size
        self.waiters = 0

    async def acquire(self) -> None:
        """Take a slot, or raise the 429 once the queue is full or times out."""
        if not self.slots.locked():
            await self.slots.acquire()
            return
        if self.waiters >= self.max_waiters:
            raise tile_busy_error()
        self.waiters += 1
        try:
            await asyncio.wait_for(self.slots.acquire(), _SLOT_WAIT_SECONDS)
        except TimeoutError:
            raise tile_busy_error()
        finally:
            self.waiters -= 1

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one slot for the body; release on every exit."""
        await self.acquire()
        try:
            yield
        finally:
            self.slots.release()


_vector_renders = _RenderBudget(settings.tile_pool_max_size)
# Raster renders load Titiler rather than the tile pool, so neither kind can
# starve the other. No setting describes Titiler's capacity; the vector size
# already fits a cold map view's burst.
_raster_renders = _RenderBudget(settings.tile_pool_max_size)


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
        async with _vector_renders.slot():
            yield
    finally:
        if tenant_sem is not None:
            tenant_sem.release()


@asynccontextmanager
async def raster_render_slot() -> AsyncIterator[None]:
    """Hold one raster render slot; a full budget queues briefly, then answers 429."""
    async with _raster_renders.slot():
        yield

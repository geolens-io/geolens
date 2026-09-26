"""Bound uncached vector and cluster work in each API process."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore
from typing import Any

from app.core.config import settings
from app.processing.tiles.responses import tile_busy_error

_render_slots = BoundedSemaphore(settings.tile_pool_max_size)


@asynccontextmanager
async def tile_render_slot(tenant_sem: Any = None) -> AsyncIterator[None]:
    """Admit tenant work before reserving shared capacity; release on every exit."""
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
        if not _render_slots.acquire(blocking=False):
            raise tile_busy_error()
        try:
            yield
        finally:
            _render_slots.release()
    finally:
        if tenant_sem is not None:
            tenant_sem.release()

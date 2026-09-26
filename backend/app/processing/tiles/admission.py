"""Bound uncached vector and cluster work in each API process."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore

from app.core.config import settings
from app.processing.tiles.responses import tile_busy_error

_render_slots = BoundedSemaphore(settings.tile_pool_max_size)


@contextmanager
def tile_render_slot() -> Iterator[None]:
    """Admit one render without queueing; release on every exit, including cancellation."""
    if not _render_slots.acquire(blocking=False):
        raise tile_busy_error()
    try:
        yield
    finally:
        _render_slots.release()

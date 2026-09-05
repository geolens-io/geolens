"""The one lock order for the (datasets, records) row pair (#1847).

Lives in ``platform/`` because ``processing/`` may not import
``app.modules.catalog``: worker callers pass the mapped classes the port hands
them.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import is_lock_conflict

# The budget a REQUEST spends waiting for the pair. A worker passes
# ``lock_timeout=None``: ``SET LOCAL`` applies for the rest of the transaction,
# and this budget would fail an ingest on contention it must wait out.
REQUEST_LOCK_TIMEOUT = "2s"

# Resolved at call time, not bound as a default, so the constant above stays
# the single source of truth.
_USE_REQUEST_DEFAULT: Any = object()


# The machine-readable code for a contended row, wherever it is reported: the
# 409 body, and a bulk-delete item that carries its conflict instead of raising.
CATALOG_LOCK_CONFLICT_CODE = "catalog_lock_conflict"


# fix(#1847): set when THIS request installed the catalog timeout, so the
# boundary handler does not read an unrelated 40P01 as a busy dataset.
catalog_timeout_installed: ContextVar[bool] = ContextVar(
    "catalog_timeout_installed", default=False
)


class CatalogLockConflict(Exception):
    """Another transaction holds the catalog rows this one needs.

    One handler (``app/api/main.py``) answers 409 for it, wherever the
    acquisition was reached from. A worker lets it propagate and fails its job.
    """


async def lock_catalog_rows(
    session: AsyncSession,
    *,
    dataset_cls: Any,
    record_cls: Any,
    dataset_id: Any,
    record_id: Any,
    lock_timeout: str | None = _USE_REQUEST_DEFAULT,
    raster_asset_cls: Any = None,
) -> None:
    """Lock the catalog rows for a write: ``raster_assets`` (when given), then
    ``datasets``, then ``records``.

    Call it before the transaction's first write to either row, and after any
    network I/O or data-table work. A writer that touches "only" one row still
    needs it: stamping ``record.updated_by`` and rolling ``tile_cache_version``
    is both, and the ORM flushes ``records`` before ``datasets`` on its own.

    ``raster_asset_cls`` puts the raster child at the front of the order, for a
    transaction that will also reach ``raster_assets``.

    Raises ``CatalogLockConflict`` on 55P03 or 40P01, having rolled back.
    """
    if lock_timeout is _USE_REQUEST_DEFAULT:
        lock_timeout = REQUEST_LOCK_TIMEOUT
    if lock_timeout is not None:
        # `SET LOCAL` takes a literal; this value is a constant, never
        # request-supplied.
        await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
        # Each request runs in its own task, so this cannot leak across them.
        catalog_timeout_installed.set(True)

    # `no_autoflush` so the order below is what reaches PostgreSQL: an
    # autoflush here emits the ORM's own order, which is the inversion.
    try:
        with session.no_autoflush:
            if raster_asset_cls is not None:
                await session.execute(
                    select(raster_asset_cls.dataset_id)
                    .where(raster_asset_cls.dataset_id == dataset_id)
                    .with_for_update()
                )
            # One column on each table alone; a joined relationship would not
            # lock the joined row and would touch records first.
            await session.execute(
                select(dataset_cls.id)
                .where(dataset_cls.id == dataset_id)
                .with_for_update()
            )
            if record_id is not None:
                await session.execute(
                    select(record_cls.id)
                    .where(record_cls.id == record_id)
                    .with_for_update()
                )
    except DBAPIError as exc:
        if not is_lock_conflict(exc):
            raise
        # Roll back so the caller's retry is clean. Nothing is read off an ORM
        # instance after this: rollback expires them, and a lazy load from the
        # exception handler would raise MissingGreenlet instead of the 409.
        await session.rollback()
        raise CatalogLockConflict(
            "Another operation is updating this dataset's catalog entry."
        ) from exc

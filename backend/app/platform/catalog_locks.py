"""The one lock order for the (datasets, records) row pair (#1847).

Lives in ``platform/`` because ``processing/`` may not import
``app.modules.catalog``: worker callers pass the mapped classes the port hands
them.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

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


# fix(#1847, #1890): true from the SET LOCAL until the transaction that ran it
# commits, so the boundary handler answers 409 only for a wait inside it.
catalog_timeout_installed: ContextVar[bool] = ContextVar(
    "catalog_timeout_installed", default=False
)

_MARKER_LISTENER_KEY = "catalog_timeout_marker_listener"


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
    await _install_lock_timeout(session, lock_timeout)

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
        await _raise_rolled_back_conflict(session, exc)


async def lock_ingest_jobs(
    session: AsyncSession,
    *,
    job_cls: Any,
    dataset_id: Any,
    lock_timeout: str | None = _USE_REQUEST_DEFAULT,
) -> None:
    """Take a dataset's ingest-job rows, ahead of :func:`lock_catalog_rows`.

    For a transaction whose delete cascades into ``ingest_jobs``: a worker
    holds its job row before any data-table or catalog lock, so the deleter
    takes those rows before either. Same timeout and exception contract.
    """
    await _install_lock_timeout(session, lock_timeout)
    try:
        with session.no_autoflush:
            await session.execute(
                select(job_cls.id)
                .where(job_cls.dataset_id == dataset_id)
                .with_for_update()
            )
    except DBAPIError as exc:
        if not is_lock_conflict(exc):
            raise
        await _raise_rolled_back_conflict(session, exc)


async def _install_lock_timeout(
    session: AsyncSession, lock_timeout: str | None
) -> None:
    if lock_timeout is _USE_REQUEST_DEFAULT:
        lock_timeout = REQUEST_LOCK_TIMEOUT
    if lock_timeout is not None:
        # `SET LOCAL` takes a literal; this value is a constant, never
        # request-supplied.
        await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
        _clear_marker_on_commit(session)
        # Each request runs in its own task, so this cannot leak across them.
        catalog_timeout_installed.set(True)


def _clear_marker_on_commit(session: AsyncSession) -> None:
    """Register, once per session, the commit listener that ends the marker.

    The listener runs inside ``commit()`` on the request's own task, so the
    reset lands in the context that set the marker.
    """
    if session.info.get(_MARKER_LISTENER_KEY):
        return
    session.info[_MARKER_LISTENER_KEY] = True
    event.listen(session.sync_session, "after_commit", _forget_lock_timeout)


def _forget_lock_timeout(_session: Any) -> None:
    catalog_timeout_installed.set(False)


async def _raise_rolled_back_conflict(session: AsyncSession, exc: DBAPIError) -> None:
    # Roll back so the caller's retry is clean. Nothing is read off an ORM
    # instance after this: rollback expires them, and a lazy load from the
    # exception handler would raise MissingGreenlet instead of the 409.
    await session.rollback()
    raise CatalogLockConflict(
        "Another operation is updating this dataset's catalog entry."
    ) from exc


async def bump_tile_cache_version_atomic(
    session: AsyncSession, *, dataset_cls: Any, dataset_id: Any
) -> int | None:
    """Roll ``tile_cache_version`` in the database and return the new value.

    ``coalesce(tile_cache_version, 1) + 1``, evaluated against the row at
    write time, so a counter read before a lock wait is never written back
    over a peer's commit. Call it in the same transaction as the tile-content
    change it describes. None when the row no longer exists.
    """
    return await session.scalar(
        update(dataset_cls)
        .where(dataset_cls.id == dataset_id)
        .values(tile_cache_version=func.coalesce(dataset_cls.tile_cache_version, 1) + 1)
        .returning(dataset_cls.tile_cache_version)
        .execution_options(synchronize_session=False)
    )


async def bump_tile_cache_version_on(session: AsyncSession, dataset: Any) -> int | None:
    """:func:`bump_tile_cache_version_atomic` for a loaded ``Dataset`` instance.

    The instance's ``tile_cache_version`` is set to the returned value without
    marking it dirty, so a later reader sees what was published and the flush
    does not write it back. The one spelling for a request handler, whose
    instance was loaded before it waited for the row.
    """
    version = await bump_tile_cache_version_atomic(
        session, dataset_cls=type(dataset), dataset_id=dataset.id
    )
    if version is not None:
        set_committed_value(dataset, "tile_cache_version", version)
    return version

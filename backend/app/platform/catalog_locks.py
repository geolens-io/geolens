"""The one lock order for the (datasets, records) row pair (fix(#1847)).

Lives in ``platform/`` because both halves of the application need it:
``processing/`` may not import ``app.modules.catalog``, so worker callers pass
the mapped classes ``ProcessingPort`` hands them.
"""

from __future__ import annotations

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


class CatalogLockConflict(Exception):
    """Another transaction holds the catalog rows this one needs.

    Raised instead of a bare ``DBAPIError`` so one handler
    (``app/api/main.py``) answers 409 wherever the acquisition is reached from.
    A worker lets it propagate and fails its job.
    """


async def lock_catalog_rows(
    session: AsyncSession,
    *,
    dataset_cls: Any,
    record_cls: Any,
    dataset_id: Any,
    record_id: Any,
    lock_timeout: str | None = _USE_REQUEST_DEFAULT,
) -> None:
    """Take the datasets row, then the records row.

    **THE ORDER: datasets first, records second.** Call this from any
    transaction that will write both rows, before it writes either, and after
    any network I/O or data-table work it does. Cite this docstring rather than
    restating the rule.

    The order is the one the refresh workers and the VRT publish already take,
    to make a superseded-content check and its dependent write indivisible.

    Calling it is not optional for a writer that "only" touches one row.
    Stamping ``record.updated_by`` and rolling ``tile_cache_version`` is both,
    and SQLAlchemy flushes ``catalog.records`` first because
    ``Dataset.record_id`` makes ``Record`` the parent mapper. A transaction
    that acquires nothing therefore inverts by default. The acquisition must
    precede the transaction's FIRST write to either row, not merely sit in the
    same flush as both.

    Raises ``CatalogLockConflict`` on 55P03 or 40P01, having rolled back.
    """
    if lock_timeout is _USE_REQUEST_DEFAULT:
        lock_timeout = REQUEST_LOCK_TIMEOUT
    if lock_timeout is not None:
        # `SET LOCAL` takes a literal; this value is a constant, never
        # request-supplied.
        await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))

    # `no_autoflush` so the order below is what reaches PostgreSQL: an
    # autoflush here emits the ORM's own order, which is the inversion.
    try:
        with session.no_autoflush:
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

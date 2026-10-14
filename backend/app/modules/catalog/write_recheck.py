"""Write guards checked again once the write holds its row lock.

A write guard runs when a request starts, and the row lock comes later, just
before the write. An ownership transfer, a role change, a deactivation or a
visibility change can land in between. The guard records the writer it
admitted on the session; the lock helper re-checks that writer against the
rows as committed once it holds the lock, which also holds off a transfer
until the write commits.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from weakref import ReferenceType, WeakKeyDictionary, ref

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.permissions import user_standing_columns


@dataclass
class _AdmittedWriter:
    user: Identity
    # The transaction that last re-checked this writer under the row lock. A
    # weak reference: a transaction refers to its session, which would then
    # never leave the registry below.
    rechecked_in: ReferenceType[Any] | None = None

    def rechecked_by(self, transaction: Any) -> bool:
        return self.rechecked_in is not None and self.rechecked_in() is transaction


# Per session, so an entry ends with the session that holds it.
_ADMITTED: WeakKeyDictionary[Any, dict[tuple[str, uuid.UUID], _AdmittedWriter]] = (
    WeakKeyDictionary()
)


def admit_writer(db: AsyncSession, key: tuple[str, uuid.UUID], user: Identity) -> None:
    """Record that a write guard admitted ``user`` to the object ``key`` names.

    Kept for the session, so a later transaction's lock re-checks it too.
    """
    admitted = _ADMITTED.setdefault(db.sync_session, {})
    if key not in admitted or admitted[key].user.id != user.id:
        admitted[key] = _AdmittedWriter(user)


async def recheck_admitted_writer(
    db: AsyncSession,
    key: tuple[str, uuid.UUID],
    columns: Sequence[Any],
    where: Any,
    enforce: Callable[[Identity, Any], Awaitable[None]],
) -> None:
    """Re-check the writer a guard admitted to ``key``. Call holding the row lock.

    One query reads ``columns`` of the row ``where`` names, the writer's role
    names as ``roles`` and whether the account is active as ``active``, all as
    committed now. ``enforce(user, row)`` raises to refuse; ``row`` is None
    when the row is gone. Runs once per transaction or savepoint, since the
    lock holds the row until that ends, and does nothing when no guard
    admitted a writer to ``key`` in this session.
    """
    sync_session = db.sync_session
    admitted = _ADMITTED.get(sync_session, {}).get(key)
    if admitted is None:
        return
    # A savepoint's rollback releases the row locks taken inside it.
    transaction = (
        sync_session.get_nested_transaction() or sync_session.get_transaction()
    )
    if admitted.rechecked_by(transaction):
        return
    statement = select(*columns, *user_standing_columns(admitted.user.id)).where(where)
    # A flush here would write ahead of the caller's lock order.
    with db.no_autoflush:
        row = (await db.execute(statement)).one_or_none()
    await enforce(admitted.user, row)
    admitted.rechecked_in = ref(transaction)


class _Committed:
    """``base`` with some attributes replaced by their committed values."""

    def __init__(self, base: Any, **values: Any) -> None:
        self.__dict__.update(values)
        self._base = base

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


async def recheck_dataset_write_access(db: AsyncSession, dataset: Any) -> None:
    """Re-run ``check_dataset_write_access`` for the writer it admitted, under
    the dataset's catalog row lock, with the same 404 or 403.

    The guard reads the record's owner, visibility and status and the
    writer's roles as committed now. Columns this request has changed but not
    flushed are not consulted.
    """
    from app.modules.catalog.authorization import (
        DATASET_WRITE_DENIED,
        check_dataset_write_access,
    )
    from app.modules.catalog.datasets.domain.models import Record

    async def enforce(user: Identity, row: Any) -> None:
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
            )
        if not row.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=DATASET_WRITE_DENIED
            )
        record = _Committed(
            dataset.record,
            created_by=row.created_by,
            visibility=row.visibility,
            record_status=row.record_status,
        )
        await check_dataset_write_access(
            db,
            _Committed(dataset, record=record),
            dataset.id,
            user,
            user_roles=set(row.roles),
        )

    await recheck_admitted_writer(
        db,
        ("dataset", dataset.id),
        (Record.created_by, Record.visibility, Record.record_status),
        Record.id == dataset.record_id,
        enforce,
    )

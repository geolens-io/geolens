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
from datetime import datetime
from typing import Any
from weakref import ReferenceType, WeakKeyDictionary, ref

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity, IdentityRole, IdentitySnapshot
from app.modules.auth.permissions import admitted_capabilities, user_standing_columns
from app.platform.extensions import get_permission_extension
from app.platform.request_credential import api_key_scope_refusal, is_publish_key


@dataclass
class _AdmittedWriter:
    user: Identity
    # Read at admission: a rollback since then expires an ORM caller, and an
    # attribute read would then load lazily, which an async session refuses.
    user_id: uuid.UUID
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
    if key not in admitted or admitted[key].user_id != user.id:
        admitted[key] = _AdmittedWriter(user, user.id)


async def recheck_admitted_writer(
    db: AsyncSession,
    key: tuple[str, uuid.UUID],
    columns: Sequence[Any],
    where: Any,
    enforce: Callable[[Identity, Any], Awaitable[None]],
) -> None:
    """Re-check the writer a guard admitted to ``key``. Call holding the row lock.

    One query reads ``columns`` of the row ``where`` names, the writer's role
    names as ``roles``, whether the account is active as ``active`` and the
    rest of its identity, all as committed now. ``enforce(user, row)`` gets
    that identity and raises to refuse; ``row`` is None when the row is gone.
    Then each capability ``require_permission`` admitted the writer under must
    still be granted to those roles, and a writer admitted to make something
    public under ``restrict_public_visibility`` must still be an admin, or
    403. Runs once per transaction or savepoint, since the lock holds the row
    until that ends, and does nothing when no guard admitted a writer to
    ``key`` in this session.
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
    statement = select(*columns, *user_standing_columns(admitted.user_id)).where(where)
    # A flush here would write ahead of the caller's lock order.
    with db.no_autoflush:
        row = (await db.execute(statement)).one_or_none()
    judged = row
    if row is not None and is_publish_key(db):
        # A publish key acts only on its owner's own objects, as the guard
        # judged it; the admitted capabilities below keep the real roles.
        judged = _Committed(row, roles=[r for r in row.roles if r != "admin"])
    # Not the caller object: its loaded roles predate any change since the guard.
    admitted.user = _committed_identity(admitted.user_id, judged)
    await enforce(admitted.user, judged)
    await _recheck_capabilities(db, admitted, set(row.roles))
    if not await public_visibility_still_allowed(
        db, admitted_public_visibility(db, admitted.user_id), set(row.roles)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=PUBLIC_VISIBILITY_DENIED
        )
    admitted.rechecked_in = ref(transaction)


def _committed_identity(user_id: uuid.UUID, row: Any) -> IdentitySnapshot:
    return IdentitySnapshot(
        id=user_id,
        username=getattr(row, "username", None),
        email=getattr(row, "email", None),
        is_active=bool(getattr(row, "active", False)),
        roles=tuple(IdentityRole(name) for name in getattr(row, "roles", ())),
        created_at=getattr(row, "created_at", None),
    )


async def _recheck_capabilities(
    db: AsyncSession, admitted: _AdmittedWriter, roles: set[str]
) -> None:
    # Against the matrix the request was admitted with: re-reading it would
    # cost a query, and a role change is what this re-check is for.
    capabilities, matrix = admitted_capabilities(db, admitted.user_id)
    for capability in sorted(capabilities):
        if not await get_permission_extension().check_permission(
            db, admitted.user, capability, user_roles=roles, permission_matrix=matrix
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {capability}",
            )


PUBLIC_VISIBILITY_DENIED = (
    "Public visibility is restricted to administrators on this instance. "
    "Choose a narrower visibility or ask an admin to make this content public."
)

_ADMITTED_PUBLIC_VISIBILITY = "admitted_public_visibility"


def admit_public_visibility(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Record that the restricted-public gate let ``user_id`` make something
    public in this session, as an admin."""
    db.info.setdefault(_ADMITTED_PUBLIC_VISIBILITY, set()).add(user_id)


def admitted_public_visibility(db: AsyncSession, user_id: uuid.UUID) -> bool:
    return user_id in db.info.get(_ADMITTED_PUBLIC_VISIBILITY, set())


def forget_public_visibility(db: AsyncSession, user_id: uuid.UUID) -> None:
    db.info.get(_ADMITTED_PUBLIC_VISIBILITY, set()).discard(user_id)


async def public_visibility_still_allowed(
    db: AsyncSession, admitted: bool, roles: set[str]
) -> bool:
    """Whether a write admitted to make something public may still do so.

    Only a write the restricted-public gate admitted is re-checked, and only
    while the restriction is still on: such a writer must still be an admin.
    """
    from app.core.persistent_config import RESTRICT_PUBLIC_VISIBILITY

    if not admitted or "admin" in roles:
        return True
    return not await RESTRICT_PUBLIC_VISIBILITY.get(db)


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


RECORD_WRITE_DENIED = "Not authorized to modify this record"


async def recheck_record_write_access(db: AsyncSession, record_id: uuid.UUID) -> None:
    """Re-run the record write guard for the writer it admitted, against the
    record's owner and the writer's roles as committed now. Call holding the
    record row."""
    from app.modules.catalog.datasets.domain.models import Record

    async def enforce(user: Identity, row: Any) -> None:
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Record not found"
            )
        if not row.active or (row.created_by != user.id and "admin" not in row.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=RECORD_WRITE_DENIED
            )

    await recheck_admitted_writer(
        db, ("record", record_id), (Record.created_by,), Record.id == record_id, enforce
    )


_VISIBILITY_ORDER = ("private", "restricted", "internal", "public")


async def refuse_publish_key_widening(
    db: AsyncSession,
    record_id: uuid.UUID,
    *,
    visibility: str | None,
    record_status: str | None,
) -> None:
    """Refuse a publish key a metadata change that widens a record's visibility
    or opens it to anonymous readers.

    A publish key may keep a record's visibility or narrow it. It may publish
    an internal or restricted draft, but not a public one, since publishing is
    what opens a public record to anonymous readers. Call holding the record
    row, so the values compared are the committed ones.
    """
    if not is_publish_key(db):
        return
    from app.modules.catalog.datasets.domain.models import Record

    with db.no_autoflush:
        now = (
            await db.execute(
                select(Record.visibility, Record.record_status).where(
                    Record.id == record_id
                )
            )
        ).one()
    if visibility is not None and _VISIBILITY_ORDER.index(
        visibility
    ) > _VISIBILITY_ORDER.index(now.visibility):
        raise api_key_scope_refusal("A publish key can't widen a dataset's visibility")
    if (
        (visibility or now.visibility) == "public"
        and record_status == "published"
        and now.record_status != "published"
    ):
        raise api_key_scope_refusal("A publish key can't publish a public dataset")


def refuse_stale_write(updated_at: datetime, expected: datetime | None) -> None:
    """409 ``stale_write`` when *updated_at*, read under the row lock, isn't
    the *expected* value the caller read; nothing when *expected* is None."""
    if expected is not None and updated_at != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_write",
                "message": (
                    "This changed after it was read, so nothing was written. "
                    "Read it again and retry."
                ),
            },
        )

"""Collection resolution and membership for publish manifests.

Every refusal is a code the caller turns into a job warning; none raises.
Write functions flush but never commit.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import is_lock_conflict
from app.core.identity import Identity
from app.core.permissions import MANAGE_COLLECTIONS
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.permissions import (
    admit_capabilities,
    get_effective_permissions,
    get_user_roles,
)
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.collections.service import (
    add_datasets_to_collection,
    check_collection_ownership,
    create_collection,
    get_collection,
    lock_collection_for_write,
)
from app.platform.catalog_locks import WORKER_LOCK_TIMEOUT
from app.platform.extensions import get_permission_extension

COLLECTION_REFUSED = "A033"


async def _may_manage_collections(session: AsyncSession, user: Identity) -> bool:
    """The check ``require_permission("manage_collections")`` makes on the
    router, recorded the same way so the collection lock makes it again.

    It reads the caller's full roles: a publish key narrows which objects its
    owner's admin role reaches, which the ownership check applies, not which
    capabilities the owner holds.
    """
    matrix = await get_effective_permissions(session)
    granted = await get_permission_extension().check_permission(
        session,
        user,
        MANAGE_COLLECTIONS,
        user_roles=await get_user_roles(session, user),
        permission_matrix=matrix,
    )
    if granted:
        admit_capabilities(session, user.id, (MANAGE_COLLECTIONS,), matrix)
    return granted


async def _by_name(session: AsyncSession, name: Any) -> Collection | None:
    found = await session.execute(select(Collection).where(Collection.name == name))
    return found.scalar_one_or_none()


async def _may_write_collection(
    session: AsyncSession, collection: Collection, user: Identity
) -> bool:
    if not await _may_manage_collections(session, user):
        return False
    try:
        await check_collection_ownership(session, collection, user)
    except HTTPException:
        return False
    return True


async def resolve_manifest_collection(
    session: AsyncSession,
    ref: Mapping[str, Any],
    user: Identity,
    *,
    may_create: bool,
) -> tuple[uuid.UUID | None, str | None]:
    """Resolve a manifest's ``{"id": ...}`` or ``{"name": ...}`` collection.

    Returns ``(collection_id, None)`` when the caller may add datasets to it,
    else ``(None, "A033")``. A name that matches nothing is created when
    ``may_create`` is set and the caller holds ``manage_collections``.
    """
    collection: Collection | None
    if ref.get("id") is not None:
        collection = await get_collection(session, uuid.UUID(str(ref["id"])))
    else:
        collection = await _by_name(session, ref.get("name"))

    if collection is not None:
        if await _may_write_collection(session, collection, user):
            return collection.id, None
        return None, COLLECTION_REFUSED

    name = ref.get("name")
    if not name or not may_create or not await _may_manage_collections(session, user):
        return None, COLLECTION_REFUSED
    # Flushed first: the savepoint would flush the caller's pending work
    # itself, and a failure there has to surface as the caller's error
    # rather than read as a lost name.
    await session.flush()
    try:
        # A savepoint keeps a lost name race from poisoning the caller's transaction.
        async with session.begin_nested():
            created = await create_collection(session, name, None, user.id)
    except IntegrityError:
        raced = await _by_name(session, name)
        if raced is None:
            raise
        if await _may_write_collection(session, raced, user):
            return raced.id, None
        return None, COLLECTION_REFUSED
    await audit_emit(
        session,
        AuditEvent(
            user_id=user.id,
            action="collection.create",
            resource_type="collection",
            resource_id=created.id,
            details={"name": name},
        ),
    )
    return created.id, None


async def _wait_for_collection(session: AsyncSession, collection_id: uuid.UUID) -> bool:
    """Take the collection row with a worker's patience; False when the wait fails.

    In a savepoint: ``lock_collection_for_write`` rolls back the whole
    transaction when its wait fails, which here would take the caller's new
    dataset with it.
    """
    previous = await session.scalar(text("SELECT current_setting('lock_timeout')"))
    savepoint = await session.begin_nested()
    try:
        await session.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": WORKER_LOCK_TIMEOUT},
        )
        await session.execute(
            select(Collection.id)
            .where(Collection.id == collection_id)
            .with_for_update(key_share=True)
        )
    except DBAPIError as exc:
        await savepoint.rollback()
        if not is_lock_conflict(exc):
            raise
        return False
    await savepoint.commit()
    await session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"), {"value": previous}
    )
    return True


async def add_dataset_to_manifest_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
    dataset_id: uuid.UUID,
    user: Identity,
) -> str | None:
    """Add a dataset to a collection the caller may modify.

    Returns ``None`` on success and ``"A033"`` when the collection is gone,
    the caller lacks ``manage_collections`` or ownership, or the collection row
    stays busy past ``WORKER_LOCK_TIMEOUT``. Call it after any slow work in
    the transaction, since the row is held until the caller commits.
    """
    collection = await get_collection(session, collection_id)
    if collection is None or not await _may_write_collection(session, collection, user):
        return COLLECTION_REFUSED
    if not await _wait_for_collection(session, collection_id):
        return COLLECTION_REFUSED
    try:
        # Held already, so this only re-checks the writer.
        await lock_collection_for_write(session, collection_id)
    except HTTPException:
        return COLLECTION_REFUSED
    await add_datasets_to_collection(session, collection_id, [dataset_id], user.id)
    return None

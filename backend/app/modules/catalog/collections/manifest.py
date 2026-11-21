"""Collection resolution and membership for publish manifests.

Every refusal is a code the caller turns into a job warning; none raises.
Write functions flush but never commit.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.permissions import MANAGE_COLLECTIONS
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.permissions import get_effective_permissions
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.collections.service import (
    add_datasets_to_collection,
    check_collection_ownership,
    create_collection,
    get_collection,
    lock_collection_for_write,
)
from app.platform.extensions import get_permission_extension

COLLECTION_REFUSED = "A033"


async def _may_manage_collections(session: AsyncSession, user: Identity) -> bool:
    """The check ``require_permission("manage_collections")`` makes on the router."""
    roles = await get_user_roles(session, user)
    return await get_permission_extension().check_permission(
        session,
        user,
        MANAGE_COLLECTIONS,
        user_roles=roles,
        permission_matrix=await get_effective_permissions(session),
    )


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
        found = await session.execute(
            select(Collection).where(Collection.name == ref.get("name"))
        )
        collection = found.scalar_one_or_none()

    if collection is not None:
        if await _may_write_collection(session, collection, user):
            return collection.id, None
        return None, COLLECTION_REFUSED

    name = ref.get("name")
    if not name or not may_create or not await _may_manage_collections(session, user):
        return None, COLLECTION_REFUSED
    try:
        # A savepoint keeps a lost name race from poisoning the caller's transaction.
        async with session.begin_nested():
            created = await create_collection(session, name, None, user.id)
    except IntegrityError:
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


async def add_dataset_to_manifest_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
    dataset_id: uuid.UUID,
    user: Identity,
) -> str | None:
    """Add a dataset to a collection the caller may modify.

    Returns ``None`` on success and ``"A033"`` when the collection is gone or
    the caller lacks ``manage_collections`` or ownership.
    """
    collection = await get_collection(session, collection_id)
    if collection is None or not await _may_write_collection(session, collection, user):
        return COLLECTION_REFUSED
    try:
        await lock_collection_for_write(session, collection_id)
    except HTTPException:
        return COLLECTION_REFUSED
    await add_datasets_to_collection(session, collection_id, [dataset_id], user.id)
    return None

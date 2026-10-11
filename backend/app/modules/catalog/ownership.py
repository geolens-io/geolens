"""Admin-only transfer of dataset and map ownership.

The owner is ``created_by`` on the dataset's record or on the map. Everything
keyed on that column follows it: the owner-or-admin write guards, private and
draft visibility, provenance detail and quota usage. Visibility, grants,
collection membership, embed and share tokens, API keys and job history stay
as they are.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.models import User
from app.modules.catalog.authorization import get_user_roles
from app.platform.extensions import get_permission_extension


def _refuse_target(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
    )


async def resolve_new_owner(
    db: AsyncSession,
    owner_id: uuid.UUID | None,
    *,
    actor_roles: set[str],
    capability: str,
) -> User:
    """Return the user an admin is handing an object to.

    Raises 403 unless the actor is an admin, whoever owns the object now.
    Raises 422 unless ``owner_id`` names an active user whose roles grant
    ``capability``, the permission that creating the same kind of object
    requires.
    """
    if "admin" not in actor_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin may transfer ownership.",
        )
    if owner_id is None:
        raise _refuse_target("owner_id cannot be null.")
    new_owner = await db.get(User, owner_id)
    if new_owner is None:
        raise _refuse_target("owner_id does not name a user.")
    if not new_owner.is_active:
        raise _refuse_target("The new owner's account is not active.")
    granted = await get_permission_extension().check_permission(
        db,
        new_owner,
        capability,
        user_roles=await get_user_roles(db, new_owner),
    )
    if not granted:
        raise _refuse_target(
            f"The new owner's role does not grant the {capability} permission."
        )
    return new_owner


async def _locked_owner(db: AsyncSession, owned: Any) -> uuid.UUID | None:
    # Reload under a row lock. With a stale loaded value, a concurrent
    # transfer would leave the audit row naming the wrong previous owner, and
    # the ORM would skip an UPDATE back to the value it still holds.
    await db.refresh(owned, attribute_names=["created_by"], with_for_update=True)
    return owned.created_by


def _transfer_details(
    previous: uuid.UUID | None, new_owner: User
) -> dict[str, str | None]:
    return {
        "previous_owner_id": str(previous) if previous is not None else None,
        "new_owner_id": str(new_owner.id),
    }


async def transfer_dataset_owner(
    db: AsyncSession,
    record: Any,
    dataset_id: uuid.UUID,
    new_owner: User,
    *,
    actor: Identity,
    ip_address: str | None,
) -> None:
    """Make ``new_owner`` the owner of the dataset and write one audit row.

    Call after the dataset's catalog rows are locked. A transfer to the
    current owner changes nothing and writes no row. Does not commit.
    """
    previous = await _locked_owner(db, record)
    if previous == new_owner.id:
        return
    record.created_by = new_owner.id
    record.updated_by = actor.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=actor.id,
            action="dataset.transfer_owner",
            resource_type="dataset",
            resource_id=dataset_id,
            details=_transfer_details(previous, new_owner),
            ip_address=ip_address,
        ),
    )


async def transfer_map_owner(
    db: AsyncSession,
    map_obj: Any,
    new_owner: User,
    *,
    actor: Identity,
    ip_address: str | None,
) -> None:
    """Make ``new_owner`` the owner of the map and write one audit row.

    A transfer to the current owner changes nothing and writes no row. Does
    not commit.
    """
    previous = await _locked_owner(db, map_obj)
    if previous == new_owner.id:
        return
    map_obj.created_by = new_owner.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=actor.id,
            action="map.transfer_owner",
            resource_type="map",
            resource_id=map_obj.id,
            details=_transfer_details(previous, new_owner),
            ip_address=ip_address,
        ),
    )

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
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.permissions import EDIT_METADATA, UPLOAD
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.service import get_user_identity
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.maps.service import (
    filter_layer_rows_by_dataset_visibility,
    get_map_with_layers,
    terrain_dataset_ids_visible_to,
)
from app.platform.catalog_locks import bump_publication_version_on
from app.platform.extensions import get_permission_extension
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import ACTIVE_RUN_STATUSES


def _unprocessable(detail: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
    )


def require_transfer_admin(
    actor_roles: set[str], owner_id: uuid.UUID | None
) -> uuid.UUID:
    """Return ``owner_id`` when an admin may hand the object to it.

    Raises 403 unless the actor is an admin, whoever owns the object now, and
    422 for a null ``owner_id``. The target account is vetted by the
    ``transfer_*_owner`` call, once the owner is known to change.
    """
    if "admin" not in actor_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin may transfer ownership.",
        )
    if owner_id is None:
        raise _unprocessable("owner_id cannot be null.")
    return owner_id


async def _vet_new_owner(
    db: AsyncSession, owner_id: uuid.UUID, capability: str
) -> Identity:
    # ``capability`` is the permission creating the same kind of object needs.
    new_owner = await get_user_identity(db, owner_id)
    if new_owner is None:
        raise _unprocessable("owner_id does not name a user.")
    if not new_owner.is_active:
        raise _unprocessable("The new owner's account is not active.")
    granted = await get_permission_extension().check_permission(
        db,
        new_owner,
        capability,
        user_roles=await get_user_roles(db, new_owner),
    )
    if not granted:
        raise _unprocessable(
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
    previous: uuid.UUID | None, new_owner: Identity
) -> dict[str, str | None]:
    return {
        "previous_owner_id": str(previous) if previous is not None else None,
        "new_owner_id": str(new_owner.id),
    }


async def transfer_dataset_owner(
    db: AsyncSession,
    dataset: Any,
    owner_id: uuid.UUID,
    *,
    actor: Identity,
    ip_address: str | None,
) -> None:
    """Make ``owner_id`` the owner of the dataset and write one audit row.

    Call after the dataset's catalog rows are locked. A transfer to the
    current owner changes nothing, vets nothing and writes no row. Raises 422
    for a target that is unknown, inactive or lacks ``upload``, and 409 while
    a refresh or re-upload run is active. Does not commit.
    """
    record = dataset.record
    previous = await _locked_owner(db, record)
    if previous == owner_id:
        return
    new_owner = await _vet_new_owner(db, owner_id, UPLOAD)
    # A replacement or refresh admitted under the previous owner would
    # publish into the new owner's dataset after the transfer.
    if await db.scalar(
        select(
            exists().where(
                DatasetRefreshRun.dataset_id == dataset.id,
                DatasetRefreshRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "A refresh or re-upload is running for this dataset. "
                    "Wait for it to finish or cancel it, then transfer."
                ),
            },
        )
    record.created_by = new_owner.id
    record.updated_by = actor.id
    # Signed tile templates bind this counter, and the previous owner may
    # hold one for a dataset they can no longer read.
    await bump_publication_version_on(db, dataset)
    await audit_emit(
        db,
        AuditEvent(
            user_id=actor.id,
            action="dataset.transfer_owner",
            resource_type="dataset",
            resource_id=dataset.id,
            details=_transfer_details(previous, new_owner),
            ip_address=ip_address,
        ),
    )


async def _refuse_hidden_datasets(
    db: AsyncSession, map_id: uuid.UUID, new_owner: Identity
) -> None:
    """Refuse an owner who cannot read every dataset the map draws on.

    Owner-only map responses list layers unfiltered, so an owner who cannot
    read a layer's dataset would see its names and columns there.
    """
    map_obj, layer_rows, _, _ = await get_map_with_layers(db, map_id)
    visible = await filter_layer_rows_by_dataset_visibility(db, layer_rows, new_owner)
    visible_ids = {row.layer.dataset_id for row in visible}
    hidden = {
        str(row.layer.dataset_id)
        for row in layer_rows
        if row.layer.dataset_id not in visible_ids
    }
    terrain_id = (map_obj.terrain_config or {}).get("source_dataset_id")
    if terrain_id is not None and str(terrain_id) not in (
        await terrain_dataset_ids_visible_to(
            db, map_obj.terrain_config, visible_ids, new_owner
        )
    ):
        hidden.add(str(terrain_id))
    if hidden:
        raise _unprocessable(
            {
                "message": (
                    "The new owner cannot read every dataset this map uses. "
                    "Transfer or share those datasets first."
                ),
                "datasets": sorted(hidden),
            }
        )


async def transfer_map_owner(
    db: AsyncSession,
    map_obj: Any,
    owner_id: uuid.UUID,
    *,
    actor: Identity,
    ip_address: str | None,
) -> None:
    """Make ``owner_id`` the owner of the map and write one audit row.

    A transfer to the current owner changes nothing, vets nothing and writes
    no row. Raises 422 for a target that is unknown, inactive, lacks
    ``edit_metadata`` or cannot read every dataset the map uses. Does not
    commit.
    """
    previous = await _locked_owner(db, map_obj)
    if previous == owner_id:
        return
    new_owner = await _vet_new_owner(db, owner_id, EDIT_METADATA)
    await _refuse_hidden_datasets(db, map_obj.id, new_owner)
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

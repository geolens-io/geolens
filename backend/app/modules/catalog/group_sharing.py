"""Who may share a dataset or a map with which sharing groups.

An owner may add only groups they belong to, and an admin any group of the
item's tenant. An owner may keep or drop a group they have since left.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Select, delete, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import Group, GroupMember
from app.modules.auth.schemas import GroupRef


class UnknownGroupsError(LookupError):
    """Groups that don't exist, or belong to another tenant than the item."""

    def __init__(self, group_ids: Iterable[uuid.UUID]) -> None:
        super().__init__("Group not found")
        self.group_ids = sorted(group_ids)


class GroupNotJoinedError(PermissionError):
    """A non-admin owner named a group they don't belong to."""


async def lock_share_groups(
    session: AsyncSession,
    wanted: set[uuid.UUID],
    granted: Select[Any],
    tenant_id: uuid.UUID | None,
) -> None:
    """Lock ``wanted`` and the groups ``granted`` selects against deletion.

    Raises ``UnknownGroupsError`` for a wanted group that doesn't exist or
    belongs to another tenant than ``tenant_id``. Call before locking the
    item's own rows, the order a group deletion takes them.
    """
    found = await session.execute(
        select(Group.id, Group.tenant_id)
        .where(or_(Group.id.in_(wanted), Group.id.in_(granted)))
        .order_by(Group.id)
        .with_for_update(read=True, key_share=True)
    )
    usable = {row.id for row in found.all() if row.tenant_id == tenant_id}
    if wanted - usable:
        raise UnknownGroupsError(wanted - usable)


async def refuse_unjoined_groups(
    session: AsyncSession, added: set[uuid.UUID], actor: Identity, *, is_admin: bool
) -> None:
    """Raise ``GroupNotJoinedError`` when a non-admin adds a group they aren't in."""
    if not added or is_admin:
        return
    if added - await joined_groups(session, actor, added):
        raise GroupNotJoinedError


async def joined_groups(
    session: AsyncSession, actor: Identity, group_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """The groups of ``group_ids`` that ``actor`` belongs to."""
    return set(
        await session.scalars(
            select(GroupMember.group_id)
            .where(GroupMember.user_id == actor.id)
            .where(GroupMember.group_id.in_(set(group_ids)))
        )
    )


async def write_group_grants(
    session: AsyncSession,
    grant: type,
    item_key: str,
    item_id: uuid.UUID,
    *,
    added: set[uuid.UUID],
    removed: set[uuid.UUID],
    actor: Identity,
) -> None:
    """Delete ``removed`` and insert ``added`` grant rows of ``grant`` for the
    item its ``item_key`` column names."""
    if removed:
        await session.execute(
            delete(grant)
            .where(getattr(grant, item_key) == item_id)
            .where(grant.group_id.in_(removed))
        )
    if added:
        await session.execute(
            insert(grant).values(
                [
                    {item_key: item_id, "group_id": group_id, "granted_by": actor.id}
                    for group_id in sorted(added)
                ]
            )
        )


async def group_refs(session: AsyncSession, granted: Select[Any]) -> list[GroupRef]:
    """The groups ``granted`` selects, by name."""
    rows = await session.execute(
        select(Group.id, Group.name)
        .where(Group.id.in_(granted))
        .order_by(Group.name, Group.id)
    )
    return [GroupRef(id=row.id, name=row.name) for row in rows.all()]

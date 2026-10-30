"""Who may share a dataset, map or story with which sharing groups, and
what a group grant admits.

An owner may add only groups they belong to, and an admin any group of the
item's tenant. An owner may keep or drop a group they have since left.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    delete,
    exists,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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


def granted_group_member(
    grant: Any, item_key: str, item_id: Any, user_id: Any
) -> ColumnElement[bool]:
    """Whether ``user_id`` belongs to a group ``grant`` grants on the item its
    ``item_key`` column names."""
    member = exists().where(
        getattr(grant, item_key) == item_id,
        GroupMember.group_id == grant.group_id,
        GroupMember.user_id == user_id,
    )
    # Explicit: auto-correlation reaches only the immediately enclosing select.
    return member.correlate_except(grant, GroupMember)


async def unshare_sole_group_items(
    session: AsyncSession, item: Any, grant: Any, item_key: str, group_id: uuid.UUID
) -> None:
    """Make private the restricted ``item`` rows ``group_id`` is the last
    group of.

    Call holding the group's row lock, before its deletion cascades its grants
    away. Locks each item shared with the group, in id order, so concurrent
    deletions of an item's last two groups can't each count the other's grant
    as still there.
    """
    item_id = getattr(grant, item_key)
    shared = select(item_id).where(grant.group_id == group_id)
    await session.execute(
        select(item.id)
        .where(item.id.in_(shared))
        .order_by(item.id)
        .with_for_update(key_share=True)
    )
    other = aliased(grant)
    sole = shared.where(
        ~exists().where(getattr(other, item_key) == item_id, other.group_id != group_id)
    )
    await session.execute(
        update(item)
        .where(item.id.in_(sole))
        .where(item.visibility == "restricted")
        .values(visibility="private")
        .execution_options(synchronize_session=False)
    )

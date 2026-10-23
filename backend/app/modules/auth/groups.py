"""Sharing groups: admin-managed named sets of users."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Group, GroupMember, User


class GroupNotFoundError(LookupError):
    pass


class GroupMemberNotFoundError(LookupError):
    pass


class UnknownUsersError(LookupError):
    def __init__(self, user_ids: Sequence[uuid.UUID]) -> None:
        super().__init__("User not found")
        self.user_ids = list(user_ids)


async def get_group(
    db: AsyncSession, group_id: uuid.UUID, *, for_update: bool = False
) -> Group:
    stmt = select(Group).where(Group.id == group_id)
    if for_update:
        stmt = stmt.with_for_update()
    group = (await db.execute(stmt)).scalar_one_or_none()
    if group is None:
        raise GroupNotFoundError(group_id)
    return group


async def member_counts(
    db: AsyncSession, group_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not group_ids:
        return {}
    rows = await db.execute(
        select(GroupMember.group_id, func.count())
        .where(GroupMember.group_id.in_(group_ids))
        .group_by(GroupMember.group_id)
    )
    counts = {group_id: 0 for group_id in group_ids}
    counts.update({group_id: count for group_id, count in rows.all()})
    return counts


async def list_groups(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    member_id: uuid.UUID | None = None,
) -> tuple[list[Group], int]:
    """Groups by name and their total; only ``member_id``'s groups when given."""
    stmt = select(Group)
    if member_id is not None:
        stmt = stmt.where(
            Group.id.in_(
                select(GroupMember.group_id).where(GroupMember.user_id == member_id)
            )
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    groups = await db.scalars(
        stmt.order_by(Group.name, Group.id).offset(skip).limit(limit)
    )
    return list(groups), total


async def create_group(db: AsyncSession, name: str) -> Group:
    """Add a group; a duplicate name raises ``IntegrityError`` at flush."""
    group = Group(name=name)
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return group


async def rename_group(
    db: AsyncSession, group_id: uuid.UUID, name: str
) -> tuple[Group, str]:
    """Rename a group; return it and its previous name."""
    group = await get_group(db, group_id, for_update=True)
    previous = group.name
    group.name = name
    await db.flush()
    await db.refresh(group)
    return group, previous


async def delete_group(
    db: AsyncSession, group_id: uuid.UUID, *, id_limit: int
) -> tuple[str, int, list[uuid.UUID]]:
    """Delete a group and its memberships.

    Returns its name, its exact member count, and at most ``id_limit`` of its
    former members' ids.
    """
    group = await get_group(db, group_id, for_update=True)
    count = (await member_counts(db, [group_id]))[group_id]
    member_ids = (
        (
            await db.execute(
                select(GroupMember.user_id)
                .where(GroupMember.group_id == group_id)
                .order_by(GroupMember.user_id)
                .limit(id_limit)
            )
        )
        .scalars()
        .all()
    )
    name = group.name
    await db.delete(group)
    await db.flush()
    return name, count, list(member_ids)


async def list_members(
    db: AsyncSession, group_id: uuid.UUID, *, skip: int, limit: int
) -> tuple[list[tuple[uuid.UUID, str]], int]:
    await get_group(db, group_id)
    total = (await member_counts(db, [group_id]))[group_id]
    rows = await db.execute(
        select(User.id, User.username)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.username, User.id)
        .offset(skip)
        .limit(limit)
    )
    return [(row.id, row.username) for row in rows.all()], total


async def add_members(
    db: AsyncSession, group_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
) -> tuple[Group, list[uuid.UUID]]:
    """Add users to a group, all or none; return it and the users newly added."""
    group = await get_group(db, group_id, for_update=True)
    wanted = list(dict.fromkeys(user_ids))
    # KEY SHARE keeps each user from being deleted between this check and
    # the insert, so the FK can't fail after the check passed.
    found = set(
        (
            await db.execute(
                select(User.id)
                .where(User.id.in_(wanted))
                .with_for_update(read=True, key_share=True)
            )
        )
        .scalars()
        .all()
    )
    missing = [user_id for user_id in wanted if user_id not in found]
    if missing:
        raise UnknownUsersError(missing)
    inserted = await db.execute(
        insert(GroupMember)
        .values([{"group_id": group_id, "user_id": user_id} for user_id in wanted])
        .on_conflict_do_nothing(index_elements=["group_id", "user_id"])
        .returning(GroupMember.user_id)
    )
    return group, list(inserted.scalars().all())


async def remove_member(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await get_group(db, group_id, for_update=True)
    removed = await db.execute(
        delete(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .returning(GroupMember.user_id)
    )
    if removed.scalar_one_or_none() is None:
        raise GroupMemberNotFoundError(user_id)

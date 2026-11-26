"""Who may share a dataset, map or story with which sharing groups, and
what a group grant admits.

An owner may add only groups they belong to, and an admin any group of the
item's tenant. An owner may keep or drop a group they have since left.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
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
from app.platform.record_audience import widens_audience
from app.platform.request_credential import refuse_publish_key


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


async def lock_groups(
    session: AsyncSession, wanted: set[uuid.UUID], granted: Select[Any]
) -> None:
    """Lock ``wanted`` and the groups ``granted`` selects against deletion,
    whether or not they exist, as ``lock_share_groups`` does."""
    await session.execute(
        select(Group.id)
        .where(or_(Group.id.in_(wanted), Group.id.in_(granted)))
        .order_by(Group.id)
        .with_for_update(read=True, key_share=True)
    )


# The ``audience_before`` that says to judge a group change by the item's
# stored visibility, as the sharing routes do.
CURRENT_LEVEL = "current"


@dataclass(frozen=True)
class SharePlan:
    """What sharing an item with exactly some groups would leave.

    ``groups`` are the ones it ends with, by name. ``left_off`` names the
    wanted groups that don't exist, belong to another tenant, or that a
    non-admin would add without being a member; nothing else of them is
    known to the caller. ``held_back`` are the groups the item may not gain
    without reaching more people than it does, and ``added`` the groups it
    gains. ``unchanged`` means the item keeps its groups as they are, since
    the share was held back. ``granted`` are the item's groups when planned.
    """

    groups: list[GroupRef]
    left_off: list[uuid.UUID]
    held_back: list[GroupRef]
    added: list[GroupRef]
    unchanged: bool = False
    granted: frozenset[uuid.UUID] = frozenset()

    @property
    def group_ids(self) -> list[uuid.UUID]:
        return [group.id for group in self.groups]


def active_tenant_id(item: Any | None) -> uuid.UUID | None:
    """The tenant an item's groups must belong to: the stored item's, or the
    request's own for an item a publish is about to create."""
    if item is not None:
        return item.tenant_id
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tenant = current_tenant_var.get() if is_multi_tenant() else None
    return uuid.UUID(str(tenant)) if tenant else None


def level_with_groups(
    level: str, has_groups: bool, *, role_granted: bool = False
) -> str:
    """The visibility an item at ``level`` ends at with or without groups:
    grants make a private item restricted, and a restricted one left with no
    group, and no role grant, becomes private."""
    if level not in ("private", "restricted"):
        return level
    if has_groups or (level == "restricted" and role_granted):
        return "restricted"
    return "private"


async def plan_share_groups(
    session: AsyncSession,
    wanted: Iterable[uuid.UUID],
    current: set[uuid.UUID],
    actor: Identity,
    *,
    is_admin: bool,
    tenant_id: uuid.UUID | None,
) -> SharePlan:
    """Plan sharing an item granted ``current`` with exactly ``wanted``,
    leaving off what the sharing route would refuse instead of raising.

    A current group is kept when wanted, as the route keeps a group its
    owner has since left. Writes nothing.
    """
    wanted = set(wanted)
    rows = (
        await session.execute(
            select(Group.id, Group.name, Group.tenant_id).where(
                Group.id.in_(wanted | current)
            )
        )
    ).all()
    names = {row.id: row.name for row in rows if row.tenant_id == tenant_id}
    usable = wanted & set(names)
    added = usable - current
    if added and not is_admin:
        added &= await joined_groups(session, actor, added)

    def refs(ids: Iterable[uuid.UUID]) -> list[GroupRef]:
        return sorted(
            (GroupRef(id=group_id, name=names[group_id]) for group_id in ids),
            key=lambda ref: (ref.name, ref.id),
        )

    return SharePlan(
        groups=refs((usable & current) | added),
        left_off=sorted(wanted - (usable & current) - added),
        held_back=[],
        added=refs(added),
        granted=frozenset(current),
    )


def hold_back_widening(
    plan: SharePlan, before: str | None, level: str, *, role_granted: bool = False
) -> SharePlan:
    """``plan``, held back whole when it would let more people read the item
    than at ``before`` (None for an item the publish creates) once it is at
    ``level`` with the planned groups: the item then keeps its groups as they
    are. A restricted item would gain the groups it adds; a private one
    every planned group, retained ones too."""
    if before is None:
        return plan
    after = level_with_groups(level, bool(plan.groups), role_granted=role_granted)
    if not widens_audience(before, after, added_groups=bool(plan.added)):
        return plan
    held = plan.added if before == "restricted" else plan.groups
    return replace(plan, held_back=[*plan.held_back, *held], added=[], unchanged=True)


def hold_back_revoked(
    plan: SharePlan, granted_at_plan: Iterable[uuid.UUID]
) -> SharePlan:
    """``plan`` without the groups the item had when the share was planned
    and has lost since: a grant removed after the plan wins over it."""
    revoked = set(granted_at_plan) - plan.granted
    held = [group for group in plan.added if group.id in revoked]
    if not held:
        return plan
    return replace(
        plan,
        groups=[group for group in plan.groups if group.id not in revoked],
        added=[group for group in plan.added if group.id not in revoked],
        held_back=[*plan.held_back, *held],
    )


def refuse_publish_key_widening_share(
    session: AsyncSession, before: str | None, after: str, added: set[uuid.UUID]
) -> None:
    """Refuse a publish key a group change that lets more people read an
    item than at ``before``, None for one this transaction created: a wider
    level, retained grants taking effect included, or groups added to a
    restricted item."""
    if before is not None and widens_audience(before, after, added_groups=bool(added)):
        refuse_publish_key(
            session, "A publish key can't share an item with more people."
        )


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

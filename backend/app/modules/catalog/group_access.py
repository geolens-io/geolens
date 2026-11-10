"""Group membership changes that move who may read the group's datasets.

Adding or removing a member, or deleting a group, can change the audience of
every dataset granted to the group without writing the dataset. When the
group's active members change, outstanding tile signatures are retired. A
widening, which includes a member's account becoming active again, may not
let a VRT newly reach past one of its members; a narrowing is a revocation
and is never refused, so a VRT it leaves reaching past a member stops serving
tiles and a map stops showing the layer to whoever lost it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Group, GroupMember, User
from app.modules.catalog.authorization import (
    VRT_AUDIENCE_EXCEEDS_SOURCES,
    answers_audience_questions,
    vrt_links_beyond_audience,
)
from app.modules.catalog.datasets.domain.models import DatasetGroupGrant
from app.platform.catalog_locks import bump_publication_versions
from app.platform.extensions import get_permission_extension

T = TypeVar("T")


async def change_group_access(
    db: AsyncSession,
    group_id: uuid.UUID,
    change: Callable[[], Awaitable[T]],
    *,
    narrowing: bool,
) -> T:
    """Run ``change``, a membership change to ``group_id`` that flushes its
    writes, and return its result.

    Raises 422 when a widening change makes a VRT reach past one of its
    members. Does not commit.
    """
    await db.execute(select(Group.id).where(Group.id == group_id).with_for_update())
    granted = list(
        await db.scalars(
            select(DatasetGroupGrant.dataset_id).where(
                DatasetGroupGrant.group_id == group_id
            )
        )
    )
    if not granted:
        return await change()

    active_before = await _active_member_count(db, group_id)

    async def widened() -> bool:
        return await _active_member_count(db, group_id) > active_before

    if narrowing:
        result = await change()
    else:
        result = await _admit_widening(db, granted, change, widened)
    # Each change only adds or only removes, so the count shows whether it
    # granted or revoked anything.
    if await _active_member_count(db, group_id) != active_before:
        await bump_publication_versions(db, granted)
    return result


async def _active_member_count(db: AsyncSession, group_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(GroupMember)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .where(User.status == "active")
        .where(User.is_active.is_(True))
    )


async def reactivate_member_access(
    db: AsyncSession, user_id: uuid.UUID, change: Callable[[], Awaitable[T]]
) -> T:
    """Run ``change``, which makes ``user_id`` an active account again and
    flushes, and return its result.

    An inactive account is outside every audience, so its return widens each
    of its groups as adding it would, and gets the same 422. Does not commit.
    """
    group_ids = list(
        await db.scalars(
            select(Group.id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.user_id == user_id)
            .order_by(Group.id)
            .with_for_update(of=Group)
        )
    )
    granted = list(
        await db.scalars(
            select(DatasetGroupGrant.dataset_id)
            .where(DatasetGroupGrant.group_id.in_(group_ids))
            .distinct()
        )
    )
    if not granted:
        return await change()

    async def widened() -> bool:
        return bool(
            await db.scalar(
                select(User.is_active.is_(True) & (User.status == "active")).where(
                    User.id == user_id
                )
            )
        )

    return await _admit_widening(db, granted, change, widened)


async def _admit_widening(
    db: AsyncSession,
    granted: list[uuid.UUID],
    change: Callable[[], Awaitable[T]],
    widened: Callable[[], Awaitable[bool]],
) -> T:
    """Run ``change``; raise 422 if it makes a VRT linked to ``granted`` newly
    reach past one of its members.

    ``widened`` says, after ``change``, whether it added an active reader.
    """
    exceeded_before = await vrt_links_beyond_audience(db, granted)
    result = await change()
    exceeded_after = await vrt_links_beyond_audience(db, granted)
    if not answers_audience_questions(get_permission_extension()):
        # Such an authority has every link counted as exceeded, so nothing is
        # ever newly exceeded; refuse any real widening over a VRT link.
        if exceeded_after and await widened():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=VRT_AUDIENCE_EXCEEDS_SOURCES,
            )
        return result
    newly = sorted(
        {title for pair, title in exceeded_after.items() if pair not in exceeded_before}
    )
    if newly:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This change would let VRTs reach people who cannot see "
            f"all of their source datasets: {', '.join(newly)}",
        )
    return result

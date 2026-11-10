"""Sharing a story with groups.

A private story shared with a group becomes restricted: once published, the
group's members read it besides its owner and admins. A restricted story left
with no group is private again. Internal and public stories keep their
audience; their grants take effect once the story narrows to private. Each
scene's map stays behind its own guard, and a story can't newly reach a group
some of whose members can't read a map its published scenes use.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import groups_lacking_maps
from app.modules.catalog.group_sharing import (
    group_refs,
    lock_share_groups,
    refuse_unjoined_groups,
    unshare_sole_group_items,
    write_group_grants,
)
from app.modules.catalog.maps.service import (
    check_map_ownership,
    get_map,
    record_map_groups_change,
    set_map_groups,
)
from app.modules.catalog.stories.models import Story, StoryGroupGrant
from app.modules.catalog.stories.service import (
    RESTRICTED_STORY_VISIBILITY,
    StoryReachError,
    grouped_visibility,
    refuse_blocking_maps,
    scene_map_ids,
    story_grants,
    story_group_ids,
)

T = TypeVar("T")


@dataclass
class SharedMap:
    """A map shared with a story's groups on the way."""

    id: uuid.UUID
    name: str
    previous: str
    visibility: str
    group_ids: list[uuid.UUID]


@dataclass
class StoryShareResult:
    # The story's visibility before, or None when nothing changed.
    previous: str | None
    shared_maps: list[SharedMap] = field(default_factory=list)


async def story_groups(db: AsyncSession, story_id: uuid.UUID) -> list[GroupRef]:
    """The groups a story is shared with, by name."""
    return await group_refs(db, story_grants(story_id))


async def lock_story_groups(
    db: AsyncSession, story: Story, wanted: Iterable[uuid.UUID] = ()
) -> None:
    """Lock ``wanted`` and the story's groups against deletion.

    Call before ``lock_story``, the order a group deletion takes them. Raises
    ``UnknownGroupsError`` for a wanted group that doesn't exist or belongs to
    another tenant.
    """
    await lock_share_groups(db, set(wanted), story_grants(story.id), story.tenant_id)


async def story_visibility_for(
    db: AsyncSession, story_id: uuid.UUID, requested: str
) -> str:
    """The visibility a write of ``requested`` gives the story; see
    ``grouped_visibility``."""
    has_groups = await db.scalar(
        select(exists().where(StoryGroupGrant.story_id == story_id))
    )
    return grouped_visibility(requested, bool(has_groups))


async def unshare_group_stories(db: AsyncSession, group_id: uuid.UUID) -> None:
    """Make private the restricted stories ``group_id`` is the last group of; see
    ``unshare_sole_group_items``."""
    await unshare_sole_group_items(db, Story, StoryGroupGrant, "story_id", group_id)


async def audit_shared_maps(
    db: AsyncSession,
    shared: list[SharedMap],
    actor: Identity,
    ip_address: str | None,
    story_id: uuid.UUID,
) -> None:
    """Record each map a story write shared with its groups, as sharing the
    map itself does."""
    for map_ in shared:
        await record_map_groups_change(
            db,
            map_.id,
            map_.name,
            previous=map_.previous,
            group_ids=map_.group_ids,
            actor=actor,
            visibility=map_.visibility,
            ip_address=ip_address,
            details={"shared_with_story": str(story_id)},
        )


async def share_blocking_maps(
    db: AsyncSession, exc: StoryReachError, actor: Identity
) -> list[SharedMap]:
    """Share each map ``exc`` names with the groups that lack it, keeping the
    map's other groups, through the map sharing path and its guards. A
    private map becomes restricted; layers the groups can't read stay hidden
    from them. A map deleted since is skipped."""
    shared = []
    for blocking in sorted(exc.maps, key=lambda m: str(m.id)):
        map_obj = await get_map(db, blocking.id)
        if map_obj is None:
            continue
        roles = await check_map_ownership(map_obj, actor, db)
        result = await set_map_groups(
            db,
            map_obj,
            exc.lacking.get(blocking.id, ()),
            actor=actor,
            is_admin="admin" in roles,
            confirm="map_only",
            keep_current=True,
        )
        if result.previous is not None:
            shared.append(
                SharedMap(
                    map_obj.id,
                    map_obj.name,
                    result.previous,
                    map_obj.visibility,
                    result.group_ids,
                )
            )
    return shared


async def sharing_blocking_maps(
    db: AsyncSession,
    attempt: Callable[[], Awaitable[T]],
    actor: Identity,
    confirm: Literal["share_maps"] | None,
) -> tuple[T, list[SharedMap]]:
    """Run ``attempt``; when it raises ``StoryReachError`` and ``confirm`` is
    ``share_maps``, share the blocking maps and run it again.

    Shares nothing, and re-raises, unless every blocking map is named and
    ``can_share``. Does not commit: a caller whose second attempt raises
    leaves the maps unshared.
    """
    try:
        return await attempt(), []
    except StoryReachError as exc:
        fixable = (
            confirm == "share_maps"
            and not exc.unreadable
            and exc.maps
            and all(blocking.can_share for blocking in exc.maps)
        )
        if not fixable:
            raise
        shared = await share_blocking_maps(db, exc, actor)
    return await attempt(), shared


async def set_story_groups(
    db: AsyncSession,
    story: Story,
    group_ids: Iterable[uuid.UUID],
    *,
    actor: Identity,
    roles: set[str],
    confirm: Literal["share_maps"] | None = None,
) -> StoryShareResult:
    """Share ``story`` with exactly ``group_ids``.

    Call holding ``lock_story_groups`` for ``group_ids`` and then
    ``lock_story``, with the roles that returned. Raises
    ``GroupNotJoinedError`` when a non-admin adds a group they aren't in, and
    ``StoryReachError`` when the published story would newly reach groups
    some of whose members can't read a map it uses, unless ``confirm`` shares
    those maps (``sharing_blocking_maps``). Does not commit.
    """
    wanted = set(group_ids)
    current = await story_group_ids(db, story.id)
    added, removed = wanted - current, current - wanted
    await refuse_unjoined_groups(db, added, actor, is_admin="admin" in roles)
    previous = story.visibility
    visibility = grouped_visibility(previous, bool(wanted))
    if not (added or removed) and visibility == previous:
        return StoryShareResult(previous=None)

    result = StoryShareResult(previous=previous)
    # Grants on an internal or public story are dormant until it narrows.
    if visibility == RESTRICTED_STORY_VISIBILITY and story.published is not None:
        # Groups already reaching the story were checked when they were added.
        already = current if previous == RESTRICTED_STORY_VISIBILITY else set()
        reaching = wanted - already
        map_ids = scene_map_ids(story.published)

        async def admit() -> None:
            lacking = await groups_lacking_maps(db, map_ids, reaching)
            await refuse_blocking_maps(db, set(), lacking, actor, roles)

        _, result.shared_maps = await sharing_blocking_maps(db, admit, actor, confirm)

    await write_group_grants(
        db,
        StoryGroupGrant,
        "story_id",
        story.id,
        added=added,
        removed=removed,
        actor=actor,
    )
    story.visibility = visibility
    await db.flush()
    return result

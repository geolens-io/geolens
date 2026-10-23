"""Sharing a map with groups.

A private map shared with a group becomes restricted, readable by the
group's members besides its owner and admins, and a restricted map left with
no group is private again. Internal and public maps keep their audience; their
grants take effect once the map narrows to private. Layers stay behind each
dataset's own guard.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import exists, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import (
    ANONYMOUS_MAP_VISIBILITIES,
    RESTRICTED_MAP_VISIBILITY,
)
from app.modules.catalog.group_sharing import (
    group_refs,
    lock_share_groups,
    refuse_unjoined_groups,
    write_group_grants,
)
from app.modules.catalog.maps.models import Map, MapGroupGrant
from app.modules.catalog.maps.service_layers import lock_map_layers
from app.modules.catalog.maps.service_public import revoke_share_token_by_map
from app.modules.embed_tokens.service import revoke_embed_tokens_by_map

RESTRICTED_NEEDS_GROUPS = "Share the map with a group before making it restricted."


class RestrictedWithoutGroupsError(ValueError):
    """A write asked for ``restricted`` on a map shared with no group."""


def _granted(map_id: uuid.UUID):
    return select(MapGroupGrant.group_id).where(MapGroupGrant.map_id == map_id)


async def map_groups(session: AsyncSession, map_id: uuid.UUID) -> list[GroupRef]:
    """The groups a map is shared with, by name."""
    return await group_refs(session, _granted(map_id))


async def _retire_links(
    session: AsyncSession, map_id: uuid.UUID, current: str, new: str
) -> None:
    """Revoke the map's share and embed tokens when moving from ``current`` to
    ``new`` leaves public or enters restricted."""
    leaves_public = (
        current in ANONYMOUS_MAP_VISIBILITIES and new not in ANONYMOUS_MAP_VISIBILITIES
    )
    enters_restricted = (
        new == RESTRICTED_MAP_VISIBILITY and current != RESTRICTED_MAP_VISIBILITY
    )
    if leaves_public or enters_restricted:
        await revoke_share_token_by_map(session, map_id)
        await revoke_embed_tokens_by_map(session, map_id)


async def prepare_map_visibility(
    session: AsyncSession, map_id: uuid.UUID, requested: str
) -> str:
    """Return the visibility a write of ``requested`` gives the map: a map
    with groups is restricted wherever it would be private. Short of public,
    lock the map and revoke its links when the write narrows it.

    Raises ``RestrictedWithoutGroupsError`` for ``restricted`` on a map with
    no group.
    """
    if requested == "public":
        return requested
    await lock_map_layers(session, map_id)
    current = await session.scalar(select(Map.visibility).where(Map.id == map_id))
    visibility = requested
    if requested in ("private", RESTRICTED_MAP_VISIBILITY):
        has_groups = await session.scalar(
            select(exists().where(MapGroupGrant.map_id == map_id))
        )
        if has_groups:
            visibility = RESTRICTED_MAP_VISIBILITY
        elif requested == RESTRICTED_MAP_VISIBILITY:
            raise RestrictedWithoutGroupsError(RESTRICTED_NEEDS_GROUPS)
    await _retire_links(session, map_id, str(current), visibility)
    return visibility


async def unshare_group_maps(session: AsyncSession, group_id: uuid.UUID) -> None:
    """Make private the restricted maps ``group_id`` is the last group of.

    Call holding the group's row lock, before its deletion cascades its grants
    away; the map then reaches its owner and admins either way. Locks each map
    shared with the group, in id order, so concurrent deletions of a map's
    last two groups can't each count the other's grant as still there.
    """
    shared = select(MapGroupGrant.map_id).where(MapGroupGrant.group_id == group_id)
    await session.execute(
        select(Map.id)
        .where(Map.id.in_(shared))
        .order_by(Map.id)
        .with_for_update(key_share=True)
    )
    other = aliased(MapGroupGrant)
    sole = shared.where(
        ~exists().where(
            other.map_id == MapGroupGrant.map_id, other.group_id != group_id
        )
    )
    await session.execute(
        update(Map)
        .where(Map.id.in_(sole))
        .where(Map.visibility == RESTRICTED_MAP_VISIBILITY)
        .values(visibility="private")
        .execution_options(synchronize_session=False)
    )


async def set_map_groups(
    session: AsyncSession,
    map_obj: Map,
    group_ids: Iterable[uuid.UUID],
    *,
    actor: Identity,
    is_admin: bool,
) -> str | None:
    """Share ``map_obj`` with exactly ``group_ids``.

    Returns the map's previous visibility, or None when nothing changed.
    Call after ``check_map_ownership``. Raises ``UnknownGroupsError`` for a
    group that doesn't exist or belongs to another tenant, and
    ``GroupNotJoinedError`` when a non-admin adds a group they aren't in.
    Does not commit.
    """
    wanted = set(group_ids)
    granted = _granted(map_obj.id)
    await lock_share_groups(session, wanted, granted, map_obj.tenant_id)
    await lock_map_layers(session, map_obj.id)
    # Loaded before the lock: judge the row as committed, not as first read.
    await session.refresh(map_obj, ["visibility", "created_by"])
    current = set(await session.scalars(granted))
    added, removed = wanted - current, current - wanted
    await refuse_unjoined_groups(session, added, actor, is_admin=is_admin)
    previous = map_obj.visibility
    visibility = previous
    if visibility == "private" and wanted:
        visibility = RESTRICTED_MAP_VISIBILITY
    elif visibility == RESTRICTED_MAP_VISIBILITY and not wanted:
        visibility = "private"
    if not (added or removed) and visibility == previous:
        return None

    await write_group_grants(
        session,
        MapGroupGrant,
        "map_id",
        map_obj.id,
        added=added,
        removed=removed,
        actor=actor,
    )
    map_obj.visibility = visibility
    await session.flush()
    # Last: an embed token's revocation is cached outside this transaction.
    await _retire_links(session, map_obj.id, previous, visibility)
    return previous

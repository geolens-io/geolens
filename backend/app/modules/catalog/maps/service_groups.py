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
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import (
    ANONYMOUS_MAP_VISIBILITIES,
    RESTRICTED_MAP_VISIBILITY,
    answers_audience_questions,
)
from app.modules.catalog.group_sharing import (
    group_refs,
    lock_share_groups,
    refuse_unjoined_groups,
    unshare_sole_group_items,
    write_group_grants,
)
from app.modules.catalog.maps.models import Map, MapGroupGrant
from app.modules.catalog.maps.schemas import MapLayerAccessGap
from app.modules.catalog.maps.service_group_gaps import (
    LayersHiddenFromGroupsError,
    layer_gaps,
    share_layer_datasets,
)
from app.modules.catalog.maps.service_history import record_map_history_event
from app.modules.catalog.maps.service_layers import lock_map_layers
from app.modules.catalog.maps.service_public import revoke_share_token_by_map
from app.modules.embed_tokens.service import revoke_embed_tokens_by_map
from app.platform.extensions import get_permission_extension

RESTRICTED_NEEDS_GROUPS = "Share the map with a group before making it restricted."


class RestrictedWithoutGroupsError(ValueError):
    """A write asked for ``restricted`` on a map shared with no group."""


@dataclass
class MapShareResult:
    previous: str | None
    # The map's groups afterwards.
    group_ids: list[uuid.UUID] = field(default_factory=list)
    # Each dataset shared on the way, with its groups and visibility after.
    shared_datasets: dict[uuid.UUID, tuple[list[uuid.UUID], str]] = field(
        default_factory=dict
    )
    hidden_layers: list[MapLayerAccessGap] = field(default_factory=list)


def _granted(map_id: uuid.UUID):
    return select(MapGroupGrant.group_id).where(MapGroupGrant.map_id == map_id)


async def map_groups(session: AsyncSession, map_id: uuid.UUID) -> list[GroupRef]:
    """The groups a map is shared with, by name."""
    return await group_refs(session, _granted(map_id))


async def map_group_layer_gaps(
    session: AsyncSession, map_obj: Map, actor: Identity, is_admin: bool
) -> list[MapLayerAccessGap]:
    """A restricted map's layers some of its groups can't read, among those
    the caller reads. Empty for other maps and under an authority that can't
    answer audience questions, which would have every layer count."""
    if map_obj.visibility != RESTRICTED_MAP_VISIBILITY:
        return []
    if not answers_audience_questions(get_permission_extension()):
        return []
    groups = set(await session.scalars(_granted(map_obj.id)))
    return await layer_gaps(session, map_obj.id, groups, actor, is_admin)


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


async def record_map_groups_change(
    session: AsyncSession,
    map_id: uuid.UUID,
    map_name: str,
    *,
    previous: str,
    group_ids: list[uuid.UUID],
    actor: Identity,
    visibility: str,
    ip_address: str | None,
    details: dict[str, str] | None = None,
) -> None:
    """Audit a change to a map's groups, with ``details`` added, and record a
    visibility it moved in the map's history."""
    await audit_emit(
        session,
        AuditEvent(
            user_id=actor.id,
            action="map.update",
            resource_type="map",
            resource_id=map_id,
            details={
                "changed_fields": ["groups"],
                "group_ids": [str(group_id) for group_id in group_ids],
                "visibility": visibility,
                **(details or {}),
            },
            ip_address=ip_address,
        ),
    )
    if visibility != previous:
        await record_map_history_event(
            session,
            map_id=map_id,
            actor=actor,
            target_type="map",
            target_id=map_id,
            target_name=map_name,
            action="map.visibility_update",
            summary=f"Changed visibility to {visibility}",
            details={
                "field": "visibility",
                "previous": previous,
                "current": visibility,
            },
        )


async def unshare_group_maps(session: AsyncSession, group_id: uuid.UUID) -> None:
    """Make private the restricted maps ``group_id`` is the last group of; see
    ``unshare_sole_group_items``."""
    await unshare_sole_group_items(session, Map, MapGroupGrant, "map_id", group_id)


async def set_map_groups(
    session: AsyncSession,
    map_obj: Map,
    group_ids: Iterable[uuid.UUID],
    *,
    actor: Identity,
    is_admin: bool,
    confirm: Literal["share_datasets", "map_only"] | None = None,
    keep_current: bool = False,
) -> MapShareResult:
    """Share ``map_obj`` with exactly ``group_ids``, or with them besides its
    current groups when ``keep_current``.

    When the map ends restricted and groups that newly reach it can't read
    some layers, nothing is written unless ``confirm`` says what to do:
    ``share_datasets`` shares each dataset the caller may share with the
    groups lacking it, ``map_only`` leaves those layers hidden.

    The result's ``previous`` is the map's visibility before, or None when
    nothing changed. Call after ``check_map_ownership``. Raises
    ``UnknownGroupsError`` for a group that doesn't exist or belongs to
    another tenant, ``GroupNotJoinedError`` when a non-admin adds a group
    they aren't in, and ``LayersHiddenFromGroupsError`` for an unconfirmed
    gap. Dataset shares raise as ``set_dataset_groups`` does. Does not commit.
    """
    wanted = set(group_ids)
    granted = _granted(map_obj.id)
    await lock_share_groups(session, wanted, granted, map_obj.tenant_id)
    await lock_map_layers(session, map_obj.id)
    # Loaded before the lock: judge the row as committed, not as first read.
    await session.refresh(map_obj, ["visibility", "created_by"])
    current = set(await session.scalars(granted))
    if keep_current:
        wanted |= current
    added, removed = wanted - current, current - wanted
    await refuse_unjoined_groups(session, added, actor, is_admin=is_admin)
    previous = map_obj.visibility
    visibility = previous
    if visibility == "private" and wanted:
        visibility = RESTRICTED_MAP_VISIBILITY
    elif visibility == RESTRICTED_MAP_VISIBILITY and not wanted:
        visibility = "private"
    if not (added or removed) and visibility == previous:
        return MapShareResult(previous=None, group_ids=sorted(wanted))

    result = MapShareResult(previous=previous, group_ids=sorted(wanted))
    if visibility == RESTRICTED_MAP_VISIBILITY:
        # Grants on an internal or public map are dormant until it narrows.
        reaching = added if previous == RESTRICTED_MAP_VISIBILITY else wanted
        gaps = await layer_gaps(session, map_obj.id, reaching, actor, is_admin)
        if gaps and confirm is None:
            raise LayersHiddenFromGroupsError(gaps)
        if gaps and confirm == "share_datasets":
            result.shared_datasets = await share_layer_datasets(
                session, gaps, actor, is_admin
            )
            # Each shared dataset now grants exactly the groups it lacked.
            gaps = [gap for gap in gaps if gap.dataset_id not in result.shared_datasets]
        result.hidden_layers = gaps

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
    return result

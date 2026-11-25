"""Who a manifest map is shared with: its groups, and the warnings about
readers it reaches or misses.

The publish shares a map with groups through the map sharing path, after
its visibility is written, and never widens a dataset it doesn't publish.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import (
    RESTRICTED_MAP_VISIBILITY,
    answers_audience_questions,
    groups_lacking_datasets,
)
from app.modules.catalog.group_sharing import (
    SharePlan,
    active_tenant_id,
    hold_back_widening,
    lock_groups,
    plan_share_groups,
)
from app.modules.catalog.maps.manifest_messages import (
    GROUP_LEFT_OFF,
    MORE_VISIBLE,
    SHARING_KEPT,
    listed,
    message,
    short,
)
from app.modules.catalog.maps.models import Map, MapGroupGrant
from app.modules.catalog.maps.service_groups import (
    map_groups,
    record_map_groups_change,
    set_map_groups,
)
from app.platform.extensions import get_permission_extension
from app.platform.record_audience import audience_phrase


async def lock_entry_groups(session: AsyncSession, entry: Any) -> None:
    """Lock the groups a map entry names and the ones its map has, before
    the map's row, the order a group deletion takes them."""
    if entry.groups is None:
        return
    await lock_groups(
        session,
        set(entry.groups),
        select(MapGroupGrant.group_id)
        .join(Map, Map.id == MapGroupGrant.map_id)
        .where(Map.manifest_key == entry.key),
    )


async def plan_map_groups(
    session: AsyncSession,
    entry: Any,
    map_obj: Map | None,
    user: Identity,
    *,
    is_admin: bool,
    is_key: bool,
    level: str,
) -> tuple[list[GroupRef], SharePlan | None]:
    """The groups the map ends with, by name, and the share an entry that
    names groups asks for, None when it keeps the map's groups. ``level``
    is the visibility the apply writes before sharing.

    A publish key shares an existing map with nobody new: the planned
    groups at ``level`` are judged against who reads the map now.
    """
    stored = await map_groups(session, map_obj.id) if map_obj is not None else []
    if entry.groups is None:
        return stored, None
    current: set[uuid.UUID] = set()
    if map_obj is not None:
        current = set(
            await session.scalars(
                select(MapGroupGrant.group_id).where(MapGroupGrant.map_id == map_obj.id)
            )
        )
    share = await plan_share_groups(
        session,
        entry.groups,
        current,
        user,
        is_admin=is_admin,
        tenant_id=active_tenant_id(map_obj),
    )
    if is_key and map_obj is not None:
        share = hold_back_widening(share, map_obj.visibility, level)
    return (stored if share.unchanged else share.groups), share


def group_messages(entry: Any, share: SharePlan | None) -> list[dict[str, Any]]:
    """A058 for the groups left off, and A056 for those a publish key may
    not add. A share held back whole keeps the map's groups, so one that
    would keep a group the entry leaves out is error A056, which refuses the
    map: what it publishes would reach readers it removes."""
    if share is None:
        return []
    messages = []
    if share.left_off:
        messages.append(
            message(
                GROUP_LEFT_OFF,
                "warning",
                f"The map {short(entry.name)!r} isn't shared with "
                f"{listed([str(group_id) for group_id in share.left_off])}: no "
                "such group exists, or you aren't a member.",
                fix="Choose another group from the capabilities list.",
            )
        )
    if share.unchanged and share.granted - set(entry.groups):
        messages.append(
            message(
                SHARING_KEPT,
                "error",
                f"A publish key can't share the map {short(entry.name)!r} with "
                "more people, so its groups would stay as they are. This "
                "publish also removes groups, which would then read what it "
                "publishes, so the map was not updated.",
                fix=(
                    "Change the map's groups in GeoLens, or publish with the "
                    "groups it has now."
                ),
            )
        )
    elif share.held_back:
        names = [group.name for group in share.held_back]
        messages.append(
            message(
                SHARING_KEPT,
                "warning",
                f"A publish key can't share the map {short(entry.name)!r} with "
                f"more people, so {audience_phrase('restricted', names)} won't "
                "see it unless they already can, and its groups stay as they "
                "are.",
                fix="Share the map in GeoLens, or sign in.",
            )
        )
    return messages


def with_groups(level: str, groups: Sequence[GroupRef]) -> str:
    """The visibility a map at ``level`` stores with ``groups``: restricted
    where it would be private with a group, private where restricted
    without one."""
    if level in ("private", RESTRICTED_MAP_VISIBILITY):
        return RESTRICTED_MAP_VISIBILITY if groups else "private"
    return level


def more_visible(
    entry: Any, visibility: str, groups: Sequence[GroupRef]
) -> dict[str, Any]:
    """A057: the map reaches more people than now."""
    audience = audience_phrase(visibility, [group.name for group in groups])
    return message(
        MORE_VISIBLE,
        "warning",
        f"The map {short(entry.name)!r} will be visible to {audience}, more "
        "people than now, because its Sharing level changed in this publish.",
        fix="Continue, or keep the current level.",
    )


async def layer_sharing_gaps(
    session: AsyncSession,
    shown: Sequence[tuple[str | None, uuid.UUID, Any]],
    visibility: str,
    groups: Sequence[GroupRef],
) -> list[dict[str, Any]]:
    """A056 for each layer whose dataset some of the map's readers can't
    read. ``shown`` holds each planned layer's key (None for one added in
    GeoLens) and dataset the request doesn't publish, with its
    ``visibility``, ``record_status`` and ``title``; the publish never
    widens one, so those
    readers see the map without the layer. A public map's datasets are
    judged by the public rule instead."""
    messages = []
    if visibility == "internal":
        for key, _, dataset in shown:
            # The organization reads only a published, internal or public
            # dataset, as the permission check does.
            organization_reads = dataset.record_status == "published" and (
                dataset.visibility in ("internal", "public")
            )
            if not organization_reads:
                messages.append(_gap(key, dataset, audience_phrase("internal")))
    elif visibility == RESTRICTED_MAP_VISIBILITY and groups and shown:
        # An authority that can't answer would have every group lack every
        # layer.
        if not answers_audience_questions(get_permission_extension()):
            return []
        names = {group.id: group.name for group in groups}
        lacking = await groups_lacking_datasets(
            session, {dataset_id for _, dataset_id, _ in shown}, set(names)
        )
        for key, dataset_id, dataset in shown:
            missing = sorted(
                names[group_id] for group_id in lacking.get(dataset_id, ())
            )
            if missing:
                messages.append(
                    _gap(key, dataset, audience_phrase("restricted", missing))
                )
    return messages


def _gap(key: str | None, dataset: Any, audience: str) -> dict[str, Any]:
    layer = f"Layer {short(key)}" if key is not None else "A layer added in GeoLens"
    return message(
        SHARING_KEPT,
        "warning",
        f"{layer}: the dataset {short(dataset.title)!r} isn't "
        f"shared with {audience}, so those who can't read it won't see the "
        "layer.",
        fix="Share the dataset in GeoLens, or lower the Sharing level.",
        layer=key,
    )


async def share_map(
    session: AsyncSession,
    map_obj: Map,
    share: SharePlan,
    user: Identity,
    *,
    is_admin: bool,
    ip_address: str | None,
    audience_before: str | None,
) -> None:
    """Share the map with the planned groups through the map sharing path,
    after its visibility was written. Layers the groups can't read stay
    hidden from them: the publish shares no dataset it doesn't publish.
    ``audience_before`` is the map's visibility before the apply, None for
    a map this transaction created."""
    if share.unchanged:
        return
    result = await set_map_groups(
        session,
        map_obj,
        share.group_ids,
        actor=user,
        is_admin=is_admin,
        confirm="map_only",
        audience_before=audience_before,
    )
    # A grant change moves the map's update time in the database.
    await session.refresh(map_obj, ["visibility", "updated_at"])
    if result.previous is not None:
        await record_map_groups_change(
            session,
            map_obj.id,
            map_obj.name,
            previous=result.previous,
            group_ids=result.group_ids,
            actor=user,
            visibility=map_obj.visibility,
            ip_address=ip_address,
            details={"source": "manifest"},
        )

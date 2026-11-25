"""Who a manifest map is shared with: its groups, and the warnings about
readers it reaches or misses.

The publish shares a map with groups through the map sharing path, after
its visibility is written, and never widens a dataset it doesn't publish.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.processing_port import PendingManifestDataset
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import (
    RESTRICTED_MAP_VISIBILITY,
    answers_audience_questions,
    groups_lacking_datasets,
    groups_lacking_planned_dataset,
)
from app.modules.catalog.group_sharing import (
    SharePlan,
    active_tenant_id,
    hold_back_widening,
    level_with_groups,
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


@dataclass(frozen=True)
class ShownDataset:
    """The dataset behind a layer the planned map shows, as the publish
    leaves it. ``key`` is the layer's, None for one added in GeoLens.

    ``planned`` marks a dataset the request itself publishes: ``groups`` are
    then the ones its entry shares it with, None keeping the dataset's, and
    ``dataset_id`` is None for one the entry creates, or a stored one the
    caller can't read, which is judged on the request alone so that its
    owner and grants never shape the answer. Any other dataset keeps the
    audience it has.
    """

    key: str | None
    dataset_id: uuid.UUID | None
    title: str
    visibility: str
    record_status: str
    planned: bool = False
    groups: frozenset[uuid.UUID] | None = None


def planned_dataset(
    key: str | None,
    dataset_id: uuid.UUID | None,
    dataset: Any,
    planned: PendingManifestDataset,
) -> ShownDataset:
    """A layer's dataset as the request's own entry for it, ``planned``,
    leaves it. ``dataset`` is the stored one as the caller reads it; without
    it the dataset is judged as one the entry creates, on the request alone."""
    level = planned.visibility or (dataset.visibility if dataset else "private")
    if planned.group_ids is not None:
        level = level_with_groups(
            level, bool(planned.group_ids), role_granted=planned.role_granted
        )
    return ShownDataset(
        key,
        dataset_id if dataset is not None else None,
        planned.title,
        level,
        planned.record_status,
        planned=True,
        groups=None if planned.group_ids is None else frozenset(planned.group_ids),
    )


async def layer_sharing_gaps(
    session: AsyncSession,
    shown: Sequence[ShownDataset],
    visibility: str,
    groups: Sequence[GroupRef],
    publisher_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """A056 for each layer whose dataset some of the map's readers can't
    read. The publish never widens a dataset it doesn't publish, and one it
    does publish is judged on the level, status and groups its entry leaves,
    owned by ``publisher_id`` when the entry creates it; either way those
    readers see the map without the layer. A public map's datasets are
    judged by the public rule instead."""
    messages = []
    if visibility == "internal":
        for layer in shown:
            # The organization reads only a published, internal or public
            # dataset, as the permission check does.
            organization_reads = layer.record_status == "published" and (
                layer.visibility in ("internal", "public")
            )
            if not organization_reads:
                messages.append(_gap(layer, audience_phrase("internal")))
    elif visibility == RESTRICTED_MAP_VISIBILITY and groups and shown:
        # An authority that can't answer would have every group lack every
        # layer.
        if not answers_audience_questions(get_permission_extension()):
            return []
        names = {group.id: group.name for group in groups}
        lacking = await groups_lacking_datasets(
            session,
            {layer.dataset_id for layer in shown if not layer.planned},
            set(names),
        )
        lacking_planned: dict[ShownDataset, set[uuid.UUID]] = {}
        for layer in shown:
            if layer.planned:
                dataset = replace(layer, key=None)
                if dataset not in lacking_planned:
                    lacking_planned[dataset] = await groups_lacking_planned_dataset(
                        session,
                        set(names),
                        dataset_id=layer.dataset_id,
                        owner_id=publisher_id,
                        visibility=layer.visibility,
                        record_status=layer.record_status,
                        shared_with=layer.groups,
                    )
                without = lacking_planned[dataset]
            else:
                without = lacking.get(layer.dataset_id, set())
            missing = sorted(names[group_id] for group_id in without)
            if missing:
                messages.append(_gap(layer, audience_phrase("restricted", missing)))
    return messages


def _gap(shown: ShownDataset, audience: str) -> dict[str, Any]:
    layer = (
        f"Layer {short(shown.key)}"
        if shown.key is not None
        else "A layer added in GeoLens"
    )
    return message(
        SHARING_KEPT,
        "warning",
        f"{layer}: the dataset {short(shown.title)!r} isn't "
        f"shared with {audience}, so those who can't read it won't see the "
        "layer.",
        fix=(
            "Share the dataset with them in this publish, or lower the map's "
            "Sharing level."
            if shown.planned
            else "Share the dataset in GeoLens, or lower the Sharing level."
        ),
        layer=shown.key,
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

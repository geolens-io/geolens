"""What sharing a map with groups would hide from them, and sharing the
datasets that close the gap.

A group lacks a layer when one of its active members can't read the layer's
dataset, as the permission authority answers it.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.authorization import (
    check_dataset_write_access,
    check_vrt_audiences_after_change,
    groups_lacking_datasets,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGroupGrant,
    Record,
)
from app.modules.catalog.group_sharing import GroupNotJoinedError, joined_groups
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import MapLayerAccessGap
from app.modules.catalog.maps.service_shared import readable_dataset_ids


class DatasetGroupNotJoinedError(GroupNotJoinedError):
    """A dataset shared with a map names a group its sharer isn't in."""


class LayersHiddenFromGroupsError(Exception):
    """Sharing would leave layers some new groups can't read, unconfirmed."""

    def __init__(self, layers: list[MapLayerAccessGap]) -> None:
        super().__init__("Some layers can't be read by the map's new groups.")
        self.layers = layers


async def layer_gaps(
    session: AsyncSession,
    map_id: uuid.UUID,
    group_ids: set[uuid.UUID],
    actor: Identity,
    is_admin: bool,
) -> list[MapLayerAccessGap]:
    """The map's layers some of ``group_ids`` can't read, among the layers
    whose dataset the caller reads (others name nothing it may see)."""
    if not group_ids:
        return []
    rows = (
        await session.execute(
            select(
                MapLayer.id,
                MapLayer.display_name,
                Dataset.id.label("dataset_id"),
                Record.title,
                Record.created_by,
                Record.visibility,
                Record.record_status,
                Record.record_type,
            )
            .join(Dataset, Dataset.id == MapLayer.dataset_id)
            .join(Record, Record.id == Dataset.record_id)
            .where(MapLayer.map_id == map_id)
            .order_by(MapLayer.sort_order, MapLayer.id)
        )
    ).all()
    readable = await readable_dataset_ids(
        session, {row.dataset_id for row in rows}, actor
    )
    lacking = await groups_lacking_datasets(session, readable, group_ids)
    joined = await joined_groups(session, actor, group_ids)
    gaps = []
    vrt_refused: dict[uuid.UUID, bool] = {}
    for row in rows:
        missing = lacking.get(row.dataset_id)
        if not missing:
            continue
        can_share = (
            (is_admin or (row.created_by == actor.id and missing <= joined))
            and row.record_status == "published"
            and row.visibility in ("private", "restricted")
        )
        if can_share and row.record_type == "vrt_dataset":
            if row.dataset_id not in vrt_refused:
                vrt_refused[row.dataset_id] = await _vrt_would_pass_a_source(
                    session, row.dataset_id, missing
                )
            can_share = not vrt_refused[row.dataset_id]
        gaps.append(
            MapLayerAccessGap(
                layer_id=row.id,
                layer_title=row.display_name or row.title,
                dataset_id=row.dataset_id,
                dataset_title=row.title,
                group_ids=sorted(missing),
                can_share=can_share,
            )
        )
    return gaps


async def _vrt_would_pass_a_source(
    session: AsyncSession, dataset_id: uuid.UUID, group_ids: set[uuid.UUID]
) -> bool:
    """Whether sharing the VRT with ``group_ids`` would fail its source check,
    asked of that check in a rolled-back savepoint."""
    from app.modules.catalog.datasets.domain.service import get_dataset

    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        return True

    async def grant() -> None:
        await session.execute(
            pg_insert(DatasetGroupGrant)
            .values([{"dataset_id": dataset_id, "group_id": g} for g in group_ids])
            .on_conflict_do_nothing()
        )

    savepoint = await session.begin_nested()
    try:
        await check_vrt_audiences_after_change(
            session, dataset, visibility="restricted", regrant=grant
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_422_UNPROCESSABLE_CONTENT:
            raise
        return True
    finally:
        await savepoint.rollback()
    return False


async def share_layer_datasets(
    session: AsyncSession,
    gaps: list[MapLayerAccessGap],
    actor: Identity,
    is_admin: bool,
) -> dict[uuid.UUID, tuple[list[uuid.UUID], str]]:
    """Share each dataset the caller may share with the groups that lack it,
    through the dataset sharing path and its guards. A dataset deleted since
    is skipped."""
    from app.modules.catalog.datasets.domain.service import (
        get_dataset,
        set_dataset_groups,
    )

    wanted: dict[uuid.UUID, set[uuid.UUID]] = {}
    for gap in gaps:
        if gap.can_share:
            wanted.setdefault(gap.dataset_id, set()).update(gap.group_ids)
    shared = {}
    for dataset_id in sorted(wanted):
        dataset = await get_dataset(session, dataset_id)
        if dataset is None:
            continue
        await check_dataset_write_access(session, dataset, dataset_id, actor)
        try:
            # The current groups are read under the dataset's lock.
            await set_dataset_groups(
                session,
                dataset,
                wanted[dataset_id],
                actor=actor,
                is_admin=is_admin,
                keep_current=True,
            )
        except GroupNotJoinedError as exc:
            raise DatasetGroupNotJoinedError from exc
        groups = await session.scalars(
            select(DatasetGroupGrant.group_id).where(
                DatasetGroupGrant.dataset_id == dataset_id
            )
        )
        shared[dataset_id] = (sorted(groups), dataset.record.visibility)
    return shared

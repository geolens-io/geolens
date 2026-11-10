"""Sharing a dataset with groups.

Group grants decide who reads a ``restricted`` dataset, so changing them is a
visibility change and runs through the same guards: a VRT may not newly reach
past a source, the owner's shared maps may not lose readers, and outstanding
tile signatures are retired.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import (
    check_vrt_audiences_after_change,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.group_sharing import (
    GroupNotJoinedError as GroupNotJoinedError,
    UnknownGroupsError as UnknownGroupsError,
    group_refs,
    lock_share_groups,
    refuse_unjoined_groups,
    write_group_grants,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    DatasetGroupGrant,
)
from app.modules.catalog.datasets.domain.service_metadata import (
    _apply_visibility_change,
)


async def dataset_groups(
    session: AsyncSession, dataset_id: uuid.UUID
) -> list[GroupRef]:
    """The groups a dataset is shared with, by name."""
    return await group_refs(
        session,
        select(DatasetGroupGrant.group_id).where(
            DatasetGroupGrant.dataset_id == dataset_id
        ),
    )


async def set_dataset_groups(
    session: AsyncSession,
    dataset: Dataset,
    group_ids: Iterable[uuid.UUID],
    *,
    actor: Identity,
    is_admin: bool,
    warnings_out: list[str] | None = None,
    keep_current: bool = False,
) -> bool:
    """Share ``dataset`` with exactly ``group_ids``, or with them besides its
    current groups when ``keep_current``; return whether anything changed.

    Call after ``check_dataset_write_access``. Raises ``UnknownGroupsError``
    for a group that doesn't exist or belongs to another tenant,
    ``GroupNotJoinedError`` when a non-admin adds a group they aren't in,
    ``ValueError`` when the change strands one of the owner's shared maps,
    and 422 when a VRT would newly reach past a source. ``warnings_out``
    collects the advisory warnings a metadata PATCH would give. Does not
    commit.
    """
    wanted = set(group_ids)
    granted = select(DatasetGroupGrant.group_id).where(
        DatasetGroupGrant.dataset_id == dataset.id
    )
    await lock_share_groups(session, wanted, granted, dataset.tenant_id)
    await lock_dataset_rows_for_write(session, dataset)
    record = dataset.record
    # Loaded before the lock: judge the row as committed, not as first read.
    await session.refresh(record, ["visibility", "record_status", "created_by"])
    current = set(await session.scalars(granted))
    if keep_current:
        wanted |= current
    added, removed = wanted - current, current - wanted
    await refuse_unjoined_groups(session, added, actor, is_admin=is_admin)
    visibility = record.visibility
    if visibility == "private" and wanted:
        visibility = "restricted"
    elif visibility == "restricted" and not wanted:
        role_granted = select(exists().where(DatasetGrant.dataset_id == dataset.id))
        if not await session.scalar(role_granted):
            visibility = "private"
    if not (added or removed) and visibility == record.visibility:
        return False

    async def regrant() -> None:
        await write_group_grants(
            session,
            DatasetGroupGrant,
            "dataset_id",
            dataset.id,
            added=added,
            removed=removed,
            actor=actor,
        )
        await session.flush()

    if record.visibility in ("private", "restricted"):
        await check_vrt_audiences_after_change(
            session,
            dataset,
            visibility=visibility,
            regrant=lambda: _apply_visibility_change(
                session, record, dataset, dataset.id, visibility, regrant
            ),
        )
    else:
        # Internal and public datasets keep their audience; the grants wait
        # for a narrowing to restricted.
        await regrant()
    record.updated_by = actor.id
    await session.flush()
    from app.modules.catalog.records.inherited import (
        inherited_keyword_disclosure_warning,
    )

    warning = await inherited_keyword_disclosure_warning(
        session, record, dataset.id, actor=actor
    )
    if warning is not None and warnings_out is not None:
        warnings_out.append(warning)
    return True

"""Sharing a dataset with groups.

Group grants decide who reads a ``restricted`` dataset, so changing them is a
visibility change and runs through the same guards: a VRT may not newly reach
past a source, the owner's shared maps may not lose readers, and outstanding
tile signatures are retired.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, exists, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import Group, GroupMember
from app.modules.catalog.authorization import (
    check_vrt_audiences_after_change,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    DatasetGroupGrant,
)
from app.modules.catalog.datasets.domain.service_metadata import (
    _apply_visibility_change,
)


class UnknownGroupsError(LookupError):
    """Groups that don't exist, or belong to another tenant than the dataset."""

    def __init__(self, group_ids: Iterable[uuid.UUID]) -> None:
        super().__init__("Group not found")
        self.group_ids = sorted(group_ids)


class GroupNotJoinedError(PermissionError):
    """A non-admin owner named a group they don't belong to."""


async def dataset_groups(
    session: AsyncSession, dataset_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """The groups a dataset is shared with, as ``(id, name)`` by name."""
    rows = await session.execute(
        select(Group.id, Group.name)
        .join(DatasetGroupGrant, DatasetGroupGrant.group_id == Group.id)
        .where(DatasetGroupGrant.dataset_id == dataset_id)
        .order_by(Group.name, Group.id)
    )
    return [(row.id, row.name) for row in rows.all()]


def _visibility_with_groups(
    visibility: str, has_groups: bool, has_role_grants: bool
) -> str:
    if visibility == "private" and has_groups:
        return "restricted"
    if visibility == "restricted" and not has_groups and not has_role_grants:
        return "private"
    return visibility


async def set_dataset_groups(
    session: AsyncSession,
    dataset: Dataset,
    group_ids: Iterable[uuid.UUID],
    *,
    actor: Identity,
    is_admin: bool,
    warnings_out: list[str] | None = None,
) -> bool:
    """Share ``dataset`` with exactly ``group_ids``; return whether anything
    changed.

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
    # Groups before the dataset rows, the order a group deletion takes them.
    found = await session.execute(
        select(Group.id, Group.tenant_id)
        .where(or_(Group.id.in_(wanted), Group.id.in_(granted)))
        .order_by(Group.id)
        .with_for_update(read=True, key_share=True)
    )
    usable = {row.id for row in found.all() if row.tenant_id == dataset.tenant_id}
    if wanted - usable:
        raise UnknownGroupsError(wanted - usable)
    await lock_dataset_rows_for_write(session, dataset)

    record = dataset.record
    current = set(await session.scalars(granted))
    added, removed = wanted - current, current - wanted
    if added and not is_admin:
        joined = set(
            await session.scalars(
                select(GroupMember.group_id)
                .where(GroupMember.user_id == actor.id)
                .where(GroupMember.group_id.in_(added))
            )
        )
        if added - joined:
            raise GroupNotJoinedError
    has_role_grants = bool(
        await session.scalar(
            select(exists().where(DatasetGrant.dataset_id == dataset.id))
        )
    )
    visibility = _visibility_with_groups(
        record.visibility, bool(wanted), has_role_grants
    )
    if not (added or removed) and visibility == record.visibility:
        return False

    async def regrant() -> None:
        if removed:
            await session.execute(
                delete(DatasetGroupGrant)
                .where(DatasetGroupGrant.dataset_id == dataset.id)
                .where(DatasetGroupGrant.group_id.in_(removed))
            )
        if added:
            await session.execute(
                insert(DatasetGroupGrant).values(
                    [
                        {
                            "dataset_id": dataset.id,
                            "group_id": group_id,
                            "granted_by": actor.id,
                        }
                        for group_id in sorted(added)
                    ]
                )
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

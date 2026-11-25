"""Sharing a dataset with groups.

Group grants decide who reads a ``restricted`` dataset, so changing them is a
visibility change and runs through the same guards: a VRT may not newly reach
past a source, the owner's shared maps may not lose readers, and outstanding
tile signatures are retired.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import structlog
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.schemas import GroupRef
from app.platform.record_audience import VISIBILITY_ORDER
from app.platform.request_credential import is_publish_key
from app.modules.catalog.authorization import (
    can_view_dataset_provenance,
    check_vrt_audiences_after_change,
    get_user_roles,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.group_sharing import (
    GroupNotJoinedError as GroupNotJoinedError,
    UnknownGroupsError as UnknownGroupsError,
    CURRENT_LEVEL,
    SharePlan,
    active_tenant_id,
    group_refs,
    hold_back_revoked,
    hold_back_widening,
    lock_share_groups,
    plan_share_groups,
    refuse_publish_key_widening_share,
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

log = structlog.get_logger()


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
    audience_before: str | None = CURRENT_LEVEL,
) -> bool:
    """Share ``dataset`` with exactly ``group_ids``, or with them besides its
    current groups when ``keep_current``; return whether anything changed.

    Call after ``check_dataset_write_access``. Raises ``UnknownGroupsError``
    for a group that doesn't exist or belongs to another tenant,
    ``GroupNotJoinedError`` when a non-admin adds a group they aren't in,
    403 ``api_key_scope`` when a publish key's change lets more people read
    the dataset than at ``audience_before``: its stored visibility, the
    level before a publish that just wrote one, or None for a dataset this
    transaction created,
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
        if not await role_granted(session, dataset.id):
            visibility = "private"
    refuse_publish_key_widening_share(
        session,
        record.visibility if audience_before == CURRENT_LEVEL else audience_before,
        visibility,
        added,
    )
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


def _granted(dataset_id: uuid.UUID):
    return select(DatasetGroupGrant.group_id).where(
        DatasetGroupGrant.dataset_id == dataset_id
    )


async def role_granted(session: AsyncSession, dataset_id: uuid.UUID) -> bool:
    """Whether a role grant keeps the dataset restricted without groups."""
    return bool(
        await session.scalar(
            select(exists().where(DatasetGrant.dataset_id == dataset_id))
        )
    )


async def plan_manifest_dataset_groups(
    session: AsyncSession,
    dataset: Dataset | None,
    group_ids: Iterable[uuid.UUID],
    actor: Identity,
    *,
    level: str | None,
    audience_before: str | None = CURRENT_LEVEL,
    planned_from: str | None = None,
    granted_at_plan: Iterable[uuid.UUID] | None = None,
) -> tuple[SharePlan, bool]:
    """Plan sharing a manifest entry's dataset, None for one the entry
    creates, with exactly ``group_ids`` once it is at ``level`` (None keeps
    its visibility), as the caller's roles allow. Returns the plan and
    whether a role grant keeps the dataset restricted without groups.

    A share that lets more people read the dataset than at
    ``audience_before`` is held back whole for a publish key, and for anyone
    when the dataset was narrowed since ``planned_from``, its visibility
    when the apply planned the share: grants planned for a wider dataset
    were no change then and aren't confirmed now. A group the dataset had at
    the plan, ``granted_at_plan``, and has lost since is held back too.
    Writes nothing.
    """
    current: set[uuid.UUID] = set()
    granted_by_role = False
    if dataset is not None:
        current = set(await session.scalars(_granted(dataset.id)))
        granted_by_role = await role_granted(session, dataset.id)
    plan = await plan_share_groups(
        session,
        group_ids,
        current,
        actor,
        is_admin="admin" in await get_user_roles(session, actor),
        tenant_id=active_tenant_id(dataset),
    )
    if dataset is None:
        return plan, granted_by_role
    if granted_at_plan is not None:
        plan = hold_back_revoked(plan, granted_at_plan)
    stored = dataset.record.visibility
    before = stored if audience_before == CURRENT_LEVEL else audience_before
    narrowed = (
        before is not None
        and planned_from is not None
        and VISIBILITY_ORDER.index(before) < VISIBILITY_ORDER.index(planned_from)
    )
    if not (is_publish_key(session) or narrowed):
        return plan, granted_by_role
    return (
        hold_back_widening(plan, before, level or stored, role_granted=granted_by_role),
        granted_by_role,
    )


async def manifest_dataset_group_names(
    session: AsyncSession, dataset: Dataset, actor: Identity
) -> list[str] | None:
    """The names of the groups ``dataset`` is shared with, for its owner or
    an admin, who see them on the dataset itself; None for anyone else."""
    roles = await get_user_roles(session, actor)
    if not can_view_dataset_provenance(dataset.record, actor, roles):
        return None
    return [group.name for group in await dataset_groups(session, dataset.id)]


async def apply_manifest_dataset_groups(
    session: AsyncSession,
    dataset: Dataset,
    group_ids: Iterable[uuid.UUID],
    actor: Identity,
    *,
    audience_before: str | None,
    planned_from: str | None,
    granted_at_plan: Iterable[uuid.UUID] | None,
) -> tuple[SharePlan | None, str | None]:
    """Share a published manifest dataset with the groups of ``group_ids``
    the caller may grant, through ``set_dataset_groups`` and its guards.
    ``audience_before`` is the dataset's visibility before this publish,
    None for one it created, ``planned_from`` its visibility when the apply
    planned the share and ``granted_at_plan`` its groups then.

    Returns the plan, None when planning failed, and the refusal when the
    share was refused, as a sentence a reader can act on: the dataset then
    keeps its groups. Planning and share run in a savepoint, so neither a
    refusal nor a held-back share (``plan.unchanged``) fails the publish
    here; the caller decides what the groups that are left allow. Does not
    commit.
    """
    plan = None
    try:
        async with session.begin_nested():
            plan, _ = await plan_manifest_dataset_groups(
                session,
                dataset,
                group_ids,
                actor,
                level=None,
                audience_before=audience_before,
                planned_from=planned_from,
                granted_at_plan=granted_at_plan,
            )
            if not plan.unchanged:
                await set_dataset_groups(
                    session,
                    dataset,
                    plan.group_ids,
                    actor=actor,
                    is_admin="admin" in await get_user_roles(session, actor),
                    audience_before=audience_before,
                )
    except Exception as exc:  # broad: a refused or raced share leaves the groups as they were and must not fail the publish here
        log.warning("manifest_dataset_groups_refused", dataset_id=str(dataset.id))
        return plan, _refusal_sentence(exc)
    return plan, None


def _refusal_sentence(exc: Exception) -> str:
    """What refused a share, in the guard's own words where it has any a
    reader should see: a ``ValueError``'s text or an HTTP refusal's detail."""
    from fastapi import HTTPException

    if isinstance(exc, HTTPException) and isinstance(exc.detail, str):
        return exc.detail
    if isinstance(exc, ValueError) and str(exc):
        return str(exc)
    return "The group change could not be saved"

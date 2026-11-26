"""Which datasets and manifest keys a pending or running job still writes."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import ACTIVE_STATUSES, IngestJob


async def datasets_with_jobs_in_flight(
    db: AsyncSession, dataset_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """The datasets among ``dataset_ids`` that a pending or running job
    writes into, by its ``dataset_id`` or the one its metadata names, in one
    query. The query runs even with no ids, so a dataset the caller can't
    read costs the same queries as a missing one."""
    wanted = set(dataset_ids)
    named = IngestJob.user_metadata["dataset_id"].astext
    rows = await db.execute(
        select(IngestJob.dataset_id, named).where(
            IngestJob.status.in_(ACTIVE_STATUSES),
            or_(
                IngestJob.dataset_id.in_(sorted(wanted)),
                named.in_(sorted(str(dataset_id) for dataset_id in wanted)),
            ),
        )
    )
    found = set()
    for dataset_id, target in rows:
        found.add(dataset_id)
        found.add(uuid.UUID(target) if target else None)
    return found & wanted


async def manifest_keys_with_jobs_in_flight(
    db: AsyncSession, keys: Iterable[str]
) -> set[str]:
    """The manifest keys among ``keys`` with a pending or running job."""
    wanted = sorted(set(keys))
    if not wanted:
        return set()
    key = IngestJob.user_metadata["manifest_key"].astext
    rows = await db.execute(
        select(key)
        .where(IngestJob.status.in_(ACTIVE_STATUSES), key.in_(wanted))
        .distinct()
    )
    return set(rows.scalars())

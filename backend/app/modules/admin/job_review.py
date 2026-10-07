"""Admin job list handling of file replacements held for review.

A replacement the pipeline holds ends its ingest job as ``failed`` with the
``review_required`` code, but it waits on a decision rather than having broken,
so the failed list and count leave it out.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

REVIEW_REQUIRED = "review_required"


def _unaccepted_held_run() -> tuple[Any, ...]:
    from app.platform.refresh.models import DatasetRefreshRun

    return (
        DatasetRefreshRun.status == "blocked",
        ~DatasetRefreshRun.verification.has_key("acceptance_consumed_by_run_id"),
    )


def _awaits_acceptance(job_id: Any) -> Any:
    from app.platform.refresh.models import DatasetRefreshRun

    return (
        select(DatasetRefreshRun.id)
        .where(DatasetRefreshRun.ingest_job_id == job_id, *_unaccepted_held_run())
        .exists()
    )


def job_status_filters(status: str | None) -> list[Any]:
    """WHERE clauses for the job list's ``status`` value.

    ``awaiting_review`` is a filter value only, not a stored status.
    """
    from app.platform.jobs.models import IngestJob

    if status == "awaiting_review":
        return [
            IngestJob.status == "failed",
            IngestJob.error_code == REVIEW_REQUIRED,
            _awaits_acceptance(IngestJob.id),
        ]
    if status == "failed":
        return [
            IngestJob.status == "failed",
            IngestJob.error_code.is_distinct_from(REVIEW_REQUIRED),
        ]
    return [] if status is None else [IngestJob.status == status]


async def awaiting_review_job_ids(
    db: AsyncSession, job_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """The subset of ``job_ids`` whose held run still waits for a decision."""
    from app.platform.refresh.models import DatasetRefreshRun

    if not job_ids:
        return set()
    result = await db.scalars(
        select(DatasetRefreshRun.ingest_job_id).where(
            DatasetRefreshRun.ingest_job_id.in_(job_ids), *_unaccepted_held_run()
        )
    )
    return set(result)

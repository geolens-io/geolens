"""Admin job list handling of file replacements held for review.

A replacement the pipeline holds ends its ingest job as ``failed`` with the
``review_required`` code, but it waits on a decision rather than having broken,
so the failed list and count leave it out.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import Text, cast, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

REVIEW_REQUIRED = "review_required"


_ACCEPTED = "acceptance_consumed_by_run_id"


def _accepted_run_succeeded(held: Any) -> Any:
    """Whether the run that accepted ``held`` ended where the acceptance stays spent.

    A run that succeeded or was held again keeps it; one still in flight, failed
    or cancelled gives it back.
    """
    from app.platform.refresh.models import DatasetRefreshRun

    accepting = aliased(DatasetRefreshRun)
    return (
        select(accepting.id)
        .where(
            cast(accepting.id, Text) == held.verification[_ACCEPTED].astext,
            accepting.status.in_(("succeeded", "blocked")),
        )
        .exists()
    )


def _held_runs(job_id: Any, *conditions: Any) -> Any:
    from app.platform.refresh.models import DatasetRefreshRun

    return (
        select(DatasetRefreshRun.id)
        .where(
            DatasetRefreshRun.ingest_job_id == job_id,
            DatasetRefreshRun.status == "blocked",
            *conditions,
        )
        .exists()
    )


def job_status_filters(status: str | None) -> list[Any]:
    """WHERE clauses for the job list's ``status`` value.

    ``awaiting_review`` is a filter value only, not a stored status, and holds
    until the accepting run succeeds, since a failed one gives the acceptance back. A job
    whose held run is gone, as when its dataset was deleted, stays a failure.
    """
    from app.platform.jobs.models import IngestJob
    from app.platform.refresh.models import DatasetRefreshRun

    held = IngestJob.error_code == REVIEW_REQUIRED
    if status == "awaiting_review":
        return [
            IngestJob.status == "failed",
            held,
            _held_runs(IngestJob.id, ~_accepted_run_succeeded(DatasetRefreshRun)),
        ]
    if status == "failed":
        return [IngestJob.status == "failed", ~(held & _held_runs(IngestJob.id))]
    return [] if status is None else [IngestJob.status == status]


async def review_states(
    db: AsyncSession, job_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Literal["awaiting", "resolved"]]:
    """The review state of each of ``job_ids`` that has a held run."""
    from app.platform.refresh.models import DatasetRefreshRun

    if not job_ids:
        return {}
    rows = await db.execute(
        select(
            DatasetRefreshRun.ingest_job_id,
            _accepted_run_succeeded(DatasetRefreshRun),
        ).where(
            DatasetRefreshRun.ingest_job_id.in_(job_ids),
            DatasetRefreshRun.status == "blocked",
        )
    )
    return {job_id: "resolved" if accepted else "awaiting" for job_id, accepted in rows}

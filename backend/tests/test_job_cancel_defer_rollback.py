"""The orphan-guard rollback must not clobber a committed cancel (#1709 r11).

Round 4 recorded this window as a known-benign residual: a cancel commits
while a dispatch request is awaiting queue submission, the submission then
fails, and ``defer_with_orphan_guard`` runs
``make_ingest_job_failed_rollback`` — which blindly mutated the stale ORM
object to ``failed`` and committed over the cancellation.

It is not benign. ``failed`` is the one status ``/jobs/{id}/retry``
accepts, so the user who cancelled got a 200 plus cancellation audit
events and then a Retry affordance that restarts exactly the work they
cancelled, with the audit trail and the row disagreeing about what
happened.

The rollback is now a guarded CAS restricted to the still-pending attempt,
the same discipline as every other write in #1677: zero rows when the job
is no longer pending under that attempt — meaning a cancel, a sweep or a
worker already settled it — and the rollback correctly no-ops.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.platform.jobs.models import IngestJob
from app.platform.jobs.router import get_retry_capability
from app.processing.ingest.service import queue_ingest_job
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio


async def _pending_upload_job(session, tmp_path) -> IngestJob:
    """A committed pending vector-upload job with a real staged file.

    The file has to exist: the retry capability probes it, and the point of
    these tests is what ``can_retry`` answers afterwards.
    """
    staged = tmp_path / "parcels.geojson"
    staged.write_text('{"type": "FeatureCollection", "features": []}')
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="parcels.geojson",
        file_path=str(staged),
        created_by=admin_id,
        user_metadata={"title": "Parcels"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class _QueueDown(RuntimeError):
    """Stands in for Procrastinate being unreachable at submission time."""


async def _queue_with_failing_defer(session, job) -> None:
    """Run the real dispatch path with the queue submission failing."""

    async def _explode(*args, **kwargs):
        raise _QueueDown("queue unreachable")

    with patch(
        "app.processing.ingest.service.defer_async_with_tenant",
        side_effect=_explode,
    ):
        with pytest.raises(Exception) as excinfo:
            await queue_ingest_job(job, str(job.created_by), db=session)
    # The guard always converts a defer failure into its 503.
    assert getattr(excinfo.value, "status_code", None) == 503


async def test_defer_failure_after_cancel_leaves_the_cancel_standing(
    client: AsyncClient, admin_auth_header: dict, test_db_session, tmp_path
):
    """Cancel commits, then the queue submission fails: the row must stay
    cancelled, carry no retry affordance, and keep an audit trail that
    agrees with it."""
    job = await _pending_upload_job(test_db_session, tmp_path)

    resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text

    # The in-flight request still holds its pre-cancel view of the row —
    # that staleness is the whole race.
    await _queue_with_failing_defer(test_db_session, job)

    fresh = await test_db_session.get(IngestJob, job.id, populate_existing=True)
    assert fresh.status == "cancelled"
    assert fresh.error_message == "Cancelled by user"

    # The affordance that made this more than cosmetic: a `failed` row is
    # retryable, so the canceller was offered a restart of the work they
    # had just cancelled.
    can_retry, _reason = await get_retry_capability(fresh)
    assert can_retry is False

    retry = await client.post(f"/jobs/{job.id}/retry", headers=admin_auth_header)
    assert retry.status_code == 400
    fresh = await test_db_session.get(IngestJob, job.id, populate_existing=True)
    assert fresh.status == "cancelled"

    # And the trail agrees with the row: the cancel is recorded, and no
    # later write contradicted it.
    cancel_events = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "job.cancel",
                    AuditLog.resource_id == job.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(cancel_events) == 1


async def test_uncontested_defer_failure_still_fails_and_stays_retryable(
    test_db_session, tmp_path
):
    """The regression pin for every dispatch door: with nothing racing it,
    a failed submission must still settle the job `failed` — and retryable,
    which is the recovery the orphan guard exists to provide."""
    job = await _pending_upload_job(test_db_session, tmp_path)

    await _queue_with_failing_defer(test_db_session, job)

    fresh = await test_db_session.get(IngestJob, job.id, populate_existing=True)
    assert fresh.status == "failed"
    assert "Failed to queue ingest task" in (fresh.error_message or "")
    assert fresh.completed_at is not None

    can_retry, reason = await get_retry_capability(fresh)
    assert can_retry is True, reason

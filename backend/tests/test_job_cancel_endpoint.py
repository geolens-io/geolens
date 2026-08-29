"""POST /jobs/{id}/cancel — endpoint semantics and cancel machinery (#1677).

The endpoint's contract, pinned here:

- The DB compare-and-swap is the correctness mechanism: job row (fenced on
  the pre-read attempt id) and the bound refresh run flip to ``cancelled``
  and commit BEFORE the best-effort Procrastinate abort is even attempted.
- Idempotent repeat (already cancelled) is a 200, not an error.
- Too late (complete/failed/fanned_out) is a 409 ``job_already_finished``
  that writes nothing.
- Authorization is three arms: owner, the cross-user job capability
  (view/retry parity), or write access to the job's dataset — deliberately
  wider than retry so a dataset's owner can always unblock their own
  dataset from a run someone else started.

The no-swap-after-cancel guarantee itself is pinned separately in
``test_job_cancel_no_swap.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.audit.models import AuditLog
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob
from app.platform.jobs.sweep import audit_settled_embedding_backfill
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    ACTIVE_RUN_STATUSES,
    USER_CANCELLED_ERROR_CODE,
    cancel_active_run_for_job,
    claim_run_for_job,
    create_pending_run,
    record_refresh_failure,
    sweep_abandoned_refresh_runs,
    transition_run,
)
from tests.factories import create_dataset, create_user, get_user_id

pytestmark = pytest.mark.anyio


async def _create_job(
    session,
    *,
    created_by: uuid.UUID,
    status: str = "pending",
    dataset_id: uuid.UUID | None = None,
    attempt_id: uuid.UUID | None = None,
    user_metadata: dict | None = None,
) -> IngestJob:
    job = IngestJob(
        status=status,
        created_by=created_by,
        dataset_id=dataset_id,
        attempt_id=attempt_id or uuid.uuid4(),
        source_filename="cancel-me.geojson",
        user_metadata=user_metadata,
        started_at=datetime.now(timezone.utc) if status == "running" else None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _seed_job_with_run(session, *, username: str = "admin"):
    """Dataset + running job + claimed (running) run, reupload-shaped."""
    user_id = await get_user_id(session, username)
    dataset = await create_dataset(session, created_by=user_id)
    job = await _create_job(
        session,
        created_by=user_id,
        status="running",
        dataset_id=dataset.id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=user_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    assert await claim_run_for_job(session, job.id) == run.id
    await session.commit()
    return dataset, job, run


class _RecordingJobManager:
    def __init__(self):
        self.calls: list[tuple[int, bool]] = []

    async def cancel_job_by_id_async(self, job_id: int, abort: bool = False):
        self.calls.append((job_id, abort))
        return True


class TestCancelEndpoint:
    async def test_cancel_pending_job_aborts_queue_row(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """DB CAS lands and commits; the live queue row gets abort=True."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        # A live Procrastinate row correlated the way every sweep correlates.
        await test_db_session.execute(
            sa.text("SET LOCAL search_path TO catalog, public")
        )
        queue_id = (
            await test_db_session.execute(
                sa.text(
                    "INSERT INTO catalog.procrastinate_jobs "
                    "(queue_name, task_name, args, status) "
                    "VALUES ('ingest', 'ingest_file', "
                    "jsonb_build_object('job_id', CAST(:job_id AS text)), 'todo') "
                    "RETURNING id"
                ),
                {"job_id": str(job.id)},
            )
        ).scalar_one()
        await test_db_session.commit()

        from app.processing.ingest.tasks import task_app

        recorder = _RecordingJobManager()
        monkeypatch.setattr(task_app, "job_manager", recorder)

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "cancelled"
        assert body["id"] == str(job.id)
        assert body["run_id"] is None
        assert body["already"] is False

        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert job.error_message == "Cancelled by user"
        assert job.completed_at is not None
        assert recorder.calls == [(queue_id, True)]

    async def test_cancel_running_job_finalizes_the_bound_run(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset, job, run = await _seed_job_with_run(test_db_session)

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        assert resp.json()["run_id"] == str(run.id)

        await test_db_session.refresh(job)
        await test_db_session.refresh(run)
        assert job.status == "cancelled"
        assert run.status == "cancelled"
        assert run.error_code == USER_CANCELLED_ERROR_CODE
        assert run.finished_at is not None

        # Both audit trails committed with the CAS: the actor-attributed
        # job.cancel and the run lifecycle's refresh.cancelled.
        job_events = (
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
        assert len(job_events) == 1
        assert job_events[0].details["run_id"] == str(run.id)
        run_events = (
            (
                await test_db_session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "refresh.cancelled",
                        AuditLog.resource_id == dataset.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(run_events) == 1
        assert run_events[0].details["error_code"] == USER_CANCELLED_ERROR_CODE

    async def test_queue_lookup_failure_does_not_mask_a_committed_cancel(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#1709 review P2): the post-commit queue lookup is best-effort.

        By the time it runs, the cancel is durably committed — a lookup
        failure (connection drop, queue table unavailable) must be logged
        and swallowed, not surfaced as a 500 the UI reads as a failed
        cancel. Simulated by pointing the lookup SQL at a missing table.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        monkeypatch.setattr(
            "app.platform.jobs.router._LIVE_QUEUE_ROWS_SQL",
            sa.text("SELECT id FROM catalog.no_such_table_cancel_p2"),
        )

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"

        await test_db_session.refresh(job)
        assert job.status == "cancelled"

    async def test_second_cancel_is_idempotent(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        first = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert first.status_code == 200
        assert first.json()["already"] is False

        second = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert second.status_code == 200
        assert second.json()["already"] is True
        assert second.json()["status"] == "cancelled"

    @pytest.mark.parametrize("terminal", ["complete", "failed", "fanned_out"])
    async def test_cancel_finished_job_is_409(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        terminal: str,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status=terminal)

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "job_already_finished"
        assert detail["status"] == terminal

        await test_db_session.refresh(job)
        assert job.status == terminal

    async def test_cancel_unknown_job_is_404(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.post(
            f"/jobs/{uuid.uuid4()}/cancel", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_cancel_unauthenticated_is_401(self, client: AsyncClient):
        resp = await client.post(f"/jobs/{uuid.uuid4()}/cancel")
        assert resp.status_code == 401


async def _terminal_backfill_events(session, job_id) -> list[AuditLog]:
    """Non-`requested` embedding.backfill rows for one job — the set the
    partial unique index `uq_audit_logs_terminal_embedding_backfill` caps
    at one."""
    rows = await session.execute(
        select(AuditLog).where(
            AuditLog.action == "embedding.backfill",
            AuditLog.details["job_id"].astext == str(job_id),
            AuditLog.details["outcome"].astext != "requested",
        )
    )
    return list(rows.scalars())


class TestCancelEmbeddingBackfillAudit:
    """fix(#1709 review r3): the job row and the backfill audit trail are
    written together by whichever actor settles the job (sweep.py's rule).
    A cancelled queued backfill never runs — the queue row is aborted or the
    claim fails — so the cancel transaction is the only settling actor left."""

    @staticmethod
    def _backfill_metadata() -> dict:
        return {
            EMBEDDING_BACKFILL_METADATA_KEY: {
                "force": False,
                "operation_id": str(uuid.uuid4()),
            }
        }

    async def test_cancel_of_queued_backfill_writes_the_terminal_event(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            user_metadata=self._backfill_metadata(),
        )

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text

        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        events = await _terminal_backfill_events(test_db_session, job.id)
        assert len(events) == 1
        details = events[0].details
        assert details["outcome"] == "failed"
        assert details["error_code"] == "user_cancelled"
        assert (
            details["operation_id"]
            == job.user_metadata[EMBEDDING_BACKFILL_METADATA_KEY]["operation_id"]
        )

    async def test_late_settle_after_cancel_loses_the_terminal_race(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Fence-loss coherence: a worker or sweeper settling AFTER the
        cancel hits `uq_audit_logs_terminal_embedding_backfill` and is
        contained — one terminal entry, and it is the cancel's."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="running",
            user_metadata=self._backfill_metadata(),
        )

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text

        # The late actor: same helper the sweeps use, different error code.
        await audit_settled_embedding_backfill(
            test_db_session,
            job_id=job.id,
            user_metadata=job.user_metadata,
            created_by=job.created_by,
            error_code="worker_lost",
        )
        await test_db_session.commit()

        events = await _terminal_backfill_events(test_db_session, job.id)
        assert len(events) == 1
        assert events[0].details["error_code"] == "user_cancelled"

    async def test_non_backfill_cancel_writes_no_backfill_event(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The settle is a marker-gated no-op for every other job kind."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        assert await _terminal_backfill_events(test_db_session, job.id) == []


class TestCancelAuthorization:
    async def test_owner_can_cancel_own_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        headers, user_id = await create_user(client, admin_auth_header, "editor")
        job = await _create_job(test_db_session, created_by=uuid.UUID(user_id))

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=headers)
        assert resp.status_code == 200

    async def test_admin_can_cancel_another_users_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        _, user_id = await create_user(client, admin_auth_header, "editor")
        job = await _create_job(test_db_session, created_by=uuid.UUID(user_id))

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
        assert resp.status_code == 200

    async def test_dataset_owner_can_cancel_job_they_did_not_create(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Arm 3 — wider than retry, on purpose: the issue's motivating harm
        is `dataset_busy` blocking a dataset's owner with no way out."""
        headers, user_id = await create_user(client, admin_auth_header, "editor")
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=uuid.UUID(user_id))
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="running",
            dataset_id=dataset.id,
        )

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=headers)
        assert resp.status_code == 200

        await test_db_session.refresh(job)
        assert job.status == "cancelled"

    async def test_stranger_is_403_and_writes_nothing(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Neither owner, capability holder, nor dataset owner."""
        headers, _ = await create_user(client, admin_auth_header, "viewer")
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="running",
            dataset_id=dataset.id,
        )

        resp = await client.post(f"/jobs/{job.id}/cancel", headers=headers)
        assert resp.status_code == 403

        await test_db_session.refresh(job)
        assert job.status == "running"


class TestCancelMachinery:
    """The CAS pieces the endpoint composes, pinned individually."""

    async def test_stale_attempt_cancel_cas_writes_nothing(self, test_db_session):
        """The endpoint's exact CAS shape with a superseded attempt id
        matches zero rows — a stale cancel aimed at attempt N can never
        kill a retried attempt N+1 (mirrors retry_job's own fencing)."""
        admin_id = await get_user_id(test_db_session, "admin")
        stale_attempt = uuid.uuid4()
        job = await _create_job(
            test_db_session, created_by=admin_id, attempt_id=stale_attempt
        )
        # The retry that raced in between: same row, fresh attempt token.
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(attempt_id=uuid.uuid4())
        )
        await test_db_session.commit()

        result = await test_db_session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job.id,
                IngestJob.status.in_(("pending", "running")),
                IngestJob.attempt_id == stale_attempt,
            )
            .values(
                status="cancelled",
                error_message="Cancelled by user",
                completed_at=datetime.now(timezone.utc),
            )
        )
        await test_db_session.commit()
        assert result.rowcount == 0
        await test_db_session.refresh(job)
        assert job.status == "pending"

    async def test_transition_run_refuses_to_leave_cancelled(self, test_db_session):
        _, job, run = await _seed_job_with_run(test_db_session)
        assert await cancel_active_run_for_job(test_db_session, job.id) == run.id
        await test_db_session.commit()

        for target in ("succeeded", "failed", "running"):
            assert not await transition_run(
                test_db_session,
                run.id,
                expected=ACTIVE_RUN_STATUSES,
                to=target,
            )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "cancelled"
        assert run.error_code == USER_CANCELLED_ERROR_CODE

    async def test_record_refresh_failure_noops_on_cancelled_run(self, test_db_session):
        """The worker's broad-except cleanup path cannot overwrite a cancel."""
        _, job, run = await _seed_job_with_run(test_db_session)
        assert await cancel_active_run_for_job(test_db_session, job.id) == run.id
        await test_db_session.commit()

        result = await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="file_refresh_failed",
            error_message="worker unwound after the fence",
            contacted_origin=False,
        )
        assert result is None
        await test_db_session.refresh(run)
        assert run.status == "cancelled"
        assert run.error_code == USER_CANCELLED_ERROR_CODE

    async def test_cancel_releases_the_dataset_for_a_new_run(self, test_db_session):
        """`uq_refresh_runs_one_active` frees the moment the cancel commits."""
        dataset, job, _run = await _seed_job_with_run(test_db_session)
        assert await cancel_active_run_for_job(test_db_session, job.id) is not None
        await test_db_session.commit()

        second_job = await _create_job(
            test_db_session,
            created_by=await get_user_id(test_db_session, "admin"),
            dataset_id=dataset.id,
            user_metadata={"reupload": True},
        )
        second = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=second_job.created_by,
            ingest_job_id=second_job.id,
            feature_count_before=1,
        )
        await test_db_session.commit()
        assert second.status == "pending"

    async def test_abandonment_sweep_ignores_cancelled_runs(self, test_db_session):
        _, job, run = await _seed_job_with_run(test_db_session)
        assert await cancel_active_run_for_job(test_db_session, job.id) == run.id
        # Make the job row terminal too, as the endpoint does, so the sweep's
        # job-status predicate cannot be what excludes the row.
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(status="cancelled", completed_at=datetime.now(timezone.utc))
        )
        await test_db_session.commit()

        # Age the run past the abandonment cutoff; a non-terminal row this
        # old with no live task would be swept. The cancelled row must not be.
        await test_db_session.execute(
            update(DatasetRefreshRun)
            .where(DatasetRefreshRun.id == run.id)
            .values(started_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        )
        await test_db_session.commit()

        await sweep_abandoned_refresh_runs(test_db_session)
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "cancelled"
        assert run.error_code == USER_CANCELLED_ERROR_CODE

    async def test_cancel_active_run_for_job_without_run_is_none(self, test_db_session):
        """Plain imports have no run row; the endpoint still cancels the job."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)
        assert await cancel_active_run_for_job(test_db_session, job.id) is None

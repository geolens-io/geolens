"""Audit events and metrics for the refresh lifecycle (#1268, ADR-002 A10).

The run table is mutable and cascades with its dataset, so it is a status
board rather than a ledger. These two surfaces are what survives it: an
append-only audit trail, and series an operator can alert on.

Three properties, and why each is a test:

1. **Every lifecycle transition leaves an audit row, in the same transaction
   as the transition.** Not "usually" — a rollback must take the event with
   it, or the log claims refreshes that never started.
2. **No audit payload can carry a secret.** Asserted with a token sentinel
   rather than a key allowlist, because a leak arrives under a key nobody
   thought to forbid. The payload is a closed set of keys and the test names
   it, so widening it is a deliberate edit here rather than a drive-by.
3. **The metric series are safe under multiple uvicorn workers.** Every
   worker computes the same derived value, so anything that SUMS across
   processes reports N times the truth — the exact class of fabricated number
   #1240 existed to remove.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.audit.actions import AUDIT_ACTIONS
from app.modules.audit.models import AuditLog
from app.observability.metrics import refresh as refresh_metrics
from app.platform.jobs.models import IngestJob
from app.platform.refresh.service import (
    ABANDONED_RUN_CUTOFF_SECONDS,
    create_pending_run,
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
    sweep_abandoned_refresh_runs,
)
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio

# The complete payload contract. Widening it is a deliberate edit here.
_ALLOWED_DETAIL_KEYS = {"run_id", "origin_kind", "trigger", "status", "error_code"}

_REFRESH_ACTIONS = {
    "refresh.abandoned",
    "refresh.dispatch",
    "refresh.failed",
    "refresh.succeeded",
}


async def _seed(session, **dataset_kwargs):
    user_id = await get_user_id(session, "admin")
    dataset = await _create_dataset(session, created_by=user_id, **dataset_kwargs)
    job = IngestJob(
        dataset_id=dataset.id,
        status="running",
        source_filename="parcels.gpkg",
        source_url="https://services.example.com/geoserver/wfs",
        created_by=user_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return dataset, job


async def _refresh_audit_rows(session, dataset_id: uuid.UUID) -> list[AuditLog]:
    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.resource_id == dataset_id,
                    AuditLog.action.in_(sorted(_REFRESH_ACTIONS)),
                )
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


class TestRefreshAuditTrail:
    async def test_the_registry_carries_every_lifecycle_action(self) -> None:
        """The #1244 drift pattern: the emit sites and the registry agree.

        ``test_audit_action_registry`` proves the direction that matters
        (nothing is emitted unregistered). This names the four explicitly so
        deleting an emit site is a visible decision rather than a silently
        shrinking vocabulary.
        """
        assert _REFRESH_ACTIONS <= AUDIT_ACTIONS

    async def test_dispatch_success_and_failure_each_leave_a_row(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, job.id)
        await record_refresh_success(
            test_db_session,
            ingest_job_id=job.id,
            dataset=dataset,
            dataset_version_id=None,
            feature_count_after=57,
            schema_diff=None,
            contacted_origin=False,
        )
        await test_db_session.commit()

        rows = await _refresh_audit_rows(test_db_session, dataset.id)
        assert [r.action for r in rows] == ["refresh.dispatch", "refresh.succeeded"]
        assert [r.details["status"] for r in rows] == ["pending", "succeeded"]
        assert all(r.user_id == job.created_by for r in rows)
        assert all(r.resource_type == "dataset" for r in rows)

    async def test_a_failure_event_carries_the_code_and_not_the_message(
        self, test_db_session
    ) -> None:
        """``error_message`` is redacted free text; ``error_code`` is closed.

        Redaction is the wrong thing to lean on when a closed vocabulary is
        available, and audit rows are written for keeps.
        """
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await test_db_session.commit()
        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="credential_expired",
            error_message="GDAL: https://svc.example/wfs?token=hunter2 failed",
            contacted_origin=False,
        )
        await test_db_session.commit()

        failed = [
            r
            for r in await _refresh_audit_rows(test_db_session, dataset.id)
            if r.action == "refresh.failed"
        ]
        assert len(failed) == 1
        assert failed[0].details["error_code"] == "credential_expired"
        assert "hunter2" not in str(failed[0].details)
        assert set(failed[0].details) == _ALLOWED_DETAIL_KEYS

    async def test_no_payload_carries_a_url_a_token_or_a_schema_diff(
        self, test_db_session
    ) -> None:
        """The A10 sentinel, asserted against the whole row rather than keys.

        A key allowlist catches the leak somebody anticipated. Searching the
        serialized payload for the secret catches the one they did not.
        """
        secret = "tok-" + uuid.uuid4().hex
        dataset, job = await _seed(test_db_session)
        dataset.origin_uri = f"https://services.example.com/wfs?token={secret}"
        dataset.origin_ref = {
            "kind": "service",
            "service_type": "wfs",
            "url": "https://services.example.com/geoserver/wfs",
            "layer_id": "topp:parcels",
        }
        await test_db_session.commit()

        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, job.id)
        await record_refresh_success(
            test_db_session,
            ingest_job_id=job.id,
            dataset=dataset,
            dataset_version_id=None,
            feature_count_after=57,
            schema_diff={
                "columns_added": [{"name": "zone", "type": "String"}],
                "columns_removed": [],
                "type_changes": [],
                "row_count_old": 42,
                "row_count_new": 57,
                "row_count_delta": 15,
            },
            contacted_origin=False,
        )
        await test_db_session.commit()

        for row in await _refresh_audit_rows(test_db_session, dataset.id):
            payload = str(row.details)
            assert secret not in payload
            assert "services.example.com" not in payload
            assert "columns_added" not in payload
            assert set(row.details) == _ALLOWED_DETAIL_KEYS

    async def test_a_rolled_back_dispatch_leaves_no_event(
        self, test_db_session
    ) -> None:
        """Same transaction, which is the point.

        A dispatch refused as ``dataset_busy`` rolls back, and the log must
        roll back with it — otherwise the audit trail records refreshes that
        provably never started.
        """
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        dataset_id = dataset.id  # snapshot BEFORE the rollback
        await test_db_session.rollback()

        assert await _refresh_audit_rows(test_db_session, dataset_id) == []

    async def test_the_sweep_records_abandonment_under_its_own_verb(
        self, test_db_session
    ) -> None:
        """A run nobody watched finish is not a run that reported an error."""
        from datetime import datetime, timedelta, timezone

        dataset, job = await _seed(test_db_session)
        job.status = "failed"
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        run.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=ABANDONED_RUN_CUTOFF_SECONDS + 60
        )
        await test_db_session.commit()

        assert await sweep_abandoned_refresh_runs(test_db_session) == 1
        await test_db_session.commit()

        actions = [
            r.action for r in await _refresh_audit_rows(test_db_session, dataset.id)
        ]
        assert actions == ["refresh.dispatch", "refresh.abandoned"]


class TestReconciliationCounterPublishesOnlyAfterCommit:
    """fix(#1277 review): a counter increment cannot be taken back.

    The sweep used to increment where it ran, inside the transaction. Any
    later failure in the same pass rolls the cancellations back and leaves the
    counter claiming them — permanently, because counters only go up, so every
    rate() over that window stays wrong. Publishing therefore waits for
    durability rather than intent.
    """

    def _outcome(self, reconciled: int):
        from app.platform.jobs.router import StaleCleanupOutcome

        return StaleCleanupOutcome(
            pending_failed=0,
            running_failed=0,
            vrt_assets_recovered=0,
            vrt_generations_failed=0,
            terminal_jobs_purged=0,
            staged_paths_considered=0,
            local_files_reaped=0,
            storage_objects_reaped=0,
            staged_paths_skipped=0,
            staged_cleanup_failures=0,
            _refresh_runs_reconciled=reconciled,
        )

    def _counter_value(self) -> float:
        return refresh_metrics.refresh_sweep_reconciled_total._value.get()

    def test_publishing_an_outcome_increments_by_its_count(self) -> None:
        from app.platform.jobs.router import publish_refresh_reconciliation

        before = self._counter_value()
        publish_refresh_reconciliation(self._outcome(3))
        assert self._counter_value() == before + 3

    def test_an_outcome_that_reconciled_nothing_publishes_nothing(self) -> None:
        from app.platform.jobs.router import publish_refresh_reconciliation

        before = self._counter_value()
        publish_refresh_reconciliation(self._outcome(0))
        assert self._counter_value() == before

    def test_the_count_is_carried_out_of_the_sweep_not_incremented_inside_it(
        self,
    ) -> None:
        """The structural half: no increment survives at the sweep call site.

        A behavioural test cannot see the difference between "incremented
        after the commit" and "incremented before it" without engineering a
        mid-pass failure, so pin the shape instead — the sweep records the
        count on the outcome and the commit sites publish it.
        """
        import inspect

        from app.platform.jobs import router as jobs_router

        source = inspect.getsource(jobs_router.fail_stale_jobs)
        assert "refresh_sweep_reconciled_total.inc" not in source
        assert "_refresh_runs_reconciled=cancelled_runs" in source
        assert source.index("await db.commit()") < source.index(
            "publish_refresh_reconciliation"
        )

    def test_the_admin_path_publishes_after_its_own_commit(self) -> None:
        """commit=False hands the publish to the caller that owns the commit."""
        import inspect

        from app.platform.jobs import router as jobs_router

        source = inspect.getsource(jobs_router)
        admin = source[
            source.index("outcome = await fail_stale_jobs(db, commit=False") :
        ]
        commit_at = admin.index("await db.commit()")
        publish_at = admin.index("publish_refresh_reconciliation")
        assert commit_at < publish_at


class TestRefreshMetricSafety:
    """The multi-worker property, asserted on the metric definitions.

    Every uvicorn worker runs the same derived-gauge loop against the same
    table, so a series that aggregates by summing reports one answer per
    worker added together. There is no runtime test for this that does not
    involve forking uvicorn, and the defect is a property of the declaration —
    so the declaration is what gets pinned.
    """

    _DERIVED_GAUGES = (
        refresh_metrics.refresh_runs_active,
        refresh_metrics.refresh_runs_recent,
        refresh_metrics.refresh_run_queue_wait_seconds,
        refresh_metrics.refresh_run_duration_seconds,
    )

    def test_every_derived_gauge_reports_one_workers_value(self) -> None:
        for gauge in self._DERIVED_GAUGES:
            assert gauge._multiprocess_mode == "livemostrecent", gauge._name

    def test_the_derived_series_are_gauges_not_counters(self) -> None:
        """A counter cannot be derived from a poll without double counting."""
        for gauge in self._DERIVED_GAUGES:
            assert gauge._type == "gauge", gauge._name

    def test_request_scoped_instruments_stay_real_counters(self) -> None:
        """The sweep and the probe are observed by one worker, so they count.

        Turning these into derived gauges would lose the thing that makes
        them useful: a sweep increment is a run that ended with nobody
        reporting it, and you want the rate, not the current value.
        """
        assert refresh_metrics.refresh_sweep_reconciled_total._type == "counter"
        assert refresh_metrics.origin_probe_total._type == "counter"
        assert refresh_metrics.origin_probe_duration_seconds._type == "histogram"


class TestDerivedGaugeCycle:
    async def test_a_cycle_publishes_the_active_run_count(
        self, client, test_db_session
    ) -> None:
        """End to end against the real table, not a mocked query.

        ``client`` is required: it points ``app.core.db.engine`` at the test
        database, and the metrics cycle opens its own connection from that
        engine rather than taking the caller's session.
        """
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await test_db_session.commit()

        await refresh_metrics._refresh_run_metrics_once()
        active = refresh_metrics.refresh_runs_active.labels(
            origin_kind="service"
        )._value.get()
        assert active >= 1

    async def test_a_failing_query_does_not_break_the_loop(self, monkeypatch) -> None:
        """The loop outlives a database blip; metrics are never load-bearing."""

        class _Boom:
            def connect(self):
                raise RuntimeError("database is away")

        import app.core.db as core_db

        monkeypatch.setattr(core_db, "engine", _Boom(), raising=False)
        await refresh_metrics._refresh_run_metrics_once()  # must not raise

"""Durable refresh history and persisted schema drift (#1219, #1223, ADR-002).

Five properties this suite exists to hold:

1. A run row exists from DISPATCH, not from commit. The whole reason the row
   is written early is to represent runs that never committed, so "a failure
   leaves a row" is the property, not an edge case.
2. Every terminal path writes a terminal status. The failure branches are the
   ones people forget, and `reupload_file` has a third one that RETURNS rather
   than raising, so the broad handler never sees it.
3. The schema diff is measured at swap time against the staging table, and
   projected onto `datasets.schema_drift_status`. A preview that is never
   committed stores nothing — enforced structurally, because the only way to
   prove it about a code path is to look at where the writer is called from.
4. Third-party readers of a PUBLIC dataset's history see the timeline and not
   the people. Enumerated against NAMED signed-in strangers, not only the
   anonymous case: a requester-scoped check that exercises `user is None`
   alone reads as complete and is not.
5. `cancelled` is written only once the task is proven gone. Both refusal and
   admission are pinned — a sweep that stops cancelling anything looks
   identical to a sweep with nothing to cancel.
"""

from __future__ import annotations

import ast
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    ABANDONED_ERROR_CODE,
    ABANDONED_RUN_CUTOFF_SECONDS,
    RUN_ORIGIN_KINDS,
    RUN_STATUSES,
    RUN_TRIGGERS,
    DatasetBusyError,
    claim_run_for_job,
    create_pending_run,
    drift_status_from_diff,
    list_runs_for_dataset,
    make_refresh_run_failed_rollback,
    project_refresh_success,
    record_refresh_failure,
    record_refresh_success,
    redact_run_error,
    sweep_abandoned_refresh_runs,
    transition_run,
)
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio


def _diff(
    *,
    added: list[dict] | None = None,
    removed: list[dict] | None = None,
    type_changes: list[dict] | None = None,
    old_count: int | None = 10,
    new_count: int | None = 10,
) -> dict:
    """A compute_schema_diff-shaped payload."""
    return {
        "columns_added": added or [],
        "columns_removed": removed or [],
        "type_changes": type_changes or [],
        "row_count_old": old_count,
        "row_count_new": new_count,
        "row_count_delta": (new_count or 0) - (old_count or 0),
    }


# ---------------------------------------------------------------------------
# Drift projection — the pure rule (#1223)
# ---------------------------------------------------------------------------


class TestDriftStatusFromDiff:
    def test_no_diff_is_unknown_not_none_status(self) -> None:
        """NULL is the only spelling of "never determined"."""
        assert drift_status_from_diff(None) is None
        assert drift_status_from_diff({}) is None

    def test_identical_schema_is_none(self) -> None:
        assert drift_status_from_diff(_diff()) == "none"

    def test_row_count_change_alone_is_not_drift(self) -> None:
        """The column answers "did the SHAPE change", not "did the data"."""
        assert drift_status_from_diff(_diff(old_count=10, new_count=9999)) == "none"

    def test_added_column_is_drift(self) -> None:
        assert (
            drift_status_from_diff(_diff(added=[{"name": "zone", "type": "String"}]))
            == "drifted"
        )

    def test_removed_column_is_drift(self) -> None:
        assert (
            drift_status_from_diff(_diff(removed=[{"name": "zone", "type": "String"}]))
            == "drifted"
        )

    def test_type_change_is_drift(self) -> None:
        assert (
            drift_status_from_diff(
                _diff(
                    type_changes=[
                        {"name": "pop", "old_type": "Integer", "new_type": "String"}
                    ]
                )
            )
            == "drifted"
        )

    def test_column_rename_reads_as_drift(self) -> None:
        """#1223's named case: a rename is one add plus one removal."""
        renamed = _diff(
            added=[{"name": "zone_code", "type": "String"}],
            removed=[{"name": "zone", "type": "String"}],
        )
        assert drift_status_from_diff(renamed) == "drifted"


class TestProjectRefreshSuccess:
    def _dataset(self):
        return SimpleNamespace(
            schema_drift_status="drifted",
            last_checked_at=None,
            last_refreshed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            source_health=None,
            source_health_detail=None,
        )

    def test_drift_clears_when_the_schema_matches_again(self) -> None:
        """The other half of #1223: drifted must be able to go back to none."""
        dataset = self._dataset()
        project_refresh_success(dataset, schema_diff=_diff(), contacted_origin=False)
        assert dataset.schema_drift_status == "none"

    def test_local_refresh_does_not_claim_a_probe(self) -> None:
        dataset = self._dataset()
        project_refresh_success(dataset, schema_diff=_diff(), contacted_origin=False)
        assert dataset.last_checked_at is None

    def test_remote_refresh_stamps_last_checked_at(self) -> None:
        dataset = self._dataset()
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        project_refresh_success(
            dataset, schema_diff=_diff(), contacted_origin=True, now=now
        )
        assert dataset.last_checked_at == now

    def test_last_refreshed_at_and_health_are_not_this_function_s_business(
        self,
    ) -> None:
        """`_apply_reupload_swap` owns the first; #1222 owns the other two."""
        dataset = self._dataset()
        project_refresh_success(dataset, schema_diff=_diff(), contacted_origin=True)
        assert dataset.last_refreshed_at == datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert dataset.source_health is None
        assert dataset.source_health_detail is None


class TestRedactRunError:
    def test_query_string_token_is_stripped(self) -> None:
        message = "ogr2ogr failed on https://svc.example/FeatureServer/0?token=hunter2"
        assert "hunter2" not in redact_run_error(message)

    def test_userinfo_is_stripped(self) -> None:
        assert "s3cret" not in redact_run_error(
            "GDAL error: https://bob:s3cret@svc.example/wfs"
        )

    def test_ordinary_message_survives(self) -> None:
        """The refusal half needs its admission or a redactor that eats
        everything passes every test above."""
        message = "Layer 'parcels' has no geometry column"
        assert redact_run_error(message) == message

    def test_message_is_capped(self) -> None:
        assert len(redact_run_error("x" * 10_000)) == 2000


# ---------------------------------------------------------------------------
# Vocabulary — the Python tuples and the DB CHECKs cannot drift
# ---------------------------------------------------------------------------


class TestVocabularyMatchesTheConstraints:
    @staticmethod
    def _constraint_values(name: str) -> set[str]:
        for constraint in DatasetRefreshRun.__table__.constraints:
            if getattr(constraint, "name", None) == name:
                return set(
                    part.strip().strip("'")
                    for part in str(constraint.sqltext)
                    .split("(", 1)[1]
                    .rsplit(")", 1)[0]
                    .split(",")
                )
        raise AssertionError(f"{name} is not declared on the model")

    def test_status_values_match(self) -> None:
        assert self._constraint_values("chk_refresh_runs_status") == set(RUN_STATUSES)

    def test_trigger_values_match(self) -> None:
        assert self._constraint_values("chk_refresh_runs_trigger") == set(RUN_TRIGGERS)

    def test_origin_kind_values_match(self) -> None:
        assert self._constraint_values("chk_refresh_runs_origin_kind") == set(
            RUN_ORIGIN_KINDS
        )

    def test_scheduled_is_not_a_trigger(self) -> None:
        """Gate 4. Invariant 8 rides on this exclusion: whoever adds
        `scheduled` must add `scheduled_for` and its unique index with it."""
        assert "scheduled" not in RUN_TRIGGERS

    def test_blocked_is_not_a_status(self) -> None:
        """Reserved, not shipped — v1 has no schema policy to reach it."""
        assert "blocked" not in RUN_STATUSES


class TestCreatePendingRunRefusesBadVocabulary:
    async def test_unknown_origin_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="origin_kind"):
            await create_pending_run(
                None,  # type: ignore[arg-type]
                dataset_id=uuid.uuid4(),
                origin_kind="warehouse",
                trigger="manual",
                triggered_by=None,
                ingest_job_id=None,
                feature_count_before=None,
            )

    async def test_scheduled_trigger_raises(self) -> None:
        with pytest.raises(ValueError, match="trigger"):
            await create_pending_run(
                None,  # type: ignore[arg-type]
                dataset_id=uuid.uuid4(),
                origin_kind="service",
                trigger="scheduled",
                triggered_by=None,
                ingest_job_id=None,
                feature_count_before=None,
            )


# ---------------------------------------------------------------------------
# Structural: the run row is created at dispatch and NOWHERE else
# ---------------------------------------------------------------------------


def _enclosing_functions_calling(path: Path, callee: str) -> set[str]:
    """Names of the functions in ``path`` that call ``callee``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == callee
            ):
                found.add(node.name)
    return found


def test_only_the_commit_handler_creates_a_run() -> None:
    """#1223: "a preview that is never committed stores nothing".

    The preview endpoints and the commit endpoint live in one module, so the
    property is about which handler holds the writer — a runtime test would
    have to drive ogrinfo or a live service to say anything at all, and would
    still only prove it for the path it exercised.
    """
    api_dir = Path(__file__).resolve().parents[1] / "app/modules/catalog/datasets/api"
    callers: dict[str, set[str]] = {}
    for path in sorted(api_dir.glob("*.py")):
        found = _enclosing_functions_calling(path, "create_pending_run")
        if found:
            callers[path.name] = found

    assert callers == {"router_reupload.py": {"reupload_commit"}}, (
        f"A refresh run row may only be created by the commit handler. Found: {callers}"
    )


# ---------------------------------------------------------------------------
# DB-backed lifecycle
# ---------------------------------------------------------------------------


async def _seed(session, *, username: str = "admin", **dataset_kwargs):
    """Return (dataset, ingest_job) bound to a reupload-shaped job row."""
    user_id = await get_user_id(session, username)
    dataset = await _create_dataset(session, created_by=user_id, **dataset_kwargs)
    job = IngestJob(
        dataset_id=dataset.id,
        status="running",
        source_filename="parcels.gpkg",
        created_by=user_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return dataset, job


class TestRunLifecycle:
    async def test_pending_row_lands_with_dispatch_metadata(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await test_db_session.commit()

        assert run.status == "pending"
        assert run.ingest_job_id == job.id
        assert run.feature_count_before == dataset.feature_count
        # Stamped in Python, not by server_default: a SQL default leaves the
        # attribute expired and the read below would lazy-load under AnyIO.
        assert run.started_at is not None
        assert run.finished_at is None

    async def test_claim_moves_pending_to_running_once(self, test_db_session) -> None:
        dataset, job = await _seed(test_db_session)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=1,
        )
        await test_db_session.commit()

        assert await claim_run_for_job(test_db_session, job.id) == run.id
        # A second claim finds nothing to claim — the guard is on `pending`.
        assert await claim_run_for_job(test_db_session, job.id) is None
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "running"

    async def test_claim_with_no_run_is_not_an_error(self, test_db_session) -> None:
        """A re-upload dispatched before this table existed still completes."""
        _, job = await _seed(test_db_session)
        assert await claim_run_for_job(test_db_session, job.id) is None

    async def test_success_records_the_diff_and_projects_drift(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        before = dataset.last_refreshed_at
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, job.id)

        diff = _diff(added=[{"name": "zone", "type": "String"}], new_count=57)
        run_id = await record_refresh_success(
            test_db_session,
            ingest_job_id=job.id,
            dataset=dataset,
            dataset_version_id=None,
            feature_count_after=57,
            schema_diff=diff,
            contacted_origin=True,
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        await test_db_session.refresh(dataset)

        assert run_id == run.id
        assert run.status == "succeeded"
        assert run.finished_at is not None
        assert run.feature_count_after == 57
        assert run.schema_diff["columns_added"] == [{"name": "zone", "type": "String"}]
        assert dataset.schema_drift_status == "drifted"
        assert dataset.last_checked_at is not None
        # The swap owns last_refreshed_at; nothing here may move it.
        assert dataset.last_refreshed_at == before

    async def test_drift_clears_on_a_matching_re_refresh(self, test_db_session) -> None:
        """#1223's paired case, end to end on the stored column."""
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, job.id)
        await record_refresh_success(
            test_db_session,
            ingest_job_id=job.id,
            dataset=dataset,
            dataset_version_id=None,
            feature_count_after=42,
            schema_diff=_diff(
                added=[{"name": "zone_code", "type": "String"}],
                removed=[{"name": "zone", "type": "String"}],
            ),
            contacted_origin=False,
        )
        await test_db_session.commit()
        assert dataset.schema_drift_status == "drifted"

        second_job = IngestJob(
            dataset_id=dataset.id, status="running", created_by=job.created_by
        )
        test_db_session.add(second_job)
        await test_db_session.commit()
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=second_job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, second_job.id)
        await record_refresh_success(
            test_db_session,
            ingest_job_id=second_job.id,
            dataset=dataset,
            dataset_version_id=None,
            feature_count_after=42,
            schema_diff=_diff(),
            contacted_origin=False,
        )
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        assert dataset.schema_drift_status == "none"

    async def test_failure_is_recorded_and_freshness_is_untouched(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        dataset.last_refreshed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()

        run_id = await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="service_refresh_failed",
            error_message="GDAL: https://svc.example/wfs?token=hunter2 returned 500",
            contacted_origin=True,
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        await test_db_session.refresh(dataset)

        assert run_id == run.id
        assert run.status == "failed"
        assert run.error_code == "service_refresh_failed"
        assert "hunter2" not in run.error_message
        assert run.dataset_version_id is None
        assert dataset.last_refreshed_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert dataset.last_checked_at is not None

    async def test_local_failure_does_not_stamp_last_checked_at(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="validation_failed",
            error_message="Unsupported file",
            contacted_origin=False,
        )
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is None

    async def test_a_terminal_run_is_never_re_finalized(self, test_db_session) -> None:
        """History is append-only; a retry creates a NEW row (Decision 4d)."""
        dataset, job = await _seed(test_db_session)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="file_refresh_failed",
            error_message="boom",
            contacted_origin=False,
        )
        await test_db_session.commit()

        assert (
            await record_refresh_success(
                test_db_session,
                ingest_job_id=job.id,
                dataset=dataset,
                dataset_version_id=None,
                feature_count_after=1,
                schema_diff=_diff(),
                contacted_origin=False,
            )
            is None
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "failed"

    async def test_defer_failure_finalizes_the_run(self, test_db_session) -> None:
        """The orphan guard's rollback must not leave a ghost `pending` row."""
        dataset, job = await _seed(test_db_session)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()

        inner_calls: list[BaseException] = []

        async def _inner(exc: BaseException) -> None:
            inner_calls.append(exc)

        rollback = make_refresh_run_failed_rollback(
            _inner, db=test_db_session, ingest_job_id=job.id
        )
        await rollback(RuntimeError("queue unreachable"))
        await test_db_session.commit()
        await test_db_session.refresh(run)

        assert len(inner_calls) == 1
        assert run.status == "failed"
        assert run.error_code == "dispatch_failed"


class TestAdmissionControl:
    """One active run per dataset, enforced by the schema (amendment 2.4)."""

    async def test_a_second_active_run_is_refused(self, test_db_session) -> None:
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()

        second_job = IngestJob(
            dataset_id=dataset.id, status="pending", created_by=job.created_by
        )
        test_db_session.add(second_job)
        await test_db_session.commit()

        with pytest.raises(DatasetBusyError):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset.id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=job.created_by,
                ingest_job_id=second_job.id,
                feature_count_before=42,
            )

    async def test_the_refusal_leaves_the_transaction_usable(
        self, test_db_session
    ) -> None:
        """The SAVEPOINT is what lets the handler render a 409 at all.

        Without it the IntegrityError poisons the session and every later
        statement — including the rollback the handler needs — fails too.
        """
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()

        with pytest.raises(DatasetBusyError):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset.id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=job.created_by,
                ingest_job_id=None,
                feature_count_before=42,
            )

        # The session still works.
        assert await test_db_session.scalar(sa.text("SELECT 1")) == 1

    async def test_a_retired_run_frees_the_dataset(self, test_db_session) -> None:
        """The admission half. A refusal test alone cannot notice that the
        index started rejecting legitimate sequential refreshes."""
        dataset, job = await _seed(test_db_session)
        first = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        await claim_run_for_job(test_db_session, job.id)
        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="file_refresh_failed",
            error_message="boom",
            contacted_origin=False,
        )
        await test_db_session.commit()

        second = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        # A retry is a NEW row (Decision 4d): the history is append-only, and
        # the first run's outcome is not rewritten into the second's.
        assert second.id != first.id
        await test_db_session.refresh(first)
        assert first.status == "failed"

    async def test_an_unrelated_violation_is_not_reported_as_busy(
        self, test_db_session
    ) -> None:
        """Matching IntegrityError alone would turn every future constraint on
        this table into a misleading 409. A dangling dataset_id is a broken
        request, not a busy dataset, and must surface as itself."""
        with pytest.raises(IntegrityError):
            await create_pending_run(
                test_db_session,
                dataset_id=uuid.uuid4(),
                origin_kind="upload",
                trigger="manual",
                triggered_by=None,
                ingest_job_id=None,
                feature_count_before=1,
            )
        await test_db_session.rollback()

    async def test_two_datasets_do_not_block_each_other(self, test_db_session) -> None:
        """The index is keyed on dataset_id, not global."""
        first_dataset, first_job = await _seed(test_db_session)
        second_dataset, second_job = await _seed(test_db_session)
        for dataset, job in ((first_dataset, first_job), (second_dataset, second_job)):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset.id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=job.created_by,
                ingest_job_id=job.id,
                feature_count_before=1,
            )
        await test_db_session.commit()


class TestCompareAndSetTransitions:
    """No transition may overwrite a state it did not expect (amendment 2.3)."""

    async def _pending(self, session):
        dataset, job = await _seed(session)
        run = await create_pending_run(
            session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await session.commit()
        return dataset, job, run

    async def test_claim_stamps_claimed_at_and_leaves_started_at(
        self, test_db_session
    ) -> None:
        _, job, run = await self._pending(test_db_session)
        dispatched_at = run.started_at
        assert run.claimed_at is None

        assert await claim_run_for_job(test_db_session, job.id) == run.id
        await test_db_session.commit()
        await test_db_session.refresh(run)

        assert run.status == "running"
        assert run.claimed_at is not None
        # Queue wait is only measurable because these stay separate.
        assert run.started_at == dispatched_at
        assert run.claimed_at >= run.started_at

    async def test_a_second_claim_loses_the_race(self, test_db_session) -> None:
        _, job, run = await self._pending(test_db_session)
        assert await claim_run_for_job(test_db_session, job.id) == run.id
        await test_db_session.commit()
        await test_db_session.refresh(run)
        first_claim = run.claimed_at

        assert await claim_run_for_job(test_db_session, job.id) is None
        await test_db_session.commit()
        await test_db_session.refresh(run)
        # The loser wrote nothing at all — not even a fresh claimed_at.
        assert run.claimed_at == first_claim

    async def test_transition_refuses_a_state_it_did_not_expect(
        self, test_db_session
    ) -> None:
        """The compare-and-set itself, isolated from the active-run lookup.

        The lookup in `record_refresh_*` filters terminal rows out, so a test
        that only goes through those functions is exercising the FILTER, not
        the CAS — the two look identical from outside and only one of them
        covers the interleaving where the row changes between the lookup and
        the update. This drives `transition_run` directly, which is that
        window.
        """
        _, job, run = await self._pending(test_db_session)
        await claim_run_for_job(test_db_session, job.id)
        await test_db_session.commit()

        # The caller believes it is still `pending`; the row says `running`.
        assert (
            await transition_run(
                test_db_session, run.id, expected=("pending",), to="succeeded"
            )
            is False
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "running"

        # And the matching expectation still wins, or the guard has simply
        # stopped letting anything through.
        assert (
            await transition_run(
                test_db_session, run.id, expected=("running",), to="succeeded"
            )
            is True
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "succeeded"

    async def test_transition_cannot_resurrect_a_terminal_run(
        self, test_db_session
    ) -> None:
        """A worker that resurfaces after the sweep cancelled its run holds a
        run id that was valid when it looked it up. Only the expected-state
        test stops it writing an outcome over the correction."""
        _, job, run = await self._pending(test_db_session)
        await claim_run_for_job(test_db_session, job.id)
        await test_db_session.commit()

        run_id = run.id
        run.status = "cancelled"
        await test_db_session.commit()

        assert (
            await transition_run(
                test_db_session,
                run_id,
                expected=("running",),
                to="succeeded",
                values={"feature_count_after": 99},
            )
            is False
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "cancelled"
        assert run.feature_count_after is None

    async def test_success_cannot_overwrite_a_cancelled_run(
        self, test_db_session
    ) -> None:
        """The race the sweep makes real: a worker resurfaces after the sweep
        wrote `cancelled`. A blind UPDATE would report success for a run
        nobody was watching any more."""
        dataset, job, run = await self._pending(test_db_session)
        await claim_run_for_job(test_db_session, job.id)
        await test_db_session.commit()

        run.status = "cancelled"
        run.error_code = ABANDONED_ERROR_CODE
        await test_db_session.commit()

        assert (
            await record_refresh_success(
                test_db_session,
                ingest_job_id=job.id,
                dataset=dataset,
                dataset_version_id=None,
                feature_count_after=99,
                schema_diff=_diff(),
                contacted_origin=True,
            )
            is None
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "cancelled"
        assert run.feature_count_after is None

    async def test_failure_cannot_overwrite_a_succeeded_run(
        self, test_db_session
    ) -> None:
        dataset, job, run = await self._pending(test_db_session)
        await claim_run_for_job(test_db_session, job.id)
        await record_refresh_success(
            test_db_session,
            ingest_job_id=job.id,
            dataset=dataset,
            dataset_version_id=None,
            feature_count_after=7,
            schema_diff=_diff(),
            contacted_origin=False,
        )
        await test_db_session.commit()

        assert (
            await record_refresh_failure(
                test_db_session,
                ingest_job_id=job.id,
                error_code="file_refresh_failed",
                error_message="late arrival",
                contacted_origin=False,
            )
            is None
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "succeeded"
        assert run.error_code is None

    async def test_failure_before_the_claim_still_records(
        self, test_db_session
    ) -> None:
        """The reason `expected` is a tuple: reupload_service revalidates its
        URL for SSRF before phase 1, so that failure lands on a run that was
        never claimed. Refusing it would lose the only record of the attempt."""
        _, job, run = await self._pending(test_db_session)
        assert (
            await record_refresh_failure(
                test_db_session,
                ingest_job_id=job.id,
                error_code="service_refresh_failed",
                error_message="ssrf refusal",
                contacted_origin=False,
            )
            == run.id
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "failed"
        assert run.claimed_at is None


class TestTenantStamp:
    async def test_tenant_id_is_copied_from_the_parent_dataset(
        self, test_db_session
    ) -> None:
        """Read from the STORED column, not the ORM attribute: in
        multi-tenant mode a trigger fills the parent's column in the database
        while the attribute stays None."""
        dataset, job = await _seed(test_db_session)
        dataset_id, job_id, actor_id = dataset.id, job.id, job.created_by
        tenant_id = uuid.uuid4()
        # Written straight to the column, the way the stamping trigger writes
        # it in multi-tenant mode.
        await test_db_session.execute(
            sa.text("UPDATE catalog.datasets SET tenant_id = :t WHERE id = :id"),
            {"t": tenant_id, "id": dataset_id},
        )
        await test_db_session.commit()
        # Nothing cached may supply the answer: every ORM attribute in this
        # session is now expired, so the value can only have come from the
        # database. That is the whole claim under test.
        test_db_session.expire_all()

        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset_id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=actor_id,
            ingest_job_id=job_id,
            feature_count_before=1,
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.tenant_id == tenant_id

    async def test_single_tenant_leaves_it_null(self, test_db_session) -> None:
        dataset, job = await _seed(test_db_session)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=1,
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.tenant_id is None


class TestImmutableJobBinding:
    def test_no_write_path_reassigns_ingest_job_id(self) -> None:
        """The binding is set once at dispatch. A retry is a new row, never a
        re-pointed old one, so nothing may name this column in an UPDATE."""
        source = (
            Path(__file__).resolve().parents[1] / "app/platform/refresh/service.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        offenders: list[str] = []
        for node in ast.walk(tree):
            # `.values(...)` on an update(), and the values dicts callers build
            # and pass through `transition_run`.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "values":
                    offenders += [
                        kw.arg for kw in node.keywords if kw.arg == "ingest_job_id"
                    ]
            if isinstance(node, ast.Dict):
                offenders += [
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and key.value == "ingest_job_id"
                ]

        assert offenders == [], (
            "ingest_job_id appears in an UPDATE's values — the run's job "
            f"binding must be immutable after dispatch: {offenders}"
        )


class TestSchemaInvariants:
    async def test_status_check_refuses_an_invented_state(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        test_db_session.add(
            DatasetRefreshRun(
                dataset_id=dataset.id,
                origin_kind="upload",
                trigger="manual",
                status="blocked",
                started_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            await test_db_session.commit()
        await test_db_session.rollback()

    async def test_history_survives_the_ingest_job_purge(self, test_db_session) -> None:
        """#1219's acceptance criterion: no FK dependence on ingest_jobs."""
        dataset, job = await _seed(test_db_session)
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        run_id = run.id

        await test_db_session.execute(
            sa.text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job.id}
        )
        await test_db_session.commit()
        test_db_session.expire_all()

        survivor = await test_db_session.get(DatasetRefreshRun, run_id)
        assert survivor is not None
        assert survivor.ingest_job_id is None

    async def test_deleting_the_dataset_takes_its_history(
        self, test_db_session
    ) -> None:
        """The other direction: runs are per-dataset children, ON DELETE CASCADE."""
        dataset, job = await _seed(test_db_session)
        await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=job.id,
            feature_count_before=42,
        )
        await test_db_session.commit()
        dataset_id = dataset.id

        await test_db_session.execute(
            sa.text("DELETE FROM catalog.datasets WHERE id = :id"), {"id": dataset_id}
        )
        await test_db_session.commit()

        remaining = await test_db_session.scalar(
            sa.select(sa.func.count())
            .select_from(DatasetRefreshRun)
            .where(DatasetRefreshRun.dataset_id == dataset_id)
        )
        assert remaining == 0


# ---------------------------------------------------------------------------
# The stale-run sweep
# ---------------------------------------------------------------------------


async def _stale_run(session, *, job_status: str, age_seconds: int, run_status: str):
    """A run of the given age bound to a job in the given status."""
    dataset, job = await _seed(session)
    await session.execute(
        sa.text("UPDATE catalog.ingest_jobs SET status = :s WHERE id = :id"),
        {"s": job_status, "id": job.id},
    )
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=job.created_by,
        ingest_job_id=job.id,
        feature_count_before=42,
    )
    run.status = run_status
    run.started_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    await session.commit()
    return run, job


_WELL_PAST_CUTOFF = ABANDONED_RUN_CUTOFF_SECONDS + 600


class TestAbandonedRunSweep:
    async def test_cancels_a_pending_run_whose_job_failed(
        self, test_db_session
    ) -> None:
        run, _ = await _stale_run(
            test_db_session,
            job_status="failed",
            age_seconds=_WELL_PAST_CUTOFF,
            run_status="pending",
        )
        assert await sweep_abandoned_refresh_runs(test_db_session) >= 1
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "cancelled"
        assert run.error_code == ABANDONED_ERROR_CODE
        assert run.finished_at is not None

    async def test_leaves_a_young_run_alone(self, test_db_session) -> None:
        run, _ = await _stale_run(
            test_db_session,
            job_status="failed",
            age_seconds=60,
            run_status="pending",
        )
        await sweep_abandoned_refresh_runs(test_db_session)
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "pending"

    async def test_leaves_a_run_whose_job_is_still_alive(self, test_db_session) -> None:
        """A `running` job is still someone else's business — the ingest sweep
        gets first refusal, and skipping this round costs one cycle."""
        run, _ = await _stale_run(
            test_db_session,
            job_status="running",
            age_seconds=_WELL_PAST_CUTOFF,
            run_status="running",
        )
        await sweep_abandoned_refresh_runs(test_db_session)
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "running"

    async def test_leaves_a_run_with_a_queued_procrastinate_job(
        self, test_db_session
    ) -> None:
        """Age alone conflates "abandoned" with "waiting behind a queue"."""
        run, job = await _stale_run(
            test_db_session,
            job_status="failed",
            age_seconds=_WELL_PAST_CUTOFF,
            run_status="pending",
        )
        # Procrastinate's insert trigger writes procrastinate_events through
        # unqualified names, so the schema has to be on the search_path for a
        # hand-written INSERT the way it is for the library's own.
        await test_db_session.execute(
            sa.text("SET LOCAL search_path TO catalog, public")
        )
        await test_db_session.execute(
            sa.text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) "
                "VALUES ('ingest', 'reupload_file', "
                "jsonb_build_object('job_id', CAST(:job_id AS text)), 'todo')"
            ),
            {"job_id": str(job.id)},
        )
        await test_db_session.commit()

        await sweep_abandoned_refresh_runs(test_db_session)
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "pending"

    async def test_cancelling_releases_the_dataset_for_a_new_run(
        self, test_db_session
    ) -> None:
        """The release valve for admission control.

        `uq_refresh_runs_one_active` means a run stuck in `pending` blocks
        every later refresh of that dataset, so the sweep is not only
        bookkeeping — it is what stops a dead worker from wedging a dataset
        forever. Cancelling moves the row out of the index's predicate, which
        is a property of the index and the sweep TOGETHER; neither test alone
        would notice it breaking.
        """
        run, job = await _stale_run(
            test_db_session,
            job_status="failed",
            age_seconds=_WELL_PAST_CUTOFF,
            run_status="pending",
        )
        dataset_id = run.dataset_id

        # While it is stuck, the dataset is closed for business.
        with pytest.raises(DatasetBusyError):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset_id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=job.created_by,
                ingest_job_id=None,
                feature_count_before=1,
            )

        assert await sweep_abandoned_refresh_runs(test_db_session) >= 1
        await test_db_session.commit()

        # And open again once the sweep has proven the task gone.
        await create_pending_run(
            test_db_session,
            dataset_id=dataset_id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=None,
            feature_count_before=1,
        )
        await test_db_session.commit()

    async def test_completed_legacy_job_records_success(self, test_db_session) -> None:
        """fix(#1274 review): migration 0037's backfilled rows belong to
        legacy workers that finish by marking the job complete without ever
        calling the finalizer. A complete job IS proof the swap committed, so
        the sweep records succeeded — stamped with the job's own completion
        time — instead of leaving the row active forever and the dataset
        wedged behind the admission index. No cutoff needed: the job's
        terminal status is the proof."""
        run, job = await _stale_run(
            test_db_session,
            job_status="complete",
            age_seconds=60,
            run_status="running",
        )
        job.completed_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        await test_db_session.commit()

        assert await sweep_abandoned_refresh_runs(test_db_session) >= 1
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "succeeded"
        assert run.finished_at == job.completed_at
        assert run.error_code is None

        # And the dataset is open for business again.
        await create_pending_run(
            test_db_session,
            dataset_id=run.dataset_id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=job.created_by,
            ingest_job_id=None,
            feature_count_before=1,
        )
        await test_db_session.commit()

    async def test_leaves_terminal_runs_alone(self, test_db_session) -> None:
        run, _ = await _stale_run(
            test_db_session,
            job_status="failed",
            age_seconds=_WELL_PAST_CUTOFF,
            run_status="succeeded",
        )
        await sweep_abandoned_refresh_runs(test_db_session)
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "succeeded"


# ---------------------------------------------------------------------------
# The dataset-scoped history API
# ---------------------------------------------------------------------------


async def _seed_history(session, *, visibility: str = "public"):
    """One succeeded run with every redactable field populated."""
    dataset, job = await _seed(session, visibility=visibility)
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="manual",
        triggered_by=job.created_by,
        ingest_job_id=job.id,
        feature_count_before=42,
    )
    await session.commit()
    await record_refresh_failure(
        session,
        ingest_job_id=job.id,
        error_code="service_refresh_failed",
        error_message="Layer 'parcels' vanished from the service",
        contacted_origin=True,
    )
    await session.commit()
    await session.refresh(run)
    return dataset, run


# Decision 4e's list, named once so a test cannot quietly cover fewer fields
# than it claims to.
_REDACTED_FIELDS = (
    "triggered_by",
    "triggered_by_username",
    "error_code",
    "error_message",
    "schema_diff",
)


class TestRefreshRunListEndpoint:
    async def test_owner_sees_the_whole_row(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        dataset, run = await _seed_history(test_db_session)
        resp = await client.get(
            f"/datasets/{dataset.id}/refresh-runs", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        row = body["runs"][0]
        assert row["id"] == str(run.id)
        assert row["status"] == "failed"
        assert row["origin_kind"] == "service"
        assert row["trigger"] == "manual"
        assert row["feature_count_before"] == 42
        assert row["triggered_by"] is not None
        assert row["triggered_by_username"] == "admin"
        assert row["error_code"] == "service_refresh_failed"
        assert "parcels" in row["error_message"]

    @pytest.mark.parametrize("reader", ["viewer", "editor"])
    async def test_a_named_third_party_gets_the_timeline_without_the_people(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
        reader: str,
    ) -> None:
        """The case requester-scoped review misses: a signed-in stranger.

        Both of these are real accounts with real tokens and no grant on the
        dataset, which is a different code path from `user is None` — the
        anonymous test below cannot stand in for it.
        """
        dataset, _ = await _seed_history(test_db_session)
        headers = {"viewer": viewer_auth_header, "editor": editor_auth_header}[reader]

        resp = await client.get(f"/datasets/{dataset.id}/refresh-runs", headers=headers)
        assert resp.status_code == 200, resp.text
        row = resp.json()["runs"][0]
        # Still useful: the outcome and the timeline survive redaction.
        assert row["status"] == "failed"
        assert row["started_at"] is not None
        assert row["feature_count_before"] == 42
        for field in _REDACTED_FIELDS:
            assert row[field] is None, f"{field} leaked to a {reader}"

    async def test_anonymous_reader_is_redacted_too(
        self, client: AsyncClient, test_db_session
    ) -> None:
        dataset, _ = await _seed_history(test_db_session)
        resp = await client.get(f"/datasets/{dataset.id}/refresh-runs")
        assert resp.status_code == 200, resp.text
        row = resp.json()["runs"][0]
        for field in _REDACTED_FIELDS:
            assert row[field] is None, f"{field} leaked to an anonymous reader"

    async def test_private_history_is_not_readable_by_a_stranger(
        self, client: AsyncClient, viewer_auth_header: dict, test_db_session
    ) -> None:
        """Rule 1 on the read path — the redaction is defence in depth, not
        the access control."""
        dataset, _ = await _seed_history(test_db_session, visibility="private")
        resp = await client.get(
            f"/datasets/{dataset.id}/refresh-runs", headers=viewer_auth_header
        )
        assert resp.status_code == 404, resp.text

    async def test_missing_dataset_is_404(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        resp = await client.get(
            f"/datasets/{uuid.uuid4()}/refresh-runs", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_empty_history_is_an_empty_page(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        user_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=user_id)
        resp = await client.get(
            f"/datasets/{dataset.id}/refresh-runs", headers=admin_auth_header
        )
        assert resp.status_code == 200
        assert resp.json() == {"runs": [], "total": 0}


@contextmanager
def _stubbed_reupload_dispatch(*, side_effect: BaseException | None = None):
    """Stop the commit door's `defer` from reaching a real queue.

    Mirrors the fixture pair in test_reupload.py: the port instance is pinned
    first so the method patch is visible to the router's own lookup. Passing a
    ``side_effect`` simulates an unreachable queue, which is what the orphan
    guard exists for — deliberately explicit rather than relying on the test
    environment happening to have no worker.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.catalog.datasets.api import router_reupload

    port = router_reupload.get_catalog_port()
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None, side_effect=side_effect)
    task.configure.return_value.defer_async = AsyncMock(
        return_value=None, side_effect=side_effect
    )
    with (
        patch.object(router_reupload, "get_catalog_port", return_value=port),
        patch.object(port, "reupload_file_task", return_value=task),
    ):
        yield task


@pytest.fixture
def stub_reupload_dispatch():
    with _stubbed_reupload_dispatch() as task:
        yield task


async def _upload_for_reupload(
    client: AsyncClient, dataset_id: uuid.UUID, headers: dict
) -> str:
    resp = await client.post(
        f"/datasets/{dataset_id}/reupload",
        files={
            "file": (
                "parcels.geojson",
                b'{"type":"FeatureCollection","features":[]}',
                "application/json",
            )
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


class TestDispatchCreatesTheRun:
    """The runtime half of "created at dispatch, and nowhere earlier"."""

    async def test_upload_alone_records_nothing_and_commit_records_a_pending_run(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        stub_reupload_dispatch,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)
        job_id = await _upload_for_reupload(client, dataset.id, admin_auth_header)

        # Staging bytes are not a refresh. Nothing is committed yet, so
        # nothing may be in the history.
        _, before = await list_runs_for_dataset(test_db_session, dataset.id)
        assert before == 0

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/commit",
            json={},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text

        runs, total = await list_runs_for_dataset(test_db_session, dataset.id)
        assert total == 1
        run = runs[0]
        assert run.status == "pending"
        assert run.origin_kind == "upload"
        assert run.trigger == "manual"
        assert run.triggered_by == admin_id
        assert run.ingest_job_id == uuid.UUID(job_id)
        assert run.feature_count_before == dataset.feature_count
        assert run.finished_at is None

    async def test_a_dispatch_that_cannot_queue_leaves_a_failed_run(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The orphan guard's compensation, end to end.

        The sweep would eventually cancel this row, but the outcome is known
        at the moment the 503 is returned, and an hour of `pending` for a
        dispatch that provably never happened is the silent-failure shape.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        with _stubbed_reupload_dispatch():
            job_id = await _upload_for_reupload(client, dataset.id, admin_auth_header)

        with _stubbed_reupload_dispatch(side_effect=RuntimeError("queue down")):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job_id}/commit",
                json={},
                headers=admin_auth_header,
            )
        assert resp.status_code == 503, resp.text

        runs, total = await list_runs_for_dataset(test_db_session, dataset.id)
        assert total == 1
        assert runs[0].status == "failed"
        assert runs[0].error_code == "dispatch_failed"

    async def test_a_second_dispatch_is_refused_with_dataset_busy(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """ADR-002 Decision 5b at the door, not at the advisory lock.

        Two humans clicking commit is the ordinary case, not the exotic one.
        Refusing the second here means only one job is ever queued; refusing it
        in the worker would mean two jobs raced for the same staging table.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        with _stubbed_reupload_dispatch():
            first_job = await _upload_for_reupload(
                client, dataset.id, admin_auth_header
            )
            second_job = await _upload_for_reupload(
                client, dataset.id, admin_auth_header
            )

            accepted = await client.post(
                f"/datasets/{dataset.id}/reupload/{first_job}/commit",
                json={},
                headers=admin_auth_header,
            )
            assert accepted.status_code == 202, accepted.text

            refused = await client.post(
                f"/datasets/{dataset.id}/reupload/{second_job}/commit",
                json={},
                headers=admin_auth_header,
            )

        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "dataset_busy"

        # Exactly one run, and the refused job stays committable later.
        runs, total = await list_runs_for_dataset(test_db_session, dataset.id)
        assert total == 1
        assert runs[0].ingest_job_id == uuid.UUID(first_job)
        second = await test_db_session.get(IngestJob, uuid.UUID(second_job))
        await test_db_session.refresh(second)
        assert second.status == "pending"


class TestCommitTimeRecompute:
    """The persisted diff describes the STAGED data, never the preview.

    A preview can be minutes old, and for a live service the rows it described
    are not the rows about to be installed. Persisting the preview would put a
    number in the history that no committed data ever matched.
    """

    def _port(self):
        from app.platform.extensions import get_processing_port

        return get_processing_port()

    async def test_persisted_diff_reflects_the_staged_data_not_the_preview(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(
            test_db_session,
            column_info=[{"name": "id", "type": "Integer"}],
            feature_count=10,
        )
        port = self._port()

        # What the preview saw: the service had gained one column.
        preview_diff = port.compute_schema_diff(
            dataset.column_info,
            [{"name": "id", "type": "Integer"}, {"name": "zone", "type": "String"}],
            dataset.feature_count,
            10,
        )
        assert [c["name"] for c in preview_diff["columns_added"]] == ["zone"]

        # What the worker actually staged, minutes later: the service moved on.
        staged_columns = [
            {"name": "id", "type": "Integer"},
            {"name": "zone", "type": "String"},
            {"name": "owner", "type": "String"},
        ]
        recomputed = port.compute_schema_diff(
            dataset.column_info, staged_columns, dataset.feature_count, 31
        )

        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
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
            feature_count_after=31,
            schema_diff=recomputed,
            contacted_origin=True,
        )
        await test_db_session.commit()
        await test_db_session.refresh(run)

        assert [c["name"] for c in run.schema_diff["columns_added"]] == [
            "owner",
            "zone",
        ]
        assert run.schema_diff != preview_diff
        assert run.schema_diff["row_count_new"] == 31
        assert run.feature_count_after == 31

    def test_the_recompute_runs_before_the_swap_overwrites_its_inputs(self) -> None:
        """Order is the whole correctness argument, so pin it.

        `_apply_reupload_swap` assigns dataset.column_info and feature_count
        from the staging metadata. Compute the diff after that call and both
        sides of the comparison are the NEW data, so every diff comes back
        empty and every dataset reports schema_drift_status='none'. That
        failure is silent — a permissive default with no symptom — which is
        exactly why it gets a structural test rather than trust.
        """
        source = (
            Path(__file__).resolve().parents[1]
            / "app/processing/ingest/tasks_reupload.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            diff_lines = [
                call.lineno
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "compute_schema_diff"
            ]
            swap_lines = [
                call.lineno
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_apply_reupload_swap"
            ]
            if not diff_lines or not swap_lines:
                continue
            checked += 1
            assert max(diff_lines) < min(swap_lines), (
                f"{node.name}: compute_schema_diff must run BEFORE "
                "_apply_reupload_swap overwrites dataset.column_info"
            )

        assert checked == 2, (
            f"expected both reupload tasks to recompute the diff; found {checked}"
        )


class TestHistoryPaging:
    async def test_newest_first_and_total_counts_everything(
        self, test_db_session
    ) -> None:
        dataset, job = await _seed(test_db_session)
        base = datetime.now(timezone.utc)
        # Each run is retired before the next is created: uq_refresh_runs_one_
        # active permits exactly one pending-or-running row per dataset, which
        # is the point of the index and is also what a real history looks like.
        for offset in range(3):
            run = await create_pending_run(
                test_db_session,
                dataset_id=dataset.id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=job.created_by,
                ingest_job_id=None,
                feature_count_before=offset,
            )
            run.started_at = base - timedelta(minutes=offset)
            run.status = "succeeded"
            await test_db_session.flush()
        await test_db_session.commit()

        page, total = await list_runs_for_dataset(
            test_db_session, dataset.id, skip=0, limit=2
        )
        assert total == 3
        assert [run.feature_count_before for run in page] == [0, 1]

        tail, _ = await list_runs_for_dataset(
            test_db_session, dataset.id, skip=2, limit=2
        )
        assert [run.feature_count_before for run in tail] == [2]


class TestMigrationBackfill:
    """fix(#1274 review): in-flight legacy reupload jobs get run rows at
    upgrade, or the admission index sees their dataset as idle and admits a
    concurrent refresh against the same tables the old task will still swap."""

    @staticmethod
    def _backfill_sql() -> str:
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "alembic"
            / "versions"
            / "0037_dataset_refresh_runs.py"
        ).read_text()
        match = re.search(
            r"(INSERT INTO catalog\.dataset_refresh_runs.*?\) AS s)",
            source,
            re.DOTALL,
        )
        assert match, "backfill statement not found in migration 0037"
        return match.group(1)

    async def test_in_flight_legacy_job_gets_a_running_row(
        self, test_db_session
    ) -> None:
        from sqlalchemy import text as sa_text

        dataset, job = await _seed(test_db_session)
        job.attempt_id = uuid.uuid4()
        job.source_url = "https://svc.test/wfs"
        await test_db_session.commit()

        await test_db_session.execute(sa_text(self._backfill_sql()))
        await test_db_session.commit()

        run = (
            await test_db_session.execute(
                select(DatasetRefreshRun).where(
                    DatasetRefreshRun.ingest_job_id == job.id
                )
            )
        ).scalar_one()
        assert run.status == "running"
        assert run.origin_kind == "service"
        assert run.dataset_id == dataset.id
        # The backfilled row is refereed by the same admission index.
        with pytest.raises(DatasetBusyError):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset.id,
                origin_kind="service",
                trigger="manual",
                triggered_by=job.created_by,
                ingest_job_id=None,
                feature_count_before=None,
            )

    async def test_pending_job_with_live_task_is_backfilled(
        self, test_db_session
    ) -> None:
        """Dispatched-but-unclaimed legacy work is identified by its live
        Procrastinate row — the same correlation the abandoned-run sweep
        trusts — never by attempt_id, which every job carries from birth."""
        from sqlalchemy import text as sa_text

        _dataset, job = await _seed(test_db_session)
        job.status = "pending"
        await test_db_session.commit()
        # SET LOCAL search_path: procrastinate's insert trigger writes to
        # procrastinate_events by its unqualified name.
        await test_db_session.execute(
            sa_text("SET LOCAL search_path TO catalog, public")
        )
        await test_db_session.execute(
            sa_text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) "
                "VALUES ('ingest', 'reupload_service', "
                "jsonb_build_object('job_id', CAST(:j AS text)), 'todo')"
            ),
            {"j": str(job.id)},
        )
        await test_db_session.commit()

        await test_db_session.execute(sa_text(self._backfill_sql()))
        await test_db_session.commit()

        count = (
            await test_db_session.execute(
                select(func.count())
                .select_from(DatasetRefreshRun)
                .where(DatasetRefreshRun.ingest_job_id == job.id)
            )
        ).scalar_one()
        assert count == 1

    async def test_staged_but_undispatched_job_is_not_backfilled(
        self, test_db_session
    ) -> None:
        """A pending job with no live Procrastinate task was never handed to
        a worker — an uncommitted staged preview, not an in-flight refresh.
        attempt_id deliberately proves nothing: every job carries one from
        birth (fix #1274 review), so a run invented from it would 409 the
        real commit until the stale sweep."""
        from sqlalchemy import text as sa_text

        _dataset, job = await _seed(test_db_session)
        job.status = "pending"
        await test_db_session.commit()

        await test_db_session.execute(sa_text(self._backfill_sql()))
        await test_db_session.commit()

        count = (
            await test_db_session.execute(
                select(func.count())
                .select_from(DatasetRefreshRun)
                .where(DatasetRefreshRun.ingest_job_id == job.id)
            )
        ).scalar_one()
        assert count == 0


class TestLegacyDoubleDrain:
    async def test_reservation_survives_until_every_legacy_task_drains(
        self, test_db_session
    ) -> None:
        """fix(#1274 review): the old system had no admission control, so two
        legacy reupload tasks for one dataset can both be live while the
        backfill could represent only one. The sole run's reservation must
        outlive BOTH — releasing on its bound job's completion would let a
        new refresh race the unrepresented worker's swap."""
        from sqlalchemy import text as sa_text

        dataset, bound_job = await _seed(test_db_session)
        user_id = bound_job.created_by
        other_job = IngestJob(
            dataset_id=dataset.id,
            status="running",
            source_filename="other.gpkg",
            created_by=user_id,
            user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
        )
        test_db_session.add(other_job)
        await test_db_session.commit()

        # The backfilled run, bound to the first job; the second legacy
        # worker is represented only by its live Procrastinate task.
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset.id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=user_id,
            ingest_job_id=bound_job.id,
            feature_count_before=1,
        )
        await test_db_session.execute(
            sa_text("SET LOCAL search_path TO catalog, public")
        )
        await test_db_session.execute(
            sa_text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) "
                "VALUES ('ingest', 'reupload_file', "
                "jsonb_build_object('job_id', CAST(:j AS text)), 'doing')"
            ),
            {"j": str(other_job.id)},
        )
        bound_job.status = "complete"
        bound_job.completed_at = datetime.now(timezone.utc)
        await test_db_session.commit()

        # Bound job complete, but the OTHER legacy task is still live: hold.
        await sweep_abandoned_refresh_runs(test_db_session)
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "pending"

        # The other task drains; now the completion is safe to record.
        # search_path again: the status column's enum type is schema-local.
        await test_db_session.execute(
            sa_text("SET LOCAL search_path TO catalog, public")
        )
        await test_db_session.execute(
            sa_text(
                "UPDATE catalog.procrastinate_jobs SET status = 'succeeded' "
                "WHERE args->>'job_id' = CAST(:j AS text)"
            ),
            {"j": str(other_job.id)},
        )
        await test_db_session.commit()
        assert await sweep_abandoned_refresh_runs(test_db_session) >= 1
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "succeeded"


class TestDrainingPodAdmission:
    async def test_live_legacy_task_without_a_run_row_refuses_admission(
        self, test_db_session
    ) -> None:
        """fix(#1274 review): a reupload enqueued by a still-draining
        pre-migration API pod has a live task but no run row, so the index
        cannot referee it — admission must, until those pods drain."""
        from sqlalchemy import text as sa_text

        dataset, legacy_job = await _seed(test_db_session)
        dataset_id, legacy_job_id = dataset.id, legacy_job.id
        actor_id = legacy_job.created_by
        await test_db_session.execute(
            sa_text("SET LOCAL search_path TO catalog, public")
        )
        await test_db_session.execute(
            sa_text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) "
                "VALUES ('ingest', 'reupload_file', "
                "jsonb_build_object('job_id', CAST(:j AS text)), 'todo')"
            ),
            {"j": str(legacy_job_id)},
        )
        await test_db_session.commit()

        with pytest.raises(DatasetBusyError):
            await create_pending_run(
                test_db_session,
                dataset_id=dataset_id,
                origin_kind="upload",
                trigger="manual",
                triggered_by=actor_id,
                ingest_job_id=None,
                feature_count_before=1,
            )

        # Once the legacy job has a run row, the check goes inert and the
        # index referees as usual.
        await test_db_session.rollback()
        run = await create_pending_run(
            test_db_session,
            dataset_id=dataset_id,
            origin_kind="upload",
            trigger="manual",
            triggered_by=actor_id,
            ingest_job_id=legacy_job_id,
            feature_count_before=1,
        )
        await test_db_session.commit()
        assert run.status == "pending"


class TestInterruptedDispatchRelease:
    async def test_pending_job_with_no_task_releases_after_cutoff(
        self, test_db_session
    ) -> None:
        """fix(#1274 review): death between the commit and the defer leaves
        job and run pending with no task. The bound-job sweep waits 24 hours
        for a staged completion, but the RUN must release at the abandonment
        cutoff or every retry 409s for that whole window."""
        run, _job = await _stale_run(
            test_db_session,
            job_status="pending",
            age_seconds=_WELL_PAST_CUTOFF,
            run_status="pending",
        )
        assert await sweep_abandoned_refresh_runs(test_db_session) >= 1
        await test_db_session.commit()
        await test_db_session.refresh(run)
        assert run.status == "cancelled"

"""The job ledger moves a job once, fenced, and settles its linked rows with it."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import joinedload

import app.core.db as db_module
from app.core.db.sqlstate import is_lock_conflict
from app.core.service_tokens import register_credential_secret
from app.core.url_redaction import REDACTED_SECRET
from app.modules.audit.models import AuditLog
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs import ledger
from app.platform.jobs.heartbeat import (
    StaleIngestAttempt,
    attempt_scoped_staging_table,
    require_ingest_job_update,
)
from app.platform.jobs.ledger import (
    Ended,
    LinkedOwner,
    Outcome,
    abort,
    cancel,
    hold,
    retry,
)
from app.platform.jobs.models import (
    EMBEDDING_BACKFILL_METADATA_KEY,
    FAN_OUT_INTERRUPTED_METADATA_KEY,
    IngestJob,
)
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    USER_CANCELLED_ERROR_CODE,
    claim_run_for_job,
    create_pending_run,
    record_refresh_success,
)
from app.processing.ingest.catalog_projection import measure
from app.processing.raster.models import RasterAsset, VrtGeneration
from tests.test_reupload_swap_lock_retry import swap_in
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_embedding_backfill_queue_1542 import _release_slot
from tests.test_job_cancel_vrt import _seed_vrt_regeneration
from tests.test_refresh_dispatch_rollback import _committed_dispatch
from tests.test_stale_settlement_pass_2151 import _a_settler_waits_on_a_row_lock

pytestmark = pytest.mark.anyio

_STATUSES = ("pending", "running", "complete", "failed", "cancelled", "fanned_out")
_REASON = "Failed to queue ingest task (RuntimeError)"


@pytest.fixture(autouse=True)
async def _drop_ledger_jobs(test_db_session):
    """Keep this file's job rows out of the worker database's later sweeps."""
    yield
    await test_db_session.rollback()
    await test_db_session.execute(
        delete(IngestJob).where(IngestJob.source_filename == "ledger.geojson")
    )
    await test_db_session.commit()


async def _job(session, *, status: str = "pending", **columns) -> IngestJob:
    job = IngestJob(
        source_filename="ledger.geojson",
        status=status,
        attempt_id=uuid.uuid4(),
        **columns,
    )
    session.add(job)
    await session.commit()
    return job


async def _row(session, job_id: uuid.UUID) -> IngestJob:
    return await session.get(IngestJob, job_id, populate_existing=True)


async def _run_events(
    session, dataset_id: uuid.UUID, action: str = "refresh.failed"
) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == action, AuditLog.resource_id == dataset_id)
    )


async def _set(session, job_id: uuid.UUID, **values) -> None:
    """Move the row behind the caller's back, leaving its instance stale."""
    await session.execute(
        update(IngestJob)
        .where(IngestJob.id == job_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await session.commit()


async def _table_rows(session, table: str) -> list[str]:
    return list(
        (await session.execute(sa.text(f'SELECT name FROM data."{table}"'))).scalars()
    )


async def _version_count(session, dataset_id: uuid.UUID) -> int:
    return (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM catalog.dataset_versions"
                " WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )
    ).scalar_one()


async def _seed_running_reupload(session):
    """A dataset with a live table, its running re-upload job and claimed run,
    and the attempt's staging table holding the replacement row."""
    admin_id = await get_user_id(session, "admin")
    live = f"cancelfence_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(session, created_by=admin_id, table_name=live)

    attempt_id = uuid.uuid4()
    staging = attempt_scoped_staging_table(live, attempt_id)
    for table, row in ((live, "original"), (staging, "new_data")):
        await session.execute(
            sa.text(
                f'CREATE TABLE data."{table}" '
                "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326), "
                "geom_4326 geometry(Geometry, 4326))"
            )
        )
        await session.execute(
            sa.text(f'INSERT INTO data."{table}" (name) VALUES (:row)'),
            {"row": row},
        )

    job = IngestJob(
        dataset_id=dataset.id,
        status="running",
        attempt_id=attempt_id,
        started_at=datetime.now(timezone.utc),
        heartbeat_at=datetime.now(timezone.utc),
        source_filename="parcels.gpkg",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    assert await claim_run_for_job(session, job.id) == run.id
    await session.commit()
    return dataset, job, run, live, staging


async def _drive_finalize_verbatim(
    session,
    *,
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    staging: str,
) -> None:
    """The re-upload worker's finalize in one transaction, left uncommitted:
    measure, fenced heartbeat, swap, fenced complete, then the run's success."""
    dataset = (
        await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()
    measurement = await measure(session, dataset, table=staging, schema="data")
    await require_ingest_job_update(
        session,
        job_id,
        attempt_id,
        values={"heartbeat_at": datetime.now(timezone.utc)},
    )
    version, schema_diff = await swap_in(
        session,
        dataset=dataset,
        staging_table=staging,
        measurement=measurement,
        user_id=str(dataset.record.created_by),
        source_filename="parcels.gpkg",
        source_format="gpkg",
        original_srid=4326,
    )
    await require_ingest_job_update(
        session,
        job_id,
        attempt_id,
        values={
            "status": "complete",
            "completed_at": datetime.now(timezone.utc),
        },
    )
    await record_refresh_success(
        session,
        ingest_job_id=job_id,
        dataset=dataset,
        dataset_version_id=version.id,
        feature_count_after=measurement.metadata.get("feature_count"),
        schema_diff=schema_diff,
        contacted_origin=False,
    )


class TestHold:
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_returns_the_row_only_in_the_expected_state(
        self, test_db_session, status
    ):
        """hold returns a job in the state it expects, and None in any other."""
        job = await _job(test_db_session, status=status)
        job_id = job.id

        held = await hold(test_db_session, job_id, expect="pending")
        assert (held is not None) == (status == "pending")
        held_as_is = await hold(test_db_session, job_id, expect=status)
        assert held_as_is is not None and held_as_is.id == job_id
        await test_db_session.rollback()
        assert (await _row(test_db_session, job_id)).status == status

    async def test_misses_a_superseded_attempt(self, test_db_session):
        """hold returns None when another attempt owns the row."""
        job = await _job(test_db_session)

        assert (
            await hold(
                test_db_session, job.id, expect="pending", attempt_id=uuid.uuid4()
            )
            is None
        )
        assert (
            await hold(
                test_db_session, job.id, expect="pending", attempt_id=job.attempt_id
            )
            is not None
        )
        await test_db_session.rollback()

    async def test_locks_the_row_until_the_transaction_ends(self, test_db_session):
        """A held row refuses another transaction's lock."""
        job = await _job(test_db_session)
        job_id = job.id
        assert await hold(test_db_session, job_id, expect="pending") is not None

        async with db_module.async_session() as other:
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                await other.execute(
                    select(IngestJob.id)
                    .where(IngestJob.id == job_id)
                    .with_for_update(nowait=True)
                )
            await other.rollback()
        await test_db_session.rollback()


class TestAbort:
    @pytest.mark.parametrize("expect", ["pending", "running"])
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_fails_only_a_job_in_the_expected_state(
        self, test_db_session, status, expect
    ):
        """abort fails a job in the state it expects and writes nothing otherwise."""
        job = await _job(test_db_session, status=status)
        job_id = job.id

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON, expect=expect
        )
        if status == expect:
            assert outcome is Outcome.LANDED
            assert job.status == "failed", "the instance was not told"
        else:
            assert outcome is Outcome.MOVED
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        if status == expect:
            assert (row.status, row.error_message) == ("failed", _REASON)
            assert row.completed_at is not None
        else:
            assert (row.status, row.error_message, row.completed_at) == (
                status,
                None,
                None,
            )

    async def test_leaves_a_superseded_attempt_unwritten(self, test_db_session):
        """abort on an attempt a retry replaced reports it and writes nothing."""
        job = await _job(test_db_session)
        job_id = job.id
        await _set(test_db_session, job_id, attempt_id=uuid.uuid4())

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON
        )
        await test_db_session.commit()

        assert outcome is Outcome.SUPERSEDED
        row = await _row(test_db_session, job_id)
        assert (row.status, row.error_message) == ("pending", None)

    async def test_reports_a_missing_job(self, test_db_session):
        """abort on a row that does not exist reports it missing."""
        absent = IngestJob(id=uuid.uuid4(), attempt_id=uuid.uuid4(), status="pending")

        outcome = await abort(
            test_db_session, absent, code="dispatch_failed", reason=_REASON
        )

        assert outcome is Outcome.MISSING

    async def test_refuses_a_state_no_dispatch_leaves_a_job_in(self, test_db_session):
        """abort ends only a pending job, or a running URL import."""
        job = await _job(test_db_session, status="complete")

        with pytest.raises(ValueError):
            await abort(
                test_db_session,
                job,
                code="dispatch_failed",
                reason=_REASON,
                expect="complete",
            )

    async def test_stores_the_reason_redacted(self, test_db_session):
        """abort keeps credentials and library exception text out of the stored reason."""
        leaky = await _job(test_db_session)
        library = await _job(test_db_session)

        await abort(
            test_db_session,
            leaky,
            code="content_rejected",
            reason="Rejected https://reader:hunter2@example.test/data?token=abc",
        )
        await abort(
            test_db_session,
            library,
            code="dispatch_failed",
            reason=OSError("connection to 10.0.0.5 refused"),
        )
        await test_db_session.commit()

        stored = (await _row(test_db_session, leaky.id)).error_message
        assert "hunter2" not in stored and "abc" not in stored
        assert (
            await _row(test_db_session, library.id)
        ).error_message == "internal_error"

    async def test_scrubs_a_registered_credential_from_the_reason(
        self, test_db_session
    ):
        """abort scrubs a credential registered in its context out of the stored reason."""
        job = await _job(test_db_session)
        job_id = job.id
        register_credential_secret("user")

        await abort(
            test_db_session, job, code="dispatch_failed", reason="Refused for user"
        )
        await test_db_session.commit()

        assert (await _row(test_db_session, job_id)).error_message == (
            f"Refused for {REDACTED_SECRET}"
        )


class TestCancel:
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_ends_only_a_pending_or_running_job(self, test_db_session, status):
        """cancel ends a pending or running job as the user's and writes nothing otherwise."""
        job = await _job(test_db_session, status=status)
        job_id = job.id
        active = status in ("pending", "running")

        ended = await cancel(test_db_session, job, actor=uuid.uuid4())
        assert ended == Ended(Outcome.LANDED if active else Outcome.MOVED)
        if active:
            assert job.status == "cancelled", "the instance was not told"
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        if active:
            assert (row.status, row.error_message) == ("cancelled", "Cancelled by user")
            assert row.completed_at is not None
        else:
            assert (row.status, row.error_message, row.completed_at) == (
                status,
                None,
                None,
            )

    async def test_leaves_a_superseded_attempt_unwritten(self, test_db_session):
        """A cancel aimed at an attempt a retry replaced reports it and writes nothing."""
        job = await _job(test_db_session)
        job_id = job.id
        await _set(test_db_session, job_id, attempt_id=uuid.uuid4())

        ended = await cancel(test_db_session, job, actor=uuid.uuid4())
        await test_db_session.commit()

        assert ended == Ended(Outcome.SUPERSEDED)
        row = await _row(test_db_session, job_id)
        assert (row.status, row.error_message) == ("pending", None)

    async def test_stores_its_reason_as_written(self, test_db_session):
        """cancel stores its own reason unchanged when a registered credential matches part of it."""
        job = await _job(test_db_session)
        job_id = job.id
        register_credential_secret("user")

        await cancel(test_db_session, job, actor=uuid.uuid4())
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert (row.status, row.error_message) == ("cancelled", "Cancelled by user")


class TestRetry:
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_returns_only_a_failed_job_to_pending(self, test_db_session, status):
        """retry puts a failed job back to pending under a new attempt and writes nothing otherwise."""
        failed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job = await _job(
            test_db_session,
            status=status,
            error_message="boom",
            started_at=failed_at,
            heartbeat_at=failed_at,
            completed_at=failed_at,
            user_metadata={"kept": True},
        )
        job_id, old_attempt = job.id, job.attempt_id

        outcome = await retry(test_db_session, job)
        if status == "failed":
            assert outcome is Outcome.LANDED
            assert job.attempt_id not in (None, old_attempt), (
                "the instance was not told"
            )
        else:
            assert outcome is Outcome.MOVED
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        if status == "failed":
            assert (row.status, row.attempt_id) == ("pending", job.attempt_id)
            assert (row.error_message, row.started_at) == (None, None)
            assert (row.heartbeat_at, row.completed_at) == (None, None)
            assert row.user_metadata["kept"] is True
            assert row.user_metadata["staged_at"]
        else:
            assert (row.status, row.attempt_id, row.error_message) == (
                status,
                old_attempt,
                "boom",
            )

    async def test_leaves_a_superseded_attempt_unwritten(self, test_db_session):
        """A retry aimed at an attempt another retry replaced reports it and writes nothing."""
        job = await _job(test_db_session, status="failed")
        job_id, newer = job.id, uuid.uuid4()
        await _set(test_db_session, job_id, attempt_id=newer)

        assert await retry(test_db_session, job) is Outcome.SUPERSEDED
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert (row.status, row.attempt_id) == ("failed", newer)

    async def test_a_late_worker_on_the_old_attempt_writes_nothing(
        self, test_db_session, clean_tables
    ):
        """After a retry, a worker still holding the old attempt can neither claim nor finish the job."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        job = await _job(test_db_session, status="failed", dataset_id=dataset.id)
        job_id, old_attempt = job.id, job.attempt_id

        assert await retry(test_db_session, job) is Outcome.LANDED
        await test_db_session.commit()
        new_attempt = job.attempt_id

        assert not await ledger.claim(test_db_session, job_id, old_attempt)
        with pytest.raises(StaleIngestAttempt):
            await require_ingest_job_update(
                test_db_session,
                job_id,
                old_attempt,
                values={"status": "complete"},
            )
        await test_db_session.rollback()

        row = await _row(test_db_session, job_id)
        assert (row.status, row.attempt_id, row.dataset_id) == (
            "pending",
            new_attempt,
            None,
        )


class TestCreate:
    @pytest.mark.parametrize("status", ["pending", "running"])
    async def test_adds_a_pending_or_running_job(self, test_db_session, status):
        """create adds a pending job, or a running one started now."""
        job = ledger.create(
            test_db_session,
            created_by=None,
            status=status,
            source_filename="ledger.geojson",
            file_path="",
        )
        await test_db_session.commit()
        job_id = job.id

        row = await _row(test_db_session, job_id)
        assert row.status == status
        assert (row.started_at is not None) is (status == "running")

    @pytest.mark.parametrize(
        "status", ["complete", "failed", "cancelled", "fanned_out"]
    )
    async def test_refuses_a_state_only_a_transition_reaches(
        self, test_db_session, status
    ):
        """create refuses a job that would start terminal or fanned out."""
        with pytest.raises(ValueError, match="cannot be created"):
            ledger.create(
                test_db_session,
                created_by=None,
                status=status,
                source_filename="ledger.geojson",
            )


# Each owner transition's from-states, its target, and a call on a fixture job.
_OWNER_MOVES = {
    "claim": (
        ("pending",),
        "running",
        lambda s, job: ledger.claim(s, job.id, job.attempt_id),
    ),
    "stage": (
        ("running",),
        "pending",
        lambda s, job: ledger.stage(
            s, job.id, job.attempt_id, values={"file_path": "staged.geojson"}
        ),
    ),
    "fan_out": (
        ("pending",),
        "fanned_out",
        lambda s, job: ledger.fan_out(s, job.id, job.attempt_id),
    ),
    "restore": (
        ("fanned_out",),
        "pending",
        lambda s, job: ledger.restore(s, job.id, job.attempt_id),
    ),
    "fail": (
        ("running",),
        "failed",
        lambda s, job: ledger.fail(s, job.id, job.attempt_id, reason=_REASON),
    ),
}


async def _owner_end(session, end: str, job: IngestJob, **kwargs) -> bool:
    """Run ``complete`` or ``fail`` on ``job``, and say whether it landed."""
    if end == "fail":
        return await ledger.fail(
            session, job.id, job.attempt_id, reason=_REASON, **kwargs
        )
    try:
        await ledger.complete(session, job.id, job.attempt_id, **kwargs)
    except StaleIngestAttempt:
        return False
    return True


class TestOwnerTransitions:
    @pytest.mark.parametrize("status", _STATUSES)
    @pytest.mark.parametrize("move", sorted(_OWNER_MOVES))
    async def test_moves_a_job_only_from_its_own_states(
        self, test_db_session, move, status
    ):
        """Each owner transition lands from its own states and writes nothing from any other."""
        sources, target, call = _OWNER_MOVES[move]
        job = await _job(test_db_session, status=status)
        job_id = job.id

        landed = await call(test_db_session, job)
        assert landed is (status in sources)
        if landed:
            assert job.status == target, "the instance was not told"
        await test_db_session.commit()

        assert (await _row(test_db_session, job_id)).status == (
            target if landed else status
        )

    @pytest.mark.parametrize("move", sorted(_OWNER_MOVES))
    async def test_leaves_a_superseded_attempt_unwritten(self, test_db_session, move):
        """An owner transition aimed at an attempt a retry replaced writes nothing."""
        sources, _target, call = _OWNER_MOVES[move]
        job = await _job(test_db_session, status=sources[0])
        job_id = job.id
        await _set(test_db_session, job_id, attempt_id=uuid.uuid4())

        assert await call(test_db_session, job) is False
        await test_db_session.commit()

        assert (await _row(test_db_session, job_id)).status == sources[0]

    @pytest.mark.parametrize("move", sorted(_OWNER_MOVES))
    async def test_a_missing_attempt_matches_only_a_row_with_none(
        self, test_db_session, move
    ):
        """A missing attempt is fenced like any other: it matches only a row with none."""
        sources, target, call = _OWNER_MOVES[move]
        job = await _job(test_db_session, status=sources[0])
        job_id = job.id
        unset = SimpleNamespace(id=job_id, attempt_id=None)

        assert await call(test_db_session, unset) is False
        await _set(test_db_session, job_id, attempt_id=None)
        assert await call(test_db_session, job) is False
        assert await call(test_db_session, unset)
        await test_db_session.commit()

        assert (await _row(test_db_session, job_id)).status == target

    async def test_claim_starts_the_lease(self, test_db_session):
        """claim stamps the start and the lease in the same write."""
        job = await _job(test_db_session, status="pending")
        job_id = job.id

        assert await ledger.claim(test_db_session, job_id, job.attempt_id)
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert row.started_at is not None
        assert row.heartbeat_at == row.started_at

    async def test_stage_writes_what_staging_produced(self, test_db_session):
        """stage returns a running job to pending with the columns staging wrote."""
        job = await _job(test_db_session, status="running", current_step="downloading")
        job_id = job.id

        assert await ledger.stage(
            test_db_session,
            job_id,
            job.attempt_id,
            values={"file_path": "staged.geojson", "current_step": None},
        )
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert (row.status, row.file_path, row.current_step) == (
            "pending",
            "staged.geojson",
            None,
        )

    async def test_restore_takes_back_only_an_interrupted_failure(
        self, test_db_session
    ):
        """restore takes a failed parent back only with the interrupted marker, and drops it."""
        marked = await _job(
            test_db_session,
            status="failed",
            error_message="interrupted",
            user_metadata={FAN_OUT_INTERRUPTED_METADATA_KEY: True, "kept": 1},
        )
        unmarked = await _job(
            test_db_session, status="failed", user_metadata={"kept": 1}
        )
        marked_id, unmarked_id = marked.id, unmarked.id

        assert await ledger.restore(test_db_session, marked_id, marked.attempt_id)
        assert not await ledger.restore(
            test_db_session, unmarked_id, unmarked.attempt_id
        )
        await test_db_session.commit()

        row = await _row(test_db_session, marked_id)
        assert (row.status, row.error_message, row.user_metadata) == (
            "pending",
            None,
            {"kept": 1},
        )
        assert (await _row(test_db_session, unmarked_id)).status == "failed"

    @pytest.mark.parametrize("move", ["stage", "fail"])
    async def test_a_further_predicate_the_row_fails_writes_nothing(
        self, test_db_session, move
    ):
        """A transition given a further predicate writes nothing when the row no longer meets it."""
        job = await _job(
            test_db_session, status="running", user_metadata={"stage": "installing"}
        )
        job_id = job.id
        downloading = IngestJob.user_metadata["stage"].astext == "downloading"

        if move == "stage":
            landed = await ledger.stage(
                test_db_session,
                job_id,
                job.attempt_id,
                values={},
                require=(downloading,),
            )
        else:
            landed = await ledger.fail(
                test_db_session,
                job_id,
                job.attempt_id,
                reason=_REASON,
                require=(downloading,),
            )
        assert landed is False
        await test_db_session.commit()

        assert (await _row(test_db_session, job_id)).status == "running"

    @pytest.mark.parametrize(
        ("move", "values"),
        [
            ("stage", {"status": "complete"}),
            ("complete", {"completed_at": None}),
            ("fail", {"error_message": "raw"}),
            ("stage", {"attempt_id": uuid.uuid4()}),
            ("complete", {"id": uuid.uuid4()}),
        ],
    )
    async def test_refuses_values_naming_a_column_it_writes(
        self, test_db_session, move, values
    ):
        """A transition's values may not name the columns it writes or fences on."""
        job = await _job(test_db_session, status="running")
        job_id, attempt_id = job.id, job.attempt_id
        calls = {
            "stage": lambda: ledger.stage(
                test_db_session, job_id, attempt_id, values=values
            ),
            "complete": lambda: ledger.complete(
                test_db_session, job_id, attempt_id, values=values
            ),
            "fail": lambda: ledger.fail(
                test_db_session, job_id, attempt_id, reason=_REASON, values=values
            ),
        }

        with pytest.raises(ValueError, match="the ledger writes"):
            await calls[move]()


class TestComplete:
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_completes_only_a_running_job(self, test_db_session, status):
        """complete ends a running job with its further columns, and a miss raises and writes nothing."""
        job = await _job(test_db_session, status=status)
        job_id, attempt_id = job.id, job.attempt_id

        if status == "running":
            await ledger.complete(
                test_db_session, job_id, attempt_id, values={"current_step": "complete"}
            )
            assert job.status == "complete", "the instance was not told"
        else:
            with pytest.raises(StaleIngestAttempt):
                await ledger.complete(test_db_session, job_id, attempt_id)
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        if status == "running":
            assert (row.status, row.current_step) == ("complete", "complete")
            assert row.completed_at is not None
        else:
            assert (row.status, row.completed_at) == (status, None)

    async def test_a_superseded_attempt_raises_and_writes_nothing(
        self, test_db_session
    ):
        """complete aimed at an attempt a retry replaced raises and writes nothing."""
        job = await _job(test_db_session, status="running")
        job_id = job.id
        await _set(test_db_session, job_id, attempt_id=uuid.uuid4())

        with pytest.raises(StaleIngestAttempt):
            await ledger.complete(test_db_session, job_id, job.attempt_id)
        await test_db_session.commit()

        assert (await _row(test_db_session, job_id)).status == "running"


class TestFail:
    @pytest.mark.parametrize("status", _STATUSES)
    async def test_takes_a_pending_job_only_when_asked(self, test_db_session, status):
        """fail given a pending-or-running fence ends a job in either state and nothing else."""
        job = await _job(test_db_session, status=status)
        job_id = job.id

        landed = await ledger.fail(
            test_db_session,
            job_id,
            job.attempt_id,
            reason=_REASON,
            expect=("pending", "running"),
        )
        assert landed is (status in ("pending", "running"))
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        if landed:
            assert (row.status, row.error_message) == ("failed", _REASON)
            assert row.completed_at is not None
        else:
            assert (row.status, row.error_message) == (status, None)

    async def test_stores_the_reason_redacted(self, test_db_session):
        """fail keeps credentials and library exception text out of the stored reason."""
        jobs = [await _job(test_db_session, status="running") for _ in range(3)]
        (leaky, library, silent) = [(job.id, job.attempt_id) for job in jobs]

        await ledger.fail(
            test_db_session,
            *leaky,
            reason="Rejected https://reader:hunter2@example.test/data?token=abc",
        )
        await ledger.fail(
            test_db_session, *library, reason=OSError("connection to 10.0.0.5 refused")
        )
        await ledger.fail(test_db_session, *silent, reason=None)
        await test_db_session.commit()

        stored = (await _row(test_db_session, leaky[0])).error_message
        assert "hunter2" not in stored and "abc" not in stored
        assert (await _row(test_db_session, library[0])).error_message == (
            "internal_error"
        )
        assert (await _row(test_db_session, silent[0])).error_message is None


class TestAnOwnersLinkedWrite:
    @pytest.mark.parametrize("end", ["complete", "fail"])
    async def test_runs_only_when_the_end_lands(self, test_db_session, end):
        """An owner's end runs its linked write exactly when the job write lands."""
        running = await _job(test_db_session, status="running")
        finished = await _job(test_db_session, status="complete")
        ran: list[str] = []

        def _record(name: str):
            async def _linked(session) -> None:
                ran.append(name)

            return _linked

        assert await _owner_end(
            test_db_session, end, running, linked=_record("running")
        )
        assert not await _owner_end(
            test_db_session, end, finished, linked=_record("finished")
        )
        assert ran == ["running"]

    @pytest.mark.parametrize("end", ["complete", "fail"])
    async def test_a_raising_linked_write_takes_the_end_back(
        self, test_db_session, end
    ):
        """When an owner's linked write raises, the job write rolls back with it."""
        job = await _job(test_db_session, status="running")
        job_id = job.id

        async def _refuses(session) -> None:
            raise RuntimeError("linked row refused")

        with pytest.raises(RuntimeError, match="linked row refused"):
            await _owner_end(test_db_session, end, job, linked=_refuses)
        status = await test_db_session.scalar(
            select(IngestJob.status).where(IngestJob.id == job_id)
        )
        assert status == "running"
        await test_db_session.rollback()


class TestTheRefreshRunHook:
    @pytest.mark.parametrize("claimed", [False, True], ids=["pending", "claimed"])
    async def test_fails_the_run_only_when_the_job_write_lands(
        self, test_db_session, clean_tables, claimed
    ):
        """The job's run fails with the abort's code and reason exactly when the abort lands."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, dataset_id = job.id, job.dataset_id
        if claimed:
            assert await ledger.claim(test_db_session, job_id, job.attempt_id)
            assert await claim_run_for_job(test_db_session, job_id) == run_id
            await test_db_session.commit()

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON
        )
        await test_db_session.commit()

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        if claimed:
            assert outcome is Outcome.MOVED
            assert (run.status, run.error_code, run.finished_at) == (
                "running",
                None,
                None,
            )
            assert await _run_events(test_db_session, dataset_id) == 0
        else:
            assert outcome is Outcome.LANDED
            assert (run.status, run.error_code, run.error_message) == (
                "failed",
                "dispatch_failed",
                _REASON,
            )
            assert run.finished_at is not None
            assert await _run_events(test_db_session, dataset_id) == 1

    @pytest.mark.parametrize("lands", [True, False], ids=["lands", "misses"])
    async def test_cancels_the_run_only_when_the_cancel_lands(
        self, test_db_session, clean_tables, lands
    ):
        """A cancel ends the job's run as the user's, and reports it, exactly when the cancel lands."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, dataset_id, actor = job.id, job.dataset_id, job.created_by
        if not lands:
            await _set(test_db_session, job_id, status="complete")

        ended = await cancel(test_db_session, job, actor=actor)
        await test_db_session.commit()

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        cancelled_events = await _run_events(
            test_db_session, dataset_id, "refresh.cancelled"
        )
        if lands:
            assert ended == Ended(Outcome.LANDED, {"run": run_id})
            assert (run.status, run.error_code) == (
                "cancelled",
                USER_CANCELLED_ERROR_CODE,
            )
            assert cancelled_events == 1
        else:
            assert ended == Ended(Outcome.MOVED)
            assert (run.status, run.error_code) == ("pending", None)
            assert cancelled_events == 0

    async def test_a_cancel_stores_the_run_reason_as_written(
        self, test_db_session, clean_tables
    ):
        """The run a cancel ends keeps the cancel's reason unchanged when a registered credential matches part of it."""
        job, run_id = await _committed_dispatch(test_db_session)
        actor = job.created_by
        register_credential_secret("user")

        await cancel(test_db_session, job, actor=actor)
        await test_db_session.commit()

        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert (run.status, run.error_message) == ("cancelled", "Cancelled by user.")


class TestTheBackfillTrailHook:
    @pytest.mark.parametrize("claimed", [False, True], ids=["pending", "claimed"])
    async def test_closes_the_trail_only_when_the_job_write_lands(
        self, test_db_session, claimed
    ):
        """A backfill's terminal entry names the requester and the request's IP, and only a landed abort writes it."""
        await _release_slot(test_db_session)
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _job(
            test_db_session,
            status="running" if claimed else "pending",
            created_by=admin_id,
            user_metadata={
                EMBEDDING_BACKFILL_METADATA_KEY: {
                    "force": True,
                    "operation_id": "op-ledger",
                }
            },
        )
        job_id = job.id
        try:
            outcome = await abort(
                test_db_session,
                job,
                code="dispatch_failed",
                reason=_REASON,
                ip_address="203.0.113.9",
            )
            await test_db_session.commit()

            entries = (
                await test_db_session.execute(
                    select(
                        AuditLog.user_id, AuditLog.ip_address, AuditLog.details
                    ).where(
                        AuditLog.action == "embedding.backfill",
                        AuditLog.details["job_id"].astext == str(job_id),
                    )
                )
            ).all()
            if claimed:
                assert outcome is Outcome.MOVED
                assert entries == []
            else:
                assert outcome is Outcome.LANDED
                assert len(entries) == 1
                user_id, ip_address, details = entries[0]
                assert (user_id, ip_address) == (admin_id, "203.0.113.9")
                assert details == {
                    "force": True,
                    "operation_id": "op-ledger",
                    "job_id": str(job_id),
                    "outcome": "failed",
                    "error_code": "dispatch_failed",
                }
        finally:
            await _release_slot(test_db_session)

    @pytest.mark.parametrize("lands", [True, False], ids=["lands", "misses"])
    async def test_a_cancel_names_the_canceller_only_when_it_lands(
        self, client, admin_auth_header, test_db_session, lands
    ):
        """A cancelled backfill's terminal entry names the canceller, and only a landed cancel writes it."""
        await _release_slot(test_db_session)
        admin_id = await get_user_id(test_db_session, "admin")
        _headers, canceller = await create_user(client, admin_auth_header, "editor")
        job = await _job(
            test_db_session,
            status="running" if lands else "complete",
            created_by=admin_id,
            user_metadata={
                EMBEDDING_BACKFILL_METADATA_KEY: {
                    "force": False,
                    "operation_id": "op-ledger-cancel",
                }
            },
        )
        job_id = job.id
        try:
            ended = await cancel(test_db_session, job, actor=uuid.UUID(canceller))
            await test_db_session.commit()

            entries = (
                await test_db_session.execute(
                    select(
                        AuditLog.user_id, AuditLog.ip_address, AuditLog.details
                    ).where(
                        AuditLog.action == "embedding.backfill",
                        AuditLog.details["job_id"].astext == str(job_id),
                    )
                )
            ).all()
            if lands:
                assert ended.outcome is Outcome.LANDED
                assert entries == [
                    (
                        uuid.UUID(canceller),
                        None,
                        {
                            "force": False,
                            "operation_id": "op-ledger-cancel",
                            "job_id": str(job_id),
                            "outcome": "failed",
                            "error_code": USER_CANCELLED_ERROR_CODE,
                        },
                    )
                ]
            else:
                assert ended.outcome is Outcome.MOVED
                assert entries == []
        finally:
            await _release_slot(test_db_session)


class TestTheVrtHook:
    @pytest.mark.parametrize("claimed", [False, True], ids=["pending", "claimed"])
    async def test_releases_the_asset_only_when_the_job_write_lands(
        self, test_db_session, clean_tables, claimed
    ):
        """A VRT regeneration's generation fails and its asset is restored exactly when the abort lands."""
        _vrt, asset, generation, job = await _seed_vrt_regeneration(
            test_db_session, job_status="running" if claimed else "pending"
        )
        asset_id, generation_id = asset.id, generation.id

        outcome = await abort(
            test_db_session, job, code="dispatch_failed", reason=_REASON
        )
        await test_db_session.commit()

        generation = await test_db_session.get(
            VrtGeneration, generation_id, populate_existing=True
        )
        asset = await test_db_session.get(RasterAsset, asset_id, populate_existing=True)
        if claimed:
            assert outcome is Outcome.MOVED
            assert generation.status == "pending"
            assert (asset.status, asset.current_generation_id) == (
                "regenerating",
                generation_id,
            )
        else:
            assert outcome is Outcome.LANDED
            assert (generation.status, generation.error_message) == ("failed", _REASON)
            assert generation.completed_at is not None
            assert (asset.status, asset.current_generation_id) == ("ready", None)

    async def test_restores_by_the_ready_worthy_rule(
        self, test_db_session, clean_tables
    ):
        """An aborted regeneration of a VRT whose last attempt failed leaves it failed."""
        _vrt, asset, _generation, job = await _seed_vrt_regeneration(
            test_db_session, prior_failed_attempt=True
        )
        asset_id = asset.id

        assert (
            await abort(test_db_session, job, code="dispatch_failed", reason=_REASON)
            is Outcome.LANDED
        )
        await test_db_session.commit()

        asset = await test_db_session.get(RasterAsset, asset_id, populate_existing=True)
        assert (asset.status, asset.current_generation_id) == ("failed", None)

    @pytest.mark.parametrize("lands", [True, False], ids=["lands", "misses"])
    async def test_a_cancel_releases_the_asset_only_when_it_lands(
        self, test_db_session, clean_tables, lands
    ):
        """A cancelled regeneration's generation fails as the user's and its asset is restored, exactly when the cancel lands."""
        _vrt, asset, generation, job = await _seed_vrt_regeneration(
            test_db_session, job_status="running" if lands else "complete"
        )
        asset_id, generation_id, actor = asset.id, generation.id, job.created_by

        ended = await cancel(test_db_session, job, actor=actor)
        await test_db_session.commit()

        generation = await test_db_session.get(
            VrtGeneration, generation_id, populate_existing=True
        )
        asset = await test_db_session.get(RasterAsset, asset_id, populate_existing=True)
        if lands:
            assert ended == Ended(Outcome.LANDED, {"vrt": generation_id})
            assert (generation.status, generation.error_message) == (
                "failed",
                "Cancelled by user",
            )
            assert (asset.status, asset.current_generation_id) == ("ready", None)
        else:
            assert ended == Ended(Outcome.MOVED)
            assert generation.status == "pending"
            assert (asset.status, asset.current_generation_id) == (
                "regenerating",
                generation_id,
            )

    async def test_a_cancel_stores_the_generation_reason_as_written(
        self, test_db_session, clean_tables
    ):
        """The generation a cancel fails keeps the cancel's reason unchanged when a registered credential matches part of it."""
        _vrt, _asset, generation, job = await _seed_vrt_regeneration(
            test_db_session, job_status="running"
        )
        generation_id, actor = generation.id, job.created_by
        register_credential_secret("user")

        await cancel(test_db_session, job, actor=actor)
        await test_db_session.commit()

        generation = await test_db_session.get(
            VrtGeneration, generation_id, populate_existing=True
        )
        assert (generation.status, generation.error_message) == (
            "failed",
            "Cancelled by user",
        )


class TestHookContract:
    async def test_hooks_run_with_the_job_row_already_locked(
        self, test_db_session, monkeypatch
    ):
        """Every hook sees the job row locked before it touches a linked row."""
        job = await _job(test_db_session)
        job_id = job.id
        seen: list[bool] = []

        async def _probe(session, end) -> None:
            async with db_module.async_session() as other:
                try:
                    await other.execute(
                        select(IngestJob.id)
                        .where(IngestJob.id == end.job_id)
                        .with_for_update(nowait=True)
                    )
                    seen.append(False)
                except DBAPIError:
                    seen.append(True)
                await other.rollback()

        monkeypatch.setattr(ledger, "_OWNERS", {"probe": LinkedOwner(_probe)})
        assert (
            await abort(test_db_session, job, code="dispatch_failed", reason=_REASON)
            is Outcome.LANDED
        )
        await test_db_session.commit()

        assert seen == [True]
        assert (await _row(test_db_session, job_id)).status == "failed"

    @pytest.mark.parametrize("end", ["abort", "cancel"])
    async def test_a_raising_hook_rolls_back_the_job_and_every_linked_write(
        self, test_db_session, clean_tables, monkeypatch, end
    ):
        """A hook that raises leaves the job and the rows earlier hooks wrote as they were."""
        job, run_id = await _committed_dispatch(test_db_session)
        job_id, dataset_id, actor = job.id, job.dataset_id, job.created_by

        async def _raises(session, end) -> None:
            raise RuntimeError("linked row refused")

        monkeypatch.setattr(
            ledger,
            "_OWNERS",
            {"run": ledger._OWNERS["run"], "raises": LinkedOwner(_raises)},
        )
        with pytest.raises(RuntimeError, match="linked row refused"):
            if end == "abort":
                await abort(
                    test_db_session, job, code="dispatch_failed", reason=_REASON
                )
            else:
                await cancel(test_db_session, job, actor=actor)
        # A caller that commits after the error still commits nothing of the end.
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert (row.status, row.error_message) == ("pending", None)
        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert run.status == "pending"
        for action in ("refresh.failed", "refresh.cancelled"):
            assert await _run_events(test_db_session, dataset_id, action) == 0


class TestCancelAgainstAFinalize:
    async def test_a_committed_cancel_fences_out_the_swap(
        self, test_db_session, clean_tables
    ):
        """Once a cancel commits, the worker's finalize raises and its swap rolls back."""
        dataset, job, run, live, staging = await _seed_running_reupload(test_db_session)
        # Plain values: the doomed finalize's rollback expires every instance.
        dataset_id, job_id, run_id = dataset.id, job.id, run.id
        attempt_id, actor = job.attempt_id, job.created_by
        versions_before = await _version_count(test_db_session, dataset_id)

        async with db_module.async_session() as canceller:
            ended = await cancel(
                canceller, await canceller.get(IngestJob, job_id), actor=actor
            )
            await canceller.commit()
        assert ended == Ended(Outcome.LANDED, {"run": run_id})

        with pytest.raises(StaleIngestAttempt):
            await _drive_finalize_verbatim(
                test_db_session,
                dataset_id=dataset_id,
                job_id=job_id,
                attempt_id=attempt_id,
                staging=staging,
            )
            await test_db_session.commit()
        await test_db_session.rollback()

        assert await _table_rows(test_db_session, live) == ["original"]
        assert await _table_rows(test_db_session, staging) == ["new_data"]
        assert await _version_count(test_db_session, dataset_id) == versions_before
        assert (await _row(test_db_session, job_id)).status == "cancelled"
        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert (run.status, run.error_code) == ("cancelled", USER_CANCELLED_ERROR_CODE)

    async def test_a_cancel_a_finalize_holds_times_out_and_writes_nothing(
        self, test_db_session, clean_tables
    ):
        """While a finalize holds the job row, a cancel gives up after 2 s having written nothing."""
        _dataset, job, run, _live, _staging = await _seed_running_reupload(
            test_db_session
        )
        job_id, run_id = job.id, run.id
        attempt_id, actor = job.attempt_id, job.created_by
        # The finalize's first fenced write takes the row and keeps it.
        await require_ingest_job_update(
            test_db_session,
            job_id,
            attempt_id,
            values={"heartbeat_at": datetime.now(timezone.utc)},
        )

        async with db_module.async_session() as canceller:
            blocked = await canceller.get(IngestJob, job_id)
            started = time.monotonic()
            with pytest.raises(DBAPIError) as refused:
                await cancel(canceller, blocked, actor=actor)
            waited = time.monotonic() - started
            await canceller.rollback()
        assert is_lock_conflict(refused.value)
        assert 1.5 <= waited < 10, waited

        # The finalize goes on untouched and completes.
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(status="complete", completed_at=datetime.now(timezone.utc))
        )
        await test_db_session.commit()
        assert (await _row(test_db_session, job_id)).status == "complete"
        run = await test_db_session.get(
            DatasetRefreshRun, run_id, populate_existing=True
        )
        assert (run.status, run.error_code) == ("running", None)


@pytest.mark.parametrize("first", ["claim", "abort"])
async def test_an_abort_racing_a_claim_ends_the_job_once(
    test_db_session, clean_tables, first
):
    """An abort and a worker's claim on one job end it once, with one set of run writes."""
    job, run_id = await _committed_dispatch(test_db_session)
    # Read up front: the lock watcher's rollbacks expire every loaded row.
    job_id, attempt_id, dataset_id = job.id, job.attempt_id, job.dataset_id
    results: dict[str, object] = {}

    async with (
        db_module.async_session() as worker,
        db_module.async_session() as dispatcher,
    ):
        dispatched = await dispatcher.get(IngestJob, job_id)
        await dispatcher.commit()

        async def _abort() -> None:
            results["abort"] = await abort(
                dispatcher, dispatched, code="dispatch_failed", reason=_REASON
            )

        async def _claim() -> None:
            results["claim"] = await ledger.claim(worker, job_id, attempt_id)
            if results["claim"]:
                assert await claim_run_for_job(worker, job_id) == run_id

        if first == "claim":
            holder, holding, waiter, waiting = _claim, worker, _abort, dispatcher
        else:
            holder, holding, waiter, waiting = _abort, dispatcher, _claim, worker

        # The holder's transaction stays open, so the waiter blocks on the job
        # row until the holder commits.
        await holder()
        async with anyio.create_task_group() as tg:
            tg.start_soon(waiter)
            with anyio.fail_after(30):
                while not await _a_settler_waits_on_a_row_lock(test_db_session):
                    await anyio.sleep(0.05)
            await holding.commit()
        await waiting.commit()

    row = await _row(test_db_session, job_id)
    run = await test_db_session.get(DatasetRefreshRun, run_id, populate_existing=True)
    failed_events = await _run_events(test_db_session, dataset_id)
    if first == "claim":
        assert (results["claim"], results["abort"]) == (True, Outcome.MOVED)
        assert (row.status, run.status, failed_events) == ("running", "running", 0)
    else:
        assert (results["abort"], results["claim"]) == (Outcome.LANDED, False)
        assert (row.status, run.status, failed_events) == ("failed", "failed", 1)

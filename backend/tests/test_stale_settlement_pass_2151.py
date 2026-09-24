"""Every caller of the stale-job settlement pass settles the same rows, once."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import anyio
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.platform.jobs import router as router_module
from app.platform.jobs import sweep as sweep_module
from app.platform.jobs import worker as worker_module
from app.platform.jobs.models import (
    COMMIT_ATTEMPTED_METADATA_KEY,
    FAN_OUT_INTERRUPTED_METADATA_KEY,
    IngestJob,
)
from app.platform.jobs.sweep import (
    ABANDONED_UPLOAD_MESSAGE,
    FAN_OUT_CHILDLESS_GRACE_SECONDS,
    FAN_OUT_DISPATCH_INTERRUPTED_MESSAGE,
    JOB_TIMEOUT_SECONDS,
    STALE_PENDING_BOUND_MESSAGE,
    STALE_PENDING_UNBOUND_MESSAGE,
    stale_pending_cutoff_seconds,
)
from app.platform.refresh.service import (
    ABANDONED_ERROR_CODE,
    ABANDONED_RUN_CUTOFF_SECONDS,
    create_pending_run,
)
from tests.factories import create_dataset, get_user_id
from tests.stale_settlers import EVERY_SETTLER, STALE_SETTLERS
from tests.test_vrt_stale_sweep_gap002 import _make_vrt_with_generation
from tests.test_worker_startup_recovery_2145 import _queue_todo_entry

pytestmark = pytest.mark.anyio

_REQUEST = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
_STALE_RUNNING = f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"


def _ago(seconds: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _add(session: AsyncSession, **columns) -> IngestJob:
    job = IngestJob(**{"source_filename": "settle.geojson", **columns})
    session.add(job)
    await session.commit()
    return job


async def _stale_running(session: AsyncSession, **columns) -> IngestJob:
    return await _add(
        session,
        status="running",
        started_at=_ago(JOB_TIMEOUT_SECONDS + 60),
        **columns,
    )


async def _stale_pending(
    session: AsyncSession, *, bound: bool, stamped: bool = True
) -> IngestJob:
    age = stale_pending_cutoff_seconds(completion_bound=bound) + 60
    return await _add(
        session,
        status="pending",
        file_path="staging/settle/frozen/roads.geojson" if bound else "",
        created_at=_ago(age),
        user_metadata=(
            {COMMIT_ATTEMPTED_METADATA_KEY: _ago(age).isoformat()} if stamped else {}
        ),
    )


async def _stale_refresh(session: AsyncSession):
    """A dispatched refresh job past the pending cutoff, and its abandoned run."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=admin_id, name=f"settle-{uuid.uuid4().hex[:8]}"
    )
    age = (
        max(
            stale_pending_cutoff_seconds(completion_bound=False),
            ABANDONED_RUN_CUTOFF_SECONDS,
        )
        + 60
    )
    job = await _add(
        session,
        status="pending",
        file_path="",
        dataset_id=dataset.id,
        created_by=admin_id,
        created_at=_ago(age),
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset.id),
            COMMIT_ATTEMPTED_METADATA_KEY: _ago(age).isoformat(),
        },
    )
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
    )
    run.started_at = _ago(age)
    await session.commit()
    return job, run


async def _stale_vrt(session: AsyncSession):
    """A VRT regeneration job whose worker died, with its dead generation."""
    admin_id = await get_user_id(session, "admin")
    source = await create_dataset(
        session, created_by=admin_id, name=f"settle-{uuid.uuid4().hex[:8]}"
    )
    vrt_dataset, generation, asset = await _make_vrt_with_generation(
        session,
        admin_id=admin_id,
        built_from_dataset_ids=[source.id],
        linked_dataset_ids=[source.id],
    )
    job = await _stale_running(
        session,
        source_filename="vrt_regenerate",
        dataset_id=vrt_dataset.id,
        created_by=admin_id,
    )
    return job, generation, asset


async def _poll(session: AsyncSession, job: IngestJob) -> None:
    owner = SimpleNamespace(id=job.created_by)
    await router_module.get_job_status(job.id, _REQUEST, owner, session)


@EVERY_SETTLER
async def test_every_caller_settles_the_same_rows(test_db_session, settle) -> None:
    """Every caller leaves one fixture set in the same state."""
    session = test_db_session
    queued = await _stale_running(session)
    await _queue_todo_entry(session, queued.id)
    jobs = {
        "stale running": await _stale_running(session),
        "queued running": queued,
        "live running": await _add(
            session,
            status="running",
            started_at=_ago(JOB_TIMEOUT_SECONDS + 60),
            heartbeat_at=_ago(30),
        ),
        "dispatched pending": await _stale_pending(session, bound=False),
        "abandoned upload": await _stale_pending(session, bound=False, stamped=False),
        "bound pending": await _stale_pending(session, bound=True),
        "young pending": await _add(session, status="pending", file_path=""),
        "childless fan-out": await _add(
            session,
            status="fanned_out",
            completed_at=_ago(FAN_OUT_CHILDLESS_GRACE_SECONDS + 60),
        ),
    }
    jobs["refresh"], run = await _stale_refresh(session)
    jobs["vrt regeneration"], generation, asset = await _stale_vrt(session)

    await settle(session, *jobs.values())

    for row in (*jobs.values(), run, generation, asset):
        await session.refresh(row)
    assert {name: (job.status, job.error_message) for name, job in jobs.items()} == {
        "stale running": ("failed", _STALE_RUNNING),
        "queued running": ("running", None),
        "live running": ("running", None),
        "dispatched pending": ("failed", STALE_PENDING_UNBOUND_MESSAGE),
        "abandoned upload": ("cancelled", ABANDONED_UPLOAD_MESSAGE),
        "bound pending": ("failed", STALE_PENDING_BOUND_MESSAGE),
        "young pending": ("pending", None),
        "childless fan-out": ("failed", FAN_OUT_DISPATCH_INTERRUPTED_MESSAGE),
        "refresh": ("failed", STALE_PENDING_UNBOUND_MESSAGE),
        "vrt regeneration": ("failed", _STALE_RUNNING),
    }
    assert (run.status, run.error_code) == ("cancelled", ABANDONED_ERROR_CODE)
    assert (generation.status, asset.status) == ("failed", "ready")


@EVERY_SETTLER
async def test_an_analysis_job_past_its_lease_is_failed(
    test_db_session, settle
) -> None:
    """An analysis job 301 s past its heartbeat is failed under the analysis lease."""
    job = await _add(
        test_db_session,
        status="running",
        started_at=_ago(JOB_TIMEOUT_SECONDS),
        heartbeat_at=_ago(301),
        user_metadata={"analysis": {"operation": "buffer"}},
    )

    await settle(test_db_session, job)

    await test_db_session.refresh(job)
    assert (job.status, job.error_message) == (
        "failed",
        "Stale: running for over 5 minutes",
    )


@EVERY_SETTLER
async def test_an_analysis_job_inside_its_lease_is_left_running(
    test_db_session, settle
) -> None:
    """An analysis job 299 s past its heartbeat stays running."""
    job = await _add(
        test_db_session,
        status="running",
        started_at=_ago(JOB_TIMEOUT_SECONDS),
        heartbeat_at=_ago(299),
        user_metadata={"analysis": {"operation": "buffer"}},
    )

    await settle(test_db_session, job)

    await test_db_session.refresh(job)
    assert job.status == "running"


@EVERY_SETTLER
async def test_every_caller_restores_a_dead_vrt_regeneration(
    test_db_session, settle
) -> None:
    """A dead VRT job's generation is failed and its asset restored."""
    job, generation, asset = await _stale_vrt(test_db_session)

    await settle(test_db_session, job)

    for row in (job, generation, asset):
        await test_db_session.refresh(row)
    assert (job.status, generation.status, asset.status) == (
        "failed",
        "failed",
        "ready",
    )
    assert asset.current_generation_id is None


@EVERY_SETTLER
async def test_every_caller_cancels_a_stale_jobs_abandoned_run(
    test_db_session, settle
) -> None:
    """A stale refresh job is failed and its abandoned run cancelled."""
    job, run = await _stale_refresh(test_db_session)

    await settle(test_db_session, job)

    await test_db_session.refresh(job)
    await test_db_session.refresh(run)
    assert job.status == "failed"
    assert (run.status, run.error_code) == ("cancelled", ABANDONED_ERROR_CODE)


@EVERY_SETTLER
async def test_every_caller_fails_a_childless_fan_out_parent(
    test_db_session, settle
) -> None:
    """A fan-out parent with no child past the grace is failed with its marker."""
    parent = await _add(
        test_db_session,
        status="fanned_out",
        completed_at=_ago(FAN_OUT_CHILDLESS_GRACE_SECONDS + 60),
    )

    await settle(test_db_session, parent)

    await test_db_session.refresh(parent)
    assert parent.status == "failed"
    assert (parent.user_metadata or {}).get(FAN_OUT_INTERRUPTED_METADATA_KEY) is True


async def _record_poll(session: AsyncSession, job: IngestJob) -> tuple[list[str], int]:
    """Poll ``job`` and return the statements it issued and the commits it made."""
    import app.core.db as core_db

    engine = core_db.engine.sync_engine
    statements: list[str] = []
    commits: list[object] = []

    def record(_conn, _cursor, statement, *_rest) -> None:
        # A transaction's `SET LOCAL` setup is the engine's, not the poll's.
        if not statement.lstrip().upper().startswith("SET "):
            statements.append(statement)

    def record_commit(conn) -> None:
        commits.append(conn)

    event.listen(engine, "before_cursor_execute", record)
    event.listen(engine, "commit", record_commit)
    try:
        await _poll(session, job)
    finally:
        event.remove(engine, "before_cursor_execute", record)
        event.remove(engine, "commit", record_commit)
    return statements, len(commits)


async def test_polling_a_healthy_job_runs_only_its_read(test_db_session) -> None:
    """A poll of a job the pass would leave alone issues one statement."""
    healthy = [
        await _add(
            test_db_session,
            status="running",
            started_at=_ago(JOB_TIMEOUT_SECONDS + 60),
            heartbeat_at=_ago(30),
        ),
        await _add(
            test_db_session,
            status="running",
            started_at=_ago(120),
            heartbeat_at=_ago(30),
            user_metadata={"analysis": {"operation": "buffer"}},
        ),
        await _add(test_db_session, status="pending", file_path=""),
        await _add(
            test_db_session,
            status="pending",
            file_path="staging/settle/frozen/roads.geojson",
            created_at=_ago(stale_pending_cutoff_seconds(completion_bound=False) + 60),
        ),
        await _add(test_db_session, status="fanned_out", completed_at=_ago(10)),
        await _add(test_db_session, status="complete", completed_at=_ago(10)),
    ]
    stale = await _stale_running(test_db_session)

    for job in healthy:
        status = job.status
        statements, commits = await _record_poll(test_db_session, job)
        assert len(statements) == 1, (status, statements)
        assert statements[0].lstrip().upper().startswith("SELECT"), (status, statements)
        assert commits == 0, status
    # The recorder sees a settling poll, so its silence above is not blindness.
    statements, commits = await _record_poll(test_db_session, stale)
    assert len(statements) > 2
    assert commits == 1


@pytest.mark.parametrize("held_by", ["todo pending", "todo running", "child"])
async def test_polling_a_stale_job_something_holds_runs_one_read_more(
    test_db_session, held_by
) -> None:
    """A poll of a stale job its queue or children hold reads it, checks, and stops."""
    if held_by == "child":
        job = await _add(
            test_db_session,
            status="fanned_out",
            completed_at=_ago(FAN_OUT_CHILDLESS_GRACE_SECONDS + 60),
        )
        await _add(
            test_db_session,
            status="running",
            started_at=_ago(30),
            heartbeat_at=_ago(30),
            user_metadata={"fan_out_parent_id": str(job.id)},
        )
    else:
        job = (
            await _stale_pending(test_db_session, bound=False)
            if held_by == "todo pending"
            else await _stale_running(test_db_session)
        )
        await _queue_todo_entry(test_db_session, job.id)
    status = job.status

    statements, commits = await _record_poll(test_db_session, job)

    assert len(statements) == 2, statements
    assert commits == 0
    await test_db_session.refresh(job)
    assert job.status == status


async def test_a_poll_settles_only_its_own_job(test_db_session) -> None:
    """A poll's pass leaves every other job, refresh run and VRT generation alone."""
    polled = await _stale_running(test_db_session)
    other_job, other_run = await _stale_refresh(test_db_session)
    vrt_job, generation, asset = await _stale_vrt(test_db_session)

    await _poll(test_db_session, polled)

    for row in (polled, other_job, other_run, vrt_job, generation, asset):
        await test_db_session.refresh(row)
    assert polled.status == "failed"
    assert (other_job.status, other_run.status) == ("pending", "pending")
    assert (vrt_job.status, generation.status, asset.status) == (
        "running",
        "running",
        "regenerating",
    )


@STALE_SETTLERS
async def test_a_running_job_with_a_fresh_heartbeat_is_left_alone(
    test_db_session, settle
) -> None:
    """A job whose worker still renews its lease stays running, however old."""
    job = await _add(
        test_db_session,
        status="running",
        started_at=_ago(JOB_TIMEOUT_SECONDS + 60),
        heartbeat_at=_ago(30),
    )

    await settle(test_db_session)

    await test_db_session.refresh(job)
    assert job.status == "running"
    assert job.completed_at is None


async def test_recovery_logs_each_job_it_settles(test_db_session) -> None:
    """Recovery names every job it settles in its own log line."""
    running = await _stale_running(test_db_session)
    pending = await _stale_pending(test_db_session, bound=False)

    with patch.object(worker_module, "log") as log:
        await worker_module.recover_stale_jobs()

    logged = {
        call.kwargs.get("job_id"): (call.args[0], call.kwargs.get("status"))
        for call in log.warning.call_args_list
    }
    assert logged[str(running.id)] == ("Recovered stale running job", None)
    assert logged[str(pending.id)] == ("Recovered orphaned pending job", "failed")


async def _a_settler_waits_on_a_row_lock(observer: AsyncSession) -> bool:
    waiting = await observer.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() "
            "AND state = 'active' "
            "AND wait_event_type = 'Lock' "
            "AND query ILIKE '%ingest_jobs%'"
        )
    )
    # Activity is snapshotted per transaction, so each poll needs a new one.
    await observer.rollback()
    return waiting > 0


def _settled_ids(outcome) -> set:
    return set(outcome._settled_running_ids) | {
        job_id for job_id, _status in outcome._settled_pending
    }


def _hold_the_first_caller(monkeypatch, outcomes, holding, release) -> None:
    """Make the first caller of the pass hold its settled rows until released."""
    real_settle = sweep_module.settle_stale_jobs

    async def settle_and_hold_the_first_caller(db, now, **scope):
        outcome = await real_settle(db, now, **scope)
        outcomes.append(outcome)
        if len(outcomes) == 1:
            holding.set()
            with anyio.fail_after(30):
                await release.wait()
        return outcome

    for module in (sweep_module, router_module):
        monkeypatch.setattr(
            module, "settle_stale_jobs", settle_and_hold_the_first_caller
        )


async def _lifespan_sweep() -> None:
    from app.core.db import async_session

    async with async_session() as session:
        await sweep_module.fail_stale_jobs(session)


@pytest.mark.parametrize("first", ["recovery", "sweep"])
@pytest.mark.parametrize("stale", ["pending", "running"])
async def test_a_concurrent_sweep_and_recovery_settle_each_row_once(
    test_db_session, monkeypatch, first, stale
) -> None:
    """Recovery and the sweep running at once settle every stale row exactly once."""
    # Settle this database's leftovers first, so no other row is contended.
    await sweep_module.fail_stale_jobs(test_db_session)
    if stale == "pending":
        jobs = [
            await _stale_pending(test_db_session, bound=False),
            await _stale_pending(test_db_session, bound=True),
        ]
    else:
        jobs = [await _stale_running(test_db_session)]
    job_ids = {job.id for job in jobs}

    outcomes = []
    first_holds_its_rows = anyio.Event()
    release = anyio.Event()
    _hold_the_first_caller(monkeypatch, outcomes, first_holds_its_rows, release)
    callers = {
        "recovery": worker_module.recover_stale_jobs,
        "sweep": _lifespan_sweep,
    }
    second = "sweep" if first == "recovery" else "recovery"

    async with anyio.create_task_group() as tg:
        tg.start_soon(callers[first])
        with anyio.fail_after(30):
            await first_holds_its_rows.wait()
        tg.start_soon(callers[second])
        with anyio.fail_after(30):
            if stale == "pending":
                # The second caller's UPDATE blocks on a row the first holds.
                while not await _a_settler_waits_on_a_row_lock(test_db_session):
                    await anyio.sleep(0.05)
            else:
                # SKIP LOCKED: the second caller passes the held row by.
                while len(outcomes) < 2:
                    await anyio.sleep(0.05)
        release.set()

    held, other = outcomes
    assert job_ids <= _settled_ids(held)
    assert not job_ids & _settled_ids(other)
    for job in jobs:
        await test_db_session.refresh(job)
        assert job.status == "failed"


@pytest.mark.parametrize("first", ["poll", "sweep"])
async def test_a_concurrent_poll_and_sweep_settle_a_stale_job_once(
    test_db_session, monkeypatch, first
) -> None:
    """A poll and the sweep at once write a stale job, and its run, once."""
    from app.core.db import async_session

    await sweep_module.fail_stale_jobs(test_db_session)
    job, run = await _stale_refresh(test_db_session)
    # Read up front: the lock watcher's rollbacks expire every loaded row.
    job_id, dataset_id, owner = job.id, job.dataset_id, job.created_by

    outcomes = []
    first_holds_its_rows = anyio.Event()
    release = anyio.Event()
    _hold_the_first_caller(monkeypatch, outcomes, first_holds_its_rows, release)

    async def job_status_poll() -> None:
        async with async_session() as session:
            await router_module.get_job_status(
                job_id, _REQUEST, SimpleNamespace(id=owner), session
            )

    callers = {"poll": job_status_poll, "sweep": _lifespan_sweep}
    second = "sweep" if first == "poll" else "poll"

    async with anyio.create_task_group() as tg:
        tg.start_soon(callers[first])
        with anyio.fail_after(30):
            await first_holds_its_rows.wait()
        tg.start_soon(callers[second])
        with anyio.fail_after(30):
            # The second caller's UPDATE blocks on the job row the first holds.
            while not await _a_settler_waits_on_a_row_lock(test_db_session):
                await anyio.sleep(0.05)
        release.set()

    held, other = outcomes
    assert job_id in _settled_ids(held)
    assert job_id not in _settled_ids(other)
    abandoned_events = await test_db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "refresh.abandoned",
            AuditLog.resource_id == dataset_id,
        )
    )
    assert abandoned_events == 1
    await test_db_session.refresh(run)
    assert (run.status, run.error_code) == ("cancelled", ABANDONED_ERROR_CODE)

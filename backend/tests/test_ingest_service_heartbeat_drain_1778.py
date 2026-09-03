"""The service-import heartbeat's cancellation drain has a finite deadline,
and a stuck tick's own database wait does too (#1778, codex rounds 2-3 on
#1791).

fix(#1778) put each heartbeat tick's session open/write/commit/close under
``asyncio.shield`` so a caller's ``.cancel()`` could only land at the
``asyncio.sleep`` between ticks, never mid-connection -- closing an asyncpg
``ConnectionError: unexpected connection_lost() call`` seen in the merge
queue. Codex round 2 found the shield alone was not enough: the drain that
lets a shielded tick finish (``await tick`` after a cancel) was unbounded, and
the ordinary session a tick runs on carries no statement or lock timeout of
its own. A tick blocked on something else entirely -- another transaction's
row lock inside ``session.commit()`` -- would hang the drain, and with it
``ingest_service``'s own ``finally``, forever: a finished import stuck before
it could reach finalization. Round 2's fix,
``_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS``, gave up on WAITING for
such a tick after a bound -- ``asyncio.shield`` kept it running in the
background rather than cancelling it, so its connection would still close
whenever the lock eventually cleared, but until then that connection stayed
checked out and blocked, and repeated stalled imports could exhaust the
worker's pool even though their parent tasks moved on.

Round 3 bounds the tick's OWN database wait instead:
``_service_import_heartbeat_tick`` now sets ``lock_timeout``/
``statement_timeout`` on its own transaction (see
``_SERVICE_IMPORT_HEARTBEAT_TICK_DB_TIMEOUT_SECONDS``), so a blocked commit
fails INSIDE Postgres within a few seconds and its connection returns to the
pool the ordinary way, without depending on anyone giving up on waiting for
it. The round-2 drain deadline survives as a safety net above that DB
timeout, for what a DB-side timeout cannot cover (a connection stuck before
it ever reaches Postgres).

The tests through ``test_the_stuck_tick_is_not_cancelled_by_the_drain_timeout``
exercise ``_heartbeat_service_import_progress`` directly with a MOCKED tick
that never returns, standing in for one stuck on something the mock doesn't
model. Completion is checked by POLLING ``Task.done()``, never by wrapping
the heartbeat task itself in another ``asyncio.wait_for`` -- that would
cancel it on ITS OWN timeout and mask the exact thing under test, whether the
drain deadline constant is what actually bounds completion.

The tests through ``test_a_tick_blocked_on_its_own_initial_select_times_out_
inside_the_db_and_releases_its_connection`` exercise the round-3/round-6
mechanism directly against a REAL row lock held by a second, real database
session -- the one property the mocked tests above cannot stand in for.

Round 11 closes a residual: even with the drain deadline and the DB-side
lock/statement timeouts, the tick's own SELECT (inside ``_job_phase_
session``) is a snapshot, not a lock. A tick that read the row as
"running"/"ogr2ogr" can still have its OWN write land AFTER
``_finalize_ingest`` commits ``status="complete"``/``progress=1.0`` (or a
retry rotates ``attempt_id``) -- an unconditional ORM commit would then
overwrite the finalized row, by primary key, with the tick's stale progress.
The write is now a single atomic UPDATE gated on
``id + attempt_id + status="running" + current_step="ogr2ogr" + progress <
next_progress``, so it re-checks the CURRENT row rather than trusting the
earlier SELECT; zero rows affected means the job moved on, logged at debug,
nothing written. The final three tests exercise this directly against a
REAL race: ``_pause_the_tick_after_its_select`` pauses the tick
DETERMINISTICALLY right after its own SELECT (not via a real row lock, and
not via ``pg_stat_activity`` polling -- both were tried against the actual
test database this suite runs against, a live dev stack shares it, so
unrelated backends routinely show lock contention and connection-acquisition
timing varies with how busy it is, and neither technique was reliable
here), a second real session commits the competing write strictly between
the tick's SELECT and its own write, then the tick resumes and its atomic
UPDATE is checked against what actually landed.
"""

import asyncio
import uuid

import pytest

from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_vector


def _ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


async def _poll_until(predicate, *, timeout: float, interval: float = 0.01) -> bool:
    """Poll ``predicate()`` until true or ``timeout`` elapses. Returns whether
    it became true. Never wraps a task in ``wait_for`` (see module docstring)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _pause_the_tick_after_its_select(
    monkeypatch,
) -> tuple[asyncio.Event, asyncio.Event]:
    """Deterministically pause ``_service_import_heartbeat_tick`` between its
    own SELECT (inside ``_job_phase_session``) and whatever it does next, so
    a test can commit a real, concurrent mutation to the row strictly
    between the two -- the exact ordering fix(#1778 codex r11) closes a gap
    for.

    Wraps ``tasks_vector._job_phase_session`` (patched by name in
    ``tasks_vector``'s own module namespace, where
    ``_service_import_heartbeat_tick`` actually looks it up) so the real
    SELECT still runs for real, against the real database. Two events
    coordinate the two coroutines: ``reached_select`` fires once the SELECT
    has returned and the wrapper is about to await ``resume_tick``, so the
    caller knows exactly when it is safe to make its own concurrent
    write -- no fixed sleep, no ``pg_stat_activity`` polling, which this
    file's other tests measured as unreliable against the test database
    this suite actually runs against (a live dev stack shares it, so many
    unrelated backends can show lock contention at any moment, and
    connection acquisition timing varies with how busy it is).
    """
    from contextlib import asynccontextmanager

    from app.processing.ingest import tasks_common

    reached_select = asyncio.Event()
    resume_tick = asyncio.Event()
    real_job_phase_session = tasks_common._job_phase_session

    @asynccontextmanager
    async def _paused_job_phase_session(*args, **kwargs):
        async with real_job_phase_session(*args, **kwargs) as (session, job):
            reached_select.set()
            await resume_tick.wait()
            yield session, job

    monkeypatch.setattr(tasks_vector, "_job_phase_session", _paused_job_phase_session)
    return reached_select, resume_tick


@pytest.mark.anyio
async def test_a_tick_stuck_forever_does_not_hang_past_the_drain_deadline(monkeypatch):
    """A cancel lands while the tick is stuck; the heartbeat coroutine must
    still finish handling that cancellation within the (small, here) drain
    deadline, never waiting on the stuck tick itself."""
    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False
    )
    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS", 0.05
    )

    entered_tick = asyncio.Event()
    stuck_forever = asyncio.Event()  # never set

    async def _stuck_tick(job_uuid, attempt_id):
        entered_tick.set()
        await stuck_forever.wait()
        # Reached once the `finally` below releases `stuck_forever`, letting
        # this orphaned task finish quietly rather than lingering pending.
        return True

    monkeypatch.setattr(tasks_vector, "_service_import_heartbeat_tick", _stuck_tick)

    job_uuid, attempt_id = _ids()
    heartbeat_task = asyncio.create_task(
        tasks_vector._heartbeat_service_import_progress(job_uuid, attempt_id)
    )
    try:
        await asyncio.wait_for(entered_tick.wait(), timeout=1.0)
        heartbeat_task.cancel()

        # Generous slack (1s) over the drain deadline (0.05s): the property
        # under test is "finishes well before this", not the exact timing.
        finished = await _poll_until(heartbeat_task.done, timeout=1.0)
        assert finished, (
            "the heartbeat did not finish handling its cancellation within "
            "1s of a 0.05s drain deadline -- the drain is not actually bounded"
        )
        with pytest.raises(asyncio.CancelledError):
            heartbeat_task.result()
    finally:
        stuck_forever.set()
        if not heartbeat_task.done():
            heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


@pytest.mark.anyio
async def test_counterfactual_a_larger_drain_deadline_is_the_thing_that_hangs(
    monkeypatch,
):
    """Proves the deadline above is load-bearing, not incidental: raise it
    past a short polling window and the SAME stuck tick leaves the heartbeat
    task still pending at that point, because nothing else bounds
    completion. Checked by polling ``done()``, not by an enclosing
    ``wait_for`` -- that would cancel the task on its OWN timeout and pass
    regardless of the drain deadline's value, proving nothing."""
    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False
    )
    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS", 10.0
    )

    entered_tick = asyncio.Event()
    stuck_forever = asyncio.Event()  # never set

    async def _stuck_tick(job_uuid, attempt_id):
        entered_tick.set()
        await stuck_forever.wait()
        # Reached once the `finally` below releases `stuck_forever`, letting
        # this orphaned task finish quietly rather than lingering pending.
        return True

    monkeypatch.setattr(tasks_vector, "_service_import_heartbeat_tick", _stuck_tick)

    job_uuid, attempt_id = _ids()
    heartbeat_task = asyncio.create_task(
        tasks_vector._heartbeat_service_import_progress(job_uuid, attempt_id)
    )
    try:
        await asyncio.wait_for(entered_tick.wait(), timeout=1.0)
        heartbeat_task.cancel()

        await asyncio.sleep(0.3)
        assert not heartbeat_task.done(), (
            "expected the heartbeat to still be draining the stuck tick at "
            "0.3s when the drain deadline is 10s -- if it is already done, "
            "something OTHER than the deadline constant is bounding "
            "completion, and the constant this fix added is not actually "
            "load-bearing"
        )
    finally:
        # Release the stuck tick and reap both tasks without ever wrapping
        # the heartbeat task in a cancelling wait_for.
        stuck_forever.set()
        if not heartbeat_task.done():
            heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


@pytest.mark.anyio
async def test_the_stuck_tick_is_not_cancelled_by_the_drain_timeout(monkeypatch):
    """asyncio.shield's whole point here: giving up on WAITING for a stuck
    tick must not cancel the tick itself, so its connection still gets a
    chance to close cleanly rather than being torn down mid-flight -- the
    exact failure mode fix(#1778)'s shield exists to prevent."""
    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False
    )
    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS", 0.05
    )

    entered_tick = asyncio.Event()
    release_tick = asyncio.Event()
    tick_cancelled = False
    tick_completed = False

    async def _slow_tick(job_uuid, attempt_id):
        nonlocal tick_cancelled, tick_completed
        entered_tick.set()
        try:
            await release_tick.wait()
        except asyncio.CancelledError:
            tick_cancelled = True
            raise
        tick_completed = True
        return True

    monkeypatch.setattr(tasks_vector, "_service_import_heartbeat_tick", _slow_tick)

    job_uuid, attempt_id = _ids()
    heartbeat_task = asyncio.create_task(
        tasks_vector._heartbeat_service_import_progress(job_uuid, attempt_id)
    )
    await asyncio.wait_for(entered_tick.wait(), timeout=1.0)
    heartbeat_task.cancel()

    finished = await _poll_until(heartbeat_task.done, timeout=1.0)
    assert finished
    with pytest.raises(asyncio.CancelledError):
        heartbeat_task.result()

    # The drain deadline (0.05s) has already elapsed and given up waiting,
    # but the shielded tick keeps running underneath. Releasing it now and
    # letting it finish proves it was never cancelled.
    release_tick.set()
    await _poll_until(lambda: tick_completed or tick_cancelled, timeout=2.0)

    assert tick_completed, (
        "the shielded tick was cancelled instead of allowed to finish"
    )
    assert not tick_cancelled


@pytest.mark.anyio
async def test_a_tick_blocked_behind_a_held_row_lock_times_out_inside_the_db_and_releases_its_connection(
    test_db_session, monkeypatch
):
    """fix(#1778 codex r3): ``_service_import_heartbeat_tick`` sets
    ``lock_timeout``/``statement_timeout`` on its OWN transaction, so a
    commit blocked on another session's row lock fails INSIDE the database
    within a few seconds and releases its connection back to the pool --
    rather than depending on the caller merely giving up on WAITING for it
    (round 2's fix alone), which left the tick's connection itself still
    checked out and blocked, exhausting the worker's pool under repeated
    stalled imports even though their parent tasks continued.

    Uses a real row lock held by a second, real session against the real
    test database -- this is the one property a mock can't stand in for.
    """
    import app.core.db as db_module
    from sqlalchemy import event, select

    from tests.factories import get_user_id

    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_TICK_DB_TIMEOUT_SECONDS", 0.5
    )

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="LockedHeartbeatJob",
        created_by=admin_id,
        status="running",
        current_step="ogr2ogr",
        progress=0.1,
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    attempt_id = job.attempt_id

    live = {"n": 0}

    def _on_checkout(*_args):
        live["n"] += 1

    def _on_checkin(*_args):
        live["n"] -= 1

    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "checkout", _on_checkout)
    event.listen(sync_engine, "checkin", _on_checkin)

    # No connection held anywhere yet -- the true idle baseline, captured
    # before the locker session checks its own connection out, so releasing
    # THAT connection later is accounted for rather than mistaken for a leak.
    idle_baseline = live["n"]

    try:
        async with db_module.async_session() as locker_session:
            # Hold a real row lock on the job row without committing, exactly
            # what "another transaction's row lock" means in the finding.
            await locker_session.execute(
                select(IngestJob).where(IngestJob.id == job_id).with_for_update()
            )

            # +1 for the locker session's own held connection.
            with_locker_held = live["n"]
            assert with_locker_held == idle_baseline + 1

            with pytest.raises(Exception) as exc_info:
                await tasks_vector._service_import_heartbeat_tick(job_id, attempt_id)

            # The tick's OWN connection returned to the pool -- the property
            # under test. The locker session's connection is still held (it
            # is a different, deliberately-parked connection) and is not
            # released until the `async with` below exits.
            assert live["n"] == with_locker_held, (
                f"pool checkout count drifted from {with_locker_held} (locker "
                f"session held, tick about to run) to {live['n']} -- the "
                "tick's connection was not released after its own "
                "lock_timeout fired"
            )
            # It failed for the reason this fix adds, not some other cause
            # this test would otherwise pass against vacuously.
            message = str(exc_info.value).lower()
            assert "lock" in message or "canceling statement" in message, (
                f"expected a lock/statement timeout from Postgres, got: "
                f"{exc_info.value!r}"
            )

            await locker_session.rollback()

        # The locker session's own connection is released once its `async
        # with` block above exits.
        assert live["n"] == idle_baseline

        # The parent completes: once the lock clears, a fresh tick against
        # the same job succeeds normally -- the earlier timeout did not
        # leave the job, or the pool, in a broken state.
        keep_going = await tasks_vector._service_import_heartbeat_tick(
            job_id, attempt_id
        )
        assert keep_going is True
        assert live["n"] == idle_baseline
    finally:
        event.remove(sync_engine, "checkout", _on_checkout)
        event.remove(sync_engine, "checkin", _on_checkin)


@pytest.mark.anyio
async def test_a_tick_blocked_on_its_own_initial_select_times_out_inside_the_db_and_releases_its_connection(
    test_db_session, monkeypatch
):
    """fix(#1778 codex r6): the row-lock test above blocks the tick's LATER
    commit; this one blocks its FIRST statement, the SELECT
    ``_job_phase_session`` runs internally before the caller gets control at
    all. A ``FOR UPDATE`` row lock does not block a plain SELECT under
    Postgres's MVCC, so it cannot exercise this path -- an
    ``ACCESS EXCLUSIVE`` table lock does, the same class of lock a
    ``DROP``/``ALTER``/``TRUNCATE`` (or an explicit ``LOCK TABLE``) takes.

    Before fix(#1778 codex r6), ``_service_import_heartbeat_tick`` issued
    its ``SET LOCAL lock_timeout``/``statement_timeout`` AFTER entering
    ``_job_phase_session``'s ``async with`` block -- too late to protect the
    SELECT that already ran to get there, so this exact scenario hung on
    the database's server-wide default instead of the few-second budget.
    The timeouts now go INTO ``_job_phase_session`` via
    ``lock_and_statement_timeout_ms`` and take effect before its SELECT.
    """
    import app.core.db as db_module
    from sqlalchemy import event, text

    from tests.factories import get_user_id

    monkeypatch.setattr(
        tasks_vector, "_SERVICE_IMPORT_HEARTBEAT_TICK_DB_TIMEOUT_SECONDS", 0.5
    )

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="TableLockedHeartbeatJob",
        created_by=admin_id,
        status="running",
        current_step="ogr2ogr",
        progress=0.1,
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    attempt_id = job.attempt_id

    live = {"n": 0}

    def _on_checkout(*_args):
        live["n"] += 1

    def _on_checkin(*_args):
        live["n"] -= 1

    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "checkout", _on_checkout)
    event.listen(sync_engine, "checkin", _on_checkin)

    idle_baseline = live["n"]

    try:
        async with db_module.async_session() as locker_session:
            # ACCESS EXCLUSIVE blocks EVERY other lock mode, including the
            # ACCESS SHARE a plain SELECT takes -- unlike FOR UPDATE, which
            # only blocks other writers/lockers of the same row.
            await locker_session.execute(
                text("LOCK TABLE catalog.ingest_jobs IN ACCESS EXCLUSIVE MODE")
            )

            with_locker_held = live["n"]
            assert with_locker_held == idle_baseline + 1

            with pytest.raises(Exception) as exc_info:
                await tasks_vector._service_import_heartbeat_tick(job_id, attempt_id)

            assert live["n"] == with_locker_held, (
                f"pool checkout count drifted from {with_locker_held} (locker "
                f"session held, tick about to run) to {live['n']} -- the "
                "tick's connection was not released after its own "
                "lock_timeout fired"
            )
            message = str(exc_info.value).lower()
            assert "lock" in message or "canceling statement" in message, (
                f"expected a lock/statement timeout from Postgres, got: "
                f"{exc_info.value!r}"
            )

            await locker_session.rollback()

        assert live["n"] == idle_baseline

        keep_going = await tasks_vector._service_import_heartbeat_tick(
            job_id, attempt_id
        )
        assert keep_going is True
        assert live["n"] == idle_baseline
    finally:
        event.remove(sync_engine, "checkout", _on_checkout)
        event.remove(sync_engine, "checkin", _on_checkin)


@pytest.mark.anyio
async def test_a_tick_that_loses_a_race_to_finalize_does_not_clobber_the_completed_job(
    test_db_session, monkeypatch
):
    """fix(#1778 codex r11): the tick's own SELECT read the row as
    "running"/"ogr2ogr" with progress=0.5. Pause the tick DETERMINISTICALLY
    right after that SELECT (see ``_pause_the_tick_after_its_select`` below --
    this test database is shared with a live dev stack, so timing- or
    pg_stat_activity-based synchronization is not reliable enough here),
    commit ``_finalize_ingest``'s effect (status="complete",
    current_step="complete", progress=1.0) on a second, real session while
    the tick is paused, then resume it. The tick's own UPDATE must re-check
    its WHERE clause against the row Postgres just committed, not the stale
    snapshot the tick read -- it must affect zero rows and leave the
    finalized row untouched.
    """
    import app.core.db as db_module
    from sqlalchemy import select, update

    from app.platform.jobs.models import IngestJob as _IngestJob
    from tests.factories import get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="RaceFinalizeHeartbeatJob",
        created_by=admin_id,
        status="running",
        current_step="ogr2ogr",
        progress=0.5,
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    attempt_id = job.attempt_id

    reached_select, resume_tick = _pause_the_tick_after_its_select(monkeypatch)

    tick_task = asyncio.ensure_future(
        tasks_vector._service_import_heartbeat_tick(job_id, attempt_id)
    )
    await asyncio.wait_for(reached_select.wait(), timeout=5.0)

    # Simulate _finalize_ingest committing first, strictly between the
    # tick's own SELECT and its write.
    async with db_module.async_session() as finalizer_session:
        await finalizer_session.execute(
            update(_IngestJob)
            .where(_IngestJob.id == job_id)
            .values(status="complete", current_step="complete", progress=1.0)
        )
        await finalizer_session.commit()

    resume_tick.set()
    keep_going = await asyncio.wait_for(tick_task, timeout=5.0)
    assert keep_going is True

    async with db_module.async_session() as check_session:
        result = await check_session.execute(
            select(_IngestJob).where(_IngestJob.id == job_id)
        )
        final = result.scalar_one()
    assert final.status == "complete"
    assert final.current_step == "complete"
    assert final.progress == 1.0, (
        f"the tick's stale write clobbered the finalized job's progress: "
        f"{final.progress!r}"
    )


@pytest.mark.anyio
async def test_a_tick_that_loses_a_race_to_a_retry_does_not_write_into_the_new_attempt(
    test_db_session, monkeypatch
):
    """Same race as above, but the row is claimed by a NEW attempt (a retry)
    instead of finalized. The old tick's write is fenced to the OLD
    attempt_id it was called with, so once the row's attempt_id has rotated
    out from under it, the atomic UPDATE must affect zero rows -- the new
    attempt's own progress must survive untouched.
    """
    import app.core.db as db_module
    from sqlalchemy import select, update

    from app.platform.jobs.models import IngestJob as _IngestJob
    from tests.factories import get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="RaceRetryHeartbeatJob",
        created_by=admin_id,
        status="running",
        current_step="ogr2ogr",
        progress=0.5,
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    old_attempt_id = job.attempt_id
    new_attempt_id = uuid.uuid4()

    reached_select, resume_tick = _pause_the_tick_after_its_select(monkeypatch)

    tick_task = asyncio.ensure_future(
        tasks_vector._service_import_heartbeat_tick(job_id, old_attempt_id)
    )
    await asyncio.wait_for(reached_select.wait(), timeout=5.0)

    # Simulate a retry rotating attempt_id and restarting progress under the
    # new token, strictly between the OLD tick's SELECT and its write.
    async with db_module.async_session() as retry_session:
        await retry_session.execute(
            update(_IngestJob)
            .where(_IngestJob.id == job_id)
            .values(attempt_id=new_attempt_id, progress=0.2)
        )
        await retry_session.commit()

    resume_tick.set()
    keep_going = await asyncio.wait_for(tick_task, timeout=5.0)
    assert keep_going is True

    async with db_module.async_session() as check_session:
        result = await check_session.execute(
            select(_IngestJob).where(_IngestJob.id == job_id)
        )
        final = result.scalar_one()
    assert final.attempt_id == new_attempt_id
    assert final.status == "running"
    assert final.progress == 0.2, (
        f"the old attempt's stale write reached the new attempt's row: "
        f"{final.progress!r}"
    )


@pytest.mark.anyio
async def test_a_normal_tick_still_advances_progress(test_db_session):
    """Positive control for the round-11 atomic UPDATE: with nothing racing
    it, an ordinary tick must still advance progress exactly as the ORM
    commit it replaces did."""
    import app.core.db as db_module
    from sqlalchemy import select

    from app.platform.jobs.models import IngestJob as _IngestJob
    from tests.factories import get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="NormalHeartbeatJob",
        created_by=admin_id,
        status="running",
        current_step="ogr2ogr",
        progress=0.2,
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    attempt_id = job.attempt_id

    keep_going = await tasks_vector._service_import_heartbeat_tick(job_id, attempt_id)
    assert keep_going is True

    async with db_module.async_session() as check_session:
        result = await check_session.execute(
            select(_IngestJob).where(_IngestJob.id == job_id)
        )
        refreshed = result.scalar_one()
    expected = 0.2 + tasks_vector._SERVICE_IMPORT_HEARTBEAT_INCREMENT
    assert refreshed.progress == pytest.approx(expected)

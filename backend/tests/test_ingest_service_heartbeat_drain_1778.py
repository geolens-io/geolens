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

The final test exercises the round-3 mechanism directly against a REAL row
lock held by a second, real database session -- the one property the mocked
tests above cannot stand in for.
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

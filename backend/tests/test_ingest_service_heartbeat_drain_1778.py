"""The service-import heartbeat's cancellation drain has a finite deadline
(#1778, codex round 2 on #1791).

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
it could reach finalization.

``_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS`` bounds that drain.
``asyncio.shield`` keeps the stuck tick running in the background rather than
cancelling it on that timeout, so its own connection still gets to close on
its own schedule -- only the WAITING stops.

These tests exercise ``_heartbeat_service_import_progress`` directly with a
tick that never returns, standing in for one stuck on a row lock. Completion
is checked by POLLING ``Task.done()``, never by wrapping the heartbeat task
itself in another ``asyncio.wait_for`` -- that would cancel it on ITS OWN
timeout and mask the exact thing under test, whether the drain deadline
constant is what actually bounds completion.
"""

import asyncio
import uuid

import pytest

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

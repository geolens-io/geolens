"""Poll for a backend parked on a lock."""

import asyncio

from sqlalchemy import text


async def await_lock_wait_query(blocked_by: int | None = None) -> str:
    """Block until a backend is parked on a lock, and return what it is running.

    With `blocked_by`, only a backend waiting on that session's pid counts, so
    another test's or a pooled backend's wait is never read.

    Each poll uses its own session: a rollback on the test's session would
    expire the ORM objects the test still holds. ``query`` and ``state`` come
    from a snapshot while ``wait_event_type`` is read live, so a backend that
    began waiting after the snapshot can show its previous statement. A second
    poll must see the same backend still waiting on the same statement.
    """
    import app.core.db as db_module

    waiting = text(
        "SELECT pid, query FROM pg_stat_activity "
        "WHERE datname = current_database() "
        "AND state = 'active' "
        "AND wait_event_type = 'Lock' "
        "AND (CAST(:pid AS int) IS NULL OR pid = CAST(:pid AS int)) "
        "AND (CAST(:blocker AS int) IS NULL "
        "OR CAST(:blocker AS int) = ANY (pg_blocking_pids(pid))) "
        "LIMIT 1"
    )
    for _ in range(600):
        async with db_module.async_session() as probe:
            first = (
                await probe.execute(waiting, {"pid": None, "blocker": blocked_by})
            ).first()
        if first:
            async with db_module.async_session() as probe:
                again = (
                    await probe.execute(
                        waiting, {"pid": first.pid, "blocker": blocked_by}
                    )
                ).first()
            if again and again.query == first.query:
                return again.query
        await asyncio.sleep(0.01)
    raise AssertionError("no backend ever parked on a lock")

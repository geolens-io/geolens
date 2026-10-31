"""Poll for a backend parked on a lock."""

import asyncio

from sqlalchemy import text


async def await_lock_wait_query(blocked_by: int | None = None) -> str:
    """Block until a backend is parked on a lock, and return what it is running.

    With `blocked_by`, only a backend waiting on that session's pid counts, so
    another test's or a pooled backend's wait is never read.

    Each poll uses its own session: a rollback on the test's session would
    expire the ORM objects the test still holds.
    """
    import app.core.db as db_module

    for _ in range(600):
        async with db_module.async_session() as probe:
            query = await probe.scalar(
                text(
                    "SELECT query FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' "
                    "AND (CAST(:blocker AS int) IS NULL "
                    "OR CAST(:blocker AS int) = ANY (pg_blocking_pids(pid))) "
                    "LIMIT 1"
                ),
                {"blocker": blocked_by},
            )
        if query:
            return query
        await asyncio.sleep(0.01)
    raise AssertionError("no backend ever parked on a lock")

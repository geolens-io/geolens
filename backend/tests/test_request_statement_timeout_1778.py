"""fix(#1778): every ordinary DB-touching request needs a query deadline.

Nothing bounded statement execution on the engine each request uses.
``database_connect_args`` carries only the SSL branch and, behind an external
pooler, ``statement_cache_size``; ``core/db/session.py`` adds pool sizing, and
``pool_timeout`` bounds checkout rather than execution. ``db/postgresql.conf``
sets no ``statement_timeout`` either. Combined with uvicorn not cancelling a
handler when its client disconnects, one pathological plan pinned a pool slot
with no ceiling.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import text

from app.core.statement_timeout import (
    bind_request_statement_timeout,
    statement_timeout_ms,
)


def test_the_deadline_is_on_by_default_and_fits_inside_the_edge_timeout():
    from app.core.config import settings
    from app.processing.ingest.url_fetch import EDGE_PROXY_READ_TIMEOUT_SECONDS

    assert settings.db_statement_timeout_seconds > 0, (
        "shipping the knob off by default fixes nothing"
    )
    assert settings.db_statement_timeout_seconds < EDGE_PROXY_READ_TIMEOUT_SECONDS
    assert statement_timeout_ms() == settings.db_statement_timeout_seconds * 1000


def test_get_db_binds_it_and_nothing_else_does():
    """Scoped to HTTP requests. The worker shares the engine and must not get it."""
    from app.core.dependencies import get_db

    assert "bind_request_statement_timeout(session)" in inspect.getsource(get_db)

    from app.core.db import session as session_module

    src = inspect.getsource(session_module)
    assert "statement_timeout" not in src, (
        "a session default on the shared engine would kill worker ingest queries"
    )


@pytest.mark.anyio
async def test_get_db_yields_a_session_that_carries_the_deadline(test_db_session):
    """Drive the dependency itself, transaction boundaries included.

    ``test_db_session`` is requested only so the module's DB gating applies;
    the assertions run on the session ``get_db`` builds.
    """
    from app.core.dependencies import get_db

    assert statement_timeout_ms() > 0
    # pg_settings reports the raw milliseconds; SHOW renders "5min".
    expected = str(statement_timeout_ms())

    agen = get_db()
    session = await agen.__anext__()
    try:

        async def current_timeout() -> str:
            result = await session.execute(
                text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")
            )
            return result.scalar_one()

        first = await current_timeout()
        assert first == expected, "no deadline on the first transaction"

        # A handler that writes, commits, and reads again must not run the
        # rest of the request unbounded: SET LOCAL ends with its transaction.
        await session.commit()
        assert await current_timeout() == expected

        await session.rollback()
        assert await current_timeout() == expected
    finally:
        await session.rollback()
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()


@pytest.mark.anyio
async def test_a_worker_session_is_not_given_the_deadline(test_db_session):
    """The worker shares this engine and runs minutes-long ingest statements."""
    from app.core.db import async_session

    async with async_session() as session:
        result = await session.execute(
            text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")
        )
        assert result.scalar_one() == "0"
        await session.rollback()


@pytest.mark.anyio
async def test_a_query_past_the_deadline_is_cancelled(test_db_session):
    """The teeth. A short deadline aborts pg_sleep rather than waiting it out."""
    from sqlalchemy.exc import DBAPIError

    await test_db_session.execute(text("SET LOCAL statement_timeout = 250"))
    with pytest.raises(DBAPIError):
        await test_db_session.execute(text("SELECT pg_sleep(5)"))
    await test_db_session.rollback()


@pytest.mark.anyio
async def test_a_zero_setting_binds_nothing(test_db_session, monkeypatch):
    """0 is the documented off switch, and off means no listener at all."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 0)
    assert statement_timeout_ms() == 0

    bind_request_statement_timeout(test_db_session)
    result = await test_db_session.execute(
        text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")
    )
    assert result.scalar_one() == "0"
    await test_db_session.rollback()

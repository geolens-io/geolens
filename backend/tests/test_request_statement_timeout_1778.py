"""fix(#1778): every session the API opens needs a query deadline.

Nothing bounded statement execution on the engine the API uses.
``database_connect_args`` carries only the SSL branch and, behind an external
pooler, ``statement_cache_size``; ``core/db/session.py`` adds pool sizing, and
``pool_timeout`` bounds checkout rather than execution. ``db/postgresql.conf``
sets no ``statement_timeout`` either. Combined with uvicorn not cancelling a
handler when its client disconnects, one pathological plan pinned a pool slot
with no ceiling.

fix(#1778 codex r2): the deadline is on the ENGINE, not on ``get_db``. Handlers
open request-scoped sessions directly through ``async_session()`` in more than
twenty modules -- ``GET /stac/collections`` runs three aggregates that way --
so a per-dependency binding covered none of them.

fix(#1778 codex r3): and it is issued as ``SET LOCAL`` at the start of every
transaction, not as asyncpg ``server_settings``. ``server_settings`` travels in
the startup packet, which standard PgBouncer rejects, so under the documented
``DB_USE_EXTERNAL_POOLER=true`` topology every API connection and API startup
would have failed -- and the usual remedy, adding the parameter to
``ignore_startup_parameters``, drops the deadline in silence. One shape for
both topologies, so the direct and pooled paths cannot drift.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.statement_timeout import (
    install_api_statement_timeout,
    statement_timeout_ms,
)

_SHOW_TIMEOUT = text("SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")


def _fresh_engine(**kwargs):
    """An engine of our own, so the shared test engine keeps its own state."""
    from app.core.config import settings

    return create_async_engine(settings.test_database_url, poolclass=NullPool, **kwargs)


def _captured_connect_params(engine) -> dict:
    """The kwargs the dialect will hand asyncpg, captured at connect time."""
    captured: dict = {}

    @event.listens_for(engine.sync_engine, "do_connect")
    def _capture(_dialect, _conn_rec, _cargs, cparams):
        captured.clear()
        captured.update(cparams)
        return None

    return captured


def test_the_deadline_is_on_by_default_and_fits_inside_the_edge_timeout():
    from app.core.config import settings
    from app.processing.ingest.url_fetch import EDGE_PROXY_READ_TIMEOUT_SECONDS

    assert settings.db_statement_timeout_seconds > 0, (
        "shipping the knob off by default fixes nothing"
    )
    assert settings.db_statement_timeout_seconds < EDGE_PROXY_READ_TIMEOUT_SECONDS
    assert statement_timeout_ms() == settings.db_statement_timeout_seconds * 1000


def test_the_api_entrypoint_installs_it_on_the_engine():
    """Import time, so no connection predates the listener; again at lifespan."""
    from app.api import main as api_main

    src = inspect.getsource(api_main.install_api_query_deadline)
    assert "install_api_statement_timeout(engine)" in src
    assert "from app.core.db import engine" in src, (
        "fix(#909): the engine must be late-bound or the fixture's patch is lost"
    )

    module_src = inspect.getsource(api_main)
    assert "\ninstall_api_query_deadline()\n" in module_src, (
        "the install has to run at import, before the pool opens a connection"
    )
    assert "install_api_query_deadline()" in inspect.getsource(api_main.lifespan)


def test_get_db_no_longer_binds_it_per_session():
    """The per-dependency binding was the bug, not the fix."""
    from app.core.dependencies import get_db

    assert "statement_timeout" not in inspect.getsource(get_db)


def test_the_shared_engine_module_carries_no_session_default():
    """A session default there would reach the worker, which shares the module."""
    from app.core.db import session as session_module

    assert "statement_timeout" not in inspect.getsource(session_module)

    from app.core.config import settings

    assert "server_settings" not in settings.database_connect_args


def test_the_installer_sets_no_startup_parameter():
    """fix(#1778 codex r3): the source must not reach for server_settings.

    Standard PgBouncer rejects an unknown startup parameter, so a
    `server_settings` entry fails every connection under the documented
    external-pooler topology, and `ignore_startup_parameters` "fixes" it by
    dropping the deadline in silence.
    """
    from app.core.statement_timeout import install_api_statement_timeout as installer

    code = inspect.getsource(installer)
    assert "server_settings" not in code, (
        "the installer must not put anything in the startup packet"
    )
    # And the mechanism it uses instead: SET LOCAL, with a bound value.
    assert "set_config" in code
    assert "true" in code, "set_config's is_local argument must be true"


@pytest.mark.anyio
@pytest.mark.parametrize("external_pooler", [False, True])
async def test_a_session_from_async_session_runs_under_the_deadline(
    test_db_session, monkeypatch, external_pooler
):
    """The pin: not get_db, a bare `async_session()` the way handlers open one.

    fix(#1778 codex r3): run under both topologies, because they must behave
    the same. ``test_db_session`` is requested only so this module's DB gating
    applies.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "db_use_external_pooler", external_pooler)

    engine = _fresh_engine(connect_args=settings.database_connect_args)
    install_api_statement_timeout(engine)
    # Registered LAST so it observes what every earlier `do_connect` listener
    # has already put in `cparams` -- registering it first would snapshot the
    # parameters before the installer could have added anything, and the
    # assertion below would pass vacuously.
    connect_params = _captured_connect_params(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(_SHOW_TIMEOUT)
            assert result.scalar_one() == str(statement_timeout_ms())

            # The startup packet is what PgBouncer inspects, and it must carry
            # nothing of ours -- under either topology, since there is one
            # shape rather than a branch.
            assert connect_params, "no connection was opened"
            assert "server_settings" not in connect_params, (
                "a startup parameter here fails every connection through "
                "standard PgBouncer"
            )

            # SET LOCAL ends with its transaction, so the next one must get it
            # again: a handler that writes, commits and reads again stays
            # bounded.
            await session.commit()
            result = await session.execute(_SHOW_TIMEOUT)
            assert result.scalar_one() == str(statement_timeout_ms())

            await session.rollback()
            result = await session.execute(_SHOW_TIMEOUT)
            assert result.scalar_one() == str(statement_timeout_ms())
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_a_worker_engine_gets_no_deadline(test_db_session):
    """The worker is a separate process with its own engine and must stay free.

    It runs single statements for minutes while building a spatial index over a
    freshly ingested table. Its entrypoint never imports app.api.main, so
    nothing installs the listener there.
    """
    engine = _fresh_engine()  # deliberately NOT installed on
    try:
        async with engine.connect() as conn:
            result = await conn.execute(_SHOW_TIMEOUT)
            assert result.scalar_one() == "0"
    finally:
        await engine.dispose()

    # And the real property behind that: importing the worker entrypoint does
    # not pull in the module that installs the listener. Checked in a fresh
    # interpreter because this one has already imported app.api.main.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.platform.jobs.worker, sys; "
            "print('app.api.main' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert probe.returncode == 0, probe.stderr[-2000:]
    assert probe.stdout.strip() == "False", (
        "the worker entrypoint now imports app.api.main, so its engine would "
        "inherit the API's statement deadline and long ingest statements would "
        "be cancelled"
    )


@pytest.mark.anyio
async def test_set_local_still_overrides_it(test_db_session):
    """The escape hatch the long-running API routes already use."""
    engine = _fresh_engine()
    install_api_statement_timeout(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await session.execute(text("SET LOCAL statement_timeout = '1800000'"))
            result = await session.execute(_SHOW_TIMEOUT)
            assert result.scalar_one() == "1800000"
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_a_query_past_the_deadline_is_cancelled(test_db_session):
    """The teeth. A short deadline aborts pg_sleep rather than waiting it out."""
    from sqlalchemy.exc import DBAPIError

    await test_db_session.execute(text("SET LOCAL statement_timeout = 250"))
    with pytest.raises(DBAPIError):
        await test_db_session.execute(text("SELECT pg_sleep(5)"))
    await test_db_session.rollback()


@pytest.mark.anyio
async def test_a_zero_setting_installs_nothing(test_db_session, monkeypatch):
    """0 is the documented off switch, and off means no listener at all."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 0)
    assert statement_timeout_ms() == 0

    engine = _fresh_engine()
    install_api_statement_timeout(engine)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(_SHOW_TIMEOUT)
            assert result.scalar_one() == "0"
    finally:
        await engine.dispose()

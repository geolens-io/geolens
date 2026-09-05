"""fix(#1755 item 8): running migrations must not disable the loggers already registered.

``alembic/env.py`` calls ``logging.config.fileConfig()`` so a migration run gets
alembic.ini's console handler and levels. The stdlib default for that call is
``disable_existing_loggers=True``, which sets ``.disabled = True`` on every
logger object that already exists and is not named in alembic.ini's
``[loggers]`` section (root, sqlalchemy, alembic).

In production that silences whatever the API imported before the migration
step. In the test suite it is worse, because the effect outlives the call: the
session-scoped migration fixture runs once per worker, after collection has
already imported the modules under test, so every application and third-party
logger registered by then stays ``.disabled`` for the rest of the session. Three
test sites had grown their own local re-enable dance around that, and a test
that re-enables the logger it is about to assert on is testing the dance.

``.disabled`` is the one flag nothing else restores: ``setup_logging()`` never
touches it, so neither ``tests/_logging_state.configured_logging()`` nor
conftest's logging guard snapshots it.
"""

import ast
import logging
import pathlib

import httpx  # noqa: F401 -- registers the "httpx" logger at collection, before the session migration fixture calls fileConfig()
import pytest

_ENV_PY = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "env.py"


def _file_config_call() -> ast.Call:
    """The single ``fileConfig(...)`` call in alembic/env.py."""
    tree = ast.parse(_ENV_PY.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fileConfig"
    ]
    assert len(calls) == 1, f"expected one fileConfig call, found {len(calls)}"
    return calls[0]


def test_alembic_env_opts_out_of_disabling_existing_loggers():
    """env.py must pass the flag explicitly, not inherit the stdlib default."""
    keywords = {kw.arg: kw.value for kw in _file_config_call().keywords}
    assert "disable_existing_loggers" in keywords, (
        "alembic/env.py calls fileConfig() without disable_existing_loggers, so it "
        "inherits the stdlib default True and silences every logger already "
        "registered when a migration runs."
    )
    value = keywords["disable_existing_loggers"]
    assert isinstance(value, ast.Constant) and value.value is False, (
        "disable_existing_loggers must be the literal False"
    )


def test_migration_run_leaves_an_already_registered_logger_enabled():
    """The session migration ran; the "httpx" logger it did not name still works.

    The alembic logger's level is the proof that fileConfig actually ran in
    this session (alembic.ini sets it to INFO, and nothing else in the suite
    touches that logger). Without it this test would pass vacuously on a run
    where Postgres was unreachable and the migration fixture never fired.
    """
    if logging.getLogger("alembic").level != logging.INFO:
        pytest.skip(
            "alembic.ini logging was never applied in this session, so there is "
            "nothing for this test to observe"
        )
    assert logging.getLogger("httpx").disabled is False

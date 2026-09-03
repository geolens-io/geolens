"""fix(#1778): the app engine must not render bound parameters into errors.

SQLAlchemy defaults ``hide_parameters`` to False, so every StatementError
carries ``[SQL: ...] [parameters: (...)]`` in its message. The DB error
handler logs that message with a traceback, and the SEC-03 redactor in
``core/logging_config.py`` only rewrites top-level event_dict keys by name --
it is documented as shallow and cannot reach values embedded in the
``exception`` string. A connection reset or statement timeout mid-INSERT on
``catalog.users`` therefore wrote password_hash, email and username to stdout.
"""

from __future__ import annotations

from sqlalchemy.exc import StatementError


def test_app_engine_is_built_with_hide_parameters():
    from app.core.db import session as session_module

    assert session_module._engine_kwargs.get("hide_parameters") is True
    # The engine actually carries it: SQLAlchemy reads engine.hide_parameters
    # when it wraps a DBAPI error, not the kwargs dict.
    assert session_module.engine.sync_engine.hide_parameters is True


def test_hide_parameters_keeps_bound_values_out_of_the_message():
    """The behaviour the flag buys, pinned against a SQLAlchemy change."""
    secret = "bcrypt-hash-that-must-not-be-logged"
    hidden = StatementError(
        message="connection was closed",
        statement="INSERT INTO catalog.users (email, password_hash) VALUES ($1, $2)",
        params=("operator@example.com", secret),
        orig=Exception("connection was closed"),
        hide_parameters=True,
    )
    rendered = str(hidden)
    assert secret not in rendered
    assert "operator@example.com" not in rendered
    # The statement text still reaches the log, which is what the DB error
    # handler's docstring asks for.
    assert "INSERT INTO catalog.users" in rendered

    exposed = StatementError(
        message="connection was closed",
        statement="INSERT INTO catalog.users (email, password_hash) VALUES ($1, $2)",
        params=("operator@example.com", secret),
        orig=Exception("connection was closed"),
        hide_parameters=False,
    )
    # Positive control: without the flag the value is right there in the string
    # the handler logs.
    assert secret in str(exposed)

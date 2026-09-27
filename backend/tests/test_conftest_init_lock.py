"""Workers take turns at the part of their database init that is server-wide.

Each xdist worker initializes a database of its own, but the roles its init
and migrations create belong to the whole server, and two workers creating
them at once on a fresh server fail with a duplicate key on pg_authid.
"""

import threading
from contextlib import contextmanager

import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from tests.conftest import (
    _cluster_init_lock,
    _drop_test_database_if_exists,
    _quote_database_identifier,
    _worker_test_database_name,
)


def test_a_second_worker_waits_for_the_first_workers_init(monkeypatch):
    other_worker_db = _worker_test_database_name("geolens_init_lock")
    maintenance = sqlalchemy.create_engine(
        settings.database_url_sync, isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as conn:
            conn.execute(
                text(f"CREATE DATABASE {_quote_database_identifier(other_worker_db)}")
            )
    finally:
        maintenance.dispose()

    first_holds = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_worker():
        with _cluster_init_lock():
            first_holds.set()
            release_first.wait(timeout=30)

    def second_worker():
        with _cluster_init_lock():
            second_entered.set()

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    try:
        assert first_holds.wait(timeout=30)
        # The second worker's own database is not the first worker's.
        monkeypatch.setattr(settings, "postgres_db_test", other_worker_db)
        second.start()

        assert not second_entered.wait(timeout=2), (
            "the second worker's init ran while the first still held the lock"
        )
        release_first.set()
        assert second_entered.wait(timeout=30)
    finally:
        release_first.set()
        first.join(timeout=30)
        if second.ident is not None:
            second.join(timeout=30)
        _drop_test_database_if_exists(other_worker_db)


def _too_many_clients() -> OperationalError:
    return OperationalError(
        "connect", {}, Exception("FATAL: sorry, too many clients already")
    )


def test_a_refused_lock_connection_is_retried(monkeypatch):
    real_connect = sqlalchemy.engine.Engine.connect
    attempts = []

    def refuse_once(engine):
        attempts.append(engine)
        if len(attempts) == 1:
            raise _too_many_clients()
        return real_connect(engine)

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", refuse_once)
    slept = []
    entered = False
    with _cluster_init_lock(sleep_fn=slept.append, backoffs=(0.1, 0.2)):
        entered = True

    assert entered
    assert slept == [0.1]
    assert len(attempts) == 2


def test_a_lock_connection_refused_past_the_budget_raises(monkeypatch):
    def refuse(engine):
        raise _too_many_clients()

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", refuse)
    slept = []
    with pytest.raises(OperationalError, match="too many clients"):
        with _cluster_init_lock(sleep_fn=slept.append, backoffs=(0.1, 0.2)):
            pytest.fail("the lock was reported taken")

    assert slept == [0.1, 0.2]


def test_a_lock_that_cannot_be_taken_fails_setup_instead_of_skipping_init(
    monkeypatch,
):
    """Not the missing-extension case: setup raises, it never yields."""
    import tests.conftest as conftest

    @contextmanager
    def unreachable_lock():
        raise _too_many_clients()
        yield

    session_db = settings.postgres_db_test
    monkeypatch.setattr(conftest, "_SETUP_STAGGER_SECONDS", 0)
    monkeypatch.setattr(conftest, "_cluster_init_lock", unreachable_lock)
    setup = conftest._test_db_lifecycle.__wrapped__()

    try:
        with pytest.raises(OperationalError, match="too many clients"):
            next(setup)
    finally:
        setup.close()

    assert settings.postgres_db_test == session_db
    maintenance = sqlalchemy.create_engine(settings.database_url_sync)
    try:
        with maintenance.connect() as conn:
            leftover = conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :prefix"),
                {"prefix": f"{session_db}\\_%"},
            ).all()
    finally:
        maintenance.dispose()
    assert leftover == []

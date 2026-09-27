"""Workers take turns at the part of their database init that is server-wide.

Each xdist worker initializes a database of its own, but the roles its init
and migrations create belong to the whole server, and two workers creating
them at once on a fresh server fail with a duplicate key on pg_authid.
"""

import threading
import time
import zlib
from collections import defaultdict
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
import tests.conftest as conftest
from tests.conftest import (
    _CLUSTER_INIT_LOCK_KEY,
    _cluster_init_lock,
    _drop_test_database_if_exists,
    _quote_database_identifier,
    _worker_test_database_name,
)


@pytest.fixture
def live_postgres():
    if conftest._db_unavailable_reason is not None:
        pytest.skip(f"Postgres unreachable: {conftest._db_unavailable_reason}")


@pytest.fixture
def lock_key(request):
    """A key of this test's own, so it never waits on a real worker's init or another test."""
    key = zlib.crc32(request.node.nodeid.encode())
    assert key != _CLUSTER_INIT_LOCK_KEY
    return key


def test_a_second_worker_waits_for_the_first_workers_init(
    monkeypatch, live_postgres, lock_key
):
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
        with _cluster_init_lock(key=lock_key):
            first_holds.set()
            release_first.wait(timeout=30)

    def second_worker():
        with _cluster_init_lock(key=lock_key):
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


def test_a_refused_lock_connection_is_retried(monkeypatch, live_postgres, lock_key):
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
    with _cluster_init_lock(sleep_fn=slept.append, backoffs=(0.1, 0.2), key=lock_key):
        entered = True

    assert entered
    assert slept == [0.1]
    assert len(attempts) == 2


def test_a_lock_connection_refused_past_the_budget_raises(monkeypatch, lock_key):
    def refuse(engine):
        raise _too_many_clients()

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", refuse)
    slept = []
    with pytest.raises(OperationalError, match="too many clients"):
        with _cluster_init_lock(
            sleep_fn=slept.append, backoffs=(0.1, 0.2), key=lock_key
        ):
            pytest.fail("the lock was reported taken")

    assert slept == [0.1, 0.2]


def test_a_waiting_worker_holds_no_connection(monkeypatch, live_postgres, lock_key):
    real_connect = sqlalchemy.engine.Engine.connect
    backend_pids = defaultdict(list)

    def tracking_connect(engine):
        conn = real_connect(engine)
        pid = conn.connection.dbapi_connection.info.backend_pid
        backend_pids[threading.current_thread().name].append(pid)
        return conn

    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", tracking_connect)
    holder_holds = threading.Event()
    release_holder = threading.Event()
    waiter_between_attempts = threading.Event()
    resume_waiter = threading.Event()
    waiter_entered = threading.Event()

    def holder():
        with _cluster_init_lock(key=lock_key):
            holder_holds.set()
            release_holder.wait(timeout=30)

    def pause_once(seconds):
        if not waiter_between_attempts.is_set():
            waiter_between_attempts.set()
            resume_waiter.wait(timeout=30)
        time.sleep(seconds)

    def waiter():
        with _cluster_init_lock(sleep_fn=pause_once, key=lock_key):
            waiter_entered.set()

    observer = sqlalchemy.create_engine(settings.database_url_sync)

    def live_backends(pids):
        with observer.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids)"),
                {"pids": pids},
            ).scalar()

    holder_thread = threading.Thread(target=holder, name="holder")
    waiter_thread = threading.Thread(target=waiter, name="waiter")
    holder_thread.start()
    try:
        assert holder_holds.wait(timeout=30)
        waiter_thread.start()
        assert waiter_between_attempts.wait(timeout=5), (
            "the waiter kept its connection open while the lock was held"
        )
        assert live_backends(backend_pids["holder"]) == 1
        assert backend_pids["waiter"]
        deadline = time.monotonic() + 5
        while live_backends(backend_pids["waiter"]) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert live_backends(backend_pids["waiter"]) == 0

        release_holder.set()
        resume_waiter.set()
        assert waiter_entered.wait(timeout=30)
    finally:
        release_holder.set()
        resume_waiter.set()
        holder_thread.join(timeout=30)
        if waiter_thread.ident is not None:
            waiter_thread.join(timeout=30)
        observer.dispose()


def test_the_wait_for_the_lock_is_bounded(live_postgres, lock_key):
    holder_holds = threading.Event()
    release_holder = threading.Event()

    def holder():
        with _cluster_init_lock(key=lock_key):
            holder_holds.set()
            release_holder.wait(timeout=30)

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    try:
        assert holder_holds.wait(timeout=30)
        with pytest.raises(TimeoutError, match="init lock"):
            with _cluster_init_lock(wait_seconds=0.5, key=lock_key):
                pytest.fail("the lock was taken while another worker held it")
    finally:
        release_holder.set()
        holder_thread.join(timeout=30)


def _leftover_worker_databases(session_db: str) -> list:
    maintenance = sqlalchemy.create_engine(settings.database_url_sync)
    try:
        with maintenance.connect() as conn:
            return conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :prefix"),
                {"prefix": f"{session_db}\\_%"},
            ).all()
    finally:
        maintenance.dispose()


def test_a_lock_that_cannot_be_taken_fails_setup_instead_of_skipping_init(
    monkeypatch, live_postgres
):
    """Not the missing-extension case: setup raises, it never yields."""

    @contextmanager
    def unreachable_lock():
        raise _too_many_clients()
        yield

    session_db = settings.postgres_db_test
    monkeypatch.setattr(conftest, "_cluster_init_lock", unreachable_lock)
    setup = conftest._test_db_lifecycle.__wrapped__()

    try:
        with pytest.raises(OperationalError, match="too many clients"):
            next(setup)
    finally:
        setup.close()

    assert settings.postgres_db_test == session_db
    assert _leftover_worker_databases(session_db) == []


def _start_setup_with_init_engine(monkeypatch, init_engine):
    """Run the session setup with ``init_engine`` standing in for the new database's.

    Returns the setup generator and the worker databases that existed when
    ``init_engine`` was handed out.
    """
    session_db = settings.postgres_db_test
    databases_at_init = []

    @contextmanager
    def free_lock():
        yield

    real_create_engine = sqlalchemy.create_engine

    def create_engine(url, *args, **kwargs):
        if url == settings.test_database_url_sync:
            databases_at_init.extend(_leftover_worker_databases(session_db))
            return init_engine
        return real_create_engine(url, *args, **kwargs)

    monkeypatch.setattr(conftest, "_cluster_init_lock", free_lock)
    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    return conftest._test_db_lifecycle.__wrapped__(), databases_at_init


def test_a_saturated_server_during_init_fails_setup(monkeypatch, live_postgres):
    session_db = settings.postgres_db_test
    init_engine = MagicMock()
    init_engine.connect.side_effect = _too_many_clients()
    setup, databases_at_init = _start_setup_with_init_engine(monkeypatch, init_engine)

    try:
        with pytest.raises(OperationalError, match="too many clients"):
            next(setup)
    finally:
        setup.close()

    assert init_engine.connect.called
    assert databases_at_init
    assert settings.postgres_db_test == session_db
    assert _leftover_worker_databases(session_db) == []


def test_a_missing_extension_still_lets_setup_continue(monkeypatch, live_postgres):
    session_db = settings.postgres_db_test
    init_engine = MagicMock()
    conn = init_engine.connect.return_value.__enter__.return_value
    conn.execute.side_effect = OperationalError(
        "CREATE EXTENSION IF NOT EXISTS vector",
        {},
        Exception('extension "vector" is not available'),
    )
    setup, databases_at_init = _start_setup_with_init_engine(monkeypatch, init_engine)

    try:
        next(setup)
        assert _leftover_worker_databases(session_db) == []
    finally:
        setup.close()

    assert conn.execute.called
    assert databases_at_init
    assert settings.postgres_db_test == session_db

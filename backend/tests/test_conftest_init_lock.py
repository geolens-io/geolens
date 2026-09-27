"""Workers take turns at the part of their database init that is server-wide.

Each xdist worker initializes a database of its own, but the roles its init
and migrations create belong to the whole server, and two workers creating
them at once on a fresh server fail with a duplicate key on pg_authid.
"""

import threading

import sqlalchemy
from sqlalchemy import text

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

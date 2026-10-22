"""The job queue's connector behind a transaction-mode pooler such as PgBouncer."""

import psycopg
import pytest
from procrastinate import App

from app.core.config import settings
from app.platform.jobs.queue_connector import make_queue_connector


@pytest.fixture
def queue_behind_a_pooler(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "postgres_db", settings.postgres_db_test)
    monkeypatch.setattr(settings, "database_url_override", None)
    monkeypatch.setattr(settings, "db_use_external_pooler", True)
    # The test database puts the queue's schema on its default search_path, which
    # a deployment's doesn't. libpq reads PGOPTIONS only when the conninfo has none.
    monkeypatch.setenv("PGOPTIONS", "-c search_path=public")


async def test_queue_runs_without_startup_options_or_session_state(
    queue_behind_a_pooler,
):
    conninfo = psycopg.conninfo.conninfo_to_dict(settings.procrastinate_conninfo)
    assert "options" not in conninfo

    connector = make_queue_connector()
    app = App(connector=connector)
    async with app.open_async():
        # Procrastinate's functions and tables are unqualified, so these fail
        # unless its schema is on the search_path for the transaction.
        worker_id = await app.job_manager.register_worker()
        await app.job_manager.unregister_worker(worker_id)

        # Nothing outlives the transaction: under transaction pooling the
        # next client would inherit the server session.
        async with connector.pool.connection() as conn:
            cursor = await conn.execute("SHOW search_path")
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "public"

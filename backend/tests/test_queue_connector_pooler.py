"""The job queue's connector behind a transaction-mode pooler such as PgBouncer."""

from urllib.parse import quote

import pytest
from procrastinate import App

from app.core.config import settings
from app.platform.jobs.queue_connector import make_queue_connector


@pytest.fixture
def behind_a_pooler(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "postgres_db", settings.postgres_db_test)
    monkeypatch.setattr(settings, "database_url_override", None)
    monkeypatch.setattr(settings, "db_use_external_pooler", True)


@pytest.fixture
def pooled_session_without_queue_schema(behind_a_pooler, monkeypatch):
    # The test database puts the queue's schema on its default search_path, which
    # a deployment's doesn't, so the session takes it off again.
    password = quote(settings.postgres_password.get_secret_value(), safe="")
    monkeypatch.setattr(
        settings,
        "database_url_override",
        f"postgresql://{quote(settings.postgres_user, safe='')}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db_test}"
        "?options=-c%20search_path%3Dpublic",
    )


async def test_queue_sets_its_schema_per_transaction_only(
    pooled_session_without_queue_schema,
):
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


async def test_pgoptions_stays_out_of_the_startup_packet(behind_a_pooler, monkeypatch):
    monkeypatch.setenv("PGOPTIONS", "-c application_name=from_pgoptions")
    connector = make_queue_connector()
    async with App(connector=connector).open_async():
        async with connector.pool.connection() as conn:
            cursor = await conn.execute("SHOW application_name")
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] != "from_pgoptions"

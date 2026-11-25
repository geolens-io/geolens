"""The queue schema Alembic builds, against the installed procrastinate.

Alembic owns the queue's tables and functions, so procrastinate's own SQL
migrations never run here. A procrastinate release that ships one leaves this
schema behind until a migration copies the change.
"""

import contextlib
import uuid
from collections.abc import AsyncGenerator
from importlib.metadata import version

import psycopg
import pytest
from procrastinate import App, exceptions
from procrastinate.jobs import Job, Status
from procrastinate.manager import JobManager
from procrastinate.schema import SchemaManager

from app.core.config import settings
from app.platform.jobs.queue_connector import make_queue_connector

# One row per object: its kind, its name and its definition as PostgreSQL
# prints it. Ownership, grants and sequence settings are not compared.
_QUEUE_OBJECTS = """
SELECT 'function',
       p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       pg_get_functiondef(p.oid)
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = %(schema)s AND p.proname LIKE 'procrastinate%%'
UNION ALL
SELECT CASE c.relkind WHEN 'r' THEN 'table column' ELSE 'type attribute' END,
       c.relname || '.' || a.attname,
       concat_ws(
           ' ',
           a.attnum,
           format_type(a.atttypid, a.atttypmod),
           CASE WHEN a.attnotnull THEN 'NOT NULL' END,
           'DEFAULT ' || pg_get_expr(d.adbin, d.adrelid),
           'IDENTITY ' || NULLIF(a.attidentity::text, '')
       )
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
 WHERE n.nspname = %(schema)s
   AND c.relkind IN ('r', 'c')
   AND c.relname LIKE 'procrastinate%%'
   AND a.attnum > 0
   AND NOT a.attisdropped
UNION ALL
SELECT 'index', indexname, indexdef
  FROM pg_indexes
 WHERE schemaname = %(schema)s AND tablename LIKE 'procrastinate%%'
UNION ALL
SELECT 'constraint', c.relname || '.' || k.conname, pg_get_constraintdef(k.oid)
  FROM pg_constraint k
  JOIN pg_class c ON c.oid = k.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = %(schema)s AND c.relname LIKE 'procrastinate%%'
UNION ALL
SELECT 'trigger', c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid)
  FROM pg_trigger t
  JOIN pg_class c ON c.oid = t.tgrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = %(schema)s
   AND c.relname LIKE 'procrastinate%%'
   AND NOT t.tgisinternal
UNION ALL
SELECT 'enum', t.typname, string_agg(e.enumlabel, ', ' ORDER BY e.enumsortorder)
  FROM pg_enum e
  JOIN pg_type t ON t.oid = e.enumtypid
  JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = %(schema)s AND t.typname LIKE 'procrastinate%%'
 GROUP BY t.typname
"""


@pytest.fixture
def queue_on_test_database(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "postgres_db", settings.postgres_db_test)
    monkeypatch.setattr(settings, "database_url_override", None)


async def _queue_objects(
    conn: psycopg.AsyncConnection, schema: str
) -> dict[tuple[str, str], str]:
    cursor = await conn.execute(_QUEUE_OBJECTS, {"schema": schema})
    # The schema name is the one difference the two are meant to have, and
    # procrastinate's layout of a function body isn't part of its meaning.
    return {
        (kind, name.replace(f"{schema}.", "")): " ".join(
            definition.replace(f"{schema}.", "").split()
        )
        for kind, name, definition in await cursor.fetchall()
    }


async def test_queue_schema_matches_the_installed_procrastinate(
    queue_on_test_database,
):
    reference = f"procrastinate_reference_{uuid.uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(
        settings.procrastinate_conninfo
    ) as conn:
        async with conn.transaction(force_rollback=True):
            # procrastinate's schema is unqualified, so it lands in whichever
            # schema leads the search_path.
            await conn.execute(f"CREATE SCHEMA {reference}")
            await conn.execute(f"SET LOCAL search_path TO {reference}")
            await conn.execute(SchemaManager.get_schema())
            expected = await _queue_objects(conn, reference)
            migrated = await _queue_objects(conn, settings.procrastinate_schema)

    assert expected, "procrastinate's schema.sql created nothing to compare"
    drifted = sorted(
        key
        for key in expected.keys() | migrated.keys()
        if expected.get(key) != migrated.get(key)
    )
    assert not drifted, (
        f"The queue schema differs from procrastinate {version('procrastinate')}'s "
        f"schema.sql in {drifted}. Copy the change from the package's "
        "sql/migrations into an Alembic migration."
    )


@contextlib.asynccontextmanager
async def _queue() -> AsyncGenerator[tuple[JobManager, int, str]]:
    """Yield a job manager, a registered worker id and a queue name of its own."""
    queue = f"fetch-{uuid.uuid4().hex}"
    connector = make_queue_connector()
    app = App(connector=connector)
    async with app.open_async():
        worker_id = await app.job_manager.register_worker()
        try:
            yield app.job_manager, worker_id, queue
        finally:
            # The worker's test database outlives this test.
            await connector.execute_query_async(
                "DELETE FROM procrastinate_jobs WHERE queue_name = %(queue)s",
                queue=queue,
            )
            await app.job_manager.unregister_worker(worker_id)


def _job(queue: str, **fields) -> Job:
    return Job(
        queue=queue,
        task_name="fetch_test",
        **{"lock": None, "queueing_lock": None, **fields},
    )


async def test_fetch_takes_a_job_without_a_lock_past_a_held_lock(
    queue_on_test_database,
):
    async with _queue() as (jobs, worker_id, queue):
        running = await jobs.defer_job_async(_job(queue, lock="a"))
        assert (await jobs.fetch_job([queue], worker_id)).id == running.id
        await jobs.defer_job_async(_job(queue, lock="a"))
        unlocked = await jobs.defer_job_async(_job(queue))

        fetched = await jobs.fetch_job([queue], worker_id)

        assert fetched is not None
        assert (fetched.id, fetched.status, fetched.worker_id) == (
            unlocked.id,
            "doing",
            worker_id,
        )
        assert await jobs.fetch_job([queue], worker_id) is None


async def test_fetch_runs_jobs_sharing_a_lock_one_at_a_time(queue_on_test_database):
    async with _queue() as (jobs, worker_id, queue):
        first = await jobs.defer_job_async(_job(queue, lock="a"))
        second = await jobs.defer_job_async(_job(queue, lock="a"))
        other_lock = await jobs.defer_job_async(_job(queue, lock="b"))

        fetched = [await jobs.fetch_job([queue], worker_id) for _ in range(3)]
        assert [job and job.id for job in fetched] == [first.id, other_lock.id, None]

        await jobs.finish_job(fetched[0], Status.SUCCEEDED, delete_job=False)
        assert (await jobs.fetch_job([queue], worker_id)).id == second.id


async def test_fetch_takes_the_higher_priority_job_of_a_lock_first(
    queue_on_test_database,
):
    async with _queue() as (jobs, worker_id, queue):
        await jobs.defer_job_async(_job(queue, lock="a", priority=0))
        urgent = await jobs.defer_job_async(_job(queue, lock="a", priority=5))

        assert (await jobs.fetch_job([queue], worker_id)).id == urgent.id
        assert await jobs.fetch_job([queue], worker_id) is None


async def test_fetching_a_job_frees_its_queueing_lock(queue_on_test_database):
    async with _queue() as (jobs, worker_id, queue):
        waiting = await jobs.defer_job_async(_job(queue, queueing_lock="q"))
        with pytest.raises(exceptions.AlreadyEnqueued):
            await jobs.defer_job_async(_job(queue, queueing_lock="q"))

        assert (await jobs.fetch_job([queue], worker_id)).id == waiting.id

        requeued = await jobs.defer_job_async(_job(queue, queueing_lock="q"))
        assert (await jobs.fetch_job([queue], worker_id)).id == requeued.id

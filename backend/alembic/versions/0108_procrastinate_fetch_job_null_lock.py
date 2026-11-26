"""The job fetch accepts a job without a lock before it looks at other jobs.

procrastinate 3.11 changed ``procrastinate_fetch_job_v2`` this way in its own
SQL migration, which never runs here because Alembic owns the queue schema.
With the lock test inside the subquery, PostgreSQL could plan a nested loop
that scanned every other job for each job without a lock. The signature, the
return type and the job chosen are unchanged, so a worker from the previous
release keeps fetching while this runs.

Revision ID: 0108_procrastinate_fetch_job_null_lock
Revises: 0107_map_manifest_keys
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0108_procrastinate_fetch_job_null_lock"
down_revision: Union[str, None] = "0107_map_manifest_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Both bodies are procrastinate's own text. A test compares the migrated
# function with the installed package's schema.sql.
_FETCH_JOB_NULL_LOCK_FIRST = """
CREATE OR REPLACE FUNCTION catalog.procrastinate_fetch_job_v2(target_queue_names character varying[], p_worker_id bigint) RETURNS catalog.procrastinate_jobs
    LANGUAGE plpgsql
    AS $$
DECLARE
	found_jobs procrastinate_jobs;
BEGIN
    WITH candidate AS (
        SELECT jobs.*
            FROM procrastinate_jobs AS jobs
            WHERE
                -- reject the job if its lock has earlier or higher priority jobs.
                -- Jobs without a lock are accepted before the subquery is considered:
                -- keeping "jobs.lock IS NOT NULL" inside the subquery lets Postgres
                -- plan a nested loop that scans every other job for each NULL-lock job.
                (
                    jobs.lock IS NULL
                    OR NOT EXISTS (
                        SELECT 1
                            FROM procrastinate_jobs AS other_jobs
                            WHERE
                                other_jobs.lock = jobs.lock
                                AND (
                                    -- job with same lock is already running
                                    other_jobs.status = 'doing'
                                    OR
                                    -- job with same lock is waiting and has higher priority (or same priority but was queued first)
                                    (
                                        other_jobs.status = 'todo'
                                        AND (
                                            other_jobs.priority > jobs.priority
                                            OR (
                                            other_jobs.priority = jobs.priority
                                            AND other_jobs.id < jobs.id
                                            )
                                        )
                                    )
                                )
                    )
                )
                AND jobs.status = 'todo'
                AND (target_queue_names IS NULL OR jobs.queue_name = ANY( target_queue_names ))
                AND (jobs.scheduled_at IS NULL OR jobs.scheduled_at <= now())
            ORDER BY jobs.priority DESC, jobs.id ASC LIMIT 1
            FOR UPDATE OF jobs SKIP LOCKED
    )
    UPDATE procrastinate_jobs
        SET status = 'doing', worker_id = p_worker_id
        FROM candidate
        WHERE procrastinate_jobs.id = candidate.id
        RETURNING procrastinate_jobs.* INTO found_jobs;

 RETURN found_jobs;
END;
$$;
"""

_FETCH_JOB_LOCK_TEST_IN_SUBQUERY = """
CREATE OR REPLACE FUNCTION catalog.procrastinate_fetch_job_v2(target_queue_names character varying[], p_worker_id bigint) RETURNS catalog.procrastinate_jobs
    LANGUAGE plpgsql
    AS $$
DECLARE
	found_jobs procrastinate_jobs;
BEGIN
    WITH candidate AS (
        SELECT jobs.*
            FROM procrastinate_jobs AS jobs
            WHERE
                -- reject the job if its lock has earlier or higher priority jobs
                NOT EXISTS (
                    SELECT 1
                        FROM procrastinate_jobs AS other_jobs
                        WHERE
                            jobs.lock IS NOT NULL
                            AND other_jobs.lock = jobs.lock
                            AND (
                                -- job with same lock is already running
                                other_jobs.status = 'doing'
                                OR
                                -- job with same lock is waiting and has higher priority (or same priority but was queued first)
                                (
                                    other_jobs.status = 'todo'
                                    AND (
                                        other_jobs.priority > jobs.priority
                                        OR (
                                        other_jobs.priority = jobs.priority
                                        AND other_jobs.id < jobs.id
                                        )
                                    )
                                )
                            )
                )
                AND jobs.status = 'todo'
                AND (target_queue_names IS NULL OR jobs.queue_name = ANY( target_queue_names ))
                AND (jobs.scheduled_at IS NULL OR jobs.scheduled_at <= now())
            ORDER BY jobs.priority DESC, jobs.id ASC LIMIT 1
            FOR UPDATE OF jobs SKIP LOCKED
    )
    UPDATE procrastinate_jobs
        SET status = 'doing', worker_id = p_worker_id
        FROM candidate
        WHERE procrastinate_jobs.id = candidate.id
        RETURNING procrastinate_jobs.* INTO found_jobs;

 RETURN found_jobs;
END;
$$;
"""


def _replace_fetch_job(function_sql: str) -> None:
    # PL/pgSQL resolves the body's unqualified procrastinate_jobs type when the
    # function is created, so the queue's schema is on the search_path for it.
    op.execute("SET search_path TO catalog, public")
    op.execute(function_sql)
    op.execute("RESET search_path")


def upgrade() -> None:
    """Replace the function in place, keeping its owner and grants."""
    _replace_fetch_job(_FETCH_JOB_NULL_LOCK_FIRST)


def downgrade() -> None:
    """Restore the body 0002_procrastinate created."""
    _replace_fetch_job(_FETCH_JOB_LOCK_TEST_IN_SUBQUERY)

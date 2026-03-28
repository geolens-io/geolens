"""Procrastinate job queue infrastructure.

Tables, types, functions, triggers, and indexes for the procrastinate
async task queue. Managed separately from application tables since this
is third-party library infrastructure.

Revision ID: 0003_prc
Revises: 0002_tbl
Create Date: 2026-03-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0003_prc"
down_revision: Union[str, None] = "0002_tbl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ENUM types ---

    op.execute("""
CREATE TYPE catalog.procrastinate_job_event_type AS ENUM (
    'deferred',
    'started',
    'deferred_for_retry',
    'failed',
    'succeeded',
    'cancelled',
    'abort_requested',
    'aborted',
    'scheduled',
    'retried'
);
""")

    op.execute("""
CREATE TYPE catalog.procrastinate_job_status AS ENUM (
    'todo',
    'doing',
    'succeeded',
    'failed',
    'cancelled',
    'aborting',
    'aborted'
);
""")

    op.execute("""
CREATE TYPE catalog.procrastinate_job_to_defer_v1 AS (
    queue_name character varying,
    task_name character varying,
    priority integer,
    lock text,
    queueing_lock text,
    args jsonb,
    scheduled_at timestamp with time zone
);
""")

    # Set search_path so functions can reference types without catalog. prefix
    op.execute("SET search_path TO catalog, public")

    # --- Functions (10 regular + 8 trigger) ---

    op.execute("""
CREATE FUNCTION catalog.procrastinate_cancel_job_v1(job_id bigint, abort boolean, delete_job boolean) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE
    _job_id bigint;
BEGIN
    IF delete_job THEN
        DELETE FROM procrastinate_jobs
        WHERE id = job_id AND status = 'todo'
        RETURNING id INTO _job_id;
    END IF;
    IF _job_id IS NULL THEN
        IF abort THEN
            UPDATE procrastinate_jobs
            SET abort_requested = true,
                status = CASE status
                    WHEN 'todo' THEN 'cancelled'::procrastinate_job_status ELSE status
                END
            WHERE id = job_id AND status IN ('todo', 'doing')
            RETURNING id INTO _job_id;
        ELSE
            UPDATE procrastinate_jobs
            SET status = 'cancelled'::procrastinate_job_status
            WHERE id = job_id AND status = 'todo'
            RETURNING id INTO _job_id;
        END IF;
    END IF;
    RETURN _job_id;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_defer_jobs_v1(jobs catalog.procrastinate_job_to_defer_v1[]) RETURNS bigint[]
    LANGUAGE plpgsql
    AS $$
DECLARE
    job_ids bigint[];
BEGIN
    WITH inserted_jobs AS (
        INSERT INTO procrastinate_jobs (queue_name, task_name, priority, lock, queueing_lock, args, scheduled_at)
        SELECT (job).queue_name,
               (job).task_name,
               (job).priority,
               (job).lock,
               (job).queueing_lock,
               (job).args,
               (job).scheduled_at
        FROM unnest(jobs) AS job
        RETURNING id
    )
    SELECT array_agg(id) FROM inserted_jobs INTO job_ids;

    RETURN job_ids;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_defer_periodic_job_v2(_queue_name character varying, _lock character varying, _queueing_lock character varying, _task_name character varying, _priority integer, _periodic_id character varying, _defer_timestamp bigint, _args jsonb) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE
	_job_id bigint;
	_defer_id bigint;
BEGIN
    INSERT
        INTO procrastinate_periodic_defers (task_name, periodic_id, defer_timestamp)
        VALUES (_task_name, _periodic_id, _defer_timestamp)
        ON CONFLICT DO NOTHING
        RETURNING id into _defer_id;

    IF _defer_id IS NULL THEN
        RETURN NULL;
    END IF;

    UPDATE procrastinate_periodic_defers
        SET job_id = (
            SELECT COALESCE((
                SELECT unnest(procrastinate_defer_jobs_v1(
                    ARRAY[
                        ROW(
                            _queue_name,
                            _task_name,
                            _priority,
                            _lock,
                            _queueing_lock,
                            _args,
                            NULL::timestamptz
                        )
                    ]::procrastinate_job_to_defer_v1[]
                ))
            ), NULL)
        )
        WHERE id = _defer_id
        RETURNING job_id INTO _job_id;

    DELETE
        FROM procrastinate_periodic_defers
        USING (
            SELECT id
            FROM procrastinate_periodic_defers
            WHERE procrastinate_periodic_defers.task_name = _task_name
            AND procrastinate_periodic_defers.periodic_id = _periodic_id
            AND procrastinate_periodic_defers.defer_timestamp < _defer_timestamp
            ORDER BY id
            FOR UPDATE
        ) to_delete
        WHERE procrastinate_periodic_defers.id = to_delete.id;

    RETURN _job_id;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_finish_job_v1(job_id bigint, end_status catalog.procrastinate_job_status, delete_job boolean) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    _job_id bigint;
BEGIN
    IF end_status NOT IN ('succeeded', 'failed', 'aborted') THEN
        RAISE 'End status should be either "succeeded", "failed" or "aborted" (job id: %)', job_id;
    END IF;
    IF delete_job THEN
        DELETE FROM procrastinate_jobs
        WHERE id = job_id AND status IN ('todo', 'doing')
        RETURNING id INTO _job_id;
    ELSE
        UPDATE procrastinate_jobs
        SET status = end_status,
            abort_requested = false,
            attempts = CASE status
                WHEN 'doing' THEN attempts + 1 ELSE attempts
            END
        WHERE id = job_id AND status IN ('todo', 'doing')
        RETURNING id INTO _job_id;
    END IF;
    IF _job_id IS NULL THEN
        RAISE 'Job was not found or not in "doing" or "todo" status (job id: %)', job_id;
    END IF;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_notify_queue_abort_job_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    payload TEXT;
BEGIN
    SELECT json_build_object('type', 'abort_job_requested', 'job_id', NEW.id)::text INTO payload;
	PERFORM pg_notify('procrastinate_queue_v1#' || NEW.queue_name, payload);
	PERFORM pg_notify('procrastinate_any_queue_v1', payload);
	RETURN NEW;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_notify_queue_job_inserted_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    payload TEXT;
BEGIN
    SELECT json_build_object('type', 'job_inserted', 'job_id', NEW.id)::text INTO payload;
	PERFORM pg_notify('procrastinate_queue_v1#' || NEW.queue_name, payload);
	PERFORM pg_notify('procrastinate_any_queue_v1', payload);
	RETURN NEW;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_prune_stalled_workers_v1(seconds_since_heartbeat double precision) RETURNS TABLE(worker_id bigint)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    DELETE FROM procrastinate_workers
    WHERE last_heartbeat < NOW() - (seconds_since_heartbeat || 'SECOND')::INTERVAL
    RETURNING procrastinate_workers.id;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_register_worker_v1() RETURNS TABLE(worker_id bigint)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    INSERT INTO procrastinate_workers DEFAULT VALUES
    RETURNING procrastinate_workers.id;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_retry_job_v1(job_id bigint, retry_at timestamp with time zone, new_priority integer, new_queue_name character varying, new_lock character varying) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    _job_id bigint;
    _abort_requested boolean;
BEGIN
    SELECT abort_requested FROM procrastinate_jobs
    WHERE id = job_id AND status = 'doing'
    FOR UPDATE
    INTO _abort_requested;
    IF _abort_requested THEN
        UPDATE procrastinate_jobs
        SET status = 'failed'::procrastinate_job_status
        WHERE id = job_id AND status = 'doing'
        RETURNING id INTO _job_id;
    ELSE
        UPDATE procrastinate_jobs
        SET status = 'todo'::procrastinate_job_status,
            attempts = attempts + 1,
            scheduled_at = retry_at,
            priority = COALESCE(new_priority, priority),
            queue_name = COALESCE(new_queue_name, queue_name),
            lock = COALESCE(new_lock, lock)
        WHERE id = job_id AND status = 'doing'
        RETURNING id INTO _job_id;
    END IF;

    IF _job_id IS NULL THEN
        RAISE 'Job was not found or not in "doing" status (job id: %)', job_id;
    END IF;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_retry_job_v2(job_id bigint, retry_at timestamp with time zone, new_priority integer, new_queue_name character varying, new_lock character varying) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    _job_id bigint;
    _abort_requested boolean;
    _current_status procrastinate_job_status;
BEGIN
    SELECT status, abort_requested FROM procrastinate_jobs
    WHERE id = job_id AND status IN ('doing', 'failed')
    FOR UPDATE
    INTO _current_status, _abort_requested;
    IF _current_status = 'doing' AND _abort_requested THEN
        UPDATE procrastinate_jobs
        SET status = 'failed'::procrastinate_job_status
        WHERE id = job_id AND status = 'doing'
        RETURNING id INTO _job_id;
    ELSE
        UPDATE procrastinate_jobs
        SET status = 'todo'::procrastinate_job_status,
            attempts = attempts + 1,
            scheduled_at = retry_at,
            priority = COALESCE(new_priority, priority),
            queue_name = COALESCE(new_queue_name, queue_name),
            lock = COALESCE(new_lock, lock)
        WHERE id = job_id AND status IN ('doing', 'failed')
        RETURNING id INTO _job_id;
    END IF;

    IF _job_id IS NULL THEN
        RAISE 'Job was not found or has an invalid status to retry (job id: %)', job_id;
    END IF;

END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_trigger_abort_requested_events_procedure_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO procrastinate_events(job_id, type)
        VALUES (NEW.id, 'abort_requested'::procrastinate_job_event_type);
    RETURN NEW;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_trigger_function_scheduled_events_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO procrastinate_events(job_id, type, at)
        VALUES (NEW.id, 'scheduled'::procrastinate_job_event_type, NEW.scheduled_at);

	RETURN NEW;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_trigger_function_status_events_insert_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO procrastinate_events(job_id, type)
        VALUES (NEW.id, 'deferred'::procrastinate_job_event_type);
	RETURN NEW;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_trigger_function_status_events_update_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    WITH t AS (
        SELECT CASE
            WHEN OLD.status = 'todo'::procrastinate_job_status
                AND NEW.status = 'doing'::procrastinate_job_status
                THEN 'started'::procrastinate_job_event_type
            WHEN OLD.status = 'doing'::procrastinate_job_status
                AND NEW.status = 'todo'::procrastinate_job_status
                THEN 'deferred_for_retry'::procrastinate_job_event_type
            WHEN OLD.status = 'doing'::procrastinate_job_status
                AND NEW.status = 'failed'::procrastinate_job_status
                THEN 'failed'::procrastinate_job_event_type
            WHEN OLD.status = 'doing'::procrastinate_job_status
                AND NEW.status = 'succeeded'::procrastinate_job_status
                THEN 'succeeded'::procrastinate_job_event_type
            WHEN OLD.status = 'todo'::procrastinate_job_status
                AND (
                    NEW.status = 'cancelled'::procrastinate_job_status
                    OR NEW.status = 'failed'::procrastinate_job_status
                    OR NEW.status = 'succeeded'::procrastinate_job_status
                )
                THEN 'cancelled'::procrastinate_job_event_type
            WHEN OLD.status = 'doing'::procrastinate_job_status
                AND NEW.status = 'aborted'::procrastinate_job_status
                THEN 'aborted'::procrastinate_job_event_type
            WHEN OLD.status = 'failed'::procrastinate_job_status
                AND NEW.status = 'todo'::procrastinate_job_status
                THEN 'retried'::procrastinate_job_event_type
            ELSE NULL
        END as event_type
    )
    INSERT INTO procrastinate_events(job_id, type)
        SELECT NEW.id, t.event_type
        FROM t
        WHERE t.event_type IS NOT NULL;
	RETURN NEW;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_unlink_periodic_defers_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE procrastinate_periodic_defers
    SET job_id = NULL
    WHERE job_id = OLD.id;
    RETURN OLD;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_unregister_worker_v1(worker_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM procrastinate_workers
    WHERE id = worker_id;
END;
$$;
""")

    op.execute("""
CREATE FUNCTION catalog.procrastinate_update_heartbeat_v1(worker_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE procrastinate_workers
    SET last_heartbeat = NOW()
    WHERE id = worker_id;
END;
$$;
""")

    # NOTE: procrastinate_fetch_job_v2 depends on the procrastinate_jobs table
    # so it is created after tables, but we define it here since we need the
    # table to exist first. We create it after tables below.

    # --- Sequences ---

    op.execute("""
CREATE SEQUENCE catalog.procrastinate_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
""")

    op.execute("""
CREATE SEQUENCE catalog.procrastinate_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
""")

    op.execute("""
CREATE SEQUENCE catalog.procrastinate_periodic_defers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
""")

    # --- Tables ---
    # NOTE: Create workers BEFORE jobs (jobs has FK to workers)
    # NOTE: Create jobs BEFORE events and periodic_defers (they have FK to jobs)

    op.execute("""
CREATE TABLE catalog.procrastinate_workers (
    id bigint NOT NULL,
    last_heartbeat timestamp with time zone DEFAULT now() NOT NULL
);
""")

    op.execute("""
ALTER TABLE catalog.procrastinate_workers ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME catalog.procrastinate_workers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
""")

    op.execute("""
CREATE TABLE catalog.procrastinate_jobs (
    id bigint NOT NULL,
    queue_name character varying(128) NOT NULL,
    task_name character varying(128) NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    lock text,
    queueing_lock text,
    args jsonb DEFAULT '{}'::jsonb NOT NULL,
    status catalog.procrastinate_job_status DEFAULT 'todo'::catalog.procrastinate_job_status NOT NULL,
    scheduled_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    abort_requested boolean DEFAULT false NOT NULL,
    worker_id bigint,
    CONSTRAINT check_not_todo_abort_requested CHECK ((NOT ((status = 'todo'::catalog.procrastinate_job_status) AND (abort_requested = true))))
);
""")

    op.execute("""
CREATE TABLE catalog.procrastinate_events (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    type catalog.procrastinate_job_event_type,
    at timestamp with time zone DEFAULT now()
);
""")

    op.execute("""
CREATE TABLE catalog.procrastinate_periodic_defers (
    id bigint NOT NULL,
    task_name character varying(128) NOT NULL,
    defer_timestamp bigint,
    job_id bigint,
    periodic_id character varying(128) DEFAULT ''::character varying NOT NULL
);
""")

    # --- Function that depends on procrastinate_jobs table type ---

    op.execute("""
CREATE FUNCTION catalog.procrastinate_fetch_job_v2(target_queue_names character varying[], p_worker_id bigint) RETURNS catalog.procrastinate_jobs
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
""")

    # --- Alter sequences OWNED BY ---

    op.execute("""
ALTER SEQUENCE catalog.procrastinate_events_id_seq OWNED BY catalog.procrastinate_events.id;
""")

    op.execute("""
ALTER SEQUENCE catalog.procrastinate_jobs_id_seq OWNED BY catalog.procrastinate_jobs.id;
""")

    op.execute("""
ALTER SEQUENCE catalog.procrastinate_periodic_defers_id_seq OWNED BY catalog.procrastinate_periodic_defers.id;
""")

    # --- Set default values for ID columns ---

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_events ALTER COLUMN id SET DEFAULT nextval('catalog.procrastinate_events_id_seq'::regclass);
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_jobs ALTER COLUMN id SET DEFAULT nextval('catalog.procrastinate_jobs_id_seq'::regclass);
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_periodic_defers ALTER COLUMN id SET DEFAULT nextval('catalog.procrastinate_periodic_defers_id_seq'::regclass);
""")

    # --- Primary key constraints ---

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_workers
    ADD CONSTRAINT procrastinate_workers_pkey PRIMARY KEY (id);
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_jobs
    ADD CONSTRAINT procrastinate_jobs_pkey PRIMARY KEY (id);
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_events
    ADD CONSTRAINT procrastinate_events_pkey PRIMARY KEY (id);
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_periodic_defers
    ADD CONSTRAINT procrastinate_periodic_defers_pkey PRIMARY KEY (id);
""")

    # --- Unique constraint ---

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_periodic_defers
    ADD CONSTRAINT procrastinate_periodic_defers_unique UNIQUE (task_name, periodic_id, defer_timestamp);
""")

    # --- Foreign key constraints ---

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_events
    ADD CONSTRAINT procrastinate_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES catalog.procrastinate_jobs(id) ON DELETE CASCADE;
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_jobs
    ADD CONSTRAINT procrastinate_jobs_worker_id_fkey FOREIGN KEY (worker_id) REFERENCES catalog.procrastinate_workers(id) ON DELETE SET NULL;
""")

    op.execute("""
ALTER TABLE ONLY catalog.procrastinate_periodic_defers
    ADD CONSTRAINT procrastinate_periodic_defers_job_id_fkey FOREIGN KEY (job_id) REFERENCES catalog.procrastinate_jobs(id);
""")

    # --- Indexes ---

    op.execute("""
CREATE INDEX idx_procrastinate_jobs_worker_not_null ON catalog.procrastinate_jobs USING btree (worker_id) WHERE ((worker_id IS NOT NULL) AND (status = 'doing'::catalog.procrastinate_job_status));
""")

    op.execute("""
CREATE INDEX idx_procrastinate_workers_last_heartbeat ON catalog.procrastinate_workers USING btree (last_heartbeat);
""")

    op.execute("""
CREATE INDEX procrastinate_events_job_id_fkey_v1 ON catalog.procrastinate_events USING btree (job_id);
""")

    op.execute("""
CREATE INDEX procrastinate_jobs_id_lock_idx_v1 ON catalog.procrastinate_jobs USING btree (id, lock) WHERE (status = ANY (ARRAY['todo'::catalog.procrastinate_job_status, 'doing'::catalog.procrastinate_job_status]));
""")

    op.execute("""
CREATE UNIQUE INDEX procrastinate_jobs_lock_idx_v1 ON catalog.procrastinate_jobs USING btree (lock) WHERE (status = 'doing'::catalog.procrastinate_job_status);
""")

    op.execute("""
CREATE INDEX procrastinate_jobs_priority_idx_v1 ON catalog.procrastinate_jobs USING btree (priority DESC, id) WHERE (status = 'todo'::catalog.procrastinate_job_status);
""")

    op.execute("""
CREATE INDEX procrastinate_jobs_queue_name_idx_v1 ON catalog.procrastinate_jobs USING btree (queue_name);
""")

    op.execute("""
CREATE UNIQUE INDEX procrastinate_jobs_queueing_lock_idx_v1 ON catalog.procrastinate_jobs USING btree (queueing_lock) WHERE (status = 'todo'::catalog.procrastinate_job_status);
""")

    op.execute("""
CREATE INDEX procrastinate_periodic_defers_job_id_fkey_v1 ON catalog.procrastinate_periodic_defers USING btree (job_id);
""")

    # --- Triggers ---

    op.execute("""
CREATE TRIGGER procrastinate_jobs_notify_queue_job_aborted_v1 AFTER UPDATE OF abort_requested ON catalog.procrastinate_jobs FOR EACH ROW WHEN (((old.abort_requested = false) AND (new.abort_requested = true) AND (new.status = 'doing'::catalog.procrastinate_job_status))) EXECUTE FUNCTION catalog.procrastinate_notify_queue_abort_job_v1();
""")

    op.execute("""
CREATE TRIGGER procrastinate_jobs_notify_queue_job_inserted_v1 AFTER INSERT ON catalog.procrastinate_jobs FOR EACH ROW WHEN ((new.status = 'todo'::catalog.procrastinate_job_status)) EXECUTE FUNCTION catalog.procrastinate_notify_queue_job_inserted_v1();
""")

    op.execute("""
CREATE TRIGGER procrastinate_trigger_abort_requested_events_v1 AFTER UPDATE OF abort_requested ON catalog.procrastinate_jobs FOR EACH ROW WHEN ((new.abort_requested = true)) EXECUTE FUNCTION catalog.procrastinate_trigger_abort_requested_events_procedure_v1();
""")

    op.execute("""
CREATE TRIGGER procrastinate_trigger_delete_jobs_v1 BEFORE DELETE ON catalog.procrastinate_jobs FOR EACH ROW EXECUTE FUNCTION catalog.procrastinate_unlink_periodic_defers_v1();
""")

    op.execute("""
CREATE TRIGGER procrastinate_trigger_scheduled_events_v1 AFTER INSERT OR UPDATE ON catalog.procrastinate_jobs FOR EACH ROW WHEN (((new.scheduled_at IS NOT NULL) AND (new.status = 'todo'::catalog.procrastinate_job_status))) EXECUTE FUNCTION catalog.procrastinate_trigger_function_scheduled_events_v1();
""")

    op.execute("""
CREATE TRIGGER procrastinate_trigger_status_events_insert_v1 AFTER INSERT ON catalog.procrastinate_jobs FOR EACH ROW WHEN ((new.status = 'todo'::catalog.procrastinate_job_status)) EXECUTE FUNCTION catalog.procrastinate_trigger_function_status_events_insert_v1();
""")

    op.execute("""
CREATE TRIGGER procrastinate_trigger_status_events_update_v1 AFTER UPDATE OF status ON catalog.procrastinate_jobs FOR EACH ROW EXECUTE FUNCTION catalog.procrastinate_trigger_function_status_events_update_v1();
""")

    # Reset search_path so it doesn't leak into future migrations
    op.execute("RESET search_path")


def downgrade() -> None:
    # --- Drop triggers ---
    op.execute("DROP TRIGGER IF EXISTS procrastinate_trigger_status_events_update_v1 ON catalog.procrastinate_jobs;")
    op.execute("DROP TRIGGER IF EXISTS procrastinate_trigger_status_events_insert_v1 ON catalog.procrastinate_jobs;")
    op.execute("DROP TRIGGER IF EXISTS procrastinate_trigger_scheduled_events_v1 ON catalog.procrastinate_jobs;")
    op.execute("DROP TRIGGER IF EXISTS procrastinate_trigger_delete_jobs_v1 ON catalog.procrastinate_jobs;")
    op.execute("DROP TRIGGER IF EXISTS procrastinate_trigger_abort_requested_events_v1 ON catalog.procrastinate_jobs;")
    op.execute("DROP TRIGGER IF EXISTS procrastinate_jobs_notify_queue_job_inserted_v1 ON catalog.procrastinate_jobs;")
    op.execute("DROP TRIGGER IF EXISTS procrastinate_jobs_notify_queue_job_aborted_v1 ON catalog.procrastinate_jobs;")

    # --- Drop indexes ---
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_periodic_defers_job_id_fkey_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_jobs_queueing_lock_idx_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_jobs_queue_name_idx_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_jobs_priority_idx_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_jobs_lock_idx_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_jobs_id_lock_idx_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.procrastinate_events_job_id_fkey_v1;")
    op.execute("DROP INDEX IF EXISTS catalog.idx_procrastinate_workers_last_heartbeat;")
    op.execute("DROP INDEX IF EXISTS catalog.idx_procrastinate_jobs_worker_not_null;")

    # --- Drop tables (reverse order of creation) ---
    op.execute("DROP TABLE IF EXISTS catalog.procrastinate_periodic_defers CASCADE;")
    op.execute("DROP TABLE IF EXISTS catalog.procrastinate_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS catalog.procrastinate_jobs CASCADE;")
    op.execute("DROP TABLE IF EXISTS catalog.procrastinate_workers CASCADE;")

    # --- Drop sequences ---
    op.execute("DROP SEQUENCE IF EXISTS catalog.procrastinate_periodic_defers_id_seq;")
    op.execute("DROP SEQUENCE IF EXISTS catalog.procrastinate_jobs_id_seq;")
    op.execute("DROP SEQUENCE IF EXISTS catalog.procrastinate_events_id_seq;")

    # --- Drop functions ---
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_update_heartbeat_v1(bigint);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_unregister_worker_v1(bigint);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_unlink_periodic_defers_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_trigger_function_status_events_update_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_trigger_function_status_events_insert_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_trigger_function_scheduled_events_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_trigger_abort_requested_events_procedure_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_retry_job_v2(bigint, timestamp with time zone, integer, character varying, character varying);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_retry_job_v1(bigint, timestamp with time zone, integer, character varying, character varying);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_register_worker_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_prune_stalled_workers_v1(double precision);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_notify_queue_job_inserted_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_notify_queue_abort_job_v1();")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_finish_job_v1(bigint, catalog.procrastinate_job_status, boolean);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_fetch_job_v2(character varying[], bigint);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_defer_periodic_job_v2(character varying, character varying, character varying, character varying, integer, character varying, bigint, jsonb);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_defer_jobs_v1(catalog.procrastinate_job_to_defer_v1[]);")
    op.execute("DROP FUNCTION IF EXISTS catalog.procrastinate_cancel_job_v1(bigint, boolean, boolean);")

    # --- Drop types ---
    op.execute("DROP TYPE IF EXISTS catalog.procrastinate_job_to_defer_v1;")
    op.execute("DROP TYPE IF EXISTS catalog.procrastinate_job_status;")
    op.execute("DROP TYPE IF EXISTS catalog.procrastinate_job_event_type;")

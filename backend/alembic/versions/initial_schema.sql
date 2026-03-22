--
-- PostgreSQL database dump
--

-- Dumped from database version 17.5 (Debian 17.5-1.pgdg110+1)
-- Dumped by pg_dump version 17.5 (Debian 17.5-1.pgdg110+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: catalog; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS catalog;


--
-- Name: procrastinate_job_event_type; Type: TYPE; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_job_status; Type: TYPE; Schema: catalog; Owner: -
--

CREATE TYPE catalog.procrastinate_job_status AS ENUM (
    'todo',
    'doing',
    'succeeded',
    'failed',
    'cancelled',
    'aborting',
    'aborted'
);


--
-- Name: procrastinate_job_to_defer_v1; Type: TYPE; Schema: catalog; Owner: -
--

CREATE TYPE catalog.procrastinate_job_to_defer_v1 AS (
	queue_name character varying,
	task_name character varying,
	priority integer,
	lock text,
	queueing_lock text,
	args jsonb,
	scheduled_at timestamp with time zone
);


--
-- Name: immutable_array_camel_to_spaced(text[], text); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.immutable_array_camel_to_spaced(arr text[], sep text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
            SELECT array_to_string(
                ARRAY(SELECT catalog.immutable_camel_to_spaced(unnest) FROM unnest(arr)),
                sep
            );
        $$;


--
-- Name: immutable_array_to_string(text[], text); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.immutable_array_to_string(arr text[], sep text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$ SELECT array_to_string(arr, sep); $$;


--
-- Name: immutable_camel_to_spaced(text); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.immutable_camel_to_spaced(input text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
            SELECT regexp_replace(input, '([a-z])([A-Z])', '\1 \2', 'g');
        $$;


--
-- Name: immutable_jsonb_column_names(jsonb); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.immutable_jsonb_column_names(info jsonb) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
            SELECT CASE WHEN jsonb_typeof(info) = 'array'
                THEN (SELECT string_agg(elem->>'name', ' ')
                      FROM jsonb_array_elements(info) AS elem)
                ELSE NULL
            END;
        $$;


--
-- Name: immutable_jsonb_sample_values(jsonb); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.immutable_jsonb_sample_values(samples jsonb) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
            SELECT CASE WHEN jsonb_typeof(samples) = 'object'
                THEN (SELECT string_agg(val, ' ')
                      FROM (
                          SELECT jsonb_array_elements_text(value) AS val
                          FROM jsonb_each(samples)
                      ) sub)
                ELSE NULL
            END;
        $$;


--
-- Name: procrastinate_cancel_job_v1(bigint, boolean, boolean); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_defer_jobs_v1(catalog.procrastinate_job_to_defer_v1[]); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_defer_periodic_job_v2(character varying, character varying, character varying, character varying, integer, character varying, bigint, jsonb); Type: FUNCTION; Schema: catalog; Owner: -
--

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


SET default_table_access_method = heap;

--
-- Name: procrastinate_jobs; Type: TABLE; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_fetch_job_v2(character varying[], bigint); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_finish_job_v1(bigint, catalog.procrastinate_job_status, boolean); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_notify_queue_abort_job_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_notify_queue_job_inserted_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_prune_stalled_workers_v1(double precision); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_register_worker_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.procrastinate_register_worker_v1() RETURNS TABLE(worker_id bigint)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    INSERT INTO procrastinate_workers DEFAULT VALUES
    RETURNING procrastinate_workers.id;
END;
$$;


--
-- Name: procrastinate_retry_job_v1(bigint, timestamp with time zone, integer, character varying, character varying); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_retry_job_v2(bigint, timestamp with time zone, integer, character varying, character varying); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_trigger_abort_requested_events_procedure_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.procrastinate_trigger_abort_requested_events_procedure_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO procrastinate_events(job_id, type)
        VALUES (NEW.id, 'abort_requested'::procrastinate_job_event_type);
    RETURN NEW;
END;
$$;


--
-- Name: procrastinate_trigger_function_scheduled_events_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.procrastinate_trigger_function_scheduled_events_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO procrastinate_events(job_id, type, at)
        VALUES (NEW.id, 'scheduled'::procrastinate_job_event_type, NEW.scheduled_at);

	RETURN NEW;
END;
$$;


--
-- Name: procrastinate_trigger_function_status_events_insert_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.procrastinate_trigger_function_status_events_insert_v1() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO procrastinate_events(job_id, type)
        VALUES (NEW.id, 'deferred'::procrastinate_job_event_type);
	RETURN NEW;
END;
$$;


--
-- Name: procrastinate_trigger_function_status_events_update_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_unlink_periodic_defers_v1(); Type: FUNCTION; Schema: catalog; Owner: -
--

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


--
-- Name: procrastinate_unregister_worker_v1(bigint); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.procrastinate_unregister_worker_v1(worker_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM procrastinate_workers
    WHERE id = worker_id;
END;
$$;


--
-- Name: procrastinate_update_heartbeat_v1(bigint); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.procrastinate_update_heartbeat_v1(worker_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE procrastinate_workers
    SET last_heartbeat = NOW()
    WHERE id = worker_id;
END;
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: catalog; Owner: -
--

CREATE FUNCTION catalog.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;


--
-- Name: api_keys; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    key_hash character varying(128) NOT NULL,
    name character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);


--
-- Name: app_settings; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.app_settings (
    key text NOT NULL,
    value jsonb NOT NULL
);


--
-- Name: attribute_metadata; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.attribute_metadata (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_id uuid NOT NULL,
    field_name text NOT NULL,
    title text,
    description text,
    data_type text,
    units text,
    domain_type character varying(20),
    semantic_role character varying(20),
    example_values jsonb,
    ordinal_position integer,
    is_nullable boolean,
    is_current boolean DEFAULT true NOT NULL,
    user_modified_fields text[] DEFAULT '{}'::text[] NOT NULL,
    CONSTRAINT chk_domain_type CHECK (((domain_type IS NULL) OR ((domain_type)::text = ANY ((ARRAY['continuous'::character varying, 'discrete'::character varying, 'categorical'::character varying, 'coded'::character varying, 'codedValue'::character varying, 'boolean'::character varying, 'text'::character varying, 'date'::character varying, 'temporal'::character varying, 'geometry'::character varying, 'range'::character varying])::text[])))),
    CONSTRAINT chk_semantic_role CHECK (((semantic_role IS NULL) OR ((semantic_role)::text = ANY ((ARRAY['geometry'::character varying, 'identifier'::character varying, 'measure'::character varying, 'temporal'::character varying, 'categorical'::character varying, 'category'::character varying, 'label'::character varying, 'foreign_key'::character varying, 'other'::character varying])::text[]))))
);


--
-- Name: audit_logs; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    action character varying(50) NOT NULL,
    resource_type character varying(50) NOT NULL,
    resource_id uuid,
    details jsonb,
    ip_address character varying(45),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: collection_datasets; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.collection_datasets (
    collection_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    added_by uuid,
    sort_order integer DEFAULT 0
);


--
-- Name: collections; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.collections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dataset_assets; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.dataset_assets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_id uuid NOT NULL,
    key character varying(50) NOT NULL,
    href text NOT NULL,
    media_type character varying(100),
    title text,
    description text,
    roles text[],
    size_bytes bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dataset_grants; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.dataset_grants (
    dataset_id uuid NOT NULL,
    role_id uuid NOT NULL
);


--
-- Name: dataset_versions; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.dataset_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_id uuid NOT NULL,
    version_number integer NOT NULL,
    source_filename text,
    source_format text,
    feature_count integer,
    srid integer,
    geometry_type text,
    file_hash text,
    uploaded_by uuid,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: datasets; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.datasets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    table_name character varying(255) NOT NULL,
    srid integer,
    geometry_type character varying(50),
    feature_count bigint,
    column_info jsonb,
    source_format character varying(50),
    source_filename character varying(500),
    original_srid integer,
    sample_values jsonb,
    quality_detail jsonb,
    current_version integer DEFAULT 1 NOT NULL,
    source_url character varying(2000),
    record_id uuid NOT NULL,
    quality_statement text,
    quality_score_numeric double precision,
    tile_cache_ttl integer,
    quicklook_256_uri text,
    CONSTRAINT chk_datasets_geometry_type CHECK (((geometry_type IS NULL) OR (upper((geometry_type)::text) = ANY (ARRAY['POINT'::text, 'LINESTRING'::text, 'POLYGON'::text, 'MULTIPOINT'::text, 'MULTILINESTRING'::text, 'MULTIPOLYGON'::text, 'GEOMETRYCOLLECTION'::text])))),
    CONSTRAINT chk_datasets_original_srid_positive CHECK (((original_srid IS NULL) OR (original_srid > 0))),
    CONSTRAINT chk_datasets_source_format CHECK (((source_format IS NULL) OR ((source_format)::text = ANY ((ARRAY['geojson'::character varying, 'shapefile'::character varying, 'shp'::character varying, 'gpkg'::character varying, 'csv'::character varying, 'kml'::character varying, 'gml'::character varying, 'wfs'::character varying, 'arcgis_featureserver'::character varying, 'fgdb'::character varying, 'created'::character varying, 'geotiff'::character varying])::text[])))),
    CONSTRAINT chk_datasets_srid_positive CHECK (((srid IS NULL) OR (srid > 0))),
    CONSTRAINT chk_quality_score_range CHECK (((quality_score_numeric IS NULL) OR ((quality_score_numeric >= (0)::double precision) AND (quality_score_numeric <= (1)::double precision))))
);


--
-- Name: embed_tokens; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.embed_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    map_id uuid NOT NULL,
    token_hash character varying(128) NOT NULL,
    token_hint character varying(20) NOT NULL,
    name text,
    scoped_dataset_ids jsonb NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    allowed_origins jsonb,
    use_count integer DEFAULT 0 NOT NULL,
    last_used_at timestamp with time zone,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ingest_jobs; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.ingest_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_id uuid,
    status character varying(20) NOT NULL,
    source_filename character varying(500),
    file_path character varying(1000),
    error_message text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    user_metadata jsonb,
    source_url character varying(2000),
    source_layer character varying(500)
);


--
-- Name: map_layers; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.map_layers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    map_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    visible boolean DEFAULT true NOT NULL,
    opacity double precision DEFAULT '1'::double precision NOT NULL,
    paint jsonb DEFAULT '{}'::jsonb NOT NULL,
    layout jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    display_name text,
    filter jsonb,
    label_config jsonb,
    style_config jsonb,
    layer_type character varying(50) DEFAULT 'vector_geolens'::character varying NOT NULL
);


--
-- Name: map_share_tokens; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.map_share_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    map_id uuid NOT NULL,
    token text NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: maps; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.maps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    center_lng double precision,
    center_lat double precision,
    zoom double precision,
    bearing double precision DEFAULT '0'::double precision NOT NULL,
    pitch double precision DEFAULT '0'::double precision NOT NULL,
    basemap_style text DEFAULT 'positron'::text NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    visibility text DEFAULT 'private'::text NOT NULL,
    thumbnail text,
    forked_from uuid,
    CONSTRAINT ck_maps_visibility CHECK ((visibility = ANY (ARRAY['private'::text, 'internal'::text, 'public'::text])))
);


--
-- Name: oauth_accounts; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.oauth_accounts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    provider_id uuid NOT NULL,
    user_id uuid NOT NULL,
    subject character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: oauth_providers; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.oauth_providers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    provider_type character varying(20) NOT NULL,
    client_id character varying(512) NOT NULL,
    client_secret_encrypted text NOT NULL,
    discovery_url character varying(512),
    authorize_url character varying(512),
    token_url character varying(512),
    userinfo_url character varying(512),
    scopes character varying(512) DEFAULT 'openid profile email'::character varying,
    default_role character varying(50) DEFAULT 'viewer'::character varying,
    group_claim character varying(100),
    group_role_mapping jsonb,
    enabled boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: procrastinate_events; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.procrastinate_events (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    type catalog.procrastinate_job_event_type,
    at timestamp with time zone DEFAULT now()
);


--
-- Name: procrastinate_events_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.procrastinate_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: procrastinate_events_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.procrastinate_events_id_seq OWNED BY catalog.procrastinate_events.id;


--
-- Name: procrastinate_jobs_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.procrastinate_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: procrastinate_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.procrastinate_jobs_id_seq OWNED BY catalog.procrastinate_jobs.id;


--
-- Name: procrastinate_periodic_defers; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.procrastinate_periodic_defers (
    id bigint NOT NULL,
    task_name character varying(128) NOT NULL,
    defer_timestamp bigint,
    job_id bigint,
    periodic_id character varying(128) DEFAULT ''::character varying NOT NULL
);


--
-- Name: procrastinate_periodic_defers_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.procrastinate_periodic_defers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: procrastinate_periodic_defers_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.procrastinate_periodic_defers_id_seq OWNED BY catalog.procrastinate_periodic_defers.id;


--
-- Name: procrastinate_workers; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.procrastinate_workers (
    id bigint NOT NULL,
    last_heartbeat timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: procrastinate_workers_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

ALTER TABLE catalog.procrastinate_workers ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME catalog.procrastinate_workers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: raster_assets; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.raster_assets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_id uuid NOT NULL,
    asset_uri text NOT NULL,
    sha256 character varying(64),
    size_bytes bigint,
    driver character varying(50),
    storage_backend character varying(20) DEFAULT 'local'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    ingested_at timestamp with time zone,
    crs_wkt text,
    epsg integer,
    band_count integer,
    dtype character varying(30),
    nodata text,
    res_x double precision,
    res_y double precision,
    width integer,
    height integer,
    compression character varying(30),
    source_sha256 character varying(64),
    cog_status character varying(20),
    quicklook_256_uri text,
    quicklook_512_uri text,
    band_info jsonb,
    vrt_type character varying(20),
    resolution_strategy character varying(20),
    status character varying(20) DEFAULT 'ready'::character varying NOT NULL,
    current_generation_id uuid,
    last_regenerated_at timestamp with time zone,
    is_rotated boolean DEFAULT false NOT NULL,
    CONSTRAINT chk_raster_assets_status CHECK (((status)::text = ANY ((ARRAY['ready'::character varying, 'regenerating'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT chk_raster_assets_vrt_type CHECK (((vrt_type IS NULL) OR ((vrt_type)::text = ANY ((ARRAY['mosaic'::character varying, 'band_stack'::character varying])::text[]))))
);


--
-- Name: record_contacts; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.record_contacts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    record_id uuid NOT NULL,
    role character varying(30) NOT NULL,
    name text,
    email text,
    organization text,
    phone text,
    extra_json jsonb,
    sort_order integer DEFAULT 0 NOT NULL,
    CONSTRAINT chk_contact_role CHECK (((role)::text = ANY ((ARRAY['resourceProvider'::character varying, 'custodian'::character varying, 'owner'::character varying, 'user'::character varying, 'distributor'::character varying, 'originator'::character varying, 'pointOfContact'::character varying, 'principalInvestigator'::character varying, 'processor'::character varying, 'publisher'::character varying, 'author'::character varying, 'sponsor'::character varying, 'coAuthor'::character varying, 'collaborator'::character varying, 'editor'::character varying, 'mediator'::character varying, 'rightsHolder'::character varying, 'contributor'::character varying, 'funder'::character varying, 'stakeholder'::character varying])::text[])))
);


--
-- Name: record_distributions; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.record_distributions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    record_id uuid NOT NULL,
    distribution_type character varying(30) NOT NULL,
    format character varying(50) NOT NULL,
    url text NOT NULL,
    title text,
    description text,
    protocol character varying(100),
    media_type character varying(100),
    is_primary boolean DEFAULT false NOT NULL,
    auto_generated boolean DEFAULT false NOT NULL,
    CONSTRAINT chk_distribution_type CHECK (((distribution_type)::text = ANY ((ARRAY['download'::character varying, 'api'::character varying, 'ogcService'::character varying, 'ogc_features'::character varying, 'webApp'::character varying, 'offlineAccess'::character varying, 'vector_tiles'::character varying])::text[])))
);


--
-- Name: record_embeddings; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.record_embeddings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    record_id uuid NOT NULL,
    embedding public.vector NOT NULL,
    model_name character varying(100) NOT NULL,
    content_hash character varying(64) NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: record_keywords; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.record_keywords (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    record_id uuid NOT NULL,
    keyword text NOT NULL,
    vocabulary_uri text,
    keyword_type character varying(20) DEFAULT 'theme'::character varying NOT NULL,
    CONSTRAINT chk_keyword_type CHECK (((keyword_type)::text = ANY ((ARRAY['discipline'::character varying, 'place'::character varying, 'stratum'::character varying, 'temporal'::character varying, 'theme'::character varying, 'dataCentre'::character varying, 'featureType'::character varying, 'instrument'::character varying, 'platform'::character varying, 'process'::character varying, 'product'::character varying, 'project'::character varying, 'service'::character varying, 'subTopicCategory'::character varying, 'taxon'::character varying])::text[])))
);


--
-- Name: records; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.records (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    summary text,
    license text,
    source_organization text,
    owner_org text,
    visibility character varying(20) DEFAULT 'private'::character varying NOT NULL,
    record_status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    spatial_extent public.geometry(Polygon,4326),
    temporal_start date,
    temporal_end date,
    lineage_summary text,
    update_frequency character varying(30),
    usage_constraints text,
    access_constraints text,
    sensitivity_classification character varying(20),
    theme_category text[],
    created_by uuid,
    updated_by uuid,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS ((((setweight(to_tsvector('english'::regconfig, COALESCE(title, ''::text)), 'A'::"char") || setweight(to_tsvector('english'::regconfig, COALESCE(summary, ''::text)), 'B'::"char")) || setweight(to_tsvector('english'::regconfig, COALESCE(lineage_summary, ''::text)), 'C'::"char")) || setweight(to_tsvector('english'::regconfig, COALESCE(catalog.immutable_array_camel_to_spaced(theme_category, ' '::text), ''::text)), 'B'::"char"))) STORED,
    record_type character varying(20) DEFAULT 'vector_dataset'::character varying NOT NULL,
    CONSTRAINT chk_records_record_status CHECK (((record_status)::text = ANY ((ARRAY['draft'::character varying, 'ready'::character varying, 'internal'::character varying, 'published'::character varying])::text[]))),
    CONSTRAINT chk_records_record_type CHECK (((record_type)::text = ANY ((ARRAY['vector_dataset'::character varying, 'raster_dataset'::character varying, 'vrt_dataset'::character varying, 'map'::character varying, 'service'::character varying, 'collection'::character varying])::text[]))),
    CONSTRAINT chk_records_sensitivity CHECK (((sensitivity_classification IS NULL) OR ((sensitivity_classification)::text = ANY ((ARRAY['public'::character varying, 'internal'::character varying, 'confidential'::character varying, 'restricted'::character varying])::text[])))),
    CONSTRAINT chk_records_update_frequency CHECK (((update_frequency IS NULL) OR ((update_frequency)::text = ANY ((ARRAY['continual'::character varying, 'daily'::character varying, 'weekly'::character varying, 'monthly'::character varying, 'quarterly'::character varying, 'biannually'::character varying, 'annually'::character varying, 'asNeeded'::character varying, 'irregular'::character varying, 'notPlanned'::character varying, 'unknown'::character varying])::text[])))),
    CONSTRAINT chk_records_visibility CHECK (((visibility)::text = ANY ((ARRAY['public'::character varying, 'private'::character varying, 'internal'::character varying, 'restricted'::character varying])::text[]))),
    CONSTRAINT chk_temporal_ordering CHECK (((temporal_start IS NULL) OR (temporal_end IS NULL) OR (temporal_start <= temporal_end)))
);


--
-- Name: refresh_tokens; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.refresh_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(128) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked boolean DEFAULT false NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(50) NOT NULL,
    description text
);


--
-- Name: saved_searches; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.saved_searches (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    params jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_roles; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.user_roles (
    user_id uuid NOT NULL,
    role_id uuid NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    username character varying(150) NOT NULL,
    email character varying(255),
    password_hash text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    auth_provider character varying(20) DEFAULT 'local'::character varying NOT NULL
);


--
-- Name: vrt_generations; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.vrt_generations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    vrt_dataset_id uuid NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    duration_seconds double precision,
    error_message text,
    source_count integer,
    triggered_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vrt_generations_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: vrt_source_links; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.vrt_source_links (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    vrt_dataset_id uuid NOT NULL,
    source_dataset_id uuid NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: procrastinate_events id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_events ALTER COLUMN id SET DEFAULT nextval('catalog.procrastinate_events_id_seq'::regclass);


--
-- Name: procrastinate_jobs id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_jobs ALTER COLUMN id SET DEFAULT nextval('catalog.procrastinate_jobs_id_seq'::regclass);


--
-- Name: procrastinate_periodic_defers id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_periodic_defers ALTER COLUMN id SET DEFAULT nextval('catalog.procrastinate_periodic_defers_id_seq'::regclass);


--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: app_settings app_settings_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);


--
-- Name: attribute_metadata attribute_metadata_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.attribute_metadata
    ADD CONSTRAINT attribute_metadata_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: collection_datasets collection_datasets_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.collection_datasets
    ADD CONSTRAINT collection_datasets_pkey PRIMARY KEY (collection_id, dataset_id);


--
-- Name: collections collections_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.collections
    ADD CONSTRAINT collections_pkey PRIMARY KEY (id);


--
-- Name: dataset_grants dataset_grants_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_grants
    ADD CONSTRAINT dataset_grants_pkey PRIMARY KEY (dataset_id, role_id);


--
-- Name: dataset_versions dataset_versions_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_versions
    ADD CONSTRAINT dataset_versions_pkey PRIMARY KEY (id);


--
-- Name: datasets datasets_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.datasets
    ADD CONSTRAINT datasets_pkey PRIMARY KEY (id);


--
-- Name: datasets datasets_table_name_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.datasets
    ADD CONSTRAINT datasets_table_name_key UNIQUE (table_name);


--
-- Name: embed_tokens embed_tokens_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.embed_tokens
    ADD CONSTRAINT embed_tokens_pkey PRIMARY KEY (id);


--
-- Name: ingest_jobs ingest_jobs_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ingest_jobs
    ADD CONSTRAINT ingest_jobs_pkey PRIMARY KEY (id);


--
-- Name: map_layers map_layers_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_layers
    ADD CONSTRAINT map_layers_pkey PRIMARY KEY (id);


--
-- Name: map_share_tokens map_share_tokens_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_share_tokens
    ADD CONSTRAINT map_share_tokens_pkey PRIMARY KEY (id);


--
-- Name: map_share_tokens map_share_tokens_token_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_share_tokens
    ADD CONSTRAINT map_share_tokens_token_key UNIQUE (token);


--
-- Name: maps maps_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.maps
    ADD CONSTRAINT maps_pkey PRIMARY KEY (id);


--
-- Name: oauth_accounts oauth_accounts_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.oauth_accounts
    ADD CONSTRAINT oauth_accounts_pkey PRIMARY KEY (id);


--
-- Name: oauth_providers oauth_providers_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.oauth_providers
    ADD CONSTRAINT oauth_providers_pkey PRIMARY KEY (id);


--
-- Name: oauth_providers oauth_providers_slug_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.oauth_providers
    ADD CONSTRAINT oauth_providers_slug_key UNIQUE (slug);


--
-- Name: dataset_assets pk_dataset_assets; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_assets
    ADD CONSTRAINT pk_dataset_assets PRIMARY KEY (id);


--
-- Name: raster_assets pk_raster_assets; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.raster_assets
    ADD CONSTRAINT pk_raster_assets PRIMARY KEY (id);


--
-- Name: vrt_source_links pk_vrt_source_links; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.vrt_source_links
    ADD CONSTRAINT pk_vrt_source_links PRIMARY KEY (id);


--
-- Name: procrastinate_events procrastinate_events_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_events
    ADD CONSTRAINT procrastinate_events_pkey PRIMARY KEY (id);


--
-- Name: procrastinate_jobs procrastinate_jobs_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_jobs
    ADD CONSTRAINT procrastinate_jobs_pkey PRIMARY KEY (id);


--
-- Name: procrastinate_periodic_defers procrastinate_periodic_defers_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_periodic_defers
    ADD CONSTRAINT procrastinate_periodic_defers_pkey PRIMARY KEY (id);


--
-- Name: procrastinate_periodic_defers procrastinate_periodic_defers_unique; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_periodic_defers
    ADD CONSTRAINT procrastinate_periodic_defers_unique UNIQUE (task_name, periodic_id, defer_timestamp);


--
-- Name: procrastinate_workers procrastinate_workers_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_workers
    ADD CONSTRAINT procrastinate_workers_pkey PRIMARY KEY (id);


--
-- Name: record_contacts record_contacts_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_contacts
    ADD CONSTRAINT record_contacts_pkey PRIMARY KEY (id);


--
-- Name: record_distributions record_distributions_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_distributions
    ADD CONSTRAINT record_distributions_pkey PRIMARY KEY (id);


--
-- Name: record_embeddings record_embeddings_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_embeddings
    ADD CONSTRAINT record_embeddings_pkey PRIMARY KEY (id);


--
-- Name: record_keywords record_keywords_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_keywords
    ADD CONSTRAINT record_keywords_pkey PRIMARY KEY (id);


--
-- Name: records records_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.records
    ADD CONSTRAINT records_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_token_hash_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.refresh_tokens
    ADD CONSTRAINT refresh_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: saved_searches saved_searches_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.saved_searches
    ADD CONSTRAINT saved_searches_pkey PRIMARY KEY (id);


--
-- Name: attribute_metadata uq_attribute_metadata; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.attribute_metadata
    ADD CONSTRAINT uq_attribute_metadata UNIQUE (dataset_id, field_name);


--
-- Name: dataset_assets uq_dataset_assets_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_assets
    ADD CONSTRAINT uq_dataset_assets_key UNIQUE (dataset_id, key);


--
-- Name: dataset_versions uq_dataset_version; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_versions
    ADD CONSTRAINT uq_dataset_version UNIQUE (dataset_id, version_number);


--
-- Name: oauth_accounts uq_oauth_account_provider_subject; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.oauth_accounts
    ADD CONSTRAINT uq_oauth_account_provider_subject UNIQUE (provider_id, subject);


--
-- Name: raster_assets uq_raster_assets_dataset; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.raster_assets
    ADD CONSTRAINT uq_raster_assets_dataset UNIQUE (dataset_id);


--
-- Name: record_distributions uq_record_distribution; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_distributions
    ADD CONSTRAINT uq_record_distribution UNIQUE (record_id, distribution_type, format, url);


--
-- Name: record_embeddings uq_record_embedding_model; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_embeddings
    ADD CONSTRAINT uq_record_embedding_model UNIQUE (record_id, model_name);


--
-- Name: saved_searches uq_saved_searches_user_name; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.saved_searches
    ADD CONSTRAINT uq_saved_searches_user_name UNIQUE (user_id, name);


--
-- Name: vrt_source_links uq_vsl_vrt_source; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.vrt_source_links
    ADD CONSTRAINT uq_vsl_vrt_source UNIQUE (vrt_dataset_id, source_dataset_id);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: vrt_generations vrt_generations_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.vrt_generations
    ADD CONSTRAINT vrt_generations_pkey PRIMARY KEY (id);


--
-- Name: idx_attribute_metadata_dataset_current; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_attribute_metadata_dataset_current ON catalog.attribute_metadata USING btree (dataset_id, is_current);


--
-- Name: idx_attribute_metadata_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_attribute_metadata_dataset_id ON catalog.attribute_metadata USING btree (dataset_id);


--
-- Name: idx_audit_logs_action; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_audit_logs_action ON catalog.audit_logs USING btree (action);


--
-- Name: idx_audit_logs_created_at; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_audit_logs_created_at ON catalog.audit_logs USING btree (created_at);


--
-- Name: idx_audit_logs_resource_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_audit_logs_resource_id ON catalog.audit_logs USING btree (resource_id);


--
-- Name: idx_audit_logs_user_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_audit_logs_user_id ON catalog.audit_logs USING btree (user_id);


--
-- Name: idx_datasets_geometry_type; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_datasets_geometry_type ON catalog.datasets USING btree (geometry_type);


--
-- Name: idx_datasets_record_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX idx_datasets_record_id ON catalog.datasets USING btree (record_id);


--
-- Name: idx_datasets_srid; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_datasets_srid ON catalog.datasets USING btree (srid);


--
-- Name: idx_procrastinate_jobs_worker_not_null; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_procrastinate_jobs_worker_not_null ON catalog.procrastinate_jobs USING btree (worker_id) WHERE ((worker_id IS NOT NULL) AND (status = 'doing'::catalog.procrastinate_job_status));


--
-- Name: idx_procrastinate_workers_last_heartbeat; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_procrastinate_workers_last_heartbeat ON catalog.procrastinate_workers USING btree (last_heartbeat);


--
-- Name: idx_record_contacts_record_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_record_contacts_record_id ON catalog.record_contacts USING btree (record_id);


--
-- Name: idx_record_contacts_role; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_record_contacts_role ON catalog.record_contacts USING btree (role);


--
-- Name: idx_record_distributions_record_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_record_distributions_record_id ON catalog.record_distributions USING btree (record_id);


--
-- Name: idx_record_keywords_keyword; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_record_keywords_keyword ON catalog.record_keywords USING btree (keyword);


--
-- Name: idx_record_keywords_record_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_record_keywords_record_id ON catalog.record_keywords USING btree (record_id);


--
-- Name: idx_records_search_vector; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_records_search_vector ON catalog.records USING gin (search_vector);


--
-- Name: idx_records_spatial_extent; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_records_spatial_extent ON catalog.records USING gist (spatial_extent);


--
-- Name: idx_users_status_pending; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_users_status_pending ON catalog.users USING btree (status) WHERE ((status)::text = 'pending'::text);


--
-- Name: ix_catalog_embed_tokens_map_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_catalog_embed_tokens_map_id ON catalog.embed_tokens USING btree (map_id);


--
-- Name: ix_catalog_embed_tokens_token_hash; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX ix_catalog_embed_tokens_token_hash ON catalog.embed_tokens USING btree (token_hash);


--
-- Name: ix_collection_datasets_dataset; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_collection_datasets_dataset ON catalog.collection_datasets USING btree (dataset_id);


--
-- Name: ix_dataset_assets_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_dataset_assets_dataset_id ON catalog.dataset_assets USING btree (dataset_id);


--
-- Name: ix_dataset_versions_dataset; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_dataset_versions_dataset ON catalog.dataset_versions USING btree (dataset_id);


--
-- Name: ix_map_layers_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_map_layers_dataset_id ON catalog.map_layers USING btree (dataset_id);


--
-- Name: ix_map_layers_map_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_map_layers_map_id ON catalog.map_layers USING btree (map_id);


--
-- Name: ix_map_share_tokens_map_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_map_share_tokens_map_id ON catalog.map_share_tokens USING btree (map_id);


--
-- Name: ix_map_share_tokens_token; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_map_share_tokens_token ON catalog.map_share_tokens USING btree (token);


--
-- Name: ix_raster_assets_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_raster_assets_dataset_id ON catalog.raster_assets USING btree (dataset_id);


--
-- Name: ix_record_contacts_fts; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_record_contacts_fts ON catalog.record_contacts USING gin (to_tsvector('english'::regconfig, ((COALESCE(name, ''::text) || ' '::text) || COALESCE(organization, ''::text))));


--
-- Name: ix_record_keywords_fts; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_record_keywords_fts ON catalog.record_keywords USING gin (to_tsvector('english'::regconfig, keyword));


--
-- Name: ix_refresh_tokens_token_hash; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_refresh_tokens_token_hash ON catalog.refresh_tokens USING btree (token_hash);


--
-- Name: ix_refresh_tokens_user_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_refresh_tokens_user_id ON catalog.refresh_tokens USING btree (user_id);


--
-- Name: ix_saved_searches_user_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_saved_searches_user_id ON catalog.saved_searches USING btree (user_id);


--
-- Name: ix_vrt_generations_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_vrt_generations_dataset_id ON catalog.vrt_generations USING btree (vrt_dataset_id);


--
-- Name: ix_vrt_generations_status; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_vrt_generations_status ON catalog.vrt_generations USING btree (status);


--
-- Name: ix_vrt_source_links_source_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_vrt_source_links_source_dataset_id ON catalog.vrt_source_links USING btree (source_dataset_id);


--
-- Name: ix_vrt_source_links_vrt_dataset_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX ix_vrt_source_links_vrt_dataset_id ON catalog.vrt_source_links USING btree (vrt_dataset_id);


--
-- Name: procrastinate_events_job_id_fkey_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX procrastinate_events_job_id_fkey_v1 ON catalog.procrastinate_events USING btree (job_id);


--
-- Name: procrastinate_jobs_id_lock_idx_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX procrastinate_jobs_id_lock_idx_v1 ON catalog.procrastinate_jobs USING btree (id, lock) WHERE (status = ANY (ARRAY['todo'::catalog.procrastinate_job_status, 'doing'::catalog.procrastinate_job_status]));


--
-- Name: procrastinate_jobs_lock_idx_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX procrastinate_jobs_lock_idx_v1 ON catalog.procrastinate_jobs USING btree (lock) WHERE (status = 'doing'::catalog.procrastinate_job_status);


--
-- Name: procrastinate_jobs_priority_idx_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX procrastinate_jobs_priority_idx_v1 ON catalog.procrastinate_jobs USING btree (priority DESC, id) WHERE (status = 'todo'::catalog.procrastinate_job_status);


--
-- Name: procrastinate_jobs_queue_name_idx_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX procrastinate_jobs_queue_name_idx_v1 ON catalog.procrastinate_jobs USING btree (queue_name);


--
-- Name: procrastinate_jobs_queueing_lock_idx_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX procrastinate_jobs_queueing_lock_idx_v1 ON catalog.procrastinate_jobs USING btree (queueing_lock) WHERE (status = 'todo'::catalog.procrastinate_job_status);


--
-- Name: procrastinate_periodic_defers_job_id_fkey_v1; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX procrastinate_periodic_defers_job_id_fkey_v1 ON catalog.procrastinate_periodic_defers USING btree (job_id);


--
-- Name: uq_collections_name; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX uq_collections_name ON catalog.collections USING btree (name);


--
-- Name: uq_embed_tokens_one_active_per_map; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX uq_embed_tokens_one_active_per_map ON catalog.embed_tokens USING btree (map_id) WHERE (is_active = true);


--
-- Name: uq_record_keyword; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX uq_record_keyword ON catalog.record_keywords USING btree (record_id, keyword, keyword_type, COALESCE(vocabulary_uri, ''::text));


--
-- Name: procrastinate_jobs procrastinate_jobs_notify_queue_job_aborted_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_jobs_notify_queue_job_aborted_v1 AFTER UPDATE OF abort_requested ON catalog.procrastinate_jobs FOR EACH ROW WHEN (((old.abort_requested = false) AND (new.abort_requested = true) AND (new.status = 'doing'::catalog.procrastinate_job_status))) EXECUTE FUNCTION catalog.procrastinate_notify_queue_abort_job_v1();


--
-- Name: procrastinate_jobs procrastinate_jobs_notify_queue_job_inserted_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_jobs_notify_queue_job_inserted_v1 AFTER INSERT ON catalog.procrastinate_jobs FOR EACH ROW WHEN ((new.status = 'todo'::catalog.procrastinate_job_status)) EXECUTE FUNCTION catalog.procrastinate_notify_queue_job_inserted_v1();


--
-- Name: procrastinate_jobs procrastinate_trigger_abort_requested_events_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_trigger_abort_requested_events_v1 AFTER UPDATE OF abort_requested ON catalog.procrastinate_jobs FOR EACH ROW WHEN ((new.abort_requested = true)) EXECUTE FUNCTION catalog.procrastinate_trigger_abort_requested_events_procedure_v1();


--
-- Name: procrastinate_jobs procrastinate_trigger_delete_jobs_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_trigger_delete_jobs_v1 BEFORE DELETE ON catalog.procrastinate_jobs FOR EACH ROW EXECUTE FUNCTION catalog.procrastinate_unlink_periodic_defers_v1();


--
-- Name: procrastinate_jobs procrastinate_trigger_scheduled_events_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_trigger_scheduled_events_v1 AFTER INSERT OR UPDATE ON catalog.procrastinate_jobs FOR EACH ROW WHEN (((new.scheduled_at IS NOT NULL) AND (new.status = 'todo'::catalog.procrastinate_job_status))) EXECUTE FUNCTION catalog.procrastinate_trigger_function_scheduled_events_v1();


--
-- Name: procrastinate_jobs procrastinate_trigger_status_events_insert_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_trigger_status_events_insert_v1 AFTER INSERT ON catalog.procrastinate_jobs FOR EACH ROW WHEN ((new.status = 'todo'::catalog.procrastinate_job_status)) EXECUTE FUNCTION catalog.procrastinate_trigger_function_status_events_insert_v1();


--
-- Name: procrastinate_jobs procrastinate_trigger_status_events_update_v1; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER procrastinate_trigger_status_events_update_v1 AFTER UPDATE OF status ON catalog.procrastinate_jobs FOR EACH ROW EXECUTE FUNCTION catalog.procrastinate_trigger_function_status_events_update_v1();


--
-- Name: records trg_records_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER trg_records_updated_at BEFORE UPDATE ON catalog.records FOR EACH ROW EXECUTE FUNCTION catalog.set_updated_at();


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES catalog.users(id) ON DELETE CASCADE;


--
-- Name: attribute_metadata attribute_metadata_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.attribute_metadata
    ADD CONSTRAINT attribute_metadata_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: collection_datasets collection_datasets_added_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.collection_datasets
    ADD CONSTRAINT collection_datasets_added_by_fkey FOREIGN KEY (added_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: collection_datasets collection_datasets_collection_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.collection_datasets
    ADD CONSTRAINT collection_datasets_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES catalog.collections(id) ON DELETE CASCADE;


--
-- Name: collection_datasets collection_datasets_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.collection_datasets
    ADD CONSTRAINT collection_datasets_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: collections collections_created_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.collections
    ADD CONSTRAINT collections_created_by_fkey FOREIGN KEY (created_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: dataset_grants dataset_grants_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_grants
    ADD CONSTRAINT dataset_grants_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: dataset_grants dataset_grants_role_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_grants
    ADD CONSTRAINT dataset_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES catalog.roles(id) ON DELETE CASCADE;


--
-- Name: dataset_versions dataset_versions_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_versions
    ADD CONSTRAINT dataset_versions_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: dataset_versions dataset_versions_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_versions
    ADD CONSTRAINT dataset_versions_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: embed_tokens embed_tokens_created_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.embed_tokens
    ADD CONSTRAINT embed_tokens_created_by_fkey FOREIGN KEY (created_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: embed_tokens embed_tokens_map_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.embed_tokens
    ADD CONSTRAINT embed_tokens_map_id_fkey FOREIGN KEY (map_id) REFERENCES catalog.maps(id) ON DELETE CASCADE;


--
-- Name: dataset_assets fk_da_dataset; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.dataset_assets
    ADD CONSTRAINT fk_da_dataset FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: datasets fk_datasets_record_id; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.datasets
    ADD CONSTRAINT fk_datasets_record_id FOREIGN KEY (record_id) REFERENCES catalog.records(id) ON DELETE CASCADE;


--
-- Name: raster_assets fk_raster_assets_dataset; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.raster_assets
    ADD CONSTRAINT fk_raster_assets_dataset FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: vrt_source_links fk_vsl_source_dataset; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.vrt_source_links
    ADD CONSTRAINT fk_vsl_source_dataset FOREIGN KEY (source_dataset_id) REFERENCES catalog.datasets(id) ON DELETE RESTRICT;


--
-- Name: vrt_source_links fk_vsl_vrt_dataset; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.vrt_source_links
    ADD CONSTRAINT fk_vsl_vrt_dataset FOREIGN KEY (vrt_dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: ingest_jobs ingest_jobs_created_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ingest_jobs
    ADD CONSTRAINT ingest_jobs_created_by_fkey FOREIGN KEY (created_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: ingest_jobs ingest_jobs_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ingest_jobs
    ADD CONSTRAINT ingest_jobs_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE SET NULL;


--
-- Name: map_layers map_layers_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_layers
    ADD CONSTRAINT map_layers_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- Name: map_layers map_layers_map_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_layers
    ADD CONSTRAINT map_layers_map_id_fkey FOREIGN KEY (map_id) REFERENCES catalog.maps(id) ON DELETE CASCADE;


--
-- Name: map_share_tokens map_share_tokens_created_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_share_tokens
    ADD CONSTRAINT map_share_tokens_created_by_fkey FOREIGN KEY (created_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: map_share_tokens map_share_tokens_map_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.map_share_tokens
    ADD CONSTRAINT map_share_tokens_map_id_fkey FOREIGN KEY (map_id) REFERENCES catalog.maps(id) ON DELETE CASCADE;


--
-- Name: maps maps_created_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.maps
    ADD CONSTRAINT maps_created_by_fkey FOREIGN KEY (created_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: maps maps_forked_from_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.maps
    ADD CONSTRAINT maps_forked_from_fkey FOREIGN KEY (forked_from) REFERENCES catalog.maps(id) ON DELETE SET NULL;


--
-- Name: oauth_accounts oauth_accounts_provider_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.oauth_accounts
    ADD CONSTRAINT oauth_accounts_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES catalog.oauth_providers(id) ON DELETE CASCADE;


--
-- Name: oauth_accounts oauth_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.oauth_accounts
    ADD CONSTRAINT oauth_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES catalog.users(id) ON DELETE CASCADE;


--
-- Name: procrastinate_events procrastinate_events_job_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_events
    ADD CONSTRAINT procrastinate_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES catalog.procrastinate_jobs(id) ON DELETE CASCADE;


--
-- Name: procrastinate_jobs procrastinate_jobs_worker_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_jobs
    ADD CONSTRAINT procrastinate_jobs_worker_id_fkey FOREIGN KEY (worker_id) REFERENCES catalog.procrastinate_workers(id) ON DELETE SET NULL;


--
-- Name: procrastinate_periodic_defers procrastinate_periodic_defers_job_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.procrastinate_periodic_defers
    ADD CONSTRAINT procrastinate_periodic_defers_job_id_fkey FOREIGN KEY (job_id) REFERENCES catalog.procrastinate_jobs(id);


--
-- Name: record_contacts record_contacts_record_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_contacts
    ADD CONSTRAINT record_contacts_record_id_fkey FOREIGN KEY (record_id) REFERENCES catalog.records(id) ON DELETE CASCADE;


--
-- Name: record_distributions record_distributions_record_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_distributions
    ADD CONSTRAINT record_distributions_record_id_fkey FOREIGN KEY (record_id) REFERENCES catalog.records(id) ON DELETE CASCADE;


--
-- Name: record_embeddings record_embeddings_record_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_embeddings
    ADD CONSTRAINT record_embeddings_record_id_fkey FOREIGN KEY (record_id) REFERENCES catalog.records(id) ON DELETE CASCADE;


--
-- Name: record_keywords record_keywords_record_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.record_keywords
    ADD CONSTRAINT record_keywords_record_id_fkey FOREIGN KEY (record_id) REFERENCES catalog.records(id) ON DELETE CASCADE;


--
-- Name: records records_created_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.records
    ADD CONSTRAINT records_created_by_fkey FOREIGN KEY (created_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: records records_updated_by_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.records
    ADD CONSTRAINT records_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES catalog.users(id) ON DELETE SET NULL;


--
-- Name: refresh_tokens refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES catalog.users(id) ON DELETE CASCADE;


--
-- Name: saved_searches saved_searches_user_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.saved_searches
    ADD CONSTRAINT saved_searches_user_id_fkey FOREIGN KEY (user_id) REFERENCES catalog.users(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.user_roles
    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES catalog.roles(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES catalog.users(id) ON DELETE CASCADE;


--
-- Name: vrt_generations vrt_generations_vrt_dataset_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.vrt_generations
    ADD CONSTRAINT vrt_generations_vrt_dataset_id_fkey FOREIGN KEY (vrt_dataset_id) REFERENCES catalog.datasets(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


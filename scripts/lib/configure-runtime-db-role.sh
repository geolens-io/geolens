#!/usr/bin/env bash
set -euo pipefail

# Canonical PostgreSQL role/grant reconciliation for fresh bootstrap,
# existing-install adoption, and post-restore ACL repair. This script runs
# *inside* the db container as POSTGRES_USER; the application never executes it.

runtime_role="${GEOLENS_RUNTIME_DB_ROLE:-}"
runtime_password="${GEOLENS_RUNTIME_DB_PASSWORD:-}"
db_user="${POSTGRES_USER:?POSTGRES_USER is required}"
db_name="${POSTGRES_DB:?POSTGRES_DB is required}"

if [ -n "$runtime_role" ] \
    && [[ ! "$runtime_role" =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_ROLE must be a lowercase PostgreSQL identifier." >&2
    exit 64
fi
if [ "${#runtime_role}" -gt 63 ]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_ROLE must be at most 63 characters." >&2
    exit 64
fi

if [ -n "$runtime_role" ] && [ "${#runtime_password}" -lt 32 ]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_PASSWORD must contain at least 32 characters when GEOLENS_RUNTIME_DB_ROLE is set." >&2
    exit 64
fi

privileged_password="${POSTGRES_PASSWORD:-${PGPASSWORD:-}}"
if [ -n "$runtime_role" ] \
    && [ -n "$privileged_password" ] \
    && [ "$runtime_password" = "$privileged_password" ]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_PASSWORD must differ from the privileged bootstrap/migration password." >&2
    exit 64
fi

psql_args=(
    -X
    -v ON_ERROR_STOP=1
    --username "$db_user"
    --dbname "$db_name"
)
if [ -n "${POSTGRES_HOST:-}" ]; then
    psql_args+=(--host "$POSTGRES_HOST")
elif [ -n "${PGHOST:-}" ]; then
    psql_args+=(--host "$PGHOST")
fi
if [ -n "${POSTGRES_PORT:-}" ]; then
    psql_args+=(--port "$POSTGRES_PORT")
elif [ -n "${PGPORT:-}" ]; then
    psql_args+=(--port "$PGPORT")
fi

# The reader role is required in both legacy and least-privilege deployments.
# Keep this block here, rather than copying it into init-db.sh and restore.sh,
# because a restore drops schema ACLs and must rebuild the exact bootstrap shape.
psql "${psql_args[@]}" <<-'EOSQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN
        CREATE ROLE geolens_reader
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;
ALTER ROLE geolens_reader
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA data TO geolens_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA data
    GRANT SELECT ON TABLES TO geolens_reader;
EOSQL

if [ -z "$runtime_role" ]; then
    echo "GEOLENS_RUNTIME_DB_ROLE is unset; kept the legacy PostgreSQL runtime credential and reconciled geolens_reader only."
    exit 0
fi

# Use psql's \getenv and format(%L) so the password never appears in argv or
# logs and is still quoted as data. The role identifier is likewise quoted via
# format(%I); the shell validation above adds a fail-closed operator contract.
psql "${psql_args[@]}" <<-'EOSQL'
\getenv runtime_role GEOLENS_RUNTIME_DB_ROLE
\getenv runtime_password GEOLENS_RUNTIME_DB_PASSWORD

SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'runtime_role', :'runtime_password'
)
WHERE NOT EXISTS (
    SELECT FROM pg_roles WHERE rolname = :'runtime_role'
)\gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'runtime_role', :'runtime_password'
)\gexec

SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'runtime_role'
)\gexec

-- PG 15 removed PUBLIC's CREATE privilege on schema public for new clusters,
-- but GeoLens supports older/external clusters too. A runtime login that can
-- create objects on the default search_path defeats the role boundary.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('REVOKE CREATE ON SCHEMA catalog FROM %I', :'runtime_role')\gexec

SELECT format('GRANT USAGE ON SCHEMA catalog TO %I', :'runtime_role')\gexec
SELECT format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA catalog TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA catalog TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA catalog TO %I', :'runtime_role'
)\gexec

-- Future Alembic objects are owned by this privileged reconciliation/migration
-- identity. The runtime role receives DML/sequence/function rights, never DDL.
SELECT format(
    'ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT USAGE, SELECT ON SEQUENCES TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT EXECUTE ON FUNCTIONS TO %I',
    :'runtime_role'
)\gexec

-- fix(#1287 review): embedding-dimension changes are the one live admin path
-- that needs catalog relation-owner DDL. Keep the runtime login non-owning and
-- expose only this bounded operation through a hardened definer function.
-- Dynamic SQL is limited to a validated integer; every object and extension
-- type is schema-qualified, and PUBLIC receives no implicit EXECUTE grant.
CREATE OR REPLACE FUNCTION catalog.geolens_rebuild_embedding_column(new_dims integer)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    current_dims integer;
BEGIN
    IF new_dims IS NULL OR new_dims < 1 OR new_dims > 4096 THEN
        RAISE EXCEPTION 'embedding dimensions must be between 1 and 4096'
            USING ERRCODE = '22023';
    END IF;

    SELECT attribute.atttypmod
      INTO current_dims
      FROM pg_attribute AS attribute
     WHERE attribute.attrelid = to_regclass('catalog.record_embeddings')
       AND attribute.attname = 'embedding';

    IF current_dims IS NULL OR current_dims = new_dims THEN
        RETURN false;
    END IF;

    DELETE FROM catalog.record_embeddings;
    DROP INDEX IF EXISTS catalog.ix_record_embeddings_hnsw;
    EXECUTE format(
        'ALTER TABLE catalog.record_embeddings '
        'ALTER COLUMN embedding TYPE public.vector(%s) '
        'USING embedding::public.vector(%s)',
        new_dims,
        new_dims
    );
    IF new_dims <= 2000 THEN
        EXECUTE
            'CREATE INDEX ix_record_embeddings_hnsw '
            'ON catalog.record_embeddings USING hnsw '
            '(embedding public.vector_cosine_ops) '
            'WITH (m=16, ef_construction=64)';
    END IF;
    RETURN true;
END
$function$;
REVOKE ALL ON FUNCTION catalog.geolens_rebuild_embedding_column(integer)
    FROM PUBLIC;
SELECT format(
    'GRANT EXECUTE ON FUNCTION catalog.geolens_rebuild_embedding_column(integer) TO %I',
    :'runtime_role'
)\gexec

-- Single-tenant ingest and editing create and alter relations in data. Existing
-- relations were created by the old superuser runtime (or by pg_restore with
-- --no-owner), so grants alone are insufficient: PostgreSQL has no ALTER/DROP
-- privilege to grant. Transfer only data-schema runtime relations, never the
-- migration-owned catalog schema or its tables.
SELECT format('GRANT USAGE, CREATE ON SCHEMA data TO %I', :'runtime_role')\gexec
SELECT format(
    'ALTER %s %I.%I OWNER TO %I',
    CASE c.relkind
        WHEN 'r' THEN 'TABLE'
        WHEN 'p' THEN 'TABLE'
        WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW'
        WHEN 'S' THEN 'SEQUENCE'
        WHEN 'f' THEN 'FOREIGN TABLE'
    END,
    n.nspname,
    c.relname,
    :'runtime_role'
)
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = c.relowner
WHERE n.nspname = 'data'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  AND owner_role.rolname <> :'runtime_role'
ORDER BY CASE c.relkind WHEN 'S' THEN 2 ELSE 1 END, c.relname
\gexec

SELECT format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA data TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA data TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA data TO %I', :'runtime_role'
)\gexec
SELECT format('GRANT geolens_reader TO %I', :'runtime_role')\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader',
    :'runtime_role'
)\gexec

-- Fail closed if the role can still inherit/assume a powerful role, can create
-- in a protected schema, lacks its reader transition, or does not own every
-- existing runtime relation in data. The application repeats the dangerous-
-- attribute check against its live connection at boot.
SELECT (
    runtime.rolcanlogin
    AND NOT runtime.rolsuper
    AND NOT runtime.rolbypassrls
    AND NOT runtime.rolcreaterole
    AND NOT runtime.rolcreatedb
    AND NOT runtime.rolreplication
    AND NOT runtime.rolinherit
    AND NOT EXISTS (
        SELECT 1
        FROM pg_roles AS powerful
        WHERE powerful.oid <> runtime.oid
          AND (
              powerful.rolsuper OR powerful.rolbypassrls
              OR powerful.rolcreaterole OR powerful.rolcreatedb
              OR powerful.rolreplication
          )
          AND pg_has_role(runtime.oid, powerful.oid, 'MEMBER')
    )
    AND NOT has_schema_privilege(runtime.oid, 'catalog', 'CREATE')
    AND NOT has_schema_privilege(runtime.oid, 'public', 'CREATE')
    AND has_schema_privilege(runtime.oid, 'data', 'USAGE')
    AND has_schema_privilege(runtime.oid, 'data', 'CREATE')
    AND pg_has_role(runtime.oid, 'geolens_reader', 'MEMBER')
    AND NOT EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'data'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
          AND relation.relowner <> runtime.oid
    )
) AS runtime_role_safe
FROM pg_roles AS runtime
WHERE runtime.rolname = :'runtime_role'
\gset

\if :runtime_role_safe
\else
    \echo 'ERROR: runtime database role reconciliation failed its least-privilege verification.'
    \quit 1
\endif
EOSQL

echo "Least-privilege PostgreSQL runtime role reconciled: ${runtime_role}"

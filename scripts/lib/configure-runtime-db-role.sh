#!/usr/bin/env bash
set -euo pipefail

# Canonical PostgreSQL role/grant reconciliation for fresh bootstrap,
# existing-install adoption, and post-restore ACL repair. This script runs
# *inside* the db container as POSTGRES_USER; the application never executes it.

runtime_role="${GEOLENS_RUNTIME_DB_ROLE:-}"
runtime_password="${GEOLENS_RUNTIME_DB_PASSWORD:-}"
db_user="${POSTGRES_USER:?POSTGRES_USER is required}"
db_name="${POSTGRES_DB:?POSTGRES_DB is required}"
migration_role="${GEOLENS_MIGRATION_DB_ROLE:-$db_user}"
adopt_existing="${GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING:-false}"

if [ -n "$runtime_role" ] \
    && [[ ! "$runtime_role" =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_ROLE must be a lowercase PostgreSQL identifier." >&2
    exit 64
fi
if [ "${#runtime_role}" -gt 63 ]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_ROLE must be at most 63 characters." >&2
    exit 64
fi

if [ -n "$runtime_role" ] && [ "$runtime_role" = "$db_user" ]; then
    echo "ERROR: GEOLENS_RUNTIME_DB_ROLE must differ from POSTGRES_USER; the privileged bootstrap/migration identity cannot be demoted." >&2
    exit 64
fi
case "$runtime_role" in
    postgres | pg_* \
        | geolens_reader | geolens_readonly | geolens_writer | geolens_tile \
        | geolens_tenant_control | geolens_tenant_provisioner \
        | geolens_tenant_sandbox | geolens_tenant_writer \
        | geolens_tile_gateway \
        | geolens_reader_t_* | geolens_writer_t_*)
        echo "ERROR: GEOLENS_RUNTIME_DB_ROLE uses a reserved PostgreSQL/GeoLens role name: ${runtime_role}." >&2
        exit 64
        ;;
esac

if [ -n "$runtime_role" ] \
    && [[ ! "$migration_role" =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "ERROR: GEOLENS_MIGRATION_DB_ROLE must be a lowercase PostgreSQL identifier." >&2
    exit 64
fi
if [ -n "$runtime_role" ] && [ "${#migration_role}" -gt 63 ]; then
    echo "ERROR: GEOLENS_MIGRATION_DB_ROLE must be at most 63 characters." >&2
    exit 64
fi
if [ -n "$runtime_role" ] && [ "$migration_role" = "$runtime_role" ]; then
    echo "ERROR: GEOLENS_MIGRATION_DB_ROLE must differ from GEOLENS_RUNTIME_DB_ROLE." >&2
    exit 64
fi
case "$adopt_existing" in
    true | false) ;;
    *)
        echo "ERROR: GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING must be true or false." >&2
        exit 64
        ;;
esac

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

-- PostgreSQL permits a CREATEROLE provider admin to create safe roles, but
-- only a superuser may mention SUPERUSER/BYPASSRLS in ALTER ROLE, even when
-- setting them to false. Verify those attributes before using the reduced
-- hardening statement on a non-superuser connection.
SELECT rolsuper AS reconciler_is_superuser
FROM pg_roles
WHERE rolname = current_user
\gset
SELECT rolsuper OR rolbypassrls OR rolcreatedb OR rolreplication
    AS reader_has_protected_attribute
FROM pg_roles
WHERE rolname = 'geolens_reader'
\gset
\if :reconciler_is_superuser
    ALTER ROLE geolens_reader
        NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
        NOREPLICATION NOBYPASSRLS;
\else
    \if :reader_has_protected_attribute
        DO $error$
        BEGIN
            RAISE EXCEPTION 'non-superuser reconciler cannot safely harden geolens_reader.';
        END
        $error$;
    \endif
    ALTER ROLE geolens_reader
        NOLOGIN NOCREATEROLE NOINHERIT;
\endif
GRANT USAGE ON SCHEMA data TO geolens_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA data
    GRANT SELECT ON TABLES TO geolens_reader;

-- Logical backups intentionally omit ACLs, which makes restored functions
-- regain PostgreSQL's default PUBLIC EXECUTE. Repair every privileged function
-- that may already exist before the legacy-mode early exit; absent functions
-- are expected on a fresh volume before Alembic runs.
SELECT 'REVOKE ALL ON FUNCTION catalog.provision_tenant_data_schema(uuid) FROM PUBLIC'
WHERE to_regprocedure('catalog.provision_tenant_data_schema(uuid)') IS NOT NULL
\gexec
SELECT 'REVOKE ALL ON FUNCTION catalog.deprovision_tenant_data_schema(uuid) FROM PUBLIC'
WHERE to_regprocedure('catalog.deprovision_tenant_data_schema(uuid)') IS NOT NULL
\gexec
SELECT 'GRANT EXECUTE ON FUNCTION catalog.provision_tenant_data_schema(uuid) TO geolens_tenant_control'
WHERE to_regprocedure('catalog.provision_tenant_data_schema(uuid)') IS NOT NULL
  AND EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_tenant_control')
\gexec
SELECT 'GRANT EXECUTE ON FUNCTION catalog.deprovision_tenant_data_schema(uuid) TO geolens_tenant_control'
WHERE to_regprocedure('catalog.deprovision_tenant_data_schema(uuid)') IS NOT NULL
  AND EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_tenant_control')
\gexec
SELECT 'REVOKE ALL ON FUNCTION catalog.geolens_rebuild_embedding_column(integer) FROM PUBLIC'
WHERE to_regprocedure('catalog.geolens_rebuild_embedding_column(integer)') IS NOT NULL
\gexec
EOSQL

if [ -z "$runtime_role" ]; then
    echo "GEOLENS_RUNTIME_DB_ROLE is unset; kept the legacy PostgreSQL runtime credential and reconciled geolens_reader only."
    exit 0
fi

# psql's \getenv reads exported variables only. Export the defaults resolved
# above so host-side reconciliation and bundled Compose use one SQL contract.
export GEOLENS_MIGRATION_DB_ROLE="$migration_role"
export GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING="$adopt_existing"

# Use psql's \getenv and format(%L) so the password never appears in argv or
# logs and is still quoted as data. The role identifier is likewise quoted via
# format(%I); the shell validation above adds a fail-closed operator contract.
psql "${psql_args[@]}" <<-'EOSQL'
\getenv runtime_role GEOLENS_RUNTIME_DB_ROLE
\getenv runtime_password GEOLENS_RUNTIME_DB_PASSWORD
\getenv migration_role GEOLENS_MIGRATION_DB_ROLE
\getenv adopt_existing GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING

-- Role comments and memberships are cluster-global. Keep all runtime-role
-- mutations in one transaction so an ownership/ACL failure cannot leave a
-- rotated password, rebound marker, or temporary SET membership behind.
BEGIN;

SELECT 'geolens-managed-runtime-role:v2:database=' || current_database()
    AS expected_runtime_marker
\gset

-- Default privileges are per object-creating role, not per database. Refuse a
-- misspelled or absent migration owner instead of silently attaching defaults
-- to the reconciliation/admin identity.
SELECT EXISTS (
    SELECT FROM pg_roles WHERE rolname = :'migration_role'
) AS migration_role_exists
\gset
\if :migration_role_exists
\else
    DO $error$
    BEGIN
        RAISE EXCEPTION 'GEOLENS_MIGRATION_DB_ROLE does not name an existing PostgreSQL role.';
    END
    $error$;
\endif

-- A role name is not ownership proof. Existing roles are left completely
-- untouched unless a privileged GeoLens reconciler previously marked them, or
-- the operator explicitly authorizes one safe, one-time adoption. The marker
-- binds this cluster-global role to one database name and is preserved by
-- pg_dumpall --globals-only.
SELECT EXISTS (
    SELECT FROM pg_roles WHERE rolname = :'runtime_role'
) AS runtime_role_exists
\gset

\if :runtime_role_exists
    SELECT
        COALESCE(shobj_description(runtime.oid, 'pg_authid'), '')
            = :'expected_runtime_marker' AS runtime_role_managed,
        COALESCE(shobj_description(runtime.oid, 'pg_authid'), '')
            LIKE 'geolens-managed-runtime-role:v2:database=%'
            AS runtime_role_has_scoped_marker,
        CASE
            WHEN COALESCE(shobj_description(runtime.oid, 'pg_authid'), '')
                    LIKE 'geolens-managed-runtime-role:v2:database=%'
            THEN EXISTS (
                SELECT 1
                FROM pg_database
                WHERE datname = substr(
                    shobj_description(runtime.oid, 'pg_authid'),
                    length('geolens-managed-runtime-role:v2:database=') + 1
                )
            )
            ELSE false
        END AS runtime_marker_database_exists
    FROM pg_roles AS runtime
    WHERE runtime.rolname = :'runtime_role'
    \gset

    \if :runtime_role_managed
    \else
        -- Never let a second live database claim a cluster-global role, even
        -- with the adoption escape hatch. A missing prior database models a
        -- rename or globals-backed restore and still requires explicit rebind.
        \if :runtime_role_has_scoped_marker
            \if :runtime_marker_database_exists
                DO $error$
                BEGIN
                    RAISE EXCEPTION 'runtime role is managed by another existing database.';
                END
                $error$;
            \endif
        \endif
        \if :adopt_existing
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
                    FROM pg_auth_members AS membership
                    JOIN pg_roles AS granted
                      ON granted.oid = membership.roleid
                    WHERE membership.member = runtime.oid
                      AND granted.rolname <> 'geolens_reader'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pg_database
                    WHERE datdba = runtime.oid
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pg_namespace
                    WHERE nspowner = runtime.oid
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE relation.relowner = runtime.oid
                      AND namespace.nspname <> 'data'
                      -- A data table's implicit TOAST table follows its owner.
                      -- PostgreSQL reserves pg_toast* namespaces from users.
                      AND namespace.nspname NOT LIKE 'pg_toast%'
                )
            ) AS runtime_role_adoptable
            FROM pg_roles AS runtime
            WHERE runtime.rolname = :'runtime_role'
            \gset

            \if :runtime_role_adoptable
                SELECT format(
                    'COMMENT ON ROLE %I IS %L',
                    :'runtime_role', :'expected_runtime_marker'
                )
                \gexec
            \else
                DO $error$
                BEGIN
                    RAISE EXCEPTION 'existing runtime role is not safe to adopt.';
                END
                $error$;
            \endif
        \else
            DO $error$
            BEGIN
                RAISE EXCEPTION 'existing runtime role is not marked as GeoLens-managed; set GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING=true only for a verified dedicated app role.';
            END
            $error$;
        \endif
    \endif
\else
    SELECT format(
        'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
        :'runtime_role', :'runtime_password'
    )
    \gexec
    SELECT format(
        'COMMENT ON ROLE %I IS %L',
        :'runtime_role', :'expected_runtime_marker'
    )
    \gexec
\endif

-- As above, a non-superuser CREATEROLE admin may alter a role it administers,
-- but cannot spell NOSUPERUSER/NOBYPASSRLS in ALTER ROLE. Refuse dangerous
-- attributes before changing the password, then use the permitted statement.
SELECT
    reconciler.rolsuper AS reconciler_is_superuser,
    runtime.rolsuper OR runtime.rolbypassrls
        OR runtime.rolcreatedb OR runtime.rolreplication
        AS runtime_has_protected_attribute
FROM pg_roles AS reconciler
CROSS JOIN pg_roles AS runtime
WHERE reconciler.rolname = current_user
  AND runtime.rolname = :'runtime_role'
\gset
\if :reconciler_is_superuser
    SELECT format(
        'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
        :'runtime_role', :'runtime_password'
    )\gexec
\else
    \if :runtime_has_protected_attribute
        DO $error$
        BEGIN
            RAISE EXCEPTION 'non-superuser reconciler cannot safely harden the runtime role.';
        END
        $error$;
    \endif
    SELECT format(
        'ALTER ROLE %I LOGIN NOCREATEROLE NOINHERIT PASSWORD %L',
        :'runtime_role', :'runtime_password'
    )\gexec
\endif

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

-- Future Alembic objects are owned by this privileged reconciliation/migration
-- identity. The runtime role receives DML/sequence rights, never DDL. Catalog
-- functions keep their migration-authored ACLs: blanket/default EXECUTE would
-- bypass the geolens_tenant_control boundary on SECURITY DEFINER functions.
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA catalog GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
    :'migration_role', :'runtime_role'
)\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA catalog GRANT USAGE, SELECT ON SEQUENCES TO %I',
    :'migration_role', :'runtime_role'
)\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA catalog REVOKE EXECUTE ON FUNCTIONS FROM %I',
    :'migration_role', :'runtime_role'
)\gexec

-- Reconcile installs that previously ran the broad EXECUTE recipe. On a fresh
-- volume these functions do not exist until Alembic runs, so the conditional
-- REVOKEs become no-ops and migrations install their control-only ACLs.
SELECT format(
    'REVOKE ALL ON FUNCTION catalog.provision_tenant_data_schema(uuid) FROM %I',
    :'runtime_role'
)
WHERE to_regprocedure('catalog.provision_tenant_data_schema(uuid)') IS NOT NULL
\gexec
SELECT format(
    'REVOKE ALL ON FUNCTION catalog.deprovision_tenant_data_schema(uuid) FROM %I',
    :'runtime_role'
)
WHERE to_regprocedure('catalog.deprovision_tenant_data_schema(uuid)') IS NOT NULL
\gexec

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
-- privilege to grant. ALTER OWNER also requires SET authority on the target
-- role. Temporarily add only that capability and restore the exact prior
-- membership shape before commit. PostgreSQL 18 gives a CREATEROLE creator an
-- ADMIN-only membership on roles it creates, normally granted by the session's
-- bootstrap identity. A separate current-user grant supplies SET during this
-- transaction and is revoked by that same grantor, leaving the durable ADMIN
-- authority untouched for future reconciliation. PostgreSQL 13-15 have one
-- membership row per role/member pair and no SET option; any direct membership
-- already permits SET ROLE, so use the portable legacy check there.
SELECT current_setting('server_version_num')::integer >= 160000
    AS membership_options_supported
\gset
\if :membership_options_supported
    SELECT
        pg_has_role(current_user, runtime.oid, 'SET')
            AS reconciler_can_set_runtime,
        EXISTS (
            SELECT 1
            FROM pg_auth_members AS membership
            WHERE membership.roleid = runtime.oid
              AND membership.member = reconciler.oid
              AND membership.grantor = reconciler.oid
        ) AS reconciler_has_self_granted_runtime_membership
    FROM pg_roles AS runtime
    CROSS JOIN pg_roles AS reconciler
    WHERE runtime.rolname = :'runtime_role'
      AND reconciler.rolname = current_user
    \gset
\else
    SELECT
        EXISTS (
            SELECT 1
            FROM pg_auth_members AS membership
            WHERE membership.roleid = runtime.oid
              AND membership.member = reconciler.oid
        ) AS reconciler_can_set_runtime,
        false AS reconciler_has_self_granted_runtime_membership
    FROM pg_roles AS runtime
    CROSS JOIN pg_roles AS reconciler
    WHERE runtime.rolname = :'runtime_role'
      AND reconciler.rolname = current_user
    \gset
\endif

\set revoke_temporary_runtime_membership false
\if :reconciler_can_set_runtime
\else
    \if :reconciler_has_self_granted_runtime_membership
        DO $error$
        BEGIN
            RAISE EXCEPTION 'existing current-grantor runtime membership is not SET-capable; refusing to overwrite its options.';
        END
        $error$;
    \else
        SELECT format('GRANT %I TO %I', :'runtime_role', current_user)\gexec
        \set revoke_temporary_runtime_membership true
    \endif
\endif

-- Transfer only data-schema runtime relations, never the migration-owned
-- catalog schema or its tables.
SELECT format('GRANT USAGE, CREATE ON SCHEMA data TO %I', :'runtime_role')\gexec
SELECT format(
    'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA data TO %I', :'runtime_role'
)\gexec
SELECT format('GRANT geolens_reader TO %I', :'runtime_role')\gexec
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

-- Ownership checks for the remaining relation grants run as the new owner,
-- not through INHERIT. RESET ROLE before revoking the temporary SET grant.
SELECT format('SET LOCAL ROLE %I', :'runtime_role')\gexec
SELECT format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA data TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA data TO %I',
    :'runtime_role'
)\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader',
    :'runtime_role'
)\gexec
RESET ROLE;

\if :revoke_temporary_runtime_membership
    \if :membership_options_supported
        SELECT format(
            'REVOKE %I FROM %I GRANTED BY %I',
            :'runtime_role', current_user, current_user
        )\gexec
    \else
        SELECT format('REVOKE %I FROM %I', :'runtime_role', current_user)\gexec
    \endif
\endif

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
    DO $error$
    BEGIN
        RAISE EXCEPTION 'runtime database role reconciliation failed its least-privilege verification.';
    END
    $error$;
\endif
COMMIT;
EOSQL

echo "Least-privilege PostgreSQL runtime role reconciled: ${runtime_role}"

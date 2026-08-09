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
EOSQL

if [ -z "$runtime_role" ]; then
    # In legacy mode the reconciliation login still owns data relations. In
    # split-runtime mode these grants must wait until the transactional block
    # transfers ownership; a non-superuser provider admin cannot grant across
    # an old runtime owner's objects during role rotation.
    psql "${psql_args[@]}" <<-'EOSQL'
BEGIN;

-- geolens_reader is cluster-global even when the application still uses the
-- legacy database login. Close the database boundary before granting reader
-- access so a split runtime from another database cannot connect and SET ROLE.
-- REVOKE FROM PUBLIC preserves every explicit per-login CONNECT grant.
SELECT format(
    'REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database()
)\gexec
SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I', current_database(), current_user
)\gexec

-- Logical backups intentionally omit ACLs, which makes restored functions
-- regain PostgreSQL's default PUBLIC EXECUTE. The legacy login remains the
-- privileged owner, so repair the functions before completing reconciliation.
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

GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA data
    GRANT SELECT ON TABLES TO geolens_reader;
COMMIT;
EOSQL
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

SELECT
    'geolens-managed-runtime-role:v2:database=' || current_database()
        AS expected_runtime_marker,
    'geolens-retired-runtime-role:v1:database=' || current_database()
        AS expected_retired_marker
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
            = :'expected_retired_marker' AS runtime_role_retired,
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
        \if :runtime_role_retired
            -- Selecting a retired role again is an explicit, marker-proven
            -- rollback. The normal hardening below re-enables LOGIN with the
            -- newly supplied password before retiring the current role.
            SELECT format(
                'COMMENT ON ROLE %I IS %L',
                :'runtime_role', :'expected_runtime_marker'
            )
            \gexec
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

-- geolens_reader is cluster-global, as are all PostgreSQL roles. Remove the
-- database default that would let another GeoLens database's runtime login
-- connect here and SET ROLE into this database's reader grants. Keep the
-- reconciler, actual migration owner, and this database's runtime admitted;
-- any additional service login needs its own explicit per-database grant.
SELECT format(
    'REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database()
)\gexec
SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I', current_database(), current_user
)\gexec
SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'migration_role'
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

-- Releases before this ownership contract created the embedding definer as the
-- reconciliation login. Adopt only the three known privileged functions when
-- that login still owns them; an unrelated owner remains a hard failure. This
-- also repairs --no-owner restores run by the same reconciliation identity.
SELECT format(
    'ALTER FUNCTION catalog.provision_tenant_data_schema(uuid) OWNER TO %I',
    :'migration_role'
)
WHERE to_regprocedure('catalog.provision_tenant_data_schema(uuid)') IS NOT NULL
  AND pg_get_userbyid(
      (SELECT proowner FROM pg_proc
       WHERE oid = to_regprocedure('catalog.provision_tenant_data_schema(uuid)'))
  ) = current_user
  AND current_user <> :'migration_role'
\gexec
SELECT format(
    'ALTER FUNCTION catalog.deprovision_tenant_data_schema(uuid) OWNER TO %I',
    :'migration_role'
)
WHERE to_regprocedure('catalog.deprovision_tenant_data_schema(uuid)') IS NOT NULL
  AND pg_get_userbyid(
      (SELECT proowner FROM pg_proc
       WHERE oid = to_regprocedure('catalog.deprovision_tenant_data_schema(uuid)'))
  ) = current_user
  AND current_user <> :'migration_role'
\gexec
SELECT format(
    'ALTER FUNCTION catalog.geolens_rebuild_embedding_column(integer) OWNER TO %I',
    :'migration_role'
)
WHERE to_regprocedure('catalog.geolens_rebuild_embedding_column(integer)') IS NOT NULL
  AND pg_get_userbyid(
      (SELECT proowner FROM pg_proc
       WHERE oid = to_regprocedure('catalog.geolens_rebuild_embedding_column(integer)'))
  ) = current_user
  AND current_user <> :'migration_role'
\gexec

-- The bounded definer must also own the one catalog relation it alters. A
-- --no-owner restore makes the restore login its owner; transfer only that
-- known DDL surface when the current reconciler can prove ownership.
SELECT format(
    'ALTER TABLE catalog.record_embeddings OWNER TO %I', :'migration_role'
)
WHERE to_regclass('catalog.record_embeddings') IS NOT NULL
  AND pg_get_userbyid(
      (SELECT relowner FROM pg_class
       WHERE oid = to_regclass('catalog.record_embeddings'))
  ) = current_user
  AND current_user <> :'migration_role'
\gexec

-- Restores may leave other catalog relations owned by the reconciliation
-- login while future Alembic relations belong to migration_role. Grant only
-- as each validated owner; any unrelated catalog owner fails closed.
SELECT NOT EXISTS (
    SELECT 1
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
    WHERE namespace.nspname = 'catalog'
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND owner_role.rolname NOT IN (current_user, :'migration_role')
) AS catalog_relation_owners_supported
\gset
\if :catalog_relation_owners_supported
\else
    DO $error$
    BEGIN
        RAISE EXCEPTION 'catalog relations include an owner other than the reconciler or GEOLENS_MIGRATION_DB_ROLE.';
    END
    $error$;
\endif

SELECT format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO %I',
    namespace.nspname, relation.relname, :'runtime_role'
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
WHERE namespace.nspname = 'catalog'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND owner_role.rolname = current_user
\gexec
SELECT format(
    'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO %I',
    namespace.nspname, relation.relname, :'runtime_role'
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
WHERE namespace.nspname = 'catalog'
  AND relation.relkind = 'S'
  AND owner_role.rolname = current_user
\gexec

-- Catalog grants and SECURITY DEFINER privileges must come from the actual
-- migration owner, not the login that happens to run reconciliation. SET LOCAL
-- proves the provider admin's authority without granting inherited access.
SELECT format('SET LOCAL ROLE %I', :'migration_role')\gexec

SELECT format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO %I',
    namespace.nspname, relation.relname, :'runtime_role'
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
WHERE namespace.nspname = 'catalog'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND owner_role.rolname = current_user
\gexec
SELECT format(
    'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO %I',
    namespace.nspname, relation.relname, :'runtime_role'
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
WHERE namespace.nspname = 'catalog'
  AND relation.relkind = 'S'
  AND owner_role.rolname = current_user
\gexec

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
RESET ROLE;

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

-- A role-name rotation must not leave the prior database-scoped login active.
-- Collect only this database's exact active markers; cluster-global roles for
-- other databases are deliberately out of scope. REASSIGN plus DROP OWNED
-- transfers every current-database object and removes direct/default ACLs.
-- All mutations remain inside the surrounding transaction, so a later failure
-- restores both the old role and the not-yet-admitted replacement atomically.
CREATE TEMP TABLE pg_temp.geolens_superseded_runtime_roles (
    role_name name PRIMARY KEY,
    revoke_temporary_membership boolean NOT NULL DEFAULT false
) ON COMMIT DROP;
INSERT INTO pg_temp.geolens_superseded_runtime_roles (role_name)
SELECT runtime.rolname
FROM pg_roles AS runtime
WHERE runtime.rolname <> :'runtime_role'
  AND COALESCE(shobj_description(runtime.oid, 'pg_authid'), '')
      = :'expected_runtime_marker';

\if :membership_options_supported
    SELECT EXISTS (
        SELECT 1
        FROM pg_temp.geolens_superseded_runtime_roles AS superseded
        JOIN pg_roles AS runtime ON runtime.rolname = superseded.role_name
        JOIN pg_roles AS reconciler ON reconciler.rolname = current_user
        JOIN pg_auth_members AS membership
          ON membership.roleid = runtime.oid
         AND membership.member = reconciler.oid
         AND membership.grantor = reconciler.oid
        WHERE NOT pg_has_role(current_user, runtime.oid, 'SET')
    ) AS superseded_has_conflicting_membership
    \gset
    \if :superseded_has_conflicting_membership
        DO $error$
        BEGIN
            RAISE EXCEPTION 'existing current-grantor superseded-role membership is not SET-capable; refusing to overwrite its options.';
        END
        $error$;
    \endif
    UPDATE pg_temp.geolens_superseded_runtime_roles AS superseded
    SET revoke_temporary_membership = true
    FROM pg_roles AS runtime
    WHERE runtime.rolname = superseded.role_name
      AND NOT pg_has_role(current_user, runtime.oid, 'SET');
\else
    UPDATE pg_temp.geolens_superseded_runtime_roles AS superseded
    SET revoke_temporary_membership = true
    FROM pg_roles AS runtime
    WHERE runtime.rolname = superseded.role_name
      AND NOT EXISTS (
          SELECT 1
          FROM pg_auth_members AS membership
          JOIN pg_roles AS reconciler ON reconciler.oid = membership.member
          WHERE membership.roleid = runtime.oid
            AND reconciler.rolname = current_user
      );
\endif

SELECT format('GRANT %I TO %I', superseded.role_name, current_user)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
WHERE superseded.revoke_temporary_membership
\gexec

-- DROP OWNED can revoke only ACL entries issued by the active grantor. Catalog
-- grants come from migration_role, so remove its direct and default grants
-- while SET to that owner before the reconciler performs the broad cleanup.
-- This prevents a retired login's already-open session retaining catalog DML.
SELECT format(
    'GRANT SELECT ON TABLE pg_temp.geolens_superseded_runtime_roles TO %I',
    :'migration_role'
)\gexec
SELECT format('SET LOCAL ROLE %I', :'migration_role')\gexec

SELECT format(
    'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I',
    namespace.nspname, relation.relname, superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
JOIN pg_roles AS retired ON retired.rolname = superseded.role_name
JOIN pg_class AS relation ON true
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
JOIN LATERAL aclexplode(relation.relacl) AS acl
  ON acl.grantee = retired.oid
WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND owner_role.rolname = current_user
\gexec
SELECT format(
    'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM %I',
    namespace.nspname, relation.relname, superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
JOIN pg_roles AS retired ON retired.rolname = superseded.role_name
JOIN pg_class AS relation ON relation.relkind = 'S'
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
JOIN LATERAL aclexplode(relation.relacl) AS acl
  ON acl.grantee = retired.oid
WHERE owner_role.rolname = current_user
\gexec
SELECT format(
    'REVOKE ALL PRIVILEGES ON FUNCTION %I.%I(%s) FROM %I',
    namespace.nspname,
    function.proname,
    pg_get_function_identity_arguments(function.oid),
    superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
JOIN pg_roles AS retired ON retired.rolname = superseded.role_name
JOIN pg_proc AS function ON true
JOIN pg_namespace AS namespace ON namespace.oid = function.pronamespace
JOIN pg_roles AS owner_role ON owner_role.oid = function.proowner
JOIN LATERAL aclexplode(function.proacl) AS acl
  ON acl.grantee = retired.oid
WHERE owner_role.rolname = current_user
\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL PRIVILEGES ON %s FROM %I',
    current_user,
    namespace.nspname,
    CASE defaults.defaclobjtype
        WHEN 'r' THEN 'TABLES'
        WHEN 'S' THEN 'SEQUENCES'
        WHEN 'f' THEN 'FUNCTIONS'
    END,
    superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
JOIN pg_roles AS retired ON retired.rolname = superseded.role_name
JOIN pg_default_acl AS defaults
  ON defaults.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user)
JOIN pg_namespace AS namespace ON namespace.oid = defaults.defaclnamespace
JOIN LATERAL aclexplode(defaults.defaclacl) AS acl
  ON acl.grantee = retired.oid
WHERE defaults.defaclobjtype IN ('r', 'S', 'f')
\gexec
RESET ROLE;

SELECT format(
    'REASSIGN OWNED BY %I TO %I', superseded.role_name, :'runtime_role'
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
\gexec
SELECT format('DROP OWNED BY %I', superseded.role_name)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
\gexec

-- Role memberships are cluster objects, so DROP OWNED does not remove them.
-- Revoke every capability held by the retired login, not only geolens_reader;
-- missing ADMIN authority fails and rolls the entire rotation back.
SELECT format(
    'REVOKE %I FROM %I', granted.rolname, superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
JOIN pg_roles AS retired ON retired.rolname = superseded.role_name
JOIN pg_auth_members AS membership ON membership.member = retired.oid
JOIN pg_roles AS granted ON granted.oid = membership.roleid
\gexec
SELECT format(
    'REVOKE CONNECT ON DATABASE %I FROM %I',
    current_database(), superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
\gexec
SELECT format(
    'ALTER ROLE %I NOLOGIN NOINHERIT', superseded.role_name
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
\gexec
SELECT format(
    'COMMENT ON ROLE %I IS %L',
    superseded.role_name, :'expected_retired_marker'
)
FROM pg_temp.geolens_superseded_runtime_roles AS superseded
\gexec

SELECT NOT EXISTS (
    SELECT 1
    FROM pg_temp.geolens_superseded_runtime_roles AS superseded
    JOIN pg_roles AS retired ON retired.rolname = superseded.role_name
    WHERE COALESCE(shobj_description(retired.oid, 'pg_authid'), '')
              <> :'expected_retired_marker'
       OR retired.rolcanlogin
       OR has_database_privilege(
           retired.oid, current_database(), 'CONNECT'
       )
       OR EXISTS (
           SELECT 1 FROM pg_auth_members AS membership
           WHERE membership.member = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_class AS relation
           WHERE relation.relowner = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_namespace AS namespace
           WHERE namespace.nspowner = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_proc AS function
           WHERE function.proowner = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_class AS relation
           JOIN LATERAL aclexplode(relation.relacl) AS acl ON true
           WHERE acl.grantee = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_attribute AS attribute
           JOIN LATERAL aclexplode(attribute.attacl) AS acl ON true
           WHERE acl.grantee = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_namespace AS namespace
           JOIN LATERAL aclexplode(namespace.nspacl) AS acl ON true
           WHERE acl.grantee = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_proc AS function
           JOIN LATERAL aclexplode(function.proacl) AS acl ON true
           WHERE acl.grantee = retired.oid
       )
       OR EXISTS (
           SELECT 1
           FROM pg_default_acl AS defaults
           LEFT JOIN LATERAL aclexplode(defaults.defaclacl) AS acl ON true
           WHERE defaults.defaclrole = retired.oid
              OR acl.grantee = retired.oid
       )
) AS superseded_roles_retired
\gset
\if :superseded_roles_retired
\else
    DO $error$
    BEGIN
        RAISE EXCEPTION 'superseded runtime role retirement failed its least-privilege verification.';
    END
    $error$;
\endif

-- Remove only memberships this transaction added. Provider-created ADMIN-only
-- memberships and any pre-existing SET authority retain their exact shape.
\if :membership_options_supported
    SELECT format(
        'REVOKE %I FROM %I GRANTED BY %I',
        superseded.role_name, current_user, current_user
    )
    FROM pg_temp.geolens_superseded_runtime_roles AS superseded
    WHERE superseded.revoke_temporary_membership
    \gexec
\else
    SELECT format(
        'REVOKE %I FROM %I', superseded.role_name, current_user
    )
    FROM pg_temp.geolens_superseded_runtime_roles AS superseded
    WHERE superseded.revoke_temporary_membership
    \gexec
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
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
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
    AND NOT EXISTS (
        SELECT 1
        FROM pg_database AS database
        CROSS JOIN LATERAL aclexplode(
            COALESCE(database.datacl, acldefault('d', database.datdba))
        ) AS database_acl
        WHERE database.datname = current_database()
          AND database_acl.grantee = 0
          AND database_acl.privilege_type = 'CONNECT'
    )
    AND has_database_privilege(current_user, current_database(), 'CONNECT')
    AND has_database_privilege(
        :'migration_role', current_database(), 'CONNECT'
    )
    AND has_database_privilege(runtime.oid, current_database(), 'CONNECT')
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

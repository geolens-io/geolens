#!/bin/bash
set -euo pipefail

db_host="${POSTGRES_HOST:-localhost}"
db_port="${POSTGRES_PORT:-5432}"
db_user="${POSTGRES_USER:-geolens}"
test_db="${POSTGRES_DB_TEST:-geolens_test}"

psql_base=(
  -v ON_ERROR_STOP=1
  --username "$db_user"
  --host "$db_host"
  --port "$db_port"
)

# Create the test database if it does not already exist.
psql "${psql_base[@]}" --dbname postgres --set test_db="$test_db" --set db_user="$db_user" <<-'EOSQL'
    SELECT format('CREATE DATABASE %I OWNER %I', :'test_db', :'db_user')
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'test_db')\gexec
EOSQL

psql "${psql_base[@]}" --dbname "$test_db" --set test_db="$test_db" <<-'EOSQL'
    -- Match the extensions and schema shape expected by the test suite and CI.
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS unaccent;

    CREATE SCHEMA IF NOT EXISTS catalog;
    CREATE SCHEMA IF NOT EXISTS data;

    SELECT format(
        'ALTER DATABASE %I SET search_path TO catalog, data, public',
        :'test_db'
    )\gexec

    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN
            CREATE ROLE geolens_reader NOLOGIN;
        END IF;
    END
    $$;
    GRANT USAGE ON SCHEMA data TO geolens_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
    ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader;

    -- Per-tenant schema + role for multi_tenant integration tests (Phase 1209).
    -- Schema names use underscore-encoded UUIDs to match tenant_data_schema() output.
    -- The single_tenant block above (data / geolens_reader) is unchanged.

    -- Tenant A: 00000000-0000-0000-0000-000000000001
    CREATE SCHEMA IF NOT EXISTS data_t_00000000_0000_0000_0000_000000000001;
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader_t_00000000_0000_0000_0000_000000000001') THEN
            CREATE ROLE geolens_reader_t_00000000_0000_0000_0000_000000000001 NOLOGIN;
        END IF;
    END
    $$;
    GRANT USAGE ON SCHEMA data_t_00000000_0000_0000_0000_000000000001
        TO geolens_reader_t_00000000_0000_0000_0000_000000000001;
    GRANT SELECT ON ALL TABLES IN SCHEMA data_t_00000000_0000_0000_0000_000000000001
        TO geolens_reader_t_00000000_0000_0000_0000_000000000001;
    ALTER DEFAULT PRIVILEGES IN SCHEMA data_t_00000000_0000_0000_0000_000000000001
        GRANT SELECT ON TABLES TO geolens_reader_t_00000000_0000_0000_0000_000000000001;

    -- Tenant B: 00000000-0000-0000-0000-000000000002 (cross-tenant isolation tests)
    CREATE SCHEMA IF NOT EXISTS data_t_00000000_0000_0000_0000_000000000002;
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader_t_00000000_0000_0000_0000_000000000002') THEN
            CREATE ROLE geolens_reader_t_00000000_0000_0000_0000_000000000002 NOLOGIN;
        END IF;
    END
    $$;
    GRANT USAGE ON SCHEMA data_t_00000000_0000_0000_0000_000000000002
        TO geolens_reader_t_00000000_0000_0000_0000_000000000002;
    GRANT SELECT ON ALL TABLES IN SCHEMA data_t_00000000_0000_0000_0000_000000000002
        TO geolens_reader_t_00000000_0000_0000_0000_000000000002;
    ALTER DEFAULT PRIVILEGES IN SCHEMA data_t_00000000_0000_0000_0000_000000000002
        GRANT SELECT ON TABLES TO geolens_reader_t_00000000_0000_0000_0000_000000000002;
EOSQL

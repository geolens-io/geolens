#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Extensions
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS vector;
    -- pg_stat_statements: query profiling (requires shared_preload_libraries).
    -- NOTE: If you have an existing pgdata volume, init-db.sh will NOT re-run.
    -- Run this manually: CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    CREATE EXTENSION IF NOT EXISTS unaccent;

    -- Schemas
    CREATE SCHEMA IF NOT EXISTS catalog;
    CREATE SCHEMA IF NOT EXISTS data;

    -- Read-only role for data schema access
    CREATE ROLE geolens_reader NOLOGIN;
    GRANT USAGE ON SCHEMA data TO geolens_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
    ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader;

EOSQL

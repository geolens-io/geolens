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

    -- Read-only role for data schema access.
    --
    -- DBM-12 (Phase 271): Both `GRANT SELECT ON ALL TABLES` and
    -- `ALTER DEFAULT PRIVILEGES` are kept because the runtime ingest role
    -- may differ from the role that ran init-db.sh in some deployment
    -- topologies. ALTER DEFAULT PRIVILEGES only fires for tables created
    -- by THIS role (the postgres superuser running init); the per-table
    -- `grant_reader_access` call in `backend/app/processing/ingest/metadata.py`
    -- covers the case where ingest creates tables under a different role.
    -- If a deployment confirms both roles are identical, the per-table call
    -- can be removed (and this comment updated).
    CREATE ROLE geolens_reader NOLOGIN;
    GRANT USAGE ON SCHEMA data TO geolens_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
    ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader;

EOSQL

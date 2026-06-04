#!/bin/bash
set -e

# The heredoc delimiter must be QUOTED ('EOSQL') so bash
# does NOT perform command substitution on the backticks (`...`) inside the
# SQL comments below. Prior to this fix, unquoted `<<-EOSQL` caused bash to
# try executing `GRANT SELECT ON ALL TABLES`, `grant_reader_access`, and
# `backend/app/processing/ingest/metadata.py` as shell commands, aborting
# the script with `set -e` BEFORE psql ever ran. The bug was latent because
# the live geolens-db container's pgdata volume is persistent (init-db.sh
# only runs once on a fresh volume), and the backtick comments were added
# AFTER that one-time init. This surfaced when the alembic-clean-db script
# (which builds a
# fresh DB on every run) finally exercised init-db.sh against a clean
# volume.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    -- Extensions
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS vector;
    -- pg_stat_statements: query profiling. This CREATE EXTENSION only runs on a
    -- FRESH pgdata volume -- init-db.sh is a Postgres docker-entrypoint init
    -- script and never re-runs against an existing volume (see header comment).
    --
    -- E-1 runbook -- adding pg_stat_statements to an EXISTING (pre-existing) volume:
    --   1. Ensure the library is preloaded. The bundled image sets this via
    --      db/postgresql.conf (shared_preload_libraries = 'pg_stat_statements').
    --      For an external/managed Postgres, set it in postgresql.conf (or the
    --      provider's parameter group), then RESTART the server -- this GUC
    --      cannot be changed at runtime:
    --        shared_preload_libraries = 'pg_stat_statements'
    --   2. After the restart, create the extension once:
    --        CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    --   Without step 1's preload, CREATE EXTENSION succeeds but the view stays
    --   empty / errors on query -- preload is mandatory for this extension.
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    CREATE EXTENSION IF NOT EXISTS unaccent;

    -- Schemas
    CREATE SCHEMA IF NOT EXISTS catalog;
    CREATE SCHEMA IF NOT EXISTS data;

    -- Read-only role for data schema access.
    --
    -- Both `GRANT SELECT ON ALL TABLES` and
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

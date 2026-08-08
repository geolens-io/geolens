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

EOSQL

# One canonical reconciliation path owns geolens_reader plus the opt-in
# GEOLENS_RUNTIME_DB_ROLE. It is mounted separately so restore.sh and an
# existing install can run the identical grants without replaying extensions.
bash /usr/local/bin/configure-runtime-db-role

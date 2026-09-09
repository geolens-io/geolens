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
# Runs both as the container's docker-entrypoint-initdb.d hook (local socket,
# no host/port set) and from a host against a managed database (POSTGRES_HOST
# etc. exported). Host/port args are added only when set, which is what keeps
# the in-container socket path working; same pattern as the role reconciler.
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

# fix(#1992): -X skips a host .psqlrc that could `\set ON_ERROR_STOP off` and
# let a failed statement below fall through, so the script exits 0 unfixed.
psql_args=(-X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")
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

psql "${psql_args[@]}" <<-'EOSQL'
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
    -- Optional, and guarded: IF NOT EXISTS only suppresses "already exists",
    -- so an unavailable extension still ERRORs and would abort this whole
    -- script under ON_ERROR_STOP=1 on a provider that does not ship it.
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_available_extensions
                   WHERE name = 'pg_stat_statements') THEN
            CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
        ELSE
            RAISE NOTICE 'pg_stat_statements unavailable; skipping (profiling only)';
        END IF;
    END $$;
    CREATE EXTENSION IF NOT EXISTS unaccent;

    -- Schemas
    CREATE SCHEMA IF NOT EXISTS catalog;
    CREATE SCHEMA IF NOT EXISTS data;

EOSQL

# One canonical reconciliation path owns geolens_reader plus the opt-in
# GEOLENS_RUNTIME_DB_ROLE. It is mounted separately so restore.sh and an
# existing install can run the identical grants without replaying extensions.
script_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -r "${script_dir}/lib/configure-runtime-db-role.sh" ]; then
    role_reconciler="${script_dir}/lib/configure-runtime-db-role.sh"
else
    role_reconciler=/usr/local/bin/configure-runtime-db-role
fi
bash "$role_reconciler"

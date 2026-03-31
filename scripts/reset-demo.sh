#!/usr/bin/env bash
# ==============================================================================
# reset-demo.sh — Periodic demo data reset
#
# Runs inside the reset service (docker-compose.demo.yml).
# On each cycle: drops user-created data, truncates audit logs, and resets
# sequences so the demo stays clean. The seeder service re-populates on
# next restart if needed.
#
# Environment:
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST
#   RESET_INTERVAL_HOURS (default: 24, set to 0 to run once and exit)
# ==============================================================================
set -euo pipefail

INTERVAL_HOURS="${RESET_INTERVAL_HOURS:-24}"
PGHOST="${POSTGRES_HOST:-db}"
PGUSER="${POSTGRES_USER:-geolens}"
PGDATABASE="${POSTGRES_DB:-geolens}"
PGPASSWORD="${POSTGRES_PASSWORD}"

run_reset() {
    echo "[$(date -Iseconds)] Starting demo data reset..."

    PGPASSWORD="${PGPASSWORD}" psql -h "${PGHOST}" -U "${PGUSER}" -d "${PGDATABASE}" -v ON_ERROR_STOP=1 <<'SQL'
-- Remove user-uploaded data (preserves schema and extensions)
DO $$
DECLARE
    tbl TEXT;
BEGIN
    -- Drop all tables in the data schema (user dataset tables)
    FOR tbl IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'data'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS data.%I CASCADE', tbl);
    END LOOP;
END $$;

-- Clear application tables but preserve structure
TRUNCATE TABLE catalog.datasets CASCADE;
TRUNCATE TABLE catalog.collections CASCADE;
TRUNCATE TABLE catalog.maps CASCADE;
TRUNCATE TABLE catalog.map_layers CASCADE;
TRUNCATE TABLE catalog.embed_tokens CASCADE;
TRUNCATE TABLE catalog.audit_log CASCADE;
TRUNCATE TABLE catalog.api_keys CASCADE;
TRUNCATE TABLE catalog.dataset_versions CASCADE;

-- Keep the admin user, remove others
DELETE FROM catalog.users WHERE username != 'admin';

-- Reset sequences
DO $$
DECLARE
    seq_name TEXT;
BEGIN
    FOR seq_name IN
        SELECT sequence_name FROM information_schema.sequences
        WHERE sequence_schema = 'catalog'
    LOOP
        EXECUTE format('ALTER SEQUENCE catalog.%I RESTART WITH 1', seq_name);
    END LOOP;
END $$;

SQL

    echo "[$(date -Iseconds)] Demo data reset complete."
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
echo "GeoLens Demo Reset Service"
echo "  Reset interval: ${INTERVAL_HOURS}h"
echo "  Database: ${PGUSER}@${PGHOST}/${PGDATABASE}"

if [ "${INTERVAL_HOURS}" -eq 0 ]; then
    run_reset
    exit 0
fi

# Sleep first, then reset — avoids racing with seeder on initial startup
while true; do
    echo "Next reset in ${INTERVAL_HOURS} hours..."
    sleep "$((INTERVAL_HOURS * 3600))"
    run_reset
done

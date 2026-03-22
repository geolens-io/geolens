#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Argument validation
if [ $# -ne 1 ]; then
    echo "Usage: $0 <backup-file>" >&2
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

# Validate backup integrity before restore
echo "Validating backup integrity..."
if ! docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    pg_restore --list - < "$BACKUP_FILE" > /dev/null 2>&1; then
    echo "ERROR: Backup file is corrupt or invalid: $BACKUP_FILE" >&2
    echo "pg_restore --list validation failed. Aborting restore." >&2
    exit 1
fi
echo "Backup validation passed."
echo ""

# Source .env if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration with defaults
POSTGRES_USER="${POSTGRES_USER:-geolens}"
POSTGRES_DB="${POSTGRES_DB:-geolens}"
echo "Running pre-restore setup..."

docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOSQL
-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Schemas
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS data;

-- Read-only role for data schema access
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN
        CREATE ROLE geolens_reader NOLOGIN;
    END IF;
END
\$\$;
GRANT USAGE ON SCHEMA data TO geolens_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_reader;

EOSQL

echo "Restoring from: $BACKUP_FILE"

docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner < "$BACKUP_FILE"

echo "Restore complete."

# ==============================================================================
# WAL Archiving (Optional PITR Upgrade)
# ==============================================================================
#
# For point-in-time recovery (PITR), WAL archiving enables restoring the
# database to any moment between backups. This is NOT configured by default.
#
# MANAGED DATABASES (recommended):
#   AWS RDS, Google Cloud SQL, and Azure Database for PostgreSQL provide
#   native automated backups with PITR. Enable via the provider's console:
#   - AWS RDS: Modify instance -> Backup -> Enable automated backups
#   - Cloud SQL: Edit instance -> Backups -> Enable PITR
#   - Azure: Server -> Backup -> Configure retention
#   No application changes required.
#
# SELF-HOSTED DOCKER (advanced):
#   Requires postgresql.conf modifications in the db container:
#     wal_level = replica
#     archive_mode = on
#     archive_command = 'test ! -f /wal_archive/%f && cp %p /wal_archive/%f'
#   Plus a volume mount for /wal_archive and a separate WAL shipping process.
#   Consider pgBackRest for production WAL management.
#
# See: https://www.postgresql.org/docs/17/continuous-archiving.html
# ==============================================================================

#!/usr/bin/env bash
set -euo pipefail

echo "[$(date -Iseconds)] Backup service starting..."

# Install curl (not present in postgis/postgis base image)
apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install supercronic (single static binary, ~5MB)
ARCH=$(dpkg --print-architecture)
SUPERCRONIC_URL="https://github.com/aptible/supercronic/releases/download/v0.2.43/supercronic-linux-${ARCH}"
echo "[$(date -Iseconds)] Installing supercronic for ${ARCH}..."
curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic
chmod +x /usr/local/bin/supercronic

# Install boto3 for S3 upload (if S3 enabled)
if [ "${BACKUP_S3_ENABLED:-false}" = "true" ]; then
    echo "[$(date -Iseconds)] Installing boto3 for S3 uploads..."
    pip3 install --quiet --break-system-packages "boto3>=1.35.0"
fi

# Generate crontab from BACKUP_SCHEDULE env var
SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"
echo "${SCHEDULE} /scripts/backup.sh" > /tmp/crontab

echo "[$(date -Iseconds)] Backup scheduler ready: '${SCHEDULE}'"
echo "[$(date -Iseconds)] Retention: ${BACKUP_RETENTION_DAILY:-7} daily, ${BACKUP_RETENTION_WEEKLY:-4} weekly"
echo "[$(date -Iseconds)] S3 upload: ${BACKUP_S3_ENABLED:-false}"

# exec so supercronic becomes PID 1 (receives SIGTERM correctly)
exec supercronic /tmp/crontab

#!/bin/sh
# BUG-015 (Phase 1184): Extracted from docker-compose.yml minio-setup entrypoint.
#
# Previously the entrypoint used a YAML `>` (folded scalar) which collapses
# every newline into a space — the heredoc marker (CORSJSON) never appeared on
# its own line, so `cat << 'CORSJSON' ... CORSJSON` was never terminated and
# the CORS/anon policy was never applied.
#
# Mounting this file and using it as the entrypoint avoids the YAML scalar
# issue entirely, and lets `bash -n scripts/minio-setup.sh` catch syntax errors.
#
# Environment variables (passed via docker-compose.yml environment:):
#   MINIO_ROOT_USER      MinIO root user  (fail-closed via :? in docker-compose.yml)
#   MINIO_ROOT_PASSWORD  MinIO root password
#
# Note: this script runs inside the MinIO mc image (Alpine/busybox sh), not bash.
# Use POSIX sh syntax only.

set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing local/geolens

# Write the CORS policy to a temp file using a heredoc.
# The heredoc is safe here because this is a real script file, not an
# inline YAML scalar — newlines are preserved verbatim.
cat > /tmp/cors.json << 'CORSJSON'
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3600
    }
  ]
}
CORSJSON

mc anonymous set-json /tmp/cors.json local/geolens || true
exit 0

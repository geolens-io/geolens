#!/bin/sh
# Creates the geolens bucket on the cloud-dev MinIO. It is a mounted script
# because a YAML folded scalar collapses the heredoc below into one line.
#
# Environment variables (passed via docker-compose.yml environment:):
#   MINIO_ROOT_USER      MinIO root user
#   MINIO_ROOT_PASSWORD  MinIO root password
# The minio service entrypoint refuses to start when either is blank.
#
# Note: this script runs under /bin/sh inside the mc image, not necessarily bash.
# Use POSIX sh syntax only.

set -eu

# The image's /root is read-only and the container drops every capability, so
# root cannot create mc's default config directory there.
MC_CONFIG_DIR=/tmp/.mc
export MC_CONFIG_DIR

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

# ops(#1211): deliberately NO `mc ilm` rule here for aborting abandoned
# multipart uploads. mc has no abort-incomplete-multipart flag (verified
# against the pinned RELEASE.2026-09-16T00-00-00Z image), and MinIO strips
# AbortIncompleteMultipartUpload from imported lifecycle JSON
# (minio/minio#19115, closed "working as intended"). The cleanup is
# server-side instead: MINIO_API_STALE_UPLOADS_EXPIRY on the minio service
# in docker-compose*.yml. See RUNBOOK.md "Abandoned multipart uploads".
exit 0

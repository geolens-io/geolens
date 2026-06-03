#!/bin/sh
set -e

# Generate runtime config from environment variables.
# Explicit variable list avoids clobbering nginx variables like $uri.
envsubst '$API_BASE_URL $TILE_BASE_URL' \
  < /usr/share/nginx/html/env-config.template.js \
  > /usr/share/nginx/html/env-config.js

# Replace shell with nginx (PID 1).
exec nginx -g 'daemon off;'

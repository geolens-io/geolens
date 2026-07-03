#!/bin/sh
set -e

# Generate runtime config from environment variables.
# Explicit variable list avoids clobbering nginx variables like $uri.
envsubst '$API_BASE_URL $TILE_BASE_URL' \
  < /usr/share/nginx/html/env-config.template.js \
  > /usr/share/nginx/html/env-config.js

# Social scrapers (LinkedIn notably) don't resolve a relative og:image URL.
# Absolutize it when the operator set PUBLIC_APP_URL; unset leaves it relative.
if [ -n "${PUBLIC_APP_URL:-}" ]; then
  sed -i "s|content=\"/og-image.png\"|content=\"${PUBLIC_APP_URL%/}/og-image.png\"|" \
    /usr/share/nginx/html/index.html
fi

# Replace shell with nginx (PID 1).
exec nginx -g 'daemon off;'

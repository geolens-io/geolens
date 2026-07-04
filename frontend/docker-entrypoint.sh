#!/bin/sh
set -e

# Generate runtime config from environment variables.
# Explicit variable list avoids clobbering nginx variables like $uri.
envsubst '$API_BASE_URL $TILE_BASE_URL' \
  < /usr/share/nginx/html/env-config.template.js \
  > /usr/share/nginx/html/env-config.js

# Social scrapers (LinkedIn notably) don't resolve a relative og:image URL.
# Absolutize it when the operator set PUBLIC_APP_URL; unset leaves it relative.
# Truncate-write via /tmp: the html dir is root-owned (only its files are
# nginx-owned), so in-place tools like sed -i can't create their temp file there.
if [ -n "${PUBLIC_APP_URL:-}" ]; then
  html=/usr/share/nginx/html/index.html
  sed "s|content=\"/og-image.png\"|content=\"${PUBLIC_APP_URL%/}/og-image.png\"|" \
    "$html" > /tmp/index.html.new
  cat /tmp/index.html.new > "$html"
  rm -f /tmp/index.html.new
fi

# Replace shell with nginx (PID 1).
exec nginx -g 'daemon off;'

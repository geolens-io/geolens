#!/bin/sh
set -e

# Materialize the immutable SPA in a writable tmpfs. Production mounts /tmp as
# tmpfs while keeping the image root filesystem read-only.
runtime_html=/tmp/geolens-html
rm -rf "$runtime_html"
mkdir -p "$runtime_html"
cp -R /opt/geolens/html/. "$runtime_html/"

# Generate runtime config from environment variables. The explicit variable
# list avoids clobbering nginx variables like $uri.
envsubst '$API_BASE_URL $TILE_BASE_URL' \
  < "$runtime_html/env-config.template.js" \
  > "$runtime_html/env-config.js"

# Social scrapers (LinkedIn notably) don't resolve a relative og:image URL.
# Absolutize it when the operator set PUBLIC_APP_URL; unset leaves it relative.
if [ -n "${PUBLIC_APP_URL:-}" ]; then
  html="$runtime_html/index.html"
  sed "s|content=\"/og-image.png\"|content=\"${PUBLIC_APP_URL%/}/og-image.png\"|" \
    "$html" > /tmp/index.html.new
  cat /tmp/index.html.new > "$html"
  rm -f /tmp/index.html.new
fi

# Replace shell with nginx (PID 1).
exec nginx -g 'daemon off;'

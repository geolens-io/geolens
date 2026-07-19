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

# Render the nginx vhost from its template (see the TEMPLATE header in
# frontend/nginx.conf). API_UPSTREAM points the /api, raster-tile, and embed
# proxy blocks at the API service; NGINX_RESOLVER is the DNS server nginx uses
# to re-resolve that hostname. The resolver default reads the container's own
# /etc/resolv.conf nameserver (127.0.0.11 under Docker, cluster DNS on
# Kubernetes) and needs no configuration anywhere. The upstream default
# (http://api:8000) is compose-only: nginx's resolver does not apply
# resolv.conf search domains, so on Kubernetes API_UPSTREAM must be set to
# the api Service's fully qualified name
# (e.g. http://geolens-api.<namespace>.svc.cluster.local:8000) — a short
# service name will NXDOMAIN. The Helm chart passes exactly that.
API_UPSTREAM="${API_UPSTREAM:-http://api:8000}"
# Codex P2 (#577): strip trailing slashes — a URI component in a variable
# proxy_pass replaces the rewritten request URI wholesale, so a value like
# http://api:8000/ would proxy every /api, raster, and embed request to "/".
while [ "${API_UPSTREAM%/}" != "$API_UPSTREAM" ]; do
  API_UPSTREAM="${API_UPSTREAM%/}"
done
if [ -z "${NGINX_RESOLVER:-}" ]; then
  NGINX_RESOLVER="$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf 2>/dev/null || true)"
fi
NGINX_RESOLVER="${NGINX_RESOLVER:-127.0.0.11}"
case "$NGINX_RESOLVER" in
  \[*) ;;
  *:*:*) NGINX_RESOLVER="[$NGINX_RESOLVER]" ;;  # bare IPv6 nameserver → nginx bracket syntax
esac
export API_UPSTREAM NGINX_RESOLVER
mkdir -p /tmp/geolens-nginx
envsubst '$API_UPSTREAM $NGINX_RESOLVER' \
  < /opt/geolens/default.conf.template \
  > /tmp/geolens-nginx/default.conf

# Replace shell with nginx (PID 1).
exec nginx -g 'daemon off;'

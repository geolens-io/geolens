#!/bin/sh
set -e

# /app/node_modules is an anonymous volume that outlives image rebuilds, so a
# source upgrade would otherwise keep serving the previous release's
# dependencies. Reinstall whenever package-lock.json differs from the lockfile
# the volume was last installed from.
stamp=node_modules/.package-lock.sha256
want="$(sha256sum package-lock.json | cut -d' ' -f1)"
have="$(cat "$stamp" 2>/dev/null || true)"

if [ "$want" != "$have" ]; then
  echo "package-lock.json changed since node_modules was installed; running npm ci" >&2
  # node_modules is a mount point and cannot be removed itself.
  find node_modules -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  npm ci --prefer-offline
  printf '%s\n' "$want" > "$stamp"
fi

exec "$@"

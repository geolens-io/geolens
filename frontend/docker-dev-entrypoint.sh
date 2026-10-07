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
  echo "package-lock.json changed since node_modules was installed; resyncing" >&2
  # node_modules is a mount point and cannot be removed itself.
  find node_modules -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  # The image carries the dependencies it was built with, which works offline.
  baked="${BAKED_NODE_MODULES:-/opt/geolens-node_modules}"
  if [ "$(cat "$baked/.package-lock.sha256" 2>/dev/null || true)" = "$want" ]; then
    find "$baked" -mindepth 1 -maxdepth 1 ! -name .package-lock.sha256 -exec cp -a {} node_modules/ \;
  else
    npm ci --prefer-offline
  fi
  # The stamp marks a completed sync, so it is written last.
  printf '%s\n' "$want" > "$stamp"
fi

exec "$@"

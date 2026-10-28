#!/bin/sh
# Regression test: a release install must enable the bundled Valkey so
# token-protected service imports have the shared credential store they need,
# without clobbering an operator's own REDIS_URL, password or profiles.
set -eu

INSTALL_SH="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/install.sh"
[ -f "$INSTALL_SH" ] || { echo "FAIL: cannot find install.sh at $INSTALL_SH"; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

fns="$work/fns.sh"
for fn in generate_jwt_secret get_env_value update_env_value enable_bundled_cache; do
  awk -v fn="$fn" '$0 ~ "^" fn "\\(\\) \\{" {f=1} f{print} f&&/^}/{exit}' "$INSTALL_SH" >>"$fns"
done
fail() { echo "FAIL: $*" >&2; exit 1; }
# shellcheck disable=SC1090
. "$fns"

: >.env
enable_bundled_cache
pw="$(get_env_value VALKEY_PASSWORD)"
[ -n "$pw" ] || fail "no VALKEY_PASSWORD generated"
[ "$(get_env_value REDIS_URL)" = "redis://:${pw}@valkey:6379/0" ] || fail "REDIS_URL not built from the password"
[ "$(get_env_value COMPOSE_PROFILES)" = "cache" ] || fail "cache profile not enabled"
printf '%s' "$pw" | grep -Eq '^[A-Za-z0-9._~-]+$' || fail "password outside valkey's allowed charset"

enable_bundled_cache
[ "$(get_env_value VALKEY_PASSWORD)" = "$pw" ] || fail "rerun changed the password"
[ "$(get_env_value COMPOSE_PROFILES)" = "cache" ] || fail "rerun duplicated the profile"

printf 'REDIS_URL=redis://own:6379/1\nCOMPOSE_PROFILES=backup\n' >.env
enable_bundled_cache
[ "$(get_env_value REDIS_URL)" = "redis://own:6379/1" ] || fail "operator REDIS_URL overwritten"
[ "$(get_env_value COMPOSE_PROFILES)" = "backup,cache" ] || fail "profiles not appended"
[ -z "$(get_env_value VALKEY_PASSWORD)" ] || fail "password generated for an external REDIS_URL"

printf 'VALKEY_PASSWORD="quoted.pw-1"\n' >.env
enable_bundled_cache
[ "$(get_env_value REDIS_URL)" = "redis://:quoted.pw-1@valkey:6379/0" ] || fail "quoted password leaked quotes into REDIS_URL"

grep -q 'enable_bundled_cache$' "$INSTALL_SH" || fail "install.sh never calls enable_bundled_cache"

grep -q 'cleared REDIS_URL' "$INSTALL_SH" || fail "source-build fallback does not clear the bundled REDIS_URL"

echo "PASS: install.sh enables the bundled cache"

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
for fn in generate_jwt_secret get_env_value update_env_value get_env_value_decoded enable_bundled_cache drop_bundled_cache_url; do
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
[ -z "$(get_env_value VALKEY_PASSWORD)" ] || fail "password generated for an external REDIS_URL"
[ "$(get_env_value COMPOSE_PROFILES)" = "backup" ] || fail "cache profile enabled for an external REDIS_URL"

printf 'REDIS_URL=""\nCOMPOSE_PROFILES=backup\n' >.env
enable_bundled_cache
[ "$(get_env_value COMPOSE_PROFILES)" = "backup,cache" ] || fail "profiles not appended"
case "$(get_env_value REDIS_URL)" in redis://:*@valkey:6379/0) ;; *) fail "quoted-empty REDIS_URL treated as set" ;; esac

printf 'VALKEY_PASSWORD="quoted.pw-1"\n' >.env
enable_bundled_cache
[ "$(get_env_value REDIS_URL)" = "redis://:quoted.pw-1@valkey:6379/0" ] || fail "quoted password leaked quotes into REDIS_URL"

grep -q 'enable_bundled_cache$' "$INSTALL_SH" || fail "install.sh never calls enable_bundled_cache"

warn() { :; }
printf 'REDIS_URL=redis://:pw@valkey:6379/0\nVALKEY_PASSWORD=pw\nCOMPOSE_PROFILES=cache\n' >.env
drop_bundled_cache_url
[ -z "$(get_env_value REDIS_URL)" ] || fail "bundled REDIS_URL not cleared"
[ "$(get_env_value VALKEY_PASSWORD)" = "pw" ] || fail "VALKEY_PASSWORD not kept"
[ "$(get_env_value COMPOSE_PROFILES)" = "cache" ] || fail "COMPOSE_PROFILES not kept"
printf 'REDIS_URL=redis://own:6379/1\n' >.env
drop_bundled_cache_url
[ "$(get_env_value REDIS_URL)" = "redis://own:6379/1" ] || fail "operator REDIS_URL cleared"
grep -q 'drop_bundled_cache_url$' "$INSTALL_SH" || fail "install.sh never calls drop_bundled_cache_url"

echo "PASS: install.sh enables the bundled cache"

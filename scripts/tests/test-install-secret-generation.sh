#!/bin/sh
# Regression test: the installer must not ship or default
# to weak credentials. Verifies that generate_password() produces a strong,
# class-diverse value and that install.sh generates POSTGRES_PASSWORD and the
# admin password instead of keeping the public defaults `geolens` / `admin`.
set -eu

INSTALL_SH="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/install.sh"
[ -f "$INSTALL_SH" ] || { echo "FAIL: cannot find install.sh at $INSTALL_SH"; exit 1; }

# --- behavioral: extract and exercise generate_password() in isolation ---------
fns="$(mktemp)"
# Extract from generate_jwt_secret() up to (but not including) check_port().
awk '/^generate_jwt_secret\(\) \{/{f=1} /^check_port\(\) \{/{f=0} f{print}' \
  "$INSTALL_SH" >"$fns"
fail() { echo "$*" >&2; exit 1; }  # stub the helper the functions may call
# shellcheck disable=SC1090
. "$fns"
rm -f "$fns"

pw="$(generate_password)"
[ "${#pw}" -ge 16 ] || { echo "FAIL: generated password too short (${#pw})"; exit 1; }
[ "$pw" != "admin" ] || { echo "FAIL: generated password is 'admin'"; exit 1; }
[ "$pw" != "geolens" ] || { echo "FAIL: generated password is 'geolens'"; exit 1; }
printf '%s' "$pw" | grep -q '[a-z]' || { echo "FAIL: no lowercase in password"; exit 1; }
printf '%s' "$pw" | grep -q '[A-Z]' || { echo "FAIL: no uppercase in password"; exit 1; }
printf '%s' "$pw" | grep -q '[0-9]' || { echo "FAIL: no digit in password"; exit 1; }
printf '%s' "$pw" | grep -q '[^A-Za-z0-9]' || { echo "FAIL: no symbol in password"; exit 1; }
# .env / connection-string safety: must not contain = $ " ' @ : / or whitespace.
case "$pw" in
  *=* | *'$'* | *'"'* | *"'"* | *@* | *:* | */* | *' '*)
    echo "FAIL: generated password contains an unsafe character"; exit 1 ;;
esac

# --- structural: install.sh no longer defaults to weak credentials -------------
if grep -q "prompt_value 'Admin password' 'admin'" "$INSTALL_SH"; then
  echo "FAIL: install.sh still defaults the admin password to 'admin' (SEC-011)"; exit 1
fi
grep -q 'Generated POSTGRES_PASSWORD' "$INSTALL_SH" \
  || { echo "FAIL: install.sh does not generate POSTGRES_PASSWORD (SEC-010)"; exit 1; }
grep -q 'generated_admin_pw=true' "$INSTALL_SH" \
  || { echo "FAIL: install.sh does not generate an admin password (SEC-011)"; exit 1; }

# --- behavioral: POSTGRES_PASSWORD on a pre-copied or re-used .env ------------
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
pgfns="$work/pgfns.sh"
for fn in generate_jwt_secret generate_password get_env_value get_env_value_decoded update_env_value compose_project_name pgdata_volume_exists ensure_postgres_password; do
  awk -v fn="$fn" '$0 ~ "^" fn "\\(\\) \\{" {f=1} f{print} f&&/^}/{exit}' "$INSTALL_SH" >>"$pgfns"
done
say() { :; }
warn() { :; }
# shellcheck disable=SC1090
. "$pgfns"
mkdir "$work/My Install"
cd "$work/My Install"

# Stub: STUB_VOLUME=1 reports a pgdata volume, STUB_DOCKER_FAIL=1 fails the call.
docker() {
  printf '%s\n' "$*" >"$work/docker-args"
  [ "${STUB_DOCKER_FAIL:-0}" = 1 ] && return 1
  [ "${STUB_VOLUME:-0}" = 1 ] && echo myinstall_pgdata
  return 0
}

# run_ensure ENV_CREATED STUB_VOLUME STUB_DOCKER_FAIL: runs ensure_postgres_password
# in a subshell, so a fail() exit is its rc 1 and no stub setting leaks out.
run_ensure() {
  (
    unset POSTGRES_PASSWORD
    ENV_CREATED="$1" STUB_VOLUME="$2" STUB_DOCKER_FAIL="$3"
    ensure_postgres_password
  ) 2>/dev/null
}
pg_value() { get_env_value_decoded POSTGRES_PASSWORD; }

for line in 'POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD=""' "POSTGRES_PASSWORD=''" ''; do
  printf 'POSTGRES_USER=geolens\n%s\n' "$line" >.env
  run_ensure false 0 0 || { echo "FAIL: [$line] with no volume stopped the install"; exit 1; }
  v="$(pg_value)"
  [ -n "$v" ] && [ "$v" != geolens ] || { echo "FAIL: [$line] with no volume did not generate a password"; exit 1; }
  [ "$(grep -c '^POSTGRES_PASSWORD=' .env)" = 1 ] || { echo "FAIL: [$line] left more than one POSTGRES_PASSWORD line"; exit 1; }
done
grep -q 'label=com.docker.compose.project=myinstall' "$work/docker-args" \
  || { echo "FAIL: volume lookup did not use the normalized project name"; exit 1; }

printf 'POSTGRES_PASSWORD=\n' >.env
run_ensure false 1 0 && { echo "FAIL: empty value with an existing volume did not stop"; exit 1; }
[ -z "$(pg_value)" ] || { echo "FAIL: empty value with an existing volume was replaced"; exit 1; }

run_ensure false 0 1 && { echo "FAIL: a failed volume lookup did not stop"; exit 1; }
[ -z "$(pg_value)" ] || { echo "FAIL: a failed volume lookup still generated a password"; exit 1; }

( POSTGRES_PASSWORD=from-shell; export POSTGRES_PASSWORD; ensure_postgres_password ) \
  || { echo "FAIL: a value exported in the shell stopped the install"; exit 1; }
[ -z "$(pg_value)" ] || { echo "FAIL: .env was written although the shell value wins"; exit 1; }
( POSTGRES_PASSWORD=; export POSTGRES_PASSWORD; ensure_postgres_password ) 2>/dev/null \
  && { echo "FAIL: an empty value exported in the shell did not stop"; exit 1; }

printf 'POSTGRES_PASSWORD=kept-value\n' >.env
run_ensure false 0 0 && [ "$(pg_value)" = kept-value ] || { echo "FAIL: a set value was rotated"; exit 1; }

printf 'POSTGRES_PASSWORD=geolens\n' >.env
run_ensure false 0 0 && [ "$(pg_value)" = geolens ] || { echo "FAIL: an existing .env's default was rotated"; exit 1; }
run_ensure true 1 0 && [ "$(pg_value)" = geolens ] \
  || { echo "FAIL: the default was rotated although a database volume exists"; exit 1; }
run_ensure true 0 0 && [ "$(pg_value)" != geolens ] \
  || { echo "FAIL: a .env created this run kept the default"; exit 1; }

echo "PASS: install.sh secret generation (SEC-010 / SEC-011)"

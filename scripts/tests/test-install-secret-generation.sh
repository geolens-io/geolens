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
# Invariant: the installer never writes POSTGRES_PASSWORD when .env resolves it
# (as Compose does) to a non-empty value, and generates one only when it can
# show the project Compose will use has no database volume.
work="$(mktemp -d)"
real_volume=""
cleanup() {
  [ -z "$real_volume" ] || command docker volume rm "$real_volume" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
pgfns="$work/pgfns.sh"
for fn in generate_jwt_secret generate_password get_env_value get_env_value_decoded compose compose_env_value pgdata_volume_exists replace_env_key ensure_postgres_password; do
  awk -v fn="$fn" '$0 ~ "^" fn "\\(\\) \\{" {f=1} f{print} f&&/^}/{exit}' "$INSTALL_SH" >>"$pgfns"
done
say() { :; }
warn() { :; }
COMPOSE_FILE=docker-compose.yml
# shellcheck disable=SC1090
. "$pgfns"
proj="$work/My Install"
mkdir -p "$proj/scripts/lib"
cp "$(dirname "$INSTALL_SH")/lib/common.sh" "$proj/scripts/lib/common.sh"
cd "$proj"

# Stub: STUB_VOLUME=1 lists a pgdata volume, STUB_DOCKER_FAIL=1 fails the call.
docker() {
  [ "${STUB_DOCKER_FAIL:-0}" = 1 ] && return 1
  [ "${STUB_VOLUME:-0}" = 1 ] && echo 'com.docker.compose.project=myinstall,com.docker.compose.volume=pgdata'
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
pg_value() { v="$(compose_env_value POSTGRES_PASSWORD)" && printf '%s' "${v%x}"; }
pg_lines() { grep -cE "^[ $(printf '\t')]*(export[ $(printf '\t')]+)?POSTGRES_PASSWORD[ $(printf '\t')]*=" .env || true; }

# Each spelling that resolves empty is generated into exactly one line.
for body in 'POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD=""' "POSTGRES_PASSWORD=''" '' \
  'export POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD = ' '  POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD=\r' \
  'POSTGRES_PASSWORD=${UNSET_IN_THIS_TEST}'; do
  printf "POSTGRES_USER=geolens\\n$body\\n" >.env
  run_ensure false 0 0 || { echo "FAIL: [$body] with no volume stopped the install"; exit 1; }
  v="$(pg_value)"
  [ -n "$v" ] && [ "$v" != geolens ] || { echo "FAIL: [$body] with no volume did not generate a password"; exit 1; }
  [ "$(pg_lines)" = 1 ] || { echo "FAIL: [$body] left $(pg_lines) POSTGRES_PASSWORD lines"; exit 1; }
done

# Each spelling that resolves to a value is left byte-for-byte alone, even
# where a naive first-match reader would see it as empty or absent.
for body in 'export POSTGRES_PASSWORD=existing' 'POSTGRES_PASSWORD = existing' \
  'POSTGRES_PASSWORD=\nPOSTGRES_PASSWORD=existing' 'POSTGRES_PASSWORD=existing\r' \
  'POSTGRES_PASSWORD= # set me' 'OTHER_PW=abc\nPOSTGRES_PASSWORD=${OTHER_PW}'; do
  printf "POSTGRES_USER=geolens\\n$body\\n" >.env
  cp .env "$work/before"
  run_ensure false 1 0 || { echo "FAIL: [$body] stopped the install"; exit 1; }
  cmp -s .env "$work/before" || { echo "FAIL: [$body] was rewritten"; exit 1; }
done

printf 'POSTGRES_PASSWORD=\n' >.env
run_ensure false 1 0 && { echo "FAIL: empty value with an existing volume did not stop"; exit 1; }
[ -z "$(pg_value)" ] || { echo "FAIL: empty value with an existing volume was replaced"; exit 1; }
run_ensure false 0 1 && { echo "FAIL: a failed volume lookup did not stop"; exit 1; }
[ -z "$(pg_value)" ] || { echo "FAIL: a failed volume lookup still generated a password"; exit 1; }

printf 'POSTGRES_PASSWORD=existing\nPOSTGRES_PASSWORD=\n' >.env
run_ensure false 0 0 && { echo "FAIL: two lines for the key did not stop"; exit 1; }
printf 'POSTGRES_PASSWORD="unterminated\n' >.env
cp .env "$work/before"
run_ensure false 0 0 && { echo "FAIL: an unreadable line did not stop"; exit 1; }
cmp -s .env "$work/before" || { echo "FAIL: an unreadable line was rewritten"; exit 1; }

printf 'POSTGRES_PASSWORD=\n' >.env
( POSTGRES_PASSWORD=from-shell; export POSTGRES_PASSWORD; ensure_postgres_password ) \
  || { echo "FAIL: a value exported in the shell stopped the install"; exit 1; }
[ -z "$(pg_value)" ] || { echo "FAIL: .env was written although the shell value wins"; exit 1; }
( POSTGRES_PASSWORD=; export POSTGRES_PASSWORD; ensure_postgres_password ) 2>/dev/null \
  && { echo "FAIL: an empty value exported in the shell did not stop"; exit 1; }

printf 'POSTGRES_PASSWORD=geolens\n' >.env
run_ensure false 0 0 && [ "$(pg_value)" = geolens ] || { echo "FAIL: an existing .env's default was rotated"; exit 1; }
run_ensure true 1 0 && [ "$(pg_value)" = geolens ] \
  || { echo "FAIL: the default was rotated although a database volume exists"; exit 1; }
run_ensure true 0 0 && [ "$(pg_value)" != geolens ] \
  || { echo "FAIL: a .env created this run kept the default"; exit 1; }

# A checkout without the Compose-compatible reader leaves an existing .env
# alone and reads only a .env this run copied from the template.
mv scripts/lib/common.sh "$work/common.sh"
printf 'export POSTGRES_PASSWORD=existing\n' >.env
cp .env "$work/before"
run_ensure false 0 0 && cmp -s .env "$work/before" \
  || { echo "FAIL: an existing .env was changed without the reader"; exit 1; }
printf 'POSTGRES_PASSWORD=geolens\n' >.env
run_ensure true 0 0 && [ "$(get_env_value_decoded POSTGRES_PASSWORD)" != geolens ] \
  || { echo "FAIL: a template .env without the reader kept the default"; exit 1; }
mv "$work/common.sh" scripts/lib/common.sh

# Real Compose resolves the project name, inline comment and all, so the
# volume of project `<name>` is found. Skipped without a Docker daemon.
unset -f docker
if command docker compose version >/dev/null 2>&1 && command docker info >/dev/null 2>&1; then
  real_project="glinstalltest$$"
  real_volume="${real_project}_pgdata"
  printf 'services:\n  db:\n    image: busybox\n    volumes: [pgdata:/data]\nvolumes:\n  pgdata:\n' >docker-compose.yml
  command docker volume create --label "com.docker.compose.project=$real_project" \
    --label com.docker.compose.volume=pgdata "$real_volume" >/dev/null
  printf 'COMPOSE_PROJECT_NAME=%s # production\nPOSTGRES_PASSWORD=\n' "$real_project" >.env
  ( unset POSTGRES_PASSWORD COMPOSE_PROJECT_NAME; ENV_CREATED=false; ensure_postgres_password ) 2>/dev/null \
    && { echo "FAIL: the volume of a commented COMPOSE_PROJECT_NAME was missed"; exit 1; }
  [ -z "$(pg_value)" ] || { echo "FAIL: a password was generated beside an existing volume"; exit 1; }
  command docker volume rm "$real_volume" >/dev/null
  real_volume=""
  ( unset POSTGRES_PASSWORD COMPOSE_PROJECT_NAME; ENV_CREATED=false; ensure_postgres_password ) 2>/dev/null \
    || { echo "FAIL: no volume, yet the install stopped"; exit 1; }
  [ -n "$(pg_value)" ] || { echo "FAIL: no volume, yet no password was generated"; exit 1; }
else
  echo "SKIP: real Compose project-name case (no Docker daemon)"
fi

echo "PASS: install.sh secret generation (SEC-010 / SEC-011)"

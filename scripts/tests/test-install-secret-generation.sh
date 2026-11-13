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

# --- behavioral: POSTGRES_PASSWORD on a new or existing .env -----------------
# Rule: the installer writes POSTGRES_PASSWORD only into a .env this run created
# from the template. An existing .env is never rewritten: it is checked as
# Compose reads it, and an empty value stops the install.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
pgfns="$work/pgfns.sh"
for fn in generate_jwt_secret generate_password get_env_value get_env_value_decoded update_env_value compose_env_value ensure_postgres_password warn_if_database_volume_exists; do
  awk -v fn="$fn" '$0 ~ "^" fn "\\(\\) \\{" {f=1} f{print} f&&/^}/{exit}' "$INSTALL_SH" >>"$pgfns"
done
say() { :; }
warn() { printf 'Warning: %s\n' "$*" >&2; }
# shellcheck disable=SC1090
. "$pgfns"
proj="$work/install"
mkdir -p "$proj/scripts/lib"
cp "$(dirname "$INSTALL_SH")/lib/common.sh" "$proj/scripts/lib/common.sh"
cd "$proj"

# Stub: STUB_VOLUME=1 lists a database volume, STUB_DOCKER_FAIL=1 fails the call.
docker() {
  [ "${STUB_DOCKER_FAIL:-0}" = 1 ] && return 1
  [ "${STUB_VOLUME:-0}" = 1 ] && echo other_pgdata
  return 0
}

# run_ensure ENV_CREATED STUB_VOLUME STUB_DOCKER_FAIL: runs ensure_postgres_password
# in a subshell, so a fail() exit is its rc 1; warnings go to $work/stderr.
run_ensure() {
  (
    unset POSTGRES_PASSWORD
    ENV_CREATED="$1" STUB_VOLUME="$2" STUB_DOCKER_FAIL="$3"
    ensure_postgres_password
  ) 2>"$work/stderr"
}
pg_value() { v="$(compose_env_value POSTGRES_PASSWORD)" && printf '%s' "${v%x}"; }
file_mode() { ls -l .env | cut -c1-10; }
# write_env BODY: a .env holding BODY (printf escapes) with mode 600.
write_env() {
  printf "POSTGRES_USER=geolens\\n$1\\n" >.env
  chmod 600 .env
  cp -p .env "$work/before"
}
unchanged() { cmp -s .env "$work/before" && [ "$(file_mode)" = "-rw-------" ]; }

# A .env this run created gets a generated value in place of the template's.
for body in 'POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD=geolens'; do
  write_env "$body"
  run_ensure true 0 0 || { echo "FAIL: new .env [$body] stopped the install"; exit 1; }
  v="$(pg_value)"
  [ -n "$v" ] && [ "$v" != geolens ] || { echo "FAIL: new .env [$body] was not generated"; exit 1; }
done
write_env 'POSTGRES_PASSWORD='
run_ensure true 1 0 && [ -n "$(pg_value)" ] || { echo "FAIL: an existing volume blocked a new .env"; exit 1; }
grep -q 'already has a database volume' "$work/stderr" || { echo "FAIL: no warning about the existing volume"; exit 1; }
write_env 'POSTGRES_PASSWORD='
run_ensure true 0 1 && [ -n "$(pg_value)" ] || { echo "FAIL: a failed volume listing blocked a new .env"; exit 1; }

# An existing .env that resolves empty stops the install and is left as it was.
for body in 'POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD=""' "POSTGRES_PASSWORD=''" '' \
  'export POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD = ' '  POSTGRES_PASSWORD=' 'POSTGRES_PASSWORD=\r' \
  'POSTGRES_PASSWORD' 'POSTGRES_PASSWORD:' \
  'OTHER="a\nPOSTGRES_PASSWORD=x\nb"'; do
  write_env "$body"
  run_ensure false 0 0 && { echo "FAIL: existing .env [$body] did not stop"; exit 1; }
  unchanged || { echo "FAIL: existing .env [$body] was changed"; exit 1; }
done

# An existing .env that resolves to a value goes on, byte for byte and mode intact.
for body in 'POSTGRES_PASSWORD=existing' 'export POSTGRES_PASSWORD=existing' \
  'POSTGRES_PASSWORD = existing' 'POSTGRES_PASSWORD=\nPOSTGRES_PASSWORD=existing' \
  'POSTGRES_PASSWORD=existing\r' 'POSTGRES_PASSWORD= # set me' \
  'OTHER_PW=abc\nPOSTGRES_PASSWORD=${OTHER_PW}' 'POSTGRES_PASSWORD: existing' \
  'OTHER="a\nPOSTGRES_PASSWORD=\nb"\nPOSTGRES_PASSWORD=existing' 'POSTGRES_PASSWORD=geolens' \
  'POSTGRES_PASSWORD=${UNSET_IN_THIS_TEST}'; do
  write_env "$body"
  run_ensure false 1 0 || { echo "FAIL: existing .env [$body] stopped the install"; exit 1; }
  unchanged || { echo "FAIL: existing .env [$body] was changed"; exit 1; }
done
write_env 'POSTGRES_PASSWORD=geolens'
run_ensure false 0 0 && grep -q "public default 'geolens'" "$work/stderr" \
  || { echo "FAIL: no warning for the published default"; exit 1; }

write_env 'POSTGRES_PASSWORD="unterminated'
run_ensure false 0 0 && { echo "FAIL: an unreadable line did not stop"; exit 1; }
unchanged || { echo "FAIL: an unreadable line was changed"; exit 1; }

# A value exported in the shell wins over .env, as in Compose.
write_env 'POSTGRES_PASSWORD='
( POSTGRES_PASSWORD=from-shell; export POSTGRES_PASSWORD; ENV_CREATED=false; ensure_postgres_password ) \
  || { echo "FAIL: a value exported in the shell stopped the install"; exit 1; }
( POSTGRES_PASSWORD=from-shell; export POSTGRES_PASSWORD; ENV_CREATED=true; ensure_postgres_password ) \
  || { echo "FAIL: a value exported in the shell stopped a new install"; exit 1; }
unchanged || { echo "FAIL: .env was written although the shell value wins"; exit 1; }
( POSTGRES_PASSWORD=; export POSTGRES_PASSWORD; ENV_CREATED=false; ensure_postgres_password ) 2>/dev/null \
  && { echo "FAIL: an empty value exported in the shell did not stop"; exit 1; }

# A checkout without the Compose-compatible reader never stops or writes on an
# existing .env.
mv scripts/lib/common.sh "$work/common.sh"
for body in 'export POSTGRES_PASSWORD=existing' 'POSTGRES_PASSWORD='; do
  write_env "$body"
  run_ensure false 0 0 && unchanged || { echo "FAIL: [$body] without the reader stopped or changed .env"; exit 1; }
done
mv "$work/common.sh" scripts/lib/common.sh

echo "PASS: install.sh secret generation (SEC-010 / SEC-011)"

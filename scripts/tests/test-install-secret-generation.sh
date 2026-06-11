#!/bin/sh
# Regression test for SEC-010 / SEC-011: the installer must not ship or default
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

echo "PASS: install.sh secret generation (SEC-010 / SEC-011)"

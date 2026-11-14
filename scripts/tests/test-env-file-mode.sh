#!/bin/sh
# update_env_value keeps an existing .env's mode, install.sh creates .env under umask 077,
# and a failed write leaves the original file and no temp file behind.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
work="$(mktemp -d)"
trap 'chmod -R u+w "$work" 2>/dev/null; rm -rf "$work"' EXIT

# Portable mode read: ls -l is the same on GNU and BSD.
mode_of() {
  ls -l "$1" | awk '{
    m = substr($1, 2, 9); o = 0
    for (i = 1; i <= 9; i++) if (substr(m, i, 1) != "-") o += 2 ^ (9 - i)
    printf "%o", o
  }'
}
fail() { echo "FAIL: $*" >&2; exit 1; }

check_impl() {
  label="$1"; src="$2"; fn="$3"
  d="$work/$label"; mkdir -p "$d"; cd "$d"
  awk -v fn="$fn" '$0 ~ "^" fn "\\(\\) \\{" {f=1} f{print} f&&/^}/{exit}' "$src" > fn.sh
  [ -s fn.sh ] || fail "$label: update_env_value not found"
  # shellcheck disable=SC1090,SC1091
  . ./fn.sh

  umask 022
  for m in 600 640; do
    printf 'A=1\nB=2\n' > .env; chmod "$m" .env
    update_env_value A 9
    [ "$(mode_of .env)" = "$m" ] || fail "$label: mode $m became $(mode_of .env)"
    grep -qx 'A=9' .env || fail "$label: value not updated"
    grep -qx 'B=2' .env || fail "$label: other key lost"
  done

  # Failed write: the temp file cannot be moved over a directory.
  rm -f .env; mkdir .env
  if update_env_value A 1 2>/dev/null; then fail "$label: expected failure"; fi
  rmdir .env
  printf 'A=1\n' > .env; chmod 640 .env
  awk() { return 1; }
  if update_env_value A 2 2>/dev/null; then fail "$label: awk failure not reported"; fi
  unset -f awk
  [ "$(cat .env)" = "A=1" ] || fail "$label: original content changed"
  [ "$(mode_of .env)" = "640" ] || fail "$label: original mode changed"
  [ -z "$(ls -A | grep '^\.env\.tmp')" ] || fail "$label: temp file left behind"
  cd "$work"
}

check_impl install "$ROOT/scripts/install.sh" update_env_value
check_impl common "$ROOT/scripts/lib/common.sh" update_env_value
grep -q '(umask 077 && cp .env.example .env)' "$ROOT/scripts/install.sh" \
  || fail "install.sh does not create .env under umask 077"
echo "PASS: env file mode"

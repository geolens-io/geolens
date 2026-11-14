#!/bin/sh
# update_env_value keeps an existing .env's mode, install.sh creates .env under umask 077,
# and a failed write leaves the original file and no temp file behind.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
work="$(mktemp -d)"
trap 'chmod -R u+w "$work" 2>/dev/null; rm -rf "$work"' EXIT

# Portable mode read: ls -l is the same on GNU and BSD.
mode_of() {
  ls -lL "$1" | awk '{
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
  for m in 400 444 600 640; do
    rm -f .env; printf 'A=1\nB=2\n' > .env; chmod "$m" .env
    update_env_value A 9
    [ "$(mode_of .env)" = "$m" ] || fail "$label: mode $m became $(mode_of .env)"
    grep -qx 'A=9' .env || fail "$label: value not updated"
    grep -qx 'B=2' .env || fail "$label: other key lost"
  done

  # A setuid bit without execute shows as S and must not count as a set bit.
  rm -f .env; printf 'A=1\n' > .env; chmod 4644 .env
  update_env_value A 2
  [ "$(mode_of .env)" = "644" ] || fail "$label: S bit mapped to $(mode_of .env)"

  # A symlinked .env takes the target's mode; the link itself is replaced.
  rm -f .env target; printf 'A=1\n' > target; chmod 600 target; ln -s target .env
  update_env_value A 2
  [ ! -L .env ] || fail "$label: link kept"
  [ "$(mode_of .env)" = "600" ] || fail "$label: symlink result mode $(mode_of .env)"
  [ "$(cat target)" = "A=1" ] || fail "$label: link target changed"
  rm -f target

  # Failed write: each step that can fail is simulated in turn.
  rm -f .env; printf 'A=1\n' > .env; chmod 640 .env
  awk() { return 1; }
  if update_env_value A 2 2>/dev/null; then fail "$label: awk failure not reported"; fi
  unset -f awk
  mv() { return 1; }
  if update_env_value A 2 2>/dev/null; then fail "$label: mv failure not reported"; fi
  unset -f mv
  [ "$(cat .env)" = "A=1" ] || fail "$label: original content changed"
  [ "$(mode_of .env)" = "640" ] || fail "$label: original mode changed"
  [ -z "$(ls -A | grep '^\.env\.tmp')" ] || fail "$label: temp file left behind"
  cd "$work"
}

check_impl install "$ROOT/scripts/install.sh" update_env_value
check_impl common "$ROOT/scripts/lib/common.sh" update_env_value
awk '/cp \.env\.example \.env/{c=NR} /chmod 600 \.env/{m=NR} c&&!u&&/update_env_value /{u=NR} END{exit !(c && m>c && m<u)}' "$ROOT/scripts/install.sh" \
  || fail "install.sh must chmod 600 .env right after creating it, before the first update_env_value"
echo "PASS: env file mode"

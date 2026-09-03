#!/bin/sh
# fix(#1798 review round 11 audit, P1): RUNBOOK.md told operators to
# `set -a; . ./.env; set +a` in three places (globals restore, runtime-role
# verification, role rotation) — exactly the shell-sourcing restore.sh's own
# header explains get_env_value exists to avoid: `.` executes the file, so
# an operator-typed value containing a bare space becomes "set VAR=<first
# word>, run <second word> as a command" (a 127 under `set -e`) and a value
# containing backticks or $(...) is EXECUTED with the operator's privileges.
# This wrapper reads exactly one key through get_env_value's awk parser
# instead, matching how restore.sh/check-env.sh/upgrade.sh already read
# .env — a value is data here, never code.
#
# Usage: scripts/env-value.sh KEY [FILE]   (FILE defaults to ./.env)
#
# Exit status matches get_env_value: 0 with the value on stdout (possibly
# empty, if the key is present but blank) when the key was found; 1 with no
# output when the key has no line in the file at all, or the file itself
# does not exist.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "Usage: $0 KEY [FILE]" >&2
  exit 2
fi

get_env_value "$1" "${2:-.env}"

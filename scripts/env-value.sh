#!/bin/sh
# Prints one key from a .env file for RUNBOOK.md snippets. Sourcing the file
# (`set -a; . ./.env; set +a`) executes it: an operator-typed value with a bare
# space becomes "set VAR=<first word>, run <second word> as a command" (a 127
# under `set -e`), and a value with backticks or $(...) runs with the
# operator's privileges. This wrapper reads the key through get_env_value's awk
# parser, as restore.sh, check-env.sh and upgrade.sh do, so a value is data.
#
# Usage: scripts/env-value.sh KEY [FILE]   (FILE defaults to ./.env)
#
# Exit status matches get_env_value: 0 with the value on stdout (possibly
# empty, if the key is present but blank) when the key was found; 1 with no
# output when the key has no line in the file, or the file does not exist.
#
# Output is stdout-based, unlike common.sh's env_value_into, which only works
# within the shell that sourced common.sh and preserves a trailing decoded
# newline. This script runs as a separate subprocess, so callers capture it
# with command substitution, which strips a trailing newline. That only matters
# for a value deliberately ending in one; the passwords, role names and
# database names RUNBOOK.md reads this way do not.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "Usage: $0 KEY [FILE]" >&2
  exit 2
fi

get_env_value "$1" "${2:-.env}"

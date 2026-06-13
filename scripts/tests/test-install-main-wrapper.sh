#!/bin/sh
# Regression test for GAP-025: scripts/install.sh must run inside a main()
# function invoked by a single `main "$@"` on the LAST line.
#
# Under `curl -fsSL .../install.sh | sh`, statements stream and execute as they
# arrive, so a truncated download (connection drop mid-stream) would otherwise
# run a partial prefix — e.g. write a half-configured .env or leave a
# partially-fetched checkout. Wrapping the imperative body in main() means sh
# must parse the whole function before executing it, so truncation yields a
# syntax error at EOF instead of partial execution.
#
# Pure shell: no Docker, no DB, no network. Runnable locally and in CI.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_SH="$SCRIPT_DIR/../install.sh"
[ -f "$INSTALL_SH" ] || { echo "FAIL: cannot find install.sh at $INSTALL_SH"; exit 1; }

# --- structural: main() defined, invoked exactly once, on the last line --------
grep -qE '^main\(\) \{' "$INSTALL_SH" \
  || { echo "FAIL: install.sh does not define a main() function (GAP-025)"; exit 1; }

last_line="$(tail -n 1 "$INSTALL_SH")"
[ "$last_line" = 'main "$@"' ] \
  || { echo "FAIL: install.sh last line must be 'main \"\$@\"' (got: $last_line)"; exit 1; }

invocations="$(grep -cE '^main "\$@"$' "$INSTALL_SH")"
[ "$invocations" = "1" ] \
  || { echo "FAIL: expected exactly one top-level 'main \"\$@\"' (got $invocations)"; exit 1; }

# --- syntax: the script must parse cleanly -------------------------------------
sh -n "$INSTALL_SH" \
  || { echo "FAIL: install.sh has a syntax error"; exit 1; }

# --- behavioral: a truncated prefix is inert (no clone, no .env, no compose) ----
# Run a mid-function prefix in an isolated empty dir; it must error at EOF and
# create no files (main is never reached, so no real action runs).
work="$(mktemp -d)"
( cd "$work" && head -n 50 "$INSTALL_SH" | sh >/dev/null 2>&1 ) || true
created="$(ls -A "$work" | wc -l | tr -d ' ')"
rm -rf "$work"
[ "$created" = "0" ] \
  || { echo "FAIL: truncated install.sh prefix created $created file(s) — not inert (GAP-025)"; exit 1; }

echo "PASS: install.sh main() wrapper guards against truncated curl|sh (GAP-025)"

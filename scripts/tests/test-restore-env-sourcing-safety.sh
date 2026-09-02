#!/bin/sh
# Regression test for scripts/restore.sh and scripts/check-env.sh reading
# `.env` with get_env_value (an awk parser) instead of shell-sourcing it
# (fix(#1778)).
#
# Docker Compose's own `.env` parser and `sh` disagree about the same file:
# install.sh writes values verbatim (an operator-typed admin password can
# legally contain a space, and compose accepts it), and `. .env` under
# `set -e` either dies on a 127 (a value containing a bare space becomes "set
# VAR=<first word>, then run <second word> as a command") or, worse,
# EXECUTES a value containing `$(...)` or backticks with the operator's
# privileges. Neither script should do either.
#
# Pure shell with a stubbed `docker` on PATH; no real stack, no DB, no
# network. Real restore.sh / check-env.sh / common.sh.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"       # scripts/

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

FAKE="$WORK/repo"
mkdir -p "$FAKE/scripts/lib"
cp "$REPO_ROOT/restore.sh" "$FAKE/scripts/restore.sh"
cp "$REPO_ROOT/check-env.sh" "$FAKE/scripts/check-env.sh"
cp "$REPO_ROOT/lib/common.sh" "$FAKE/scripts/lib/common.sh"
chmod +x "$FAKE/scripts/restore.sh" "$FAKE/scripts/check-env.sh"
printf 'services: {}\n' > "$FAKE/docker-compose.yml"

BACKUP_FILE="$WORK/geolens_20260101_000000.dump"
printf 'PGDMP-fake-custom-format-dump-bytes\n' > "$BACKUP_FILE"

# A marker only real shell-sourcing of the poisoned .env line below would
# create. Its mere existence after a run is the injection succeeding.
PWNED_MARKER="$WORK/pwned"
rm -f "$PWNED_MARKER"

# .env carries three shapes real `.env` files can legally have and `sh`
# cannot safely `.` source:
#   - POSTGRES_USER: an operator-typed value containing a bare space
#     (install.sh's admin-password prompt accepts one; Compose does too).
#   - MINIO_ROOT_PASSWORD: a value containing a command substitution. This
#     key is NOT one restore.sh/check-env.sh ever reads — sourcing pulls it
#     in anyway as a side effect; get_env_value never touches a line it was
#     not asked to look up.
#   - GEOLENS_RUNTIME_DB_ROLE: backticks, the other command-substitution form.
# Ordered with the space-containing value LAST: shell-sourcing this file
# aborts on the first bad line, so this order proves the payload lines
# execute (or don't) independently of the space-value crash, not merely that
# neither was reached.
cat > "$FAKE/.env" <<EOF
COMPOSE_FILE=docker-compose.yml
MINIO_ROOT_PASSWORD=\$(touch $PWNED_MARKER)
GEOLENS_RUNTIME_DB_ROLE=\`touch $PWNED_MARKER\`
POSTGRES_PASSWORD=irrelevant
POSTGRES_DB=geolens
POSTGRES_USER=geolens admin
EOF

SHIM="$WORK/bin"
mkdir -p "$SHIM"
cat > "$SHIM/docker" <<'DOCKER'
#!/bin/sh
if [ "$1" = "compose" ]; then
  shift
  if [ "$1" = "-f" ]; then shift; shift; fi
  case "$1" in
    stop|start) exit 0 ;;
    exec)
      cat > /dev/null 2>/dev/null
      # A single query result column is enough to satisfy every -tAc caller
      # (has_schema_privilege, the missing-roles check, etc.).
      echo "t"
      exit 0 ;;
    *) exit 0 ;;
  esac
fi
exit 0
DOCKER
chmod +x "$SHIM/docker"

# ============================================================================
# CASE 1 — restore.sh must not crash on a POSTGRES_USER value with a space,
# and must not execute the $(...) / backtick payloads elsewhere in .env.
# ============================================================================
( cd "$WORK" && env "PATH=$SHIM:$PATH" \
    bash "$FAKE/scripts/restore.sh" "$BACKUP_FILE" </dev/null > "$WORK/out.txt" 2>&1 )
RC=$?

if [ "$RC" != "127" ]; then
  ok "restore.sh does not die with 127 on a POSTGRES_USER value containing a space"
else
  bad "restore.sh hit a 127 (command not found) sourcing the space-containing value"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if ! grep -q 'admin: command not found' "$WORK/out.txt" \
   && ! grep -q ': admin: ' "$WORK/out.txt"; then
  ok "the space-containing value's second word was never run as a command"
else
  bad "the second word of the POSTGRES_USER value was executed"
  sed 's/^/    # /' "$WORK/out.txt"
fi
if [ ! -e "$PWNED_MARKER" ]; then
  ok "the \$(...) / backtick payloads elsewhere in .env were never executed"
else
  bad "restore.sh executed a command-substitution payload from an unrelated .env line"
  rm -f "$PWNED_MARKER"
fi

# ============================================================================
# CASE 2 — check-env.sh: the same three payload shapes, same non-execution
# contract. Its docker calls always report success/reachable, so a clean run
# is expected regardless of the .env parsing method — the only thing under
# test is whether sourcing ever ran.
# ============================================================================
rm -f "$PWNED_MARKER"
( cd "$WORK" && env "PATH=$SHIM:$PATH" \
    bash "$FAKE/scripts/check-env.sh" </dev/null > "$WORK/out-checkenv.txt" 2>&1 )
CE_RC=$?

if [ "$CE_RC" != "127" ]; then
  ok "check-env.sh does not die with 127 on a POSTGRES_USER value containing a space"
else
  bad "check-env.sh hit a 127 (command not found) sourcing the space-containing value"
  sed 's/^/    # /' "$WORK/out-checkenv.txt"
fi
if [ ! -e "$PWNED_MARKER" ]; then
  ok "check-env.sh never executed the \$(...) / backtick payloads in .env"
else
  bad "check-env.sh executed a command-substitution payload from .env"
fi

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

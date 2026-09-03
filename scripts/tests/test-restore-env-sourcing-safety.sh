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

# ============================================================================
# CASE 3 — fix(#1778 review, P2): get_env_value's raw awk extraction used to
# return a Compose-quoted value WITH its quote characters still attached — a
# legal, common .env line like COMPOSE_FILE="docker-compose.prod.yml" (or
# POSTGRES_USER="geolens") came back as the 25-character string
# `"docker-compose.prod.yml"`, quotes and all, silently breaking any caller
# that put it in a path or SQL identifier. Compose itself strips exactly one
# matching pair of quotes and, inside double quotes, unescapes \" and \\.
# Drive get_env_value directly (not through restore.sh/check-env.sh, which
# only exercise a handful of keys) against every shape Compose's env-file
# reference documents, plus the $(...) payload again at the parser level —
# the value must round-trip as inert text, never be evaluated.
# ============================================================================
QUOTE_ENV="$WORK/.env.quoting"
cat > "$QUOTE_ENV" <<EOF
DOUBLE_QUOTED="docker-compose.prod.yml"
SINGLE_QUOTED='geolens'
UNQUOTED=geolens
DOUBLE_WITH_ESCAPES="a \"quoted\" value with \\\\backslash"
UNQUOTED_WITH_COMMENT=value # trailing comment
UNQUOTED_HASH_NO_SPACE=value#nothash
EMPTY_DOUBLE=""
EMPTY_SINGLE=''
DOLLAR_PAREN=\$(touch $PWNED_MARKER)
COMPOSE_FILE="docker-compose.prod.yml" # production
HASH_INSIDE_DOUBLE="value#withhash"
SINGLE_WITH_TRAILING_COMMENT='geolens' # trailing comment on a single quote
EOF
rm -f "$PWNED_MARKER"

QUOTE_DRIVER="$WORK/quote_driver.sh"
cat > "$QUOTE_DRIVER" <<DRIVER
#!/bin/sh
set -eu
. "$FAKE/scripts/lib/common.sh"
for key in DOUBLE_QUOTED SINGLE_QUOTED UNQUOTED DOUBLE_WITH_ESCAPES \\
           UNQUOTED_WITH_COMMENT UNQUOTED_HASH_NO_SPACE EMPTY_DOUBLE \\
           EMPTY_SINGLE DOLLAR_PAREN COMPOSE_FILE HASH_INSIDE_DOUBLE \\
           SINGLE_WITH_TRAILING_COMMENT; do
  printf '%s=[%s]\n' "\$key" "\$(get_env_value "\$key" "$QUOTE_ENV")"
done
DRIVER
QUOTE_OUT="$(sh "$QUOTE_DRIVER" 2>&1)"

_assert_quote_line() {
  # $1 = expected "KEY=[value]" line, $2 = description
  if printf '%s\n' "$QUOTE_OUT" | grep -qxF "$1"; then
    ok "$2"
  else
    bad "$2 (got: $(printf '%s\n' "$QUOTE_OUT" | grep "^${1%%=*}=" || echo "<no line>"))"
  fi
}

_assert_quote_line 'DOUBLE_QUOTED=[docker-compose.prod.yml]' \
  "a double-quoted value round-trips without its quotes"
_assert_quote_line 'SINGLE_QUOTED=[geolens]' \
  "a single-quoted value round-trips without its quotes"
_assert_quote_line 'UNQUOTED=[geolens]' \
  "an unquoted value is unaffected"
_assert_quote_line 'DOUBLE_WITH_ESCAPES=[a "quoted" value with \backslash]' \
  'double-quote escapes (\" and \\) unescape correctly'
_assert_quote_line 'UNQUOTED_WITH_COMMENT=[value]' \
  "an unquoted value's inline ' #comment' is stripped, matching Compose"
_assert_quote_line 'UNQUOTED_HASH_NO_SPACE=[value#nothash]' \
  "a '#' with no preceding space is literal, matching Compose"
_assert_quote_line 'EMPTY_DOUBLE=[]' "an empty double-quoted value is empty, not two quote chars"
_assert_quote_line 'EMPTY_SINGLE=[]' "an empty single-quoted value is empty, not two quote chars"

# fix(#1778 review round 2, P2): a comment MAY follow the closing quote —
# `COMPOSE_FILE="docker-compose.prod.yml" # production` is valid Compose
# syntax. The raw text does not end in a quote (it ends in the comment), so
# the "starts and ends with a quote" dispatch used to take the unquoted
# branch, strip the comment, and return the value WITH its quotes attached.
_assert_quote_line 'COMPOSE_FILE=[docker-compose.prod.yml]' \
  "a double-quoted value followed by a comment strips the comment, not just the trailing quote check"
_assert_quote_line 'HASH_INSIDE_DOUBLE=[value#withhash]' \
  "a '#' inside double quotes is preserved even with no trailing comment"
_assert_quote_line 'SINGLE_WITH_TRAILING_COMMENT=[geolens]' \
  "a single-quoted value followed by a comment strips the comment and the quotes"

if printf '%s\n' "$QUOTE_OUT" | grep -qxF 'DOLLAR_PAREN=[$(touch '"$PWNED_MARKER"')]'; then
  ok "a \$(...) value is returned as literal text by get_env_value"
else
  bad "get_env_value did not return the \$(...) value as literal text: $(printf '%s\n' "$QUOTE_OUT" | grep '^DOLLAR_PAREN=')"
fi
if [ ! -e "$PWNED_MARKER" ]; then
  ok "get_env_value never executes a \$(...) value while parsing quotes/escapes"
else
  bad "get_env_value executed a \$(...) payload while parsing"
  rm -f "$PWNED_MARKER"
fi

# ============================================================================
# CASE 4 — fix(#1778 review round 3, P2): Compose-compatible ${VAR}
# interpolation. A valid Compose .env may write
# COMPOSE_FILE="${DEPLOY_FILE}"; the plain quote/comment parsing above
# returns that literally, `${DEPLOY_FILE}` and all, instead of the value
# real Compose resolves there. get_env_value now interpolates
# ${VAR}/$VAR/${VAR:-d}/${VAR-d}/${VAR:?m} against an earlier line in the
# SAME file, then the process environment, leaving an unresolved reference
# completely unchanged (Compose's own choice — expand to empty with a
# warning — has no channel to reach an operator here; see the doc comment
# on _env_interpolate in scripts/lib/common.sh for the full reasoning).
# ============================================================================
INTERP_ENV="$WORK/.env.interp"
cat > "$INTERP_ENV" <<EOF
DEPLOY_FILE=docker-compose.prod.yml
COMPOSE_FILE="\${DEPLOY_FILE}"
UNKNOWN_REF="prefix-\${TOTALLY_UNKNOWN_XYZ}-suffix"
CHAINED_A=alpha
CHAINED_B="\${CHAINED_A}-beta"
FROM_ENV="\${GEOLENS_TEST_INTERP_VAR}"
DOLLAR_PAREN_AGAIN=\$(touch $PWNED_MARKER)
EOF
rm -f "$PWNED_MARKER"

INTERP_DRIVER="$WORK/interp_driver.sh"
cat > "$INTERP_DRIVER" <<DRIVER
#!/bin/sh
set -eu
. "$FAKE/scripts/lib/common.sh"
for key in DEPLOY_FILE COMPOSE_FILE UNKNOWN_REF CHAINED_B FROM_ENV \\
           DOLLAR_PAREN_AGAIN; do
  printf '%s=[%s]\n' "\$key" "\$(get_env_value "\$key" "$INTERP_ENV")"
done
DRIVER
INTERP_OUT="$(GEOLENS_TEST_INTERP_VAR=from-process-env sh "$INTERP_DRIVER" 2>&1)"

_assert_interp_line() {
  # $1 = expected "KEY=[value]" line, $2 = description
  if printf '%s\n' "$INTERP_OUT" | grep -qxF "$1"; then
    ok "$2"
  else
    bad "$2 (got: $(printf '%s\n' "$INTERP_OUT" | grep "^${1%%=*}=" || echo "<no line>"))"
  fi
}

_assert_interp_line 'COMPOSE_FILE=[docker-compose.prod.yml]' \
  "COMPOSE_FILE=\"\${DEPLOY_FILE}\" resolves against the earlier DEPLOY_FILE= line"
_assert_interp_line 'UNKNOWN_REF=[prefix-${TOTALLY_UNKNOWN_XYZ}-suffix]' \
  "an unresolved \${UNKNOWN} reference is left completely unchanged, not blanked"
_assert_interp_line 'CHAINED_B=[alpha-beta]' \
  "a chained reference (B references A) resolves within the bounded-pass loop"
_assert_interp_line 'FROM_ENV=[from-process-env]' \
  "a reference with no earlier-file definition falls back to the process environment"

if printf '%s\n' "$INTERP_OUT" | grep -qxF 'DOLLAR_PAREN_AGAIN=[$(touch '"$PWNED_MARKER"')]'; then
  ok "a \$(...) value survives interpolation as literal text too"
else
  bad "interpolation altered a \$(...) payload: $(printf '%s\n' "$INTERP_OUT" | grep '^DOLLAR_PAREN_AGAIN=')"
fi
if [ ! -e "$PWNED_MARKER" ]; then
  ok "interpolation never executes a \$(...) payload"
else
  bad "interpolation executed a \$(...) payload"
  rm -f "$PWNED_MARKER"
fi

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

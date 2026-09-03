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
      # fix(#1778 review round 6, P2) test support: opt-in argv logging so
      # a test can prove which POSTGRES_USER/POSTGRES_DB restore.sh
      # actually invoked psql with, without restore.sh itself changing.
      [ -n "${DOCKER_EXEC_LOG:-}" ] && printf '%s\n' "$*" >> "${DOCKER_EXEC_LOG}"
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
SINGLE_TRAILING_COMMENT_HAS_QUOTE='geolens' # use 'production'
DOUBLE_ESCAPED_WITH_COMMENT="a \"quoted\" value" # trailing comment too
SINGLE_HASH='value#hash'
UNQUOTED_HAS_EQUALS=a=b
SINGLE_HAS_EQUALS='a=b'
DOUBLE_UNKNOWN_ESCAPE="a\db"
PURE_BACKSLASH="a\\\\b"
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
           SINGLE_WITH_TRAILING_COMMENT SINGLE_TRAILING_COMMENT_HAS_QUOTE \\
           DOUBLE_ESCAPED_WITH_COMMENT SINGLE_HASH UNQUOTED_HAS_EQUALS \\
           SINGLE_HAS_EQUALS DOUBLE_UNKNOWN_ESCAPE PURE_BACKSLASH; do
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

# fix(#1798 review round 9, P2): the greedy `(.*)` in get_env_value's own
# single-quote branch backtracked to the LAST `'` on the line — a trailing
# comment containing its own apostrophe (a real-world "prefer this instead"
# comment style) matched all the way to THAT quote, returning
# "geolens' # use 'production" instead of stopping at the value's own
# closing quote right after "geolens".
_assert_quote_line "SINGLE_TRAILING_COMMENT_HAS_QUOTE=[geolens]" \
  "a single-quoted value's trailing comment may contain its own apostrophe without corrupting the parse"
_assert_quote_line 'DOUBLE_ESCAPED_WITH_COMMENT=[a "quoted" value]' \
  "a double-quoted value with an escaped quote AND a trailing comment resolves correctly"
_assert_quote_line 'SINGLE_HASH=[value#hash]' \
  "a '#' inside single quotes is preserved, matching the double-quoted case"
_assert_quote_line 'UNQUOTED_HAS_EQUALS=[a=b]' \
  "an unquoted value containing '=' is not truncated at it"
_assert_quote_line 'SINGLE_HAS_EQUALS=[a=b]' \
  "a single-quoted value containing '=' is not truncated at it"

# fix(#1798 review round 10, P2): Compose's env-file syntax
# (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax)
# documents \\, \", \n, \r, \t as the escape sequences a double-quoted
# value decodes. Everything else (\d here) is left completely unchanged —
# the prior blanket `\X -> X` unescape did not distinguish the two, so an
# undocumented escape silently lost its backslash too.
_assert_quote_line 'DOUBLE_UNKNOWN_ESCAPE=[a\db]' \
  "an undocumented double-quoted escape (not \\\\, \\\", \\n, \\r, \\t) is left completely unchanged"
_assert_quote_line 'PURE_BACKSLASH=[a\b]' \
  "a double-quoted \\\\ decodes to a single literal backslash"

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
# CASE 3b — fix(#1798 review round 10, P2): Compose's env-file syntax
# (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax)
# documents \n, \r, \t (and \\, \") as the escape sequences a
# double-quoted value decodes — POSTGRES_DB="geo\tlens" is a literal tab
# between "geo" and "lens", per Compose. The prior blanket `\X -> X`
# unescape ignored that distinction and returned "geotlens", a different
# database than the one the app containers actually connect to. Verified
# via hex digests, not _assert_quote_line's exact-line text match — a
# decoded \n embeds a real newline byte into the captured value, which
# would otherwise split it across two lines and break that comparison.
# ============================================================================
TABNL_ENV="$WORK/.env.tabnl"
cat > "$TABNL_ENV" <<EOF
TAB_ESCAPE="geo\tlens"
NEWLINE_ESCAPE="line1\nline2"
EOF

TABNL_DRIVER="$WORK/tabnl_driver.sh"
cat > "$TABNL_DRIVER" <<DRIVER
#!/bin/sh
set -eu
. "$FAKE/scripts/lib/common.sh"
get_env_value TAB_ESCAPE "$TABNL_ENV" | od -An -tx1 | tr -d ' \\n'
echo
get_env_value NEWLINE_ESCAPE "$TABNL_ENV" | od -An -tx1 | tr -d ' \\n'
echo
DRIVER
TABNL_OUT="$(sh "$TABNL_DRIVER" 2>&1)"
TAB_ACTUAL="$(printf '%s\n' "$TABNL_OUT" | sed -n '1p')"
NL_ACTUAL="$(printf '%s\n' "$TABNL_OUT" | sed -n '2p')"
TAB_EXPECTED="$(printf 'geo\tlens' | od -An -tx1 | tr -d ' \n')"
NL_EXPECTED="$(printf 'line1\nline2' | od -An -tx1 | tr -d ' \n')"

if [ "$TAB_ACTUAL" = "$TAB_EXPECTED" ]; then
  ok "a double-quoted value's documented \\t escape decodes to an actual tab byte, not the literal letter t"
else
  bad "\\t decode mismatch: got $TAB_ACTUAL want $TAB_EXPECTED"
fi
if [ "$NL_ACTUAL" = "$NL_EXPECTED" ]; then
  ok "a double-quoted value's documented \\n escape decodes to an actual newline byte, not the literal letter n"
else
  bad "\\n decode mismatch: got $NL_ACTUAL want $NL_EXPECTED"
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

# ============================================================================
# CASE 5 — fix(#1778 review round 6, P2): get_env_value distinguishes "key
# absent from the file" (returns 1, prints nothing) from "key present with
# an empty value" (returns 0, prints ""), and resolves a duplicate key to
# its LAST definition (Compose's own rule) instead of its first.
# ============================================================================
GETENV_ENV="$WORK/.env.getenv"
cat > "$GETENV_ENV" <<'EOF'
PRESENT_EMPTY=
DUPLICATE_KEY=first
DUPLICATE_KEY=second
EOF

GETENV_DRIVER="$WORK/getenv_driver.sh"
cat > "$GETENV_DRIVER" <<DRIVER
#!/bin/sh
set -eu
. "$FAKE/scripts/lib/common.sh"

if val="\$(get_env_value MISSING_KEY "$GETENV_ENV")"; then
  echo "MISSING_KEY=FOUND:[\$val]"
else
  echo "MISSING_KEY=NOTFOUND:[\$val]"
fi

if val="\$(get_env_value PRESENT_EMPTY "$GETENV_ENV")"; then
  echo "PRESENT_EMPTY=FOUND:[\$val]"
else
  echo "PRESENT_EMPTY=NOTFOUND:[\$val]"
fi

if val="\$(get_env_value DUPLICATE_KEY "$GETENV_ENV")"; then
  echo "DUPLICATE_KEY=FOUND:[\$val]"
else
  echo "DUPLICATE_KEY=NOTFOUND:[\$val]"
fi

if val="\$(get_env_value NO_SUCH_KEY "$WORK/does-not-exist.env")"; then
  echo "NO_SUCH_FILE=FOUND:[\$val]"
else
  echo "NO_SUCH_FILE=NOTFOUND:[\$val]"
fi
DRIVER
GETENV_OUT="$(sh "$GETENV_DRIVER" 2>&1)"

if printf '%s\n' "$GETENV_OUT" | grep -qxF 'MISSING_KEY=NOTFOUND:[]'; then
  ok "get_env_value reports NOT FOUND (nonzero exit) for a key with no line in the file"
else
  bad "get_env_value did not report NOT FOUND for a missing key (got: $(printf '%s\n' "$GETENV_OUT" | grep '^MISSING_KEY=' || echo '<none>'))"
fi

if printf '%s\n' "$GETENV_OUT" | grep -qxF 'PRESENT_EMPTY=FOUND:[]'; then
  ok "get_env_value reports FOUND (exit 0) for a key present with an empty value"
else
  bad "get_env_value did not report FOUND for a present-but-empty key (got: $(printf '%s\n' "$GETENV_OUT" | grep '^PRESENT_EMPTY=' || echo '<none>'))"
fi

if printf '%s\n' "$GETENV_OUT" | grep -qxF 'DUPLICATE_KEY=FOUND:[second]'; then
  ok "get_env_value resolves a duplicate key to its LAST definition, matching Compose"
else
  bad "get_env_value did not return the last duplicate-key definition (got: $(printf '%s\n' "$GETENV_OUT" | grep '^DUPLICATE_KEY=' || echo '<none>'))"
fi

if printf '%s\n' "$GETENV_OUT" | grep -qxF 'NO_SUCH_FILE=NOTFOUND:[]'; then
  ok "get_env_value reports NOT FOUND when the .env file itself does not exist"
else
  bad "get_env_value did not report NOT FOUND for a missing file (got: $(printf '%s\n' "$GETENV_OUT" | grep '^NO_SUCH_FILE=' || echo '<none>'))"
fi

# ============================================================================
# CASE 6 — fix(#1778 review round 6, P2): a setting Compose supports
# supplying purely through the process environment (`POSTGRES_DB=prod
# scripts/restore.sh ...`), deliberately OMITTED from .env, must survive —
# not be overwritten with "" and then masked by restore.sh's own
# `${POSTGRES_DB:-geolens}` default. Runs the REAL restore.sh end to end
# (same stubbed docker as CASE 1-4) and reads back which -d value the
# stubbed docker actually received.
# ============================================================================
OVERRIDE_ENV="$FAKE/.env"
cat > "$OVERRIDE_ENV" <<'EOF'
COMPOSE_FILE=docker-compose.yml
POSTGRES_USER=geolens
EOF
# POSTGRES_DB is deliberately NOT in this .env at all.

DOCKER_EXEC_LOG="$WORK/docker-exec.log"
rm -f "$DOCKER_EXEC_LOG"
( cd "$WORK" && env "PATH=$SHIM:$PATH" DOCKER_EXEC_LOG="$DOCKER_EXEC_LOG" \
    POSTGRES_DB=customdb \
    bash "$FAKE/scripts/restore.sh" "$BACKUP_FILE" </dev/null > "$WORK/case6-out.txt" 2>&1 )

if grep -qF -- '-d customdb' "$DOCKER_EXEC_LOG" 2>/dev/null; then
  ok "restore.sh preserves a POSTGRES_DB supplied only via the process environment"
else
  bad "restore.sh did not use the process-environment POSTGRES_DB (exec log: $(cat "$DOCKER_EXEC_LOG" 2>/dev/null | head -3 || echo '<empty>'))"
fi
if ! grep -qF -- '-d geolens' "$DOCKER_EXEC_LOG" 2>/dev/null; then
  ok "restore.sh did not fall back to the hardcoded 'geolens' default, masking the override"
else
  bad "restore.sh fell back to the 'geolens' default instead of the process-environment override"
fi


# ============================================================================
# CASE 7 — fix(#1798 review round 11 audit, P2): a leading UTF-8 BOM (bytes
# EF BB BF, common from PowerShell's default UTF-8 output or some Windows
# editors saving .env) sits BEFORE the first line's own text, so `^KEY=`
# never matched a key on line 1 at all — get_env_value returned "not
# found" (rc=1) for a key that genuinely IS on line 1, and every guarded
# caller's fallback then silently kept the inherited/unset value instead
# of the operator's actual setting.
# ============================================================================
BOM_ENV="$WORK/.env.bom"
printf '\357\273\277POSTGRES_DB=geolens\n' > "$BOM_ENV"

BOM_DRIVER="$WORK/bom_driver.sh"
cat > "$BOM_DRIVER" <<DRIVER
#!/bin/sh
set -eu
. "$FAKE/scripts/lib/common.sh"
if val="\$(get_env_value POSTGRES_DB "$BOM_ENV")"; then
  echo "FOUND:[\$val]"
else
  echo "NOTFOUND:[]"
fi
DRIVER
BOM_OUT="$(sh "$BOM_DRIVER" 2>&1)"

if [ "$BOM_OUT" = "FOUND:[geolens]" ]; then
  ok "a BOM-prefixed single-line .env still returns its key's value"
else
  bad "a BOM-prefixed single-line .env did not return the value (got: $BOM_OUT)"
fi

# ============================================================================
# CASE 8 — fix(#1798 review round 11 audit, P2): _env_interpolate's
# multi-pass loop resolves a chained ${VAR} reference by looking up the
# REFERENCED key's raw value and re-scanning IT for further ${VAR} tokens —
# but it reused the OUTER key's own `before_line` bound for every
# subsequent pass, instead of re-deriving the bound for each newly
# substituted value's OWN defining line. With C=orig / B=${C} / C=updated
# (C redefined AFTER B) / A=${B}: resolving B directly correctly bounds the
# ${C} lookup to "before B's own line" and gets "orig" — but resolving A
# (a DIFFERENT key, defined after both C definitions) reused A's own
# before_line for the ${C} token that came from substituting B's value,
# so that lookup saw the LATER "C=updated" line too and returned
# "updated" instead of "orig". A and B must agree on what ${C} means.
# ============================================================================
CHAIN_ENV="$WORK/.env.chain"
cat > "$CHAIN_ENV" <<'EOF'
C=orig
B="${C}"
C=updated
A="${B}"
EOF

CHAIN_DRIVER="$WORK/chain_driver.sh"
cat > "$CHAIN_DRIVER" <<DRIVER
#!/bin/sh
set -eu
. "$FAKE/scripts/lib/common.sh"
echo "A:[\$(get_env_value A "$CHAIN_ENV")]"
echo "B:[\$(get_env_value B "$CHAIN_ENV")]"
DRIVER
CHAIN_OUT="$(sh "$CHAIN_DRIVER" 2>&1)"
A_VAL="$(printf '%s\n' "$CHAIN_OUT" | sed -n 's/^A:\[\(.*\)\]$/\1/p')"
B_VAL="$(printf '%s\n' "$CHAIN_OUT" | sed -n 's/^B:\[\(.*\)\]$/\1/p')"

if [ "$A_VAL" = "$B_VAL" ]; then
  ok "a chained \${VAR} reference resolves consistently regardless of which key asks for it (A=[$A_VAL] B=[$B_VAL])"
else
  bad "a chained \${VAR} reference resolved inconsistently: A=[$A_VAL] B=[$B_VAL] (expected both to equal B's own resolution)"
fi

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

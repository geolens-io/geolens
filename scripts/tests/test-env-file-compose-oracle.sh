#!/bin/sh
# fix(#1798 review round 13, P2, review 5103870781; round 13b precedence
# follow-up): every other test in this suite pins get_env_value's
# (scripts/lib/common.sh) behavior against a WRITTEN-DOWN understanding of
# Docker Compose's `.env` grammar. This one instead asks Compose itself,
# for a corpus covering every codex .env finding from rounds 6-12 (BOM, a
# comment after a closing quote, escapes including \n/\t/\\, sibling and
# chained ${VAR} interpolation with redefinition, a value ending in a real
# trailing newline, an empty value, `=` inside a value, an undocumented
# escape left alone, and absent vs empty) plus round 13b's process-env vs
# file precedence corpus (below).
#
# COMPOSE IS THE ORACLE. When a future review finds a new divergence
# between get_env_value and real `docker compose`, the fix is to ADD A
# CORPUS CASE HERE that reproduces it (red), fix common.sh's awk/shell
# parser to match (green), and leave the case in place — not to re-argue
# what Compose's grammar "should" do from first principles. Round 13b is
# exactly that cycle: this file's own round-13 version documented (rather
# than closed) a divergence where a key defined in BOTH the .env file AND
# the shell's process environment resolved differently here than in real
# Compose (file-first here, shell-env-first in Compose) — codex flagged a
# Compose-parser mismatch on this PR every round from 6 to 12, and a
# documented-but-open divergence was exactly the shape that becomes the
# next one. get_env_value's interpolation now matches Compose's own
# precedence: the process environment wins whenever X is set there (even
# to an empty string, for the non-colon forms — see the process-env-vs-file
# precedence corpus below), falling back to an earlier line in the same
# file only when the environment has no X at all.
#
# Requires `docker compose` (a pure client-side YAML/env merge for
# `config` — no daemon, no image pull, no network) and `python3` (both
# present on this repo's CI runner and expected on any host these scripts
# run on, since restore.sh/upgrade.sh themselves require docker compose).
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)" # scripts/

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required for this oracle test (not found on PATH)" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required for this oracle test (not found on PATH)" >&2
  exit 1
fi

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

COMPOSE_YML="$WORK/oracle-compose.yml"

# Resolves KEY against FILE via REAL Docker Compose: writes a minimal
# compose file with one service whose environment sets `X: ${KEY}`, then
# `docker compose --env-file FILE config --format json`. JSON, not the
# plain `--environment` KEY=VALUE dump, because a decoded value can
# legitimately contain an embedded literal newline (a decoded `\n`) that a
# bare KEY=VALUE text line cannot represent unambiguously — JSON encodes it
# as a safe `\n` escape inside the string.
_compose_resolve_json() {
  _crj_key="$1"
  _crj_file="$2"
  cat > "$COMPOSE_YML" <<YML
services:
  svc:
    image: busybox
    environment:
      X: \${${_crj_key}}
YML
  docker compose -f "$COMPOSE_YML" --env-file "$_crj_file" config --format json 2>/dev/null
}

# Prints Compose's resolved value for KEY in FILE. Sentinel-protected (see
# scripts/lib/common.sh's own P2 fix this round) so a real trailing
# newline in the resolved value survives this capture too.
_compose_value() {
  _cv_json="$(_compose_resolve_json "$1" "$2" && printf x)" || { printf ''; return 1; }
  _cv_json="${_cv_json%x}"
  printf '%s' "$_cv_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
val = data["services"]["svc"]["environment"].get("X")
sys.stdout.write(val if val is not None else "")
'
}

# get_env_value's own resolution, in a subshell so sourcing common.sh never
# leaks its variables/functions into this test script.
_our_value() {
  ( . "$REPO_ROOT/lib/common.sh" && get_env_value "$1" "$2" )
}

# Compares get_env_value's resolution of KEY in FILE against Compose's own.
# Both captures are sentinel-protected so neither side loses a real
# trailing newline before the comparison even runs.
_assert_matches_compose() {
  _amc_key="$1"
  _amc_file="$2"
  _amc_desc="$3"

  _amc_ours="$(_our_value "$_amc_key" "$_amc_file" && printf x)"
  _amc_ours_rc=$?
  _amc_ours="${_amc_ours%x}"

  if [ "$_amc_ours_rc" -ne 0 ]; then
    bad "$_amc_desc (get_env_value itself failed unexpectedly, rc=$_amc_ours_rc)"
    return
  fi

  _amc_theirs="$(_compose_value "$_amc_key" "$_amc_file" && printf x)" || {
    bad "$_amc_desc (docker compose config itself failed to resolve $_amc_key)"
    return
  }
  _amc_theirs="${_amc_theirs%x}"

  if [ "$_amc_ours" = "$_amc_theirs" ]; then
    ok "$_amc_desc (both resolve to [$_amc_ours])"
  else
    bad "$_amc_desc (get_env_value=[$_amc_ours] Compose=[$_amc_theirs])"
  fi
}

# ============================================================================
# Corpus — one .env per case family, one key each, mirroring the fixtures
# already pinned (without a live Compose comparison) in
# test-restore-env-sourcing-safety.sh.
# ============================================================================

# BOM (round 11 audit + CI round 12 fix).
BOM_ENV="$WORK/.env.bom"
printf '\357\273\277POSTGRES_DB=geolens\n' > "$BOM_ENV"
_assert_matches_compose POSTGRES_DB "$BOM_ENV" \
  "BOM-prefixed single-line .env"

# A comment following the closing quote (round 2).
COMMENT_ENV="$WORK/.env.comment"
printf 'COMPOSE_FILE="docker-compose.prod.yml" # production\n' > "$COMMENT_ENV"
_assert_matches_compose COMPOSE_FILE "$COMMENT_ENV" \
  "a double-quoted value followed by a trailing comment"

# Escapes: \t and \n mid-value (round 10), \\ (round 9/10), an undocumented
# escape left alone (round 10).
ESCAPE_ENV="$WORK/.env.escapes"
cat > "$ESCAPE_ENV" <<EOF
DB_TAB="geo\\tlens"
DB_NL="line1\\nline2"
PURE_BACKSLASH="a\\\\b"
DOUBLE_UNKNOWN_ESCAPE="a\\db"
EOF
_assert_matches_compose DB_TAB "$ESCAPE_ENV" "a double-quoted \\t escape"
_assert_matches_compose DB_NL "$ESCAPE_ENV" "a double-quoted \\n escape"
_assert_matches_compose PURE_BACKSLASH "$ESCAPE_ENV" "a double-quoted \\\\ escape"
_assert_matches_compose DOUBLE_UNKNOWN_ESCAPE "$ESCAPE_ENV" \
  "an undocumented double-quoted escape (\\d) is left completely unchanged"

# Sibling interpolation with an outer bound that must NOT narrow between
# tokens (round 13, review 5103870781, P2 #1).
SIBLING_ENV="$WORK/.env.sibling"
cat > "$SIBLING_ENV" <<'EOF'
A=alpha
B=beta
POSTGRES_DB="${A}_${B}"
EOF
_assert_matches_compose POSTGRES_DB "$SIBLING_ENV" \
  "sibling \${A} and \${B} tokens in the same value"

# Chained interpolation with an intervening redefinition (round 11 audit).
CHAIN_ENV="$WORK/.env.chain"
cat > "$CHAIN_ENV" <<'EOF'
C=orig
B="${C}"
C=updated
A="${B}"
EOF
_assert_matches_compose A "$CHAIN_ENV" \
  "chained \${VAR} reference (A references B references the pre-redefinition C)"
_assert_matches_compose B "$CHAIN_ENV" \
  "chained \${VAR} reference resolved directly (B references the pre-redefinition C)"

# A referenced value containing a decoded literal newline (round 13, P2 #2:
# used to be built into a sed program and break it).
NLREF_ENV="$WORK/.env.nlref"
printf 'DB_NAME="prod\\narchive"\nPOSTGRES_DB="${DB_NAME}_suffix"\n' > "$NLREF_ENV"
_assert_matches_compose POSTGRES_DB "$NLREF_ENV" \
  "a referenced value containing a decoded literal newline"

# A value ending in a real trailing newline (round 13, P2 #3: used to be
# stripped by an unprotected \$(...) capture inside get_env_value itself).
TRAILING_ENV="$WORK/.env.trailing"
printf 'TRAILING_NL="geo\\n"\n' > "$TRAILING_ENV"
_assert_matches_compose TRAILING_NL "$TRAILING_ENV" \
  "a value ending in a real trailing newline"

# `=` inside unquoted and single-quoted values (round 6/9).
EQUALS_ENV="$WORK/.env.equals"
cat > "$EQUALS_ENV" <<EOF
UNQUOTED_HAS_EQUALS=a=b
SINGLE_HAS_EQUALS='a=b'
EOF
_assert_matches_compose UNQUOTED_HAS_EQUALS "$EQUALS_ENV" \
  "an unquoted value containing '='"
_assert_matches_compose SINGLE_HAS_EQUALS "$EQUALS_ENV" \
  "a single-quoted value containing '='"

# Present-but-empty (round 6) — get_env_value and Compose agree here (both
# resolve to "", exit/rc 0).
EMPTY_ENV="$WORK/.env.empty"
printf 'PRESENT_EMPTY=\n' > "$EMPTY_ENV"
_assert_matches_compose PRESENT_EMPTY "$EMPTY_ENV" \
  "a key present with an explicitly empty value"

# ============================================================================
# Absent vs empty (round 6) — the ONE place get_env_value and Compose
# deliberately DIVERGE, already documented at the top of common.sh: a key
# entirely missing from the file is rc=1/no-output from get_env_value (so
# restore.sh/check-env.sh can tell "absent" apart from "present but
# empty"), whereas Compose itself has no such channel and resolves an
# absent reference to "" with a stderr warning. Verified directly instead
# of through _assert_matches_compose, which assumes agreement.
# ============================================================================
if _absent_val="$(_our_value MISSING_KEY "$EMPTY_ENV")"; then
  bad "get_env_value reports FOUND for a key genuinely absent from the file (got: [$_absent_val])"
else
  ok "get_env_value reports NOT FOUND (rc=1) for a key genuinely absent from the file"
fi

_absent_compose="$(_compose_value MISSING_KEY "$EMPTY_ENV" && printf x)"
_absent_compose="${_absent_compose%x}"
if [ "$_absent_compose" = "" ]; then
  ok "Compose itself resolves that same absent key to an empty string (documented, accepted divergence — not a bug)"
else
  bad "Compose's own absent-key behavior changed (got: [$_absent_compose]) — the top-of-file divergence note in common.sh needs re-checking"
fi

# ============================================================================
# Process-env vs .env-file precedence (round 13b, follow-up to round 13's
# review 5103870781) — codex flagged a Compose-parser mismatch on this PR
# every round from 6 to 12; round 13's own oracle test shipped with this
# EXACT divergence merely documented rather than closed, which is exactly
# the shape that becomes the next P2. Verified through the real oracle
# (never reasoned about from first principles): Compose's process
# environment wins whenever the referenced key is SET there — even to an
# empty string, for the plain `${X}`/`${X-d}` forms — falling back to an
# earlier line in the SAME .env file only when the environment has no X at
# all. `export`/`unset` bracket each case so both get_env_value's own
# lookup and the real `docker compose` invocation below it see the exact
# same process environment.
# ============================================================================
PREC_ENV="$WORK/.env.precedence"
cat > "$PREC_ENV" <<'EOF'
TARGETVAR=fromfile
USES_PLAIN="${TARGETVAR}"
USES_COLON_DASH="${TARGETVAR:-fallback}"
USES_DASH="${TARGETVAR-fallback}"
USES_UNSET_COLON_DASH="${NOFILEVAR:-fallback}"
EOF

export TARGETVAR=fromenv
_assert_matches_compose USES_PLAIN "$PREC_ENV"   "env set (fromenv) + file key also set (fromfile): the process environment wins"
unset TARGETVAR

export TARGETVAR=
_assert_matches_compose USES_COLON_DASH "$PREC_ENV"   "env set but EMPTY + \${X:-default}: the colon form treats empty-and-set as unset, so the default applies"
_assert_matches_compose USES_DASH "$PREC_ENV"   "env set but EMPTY + \${X-default}: the non-colon form does NOT treat empty-and-set as unset, so the empty value wins over the default"
unset TARGETVAR

_assert_matches_compose USES_PLAIN "$PREC_ENV"   "env unset + file key set (fromfile): falls back to the file"

_assert_matches_compose USES_UNSET_COLON_DASH "$PREC_ENV"   "env unset + file key also unset + \${X:-default}: the default applies"

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

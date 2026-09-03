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

# fix(#1798 review round 14, review 5104197320): `docker compose config
# --format json` (the mechanism _compose_value/_compose_resolve_json use)
# was found NOT to resolve a literal `$` faithfully — it appears to
# defensively RE-ESCAPE any literal, non-interpolated `$` back into `$$`
# in its OWN serialized output, rather than show the value a real
# container would actually receive. Verified by hand while writing this
# round's corpus: `PASS=a$$b` read through `${PASS}` via `--format json`
# comes back UNCHANGED as `a$$b` (the escape never resolves), while a
# genuinely bare, single `$5` in a value comes back as `$$5` (a literal
# dollar sign gets DOUBLED in the output) — both wrong in OPPOSITE
# directions. `docker compose config --environment` and a REAL running
# container's own environment agree with each other on every one of these
# cases (cross-checked via `docker compose run --rm` with `command:
# ["sh","-c","echo [$$REALTEST]"]` reading a real container's env) and
# NEITHER matches `--format json`. So any corpus case whose EXPECTED value
# contains a literal `$` uses this helper (backed by `--environment`)
# instead of _compose_value/_assert_matches_compose. `--environment`'s own
# limitation — a bare `KEY=VALUE` text dump cannot represent a value
# containing a real embedded newline unambiguously — does not apply to any
# case in this section, so it is not a regression from the JSON approach
# there.
_compose_dollar_value() {
  _cdv_key="$1"
  _cdv_file="$2"
  _cdv_yml="$WORK/oracle-dollar-compose.yml"
  cat > "$_cdv_yml" <<YML
services:
  svc:
    image: busybox
YML
  _cdv_out="$(docker compose -f "$_cdv_yml" --env-file "$_cdv_file" config --environment 2>/dev/null && printf x)" || { printf ''; return 1; }
  _cdv_out="${_cdv_out%x}"
  # fix(#1798 review round 14, review 5104197320): a `grep`-matched line
  # carries its OWN trailing newline — capturing that raw into the
  # sentinel-protected _amcd_theirs above would leave a spurious trailing
  # `\n` on every value here (none of round 14's $-corpus values are
  # meant to end in one). Capturing the grep result through ITS OWN
  # `$(...)` strips exactly that one, incidental newline; parameter
  # expansion (not sed) removes the "KEY=" prefix so a key name is never
  # treated as a sed/regex pattern.
  _cdv_line="$(printf '%s\n' "$_cdv_out" | grep "^${_cdv_key}=")"
  printf '%s' "${_cdv_line#"${_cdv_key}="}"
}

# Same shape as _assert_matches_compose, backed by _compose_dollar_value.
_assert_matches_compose_dollar() {
  _amcd_key="$1"
  _amcd_file="$2"
  _amcd_desc="$3"

  _amcd_ours="$(_our_value "$_amcd_key" "$_amcd_file" && printf x)"
  _amcd_ours_rc=$?
  _amcd_ours="${_amcd_ours%x}"

  if [ "$_amcd_ours_rc" -ne 0 ]; then
    bad "$_amcd_desc (get_env_value itself failed unexpectedly, rc=$_amcd_ours_rc)"
    return
  fi

  _amcd_theirs="$(_compose_dollar_value "$_amcd_key" "$_amcd_file" && printf x)" || {
    bad "$_amcd_desc (docker compose config --environment itself failed to resolve $_amcd_key)"
    return
  }
  _amcd_theirs="${_amcd_theirs%x}"

  if [ "$_amcd_ours" = "$_amcd_theirs" ]; then
    ok "$_amcd_desc (both resolve to [$_amcd_ours])"
  else
    bad "$_amcd_desc (get_env_value=[$_amcd_ours] Compose(--environment)=[$_amcd_theirs])"
  fi
}

# For a key/file pair where BOTH get_env_value and real Compose are
# expected to FAIL (a required-but-missing ${VAR:?msg}/${VAR?msg}, or a
# genuinely unterminated ${VAR construct with no closing brace anywhere) —
# asserts get_env_value's own exit code is non-zero, AND separately
# confirms the compose oracle itself fails to resolve the same key/file
# (a live `docker compose config` invocation), so the pinned expectation
# is anchored to the oracle's actual behavior rather than an assumption
# that it "surely errors".
_assert_errors_like_compose() {
  _aelc_key="$1"
  _aelc_file="$2"
  _aelc_desc="$3"

  if _our_value "$_aelc_key" "$_aelc_file" >/dev/null 2>&1; then
    bad "$_aelc_desc (get_env_value succeeded, expected it to fail closed)"
    return
  fi

  _aelc_compose_rc=0
  _compose_resolve_json "$_aelc_key" "$_aelc_file" >/dev/null 2>&1 || _aelc_compose_rc=$?
  if [ "$_aelc_compose_rc" -eq 0 ]; then
    bad "$_aelc_desc (get_env_value failed closed, but real Compose did NOT — the pinned expectation may be wrong)"
    return
  fi

  ok "$_aelc_desc (both get_env_value and Compose itself fail to resolve it)"
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


# ============================================================================
# Round 14 (review 5104197320) — closes the WHOLE Compose interpolation
# grammar (https://docs.docker.com/reference/compose-file/interpolation/)
# in one push, not just the `${VAR:+alt}`/`${VAR+alt}` forms the round 13b
# verdict flagged. Codex had paid a round per operator since round 6; every
# case below was let the oracle decide, never reasoned about from the
# docs' prose alone — several turned out subtler than the docs describe
# (see the brace-matching and $$ notes below).
# ============================================================================

# --- ${VAR:+alt} / ${VAR+alt} — the alternative-value forms round 13b left
# out. Mirrors the round 13b precedence corpus shape (set-nonempty,
# set-empty, unset; the colon form treats set-but-empty as unset, the
# non-colon form does not).
PLUS_ENV="$WORK/.env.plus"
cat > "$PLUS_ENV" <<'EOF'
NONEMPTY=nonempty
EMPTYVAL=
USES_COLON_PLUS_SET="${NONEMPTY:+wasSet}"
USES_COLON_PLUS_EMPTY="${EMPTYVAL:+wasSet}"
USES_COLON_PLUS_UNSET="${TOTALLY_UNSET_XYZ:+wasSet}"
USES_PLUS_SET="${NONEMPTY+wasSet}"
USES_PLUS_EMPTY="${EMPTYVAL+wasSet}"
USES_PLUS_UNSET="${TOTALLY_UNSET_XYZ+wasSet}"
EOF
_assert_matches_compose USES_COLON_PLUS_SET "$PLUS_ENV" \
  "\${VAR:+alt}, VAR set non-empty: alt is used"
_assert_matches_compose USES_COLON_PLUS_EMPTY "$PLUS_ENV" \
  "\${VAR:+alt}, VAR set but EMPTY: the colon form treats empty as unset, alt NOT used"
_assert_matches_compose USES_COLON_PLUS_UNSET "$PLUS_ENV" \
  "\${VAR:+alt}, VAR unset: alt NOT used"
_assert_matches_compose USES_PLUS_SET "$PLUS_ENV" \
  "\${VAR+alt}, VAR set non-empty: alt is used"
_assert_matches_compose USES_PLUS_EMPTY "$PLUS_ENV" \
  "\${VAR+alt}, VAR set but EMPTY: the non-colon form does NOT treat empty as unset, alt IS used"
_assert_matches_compose USES_PLUS_UNSET "$PLUS_ENV" \
  "\${VAR+alt}, VAR unset: alt NOT used"

# ${VAR:+alt} interacting with round 13b's env-over-file precedence: the
# "is VAR set" check for +/​:+ must use the SAME precedence as everything
# else — process environment first.
PLUS_PREC_ENV="$WORK/.env.plusprecedence"
cat > "$PLUS_PREC_ENV" <<'EOF'
USES_ENV_ONLY="${PRECVAR:+wasSet}"
EOF
PLUS_PREC_ENV2="$WORK/.env.plusprecedence2"
cat > "$PLUS_PREC_ENV2" <<'EOF'
PRECVAR=fromfile
USES_FILE_AND_ENV="${PRECVAR:+wasSet}"
EOF
export PRECVAR=fromenv
_assert_matches_compose USES_ENV_ONLY "$PLUS_PREC_ENV" \
  "\${VAR:+alt}, VAR set ONLY in the process environment (absent from the file): alt is used"
unset PRECVAR
export PRECVAR=
_assert_matches_compose USES_FILE_AND_ENV "$PLUS_PREC_ENV2" \
  "\${VAR:+alt}, VAR non-empty in the file but EMPTY in the environment: environment wins, alt NOT used"
unset PRECVAR

# --- ${VAR:?err} / ${VAR?err} — the required-or-error forms. Compose
# itself hard-fails loading a file shaped like this (verified: "required
# variable ... is missing a value" from a live `docker compose config`),
# so get_env_value must fail non-zero to match — this pins the EXIT CODE,
# not a value, for the failing cases.
# fix(#1798 review round 14, review 5104197320): unlike get_env_value
# (which resolves a SINGLE key's own line, lazily), real Compose validates
# an ENTIRE .env file up front — a required-and-missing ${VAR:?msg} on ANY
# line fails loading the WHOLE file, so querying a DIFFERENT, perfectly
# resolvable key through the SAME file also fails on the Compose side (not
# because that key itself is broken, but because a sibling line is). Each
# case below therefore gets its own minimal file, so a "should succeed"
# key is never sharing a file with a line that fails to load for an
# unrelated reason.
REQ_COLON_SET_ENV="$WORK/.env.req_colon_set"
printf 'NONEMPTY=nonempty\nUSES_COLON_Q_SET="${NONEMPTY:?missing message}"\n' > "$REQ_COLON_SET_ENV"
_assert_matches_compose USES_COLON_Q_SET "$REQ_COLON_SET_ENV" \
  "\${VAR:?err}, VAR set non-empty: resolves to VAR's value, no error"

REQ_COLON_EMPTY_ENV="$WORK/.env.req_colon_empty"
printf 'EMPTYVAL=\nUSES_COLON_Q_EMPTY="${EMPTYVAL:?missing message}"\n' > "$REQ_COLON_EMPTY_ENV"
_assert_errors_like_compose USES_COLON_Q_EMPTY "$REQ_COLON_EMPTY_ENV" \
  "\${VAR:?err}, VAR set but EMPTY: the colon form treats empty as missing, get_env_value fails"

REQ_COLON_UNSET_ENV="$WORK/.env.req_colon_unset"
printf 'USES_COLON_Q_UNSET="${TOTALLY_UNSET_XYZ:?missing message}"\n' > "$REQ_COLON_UNSET_ENV"
_assert_errors_like_compose USES_COLON_Q_UNSET "$REQ_COLON_UNSET_ENV" \
  "\${VAR:?err}, VAR unset: get_env_value fails"

REQ_SET_ENV="$WORK/.env.req_set"
printf 'NONEMPTY=nonempty\nUSES_Q_SET="${NONEMPTY?missing message}"\n' > "$REQ_SET_ENV"
_assert_matches_compose USES_Q_SET "$REQ_SET_ENV" \
  "\${VAR?err}, VAR set non-empty: resolves to VAR's value, no error"

REQ_EMPTY_ENV="$WORK/.env.req_empty"
printf 'EMPTYVAL=\nUSES_Q_EMPTY="${EMPTYVAL?missing message}"\n' > "$REQ_EMPTY_ENV"
_assert_matches_compose USES_Q_EMPTY "$REQ_EMPTY_ENV" \
  "\${VAR?err}, VAR set but EMPTY: the non-colon form does NOT treat empty as missing, resolves to empty"

REQ_UNSET_ENV="$WORK/.env.req_unset"
printf 'USES_Q_UNSET="${TOTALLY_UNSET_XYZ?missing message}"\n' > "$REQ_UNSET_ENV"
_assert_errors_like_compose USES_Q_UNSET "$REQ_UNSET_ENV" \
  "\${VAR?err}, VAR unset: get_env_value fails"

# --- $$ literal escape — `docker compose config --format json` does NOT
# resolve this faithfully (see _compose_dollar_value's own doc comment for
# the full empirical finding: it re-escapes a literal `$` in either
# direction in its own output); every case here goes through
# _assert_matches_compose_dollar (`--environment`, cross-checked by hand
# against a real running container) instead.
DOLLAR_ENV="$WORK/.env.dollar"
cat > "$DOLLAR_ENV" <<'EOF'
PASSVAL=a$$b
EOF
_assert_matches_compose_dollar PASSVAL "$DOLLAR_ENV" \
  "\$\$ collapses to a single literal \$ (PASS=a\$\$b -> a\$b)"

DOLLAR_BRACE_ENV="$WORK/.env.dollarbrace"
cat > "$DOLLAR_BRACE_ENV" <<'EOF'
MSGVAL="pre$${SOMEVAR}post"
EOF
_assert_matches_compose_dollar MSGVAL "$DOLLAR_BRACE_ENV" \
  "\$\$ immediately adjacent to a { also collapses, leaving a literal (non-interpolated) \${SOMEVAR}"

DOLLAR_RESCAN_ENV="$WORK/.env.dollarrescan"
cat > "$DOLLAR_RESCAN_ENV" <<'EOF'
realvar=REALVALUE
USESVAL=pre$$realvartail
EOF
_assert_matches_compose_dollar USESVAL "$DOLLAR_RESCAN_ENV" \
  "text left over after un-escaping \$\$ is not re-scanned as a fresh reference, even when it happens to name a real variable"

# --- Nested defaults/alt-values — ${A:-${B:-x}} and ${A:+${B}}.
NESTED_ENV="$WORK/.env.nested"
cat > "$NESTED_ENV" <<'EOF'
BVAL=bval
AVAL=aval
USES_BOTH_UNSET="${NESTED_A_XYZ:-${NESTED_B_XYZ:-x}}"
USES_INNER_SET="${NESTED_A_XYZ:-${BVAL:-x}}"
USES_OUTER_SET="${AVAL:-${NESTED_B_XYZ:-x}}"
USES_PLUS_INNER_SET="${AVAL:+${BVAL}}"
USES_PLUS_OUTER_UNSET="${NESTED_A_XYZ:+${BVAL}}"
EOF
_assert_matches_compose USES_BOTH_UNSET "$NESTED_ENV" \
  "nested \${A:-\${B:-x}}, both A and B unset: resolves to the innermost default"
_assert_matches_compose USES_INNER_SET "$NESTED_ENV" \
  "nested \${A:-\${B:-x}}, A unset but B set: resolves to B's value"
_assert_matches_compose USES_OUTER_SET "$NESTED_ENV" \
  "nested \${A:-\${B:-x}}, A set: resolves to A's value (inner default never evaluated)"
_assert_matches_compose USES_PLUS_INNER_SET "$NESTED_ENV" \
  "nested \${A:+\${B}}, A set non-empty: resolves to B's value"
_assert_matches_compose USES_PLUS_OUTER_UNSET "$NESTED_ENV" \
  "nested \${A:+\${B}}, A unset: resolves to empty (alt never evaluated)"

# --- A default's own text containing a literal `}` inside a quoted value.
# Compose's own brace-matching (verified empirically, NOT the naive
# "stop at the first }" this repo's OWN earlier interpolation code used)
# counts every literal `{`/`}` toward a depth starting at 1 for the
# already-consumed opening `${`, closing at the first point depth returns
# to 0 — this is what lets a nested `${...}` reference close at the
# correct outer `}` instead of the inner one's.
BRACE_ENV="$WORK/.env.bracetext"
cat > "$BRACE_ENV" <<'EOF'
USES_BALANCED="${BRACE_UNSET_XYZ:-{foo}bar}"
USES_TRAILING_LITERAL="${BRACE_UNSET_XYZ:-x}extra}"
EOF
_assert_matches_compose USES_BALANCED "$BRACE_ENV" \
  "a default's own text may contain a balanced { } pair; the default runs to the OUTER (matching) close"
_assert_matches_compose USES_TRAILING_LITERAL "$BRACE_ENV" \
  "a } immediately after the default's own close is literal SUFFIX text, not part of the default"

# --- An unterminated ${VAR (no closing brace anywhere) and a bare $
# followed by a non-name character. "Whatever the oracle does" turned out
# to be two different answers: a genuinely unterminated ${ construct is a
# hard parse failure (Compose's own .env-file load errors, "Invalid
# template"); a bare $ that simply isn't followed by `$`, `{`, or a
# name-start character is left completely alone as literal text.
UNTERM_ENV="$WORK/.env.unterminated"
cat > "$UNTERM_ENV" <<'EOF'
SETVAR=setval
USES_UNTERM_SET=pre${SETVAR
USES_UNTERM_UNSET=pre${UNTERM_UNSET_XYZ
EOF
_assert_errors_like_compose USES_UNTERM_SET "$UNTERM_ENV" \
  "an unterminated \${VAR (no closing brace anywhere), the referenced name IS set: still a hard failure"
_assert_errors_like_compose USES_UNTERM_UNSET "$UNTERM_ENV" \
  "an unterminated \${VAR (no closing brace anywhere), the referenced name is unset: still a hard failure"

BAREDOLLAR_ENV="$WORK/.env.baredollar"
cat > "$BAREDOLLAR_ENV" <<'EOF'
USES_DIGIT=pre$5post
USES_SPACE="pre$ post"
USES_TRAILING=pre$
EOF
_assert_matches_compose_dollar USES_DIGIT "$BAREDOLLAR_ENV" \
  "a bare \$ followed by a digit is left completely unchanged"
_assert_matches_compose_dollar USES_SPACE "$BAREDOLLAR_ENV" \
  "a bare \$ followed by a space is left completely unchanged"
_assert_matches_compose_dollar USES_TRAILING "$BAREDOLLAR_ENV" \
  "a bare \$ at the very end of a value is left completely unchanged"

# --- Single-quoted values are never interpolated at all, `$$` and
# `${VAR}` alike (round 14 explicitly re-confirms this against the
# oracle, using the \$-aware helper since the pinned value itself
# contains a literal \$).
SINGLEQ_ENV="$WORK/.env.singlequote"
cat > "$SINGLEQ_ENV" <<'EOF'
SETVAR=setval
USESVAL='${SETVAR}'
EOF
_assert_matches_compose_dollar USESVAL "$SINGLEQ_ENV" \
  "a single-quoted value is never interpolated, even when it looks exactly like a reference to a SET variable"

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

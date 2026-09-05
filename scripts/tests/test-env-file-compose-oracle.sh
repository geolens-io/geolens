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

# fix(#1798 review round 15, P2, review 5104520795): the interface real
# callers (restore.sh/check-env.sh/upgrade.sh) now use is env_value_into,
# not get_env_value's own stdout return -- a plain `VAR="$(get_env_value
# ...)"` at the CALL SITE stripped a trailing decoded newline all over
# again even after get_env_value's own round-13 fix started preserving
# one internally, since ordinary command substitution always strips a
# trailing newline regardless of what the command inside it does.
# Exercises that ACTUAL caller path (source common.sh, call
# env_value_into into a scratch variable, THEN read the variable) rather
# than get_env_value directly, so a regression in env_value_into itself
# -- not just in get_env_value -- would be caught here.
_our_value_via_env_value_into() {
  # shellcheck disable=SC2154  # _test_target is assigned by env_value_into's
  # own `eval` (scripts/lib/common.sh), which shellcheck cannot trace
  # through a dynamically sourced file.
  ( . "$REPO_ROOT/lib/common.sh" && env_value_into _test_target "$1" "$2" && printf '%s' "$_test_target" )
}

# effective_env_value_into's resolution, the same way: source in a subshell,
# assign into a scratch variable, read it back.
_our_effective_value() {
  # shellcheck disable=SC2154  # _test_effective is assigned by the eval
  # inside effective_env_value_into (scripts/lib/common.sh).
  ( . "$REPO_ROOT/lib/common.sh" && effective_env_value_into _test_effective "$1" "$2" && printf '%s' "$_test_effective" )
}

# fix(#1886): a top-level ${KEY} resolves from the process environment first,
# so this compares effective_env_value_into against the oracle (get_env_value
# keeps its file-only contract and is not what preflight-env.sh reads).
_assert_effective_matches_compose() {
  _aem_key="$1"
  _aem_file="$2"
  _aem_desc="$3"

  _aem_ours="$(_our_effective_value "$_aem_key" "$_aem_file" && printf x)"
  _aem_ours_rc=$?
  _aem_ours="${_aem_ours%x}"

  if [ "$_aem_ours_rc" -ne 0 ]; then
    bad "$_aem_desc (effective_env_value_into itself failed unexpectedly, rc=$_aem_ours_rc)"
    return
  fi

  _aem_theirs="$(_compose_value "$_aem_key" "$_aem_file" && printf x)" || {
    bad "$_aem_desc (docker compose config itself failed to resolve $_aem_key)"
    return
  }
  _aem_theirs="${_aem_theirs%x}"

  if [ "$_aem_ours" = "$_aem_theirs" ]; then
    ok "$_aem_desc (both resolve to [$_aem_ours])"
  else
    bad "$_aem_desc (effective_env_value_into=[$_aem_ours] Compose=[$_aem_theirs])"
  fi
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

# fix(#1778 round 22, P2): _compose_value/_assert_matches_compose cannot
# distinguish "KEY is genuinely UNSET" from "KEY is SET to an empty
# string" -- a direct ${KEY} query collapses both to the same JSON "" (a
# real, separately-confirmed Compose behavior: querying an unset name
# directly prints a "variable is not set" WARNING on stderr but still
# resolves to "" in the JSON body, identical to a name actually set to
# "" -- case 74's own original assertion was built on that collapsed
# value and got the wrong idea about which state it was even measuring).
#
# The `-` vs `:-` operator pair distinguishes them without that
# ambiguity: `-` substitutes its fallback ONLY when the name is
# genuinely UNSET; `:-` ALSO substitutes when the name is SET but empty.
# Comparing both pins all three states from two data points, which is
# more robust than trusting a single sentinel string to never coincide
# with a real value:
#   unset:         `-`-probe = SENTINEL,  `:-`-probe = SENTINEL
#   set empty:     `-`-probe = "",        `:-`-probe = SENTINEL
#   set non-empty: `-`-probe = the value, `:-`-probe = the value
_COMPOSE_PRESENCE_SENTINEL="__R22_PRESENCE_SENTINEL__"
_compose_presence_probe() {
  _cpp_key="$1"
  _cpp_op="$2"
  _cpp_file="$3"
  cat > "$COMPOSE_YML" <<YML
services:
  svc:
    image: busybox
    environment:
      X: \${${_cpp_key}${_cpp_op}${_COMPOSE_PRESENCE_SENTINEL}}
YML
  _cpp_json="$(docker compose -f "$COMPOSE_YML" --env-file "$_cpp_file" config --format json 2>/dev/null && printf x)" || { printf ''; return 1; }
  _cpp_json="${_cpp_json%x}"
  printf '%s' "$_cpp_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
val = data["services"]["svc"]["environment"].get("X")
sys.stdout.write(val if val is not None else "")
'
}

# Prints "unset", "empty", or "nonempty" -- Compose'"'"'s TRUE presence state
# for KEY in FILE, per the probe pair above.
_compose_presence() {
  _cprs_dash="$(_compose_presence_probe "$1" "-" "$2")"
  _cprs_colondash="$(_compose_presence_probe "$1" ":-" "$2")"
  if [ "$_cprs_dash" = "$_COMPOSE_PRESENCE_SENTINEL" ] && [ "$_cprs_colondash" = "$_COMPOSE_PRESENCE_SENTINEL" ]; then
    printf 'unset'
  elif [ "$_cprs_colondash" = "$_COMPOSE_PRESENCE_SENTINEL" ]; then
    printf 'empty'
  else
    printf 'nonempty'
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

# fix(#1886): the key ITSELF, not a reference to it, resolves the same way
# for a plain ${TARGETVAR}; this is the read preflight-env.sh now performs.
export TARGETVAR=fromenv
_assert_effective_matches_compose TARGETVAR "$PREC_ENV"   "env set (fromenv) + the same key in the file (fromfile): effective_env_value_into takes the environment, like Compose"
unset TARGETVAR

export TARGETVAR=
_assert_effective_matches_compose TARGETVAR "$PREC_ENV"   "env set but EMPTY + the same key in the file: the empty environment value wins over the file line"
unset TARGETVAR

_assert_effective_matches_compose TARGETVAR "$PREC_ENV"   "env unset + the key in the file: effective_env_value_into falls back to the file line"


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


# ============================================================================
# Round 15 (review 5104520795) P2 #1 -- the caller-side trailing-newline
# gap: get_env_value preserves a trailing decoded newline internally
# (round 13), but every ACTUAL caller assigned via
# `_v="$(get_env_value ...)"`, and plain command substitution strips a
# trailing newline regardless of what get_env_value itself does. Fixed at
# the interface (env_value_into, scripts/lib/common.sh) rather than per
# caller. This corpus case exercises that real interface end to end, not
# get_env_value directly -- POSTGRES_DB is the exact key restore.sh reads
# through it.
# ============================================================================
CALLER_NL_ENV="$WORK/.env.caller_nl"
printf 'POSTGRES_DB="geo\\n"\n' > "$CALLER_NL_ENV"

CALLER_NL_OURS="$(_our_value_via_env_value_into POSTGRES_DB "$CALLER_NL_ENV" && printf x)"
CALLER_NL_OURS_RC=$?
CALLER_NL_OURS="${CALLER_NL_OURS%x}"

if [ "$CALLER_NL_OURS_RC" -ne 0 ]; then
  bad "POSTGRES_DB with a trailing decoded newline, resolved through env_value_into (env_value_into itself failed unexpectedly, rc=$CALLER_NL_OURS_RC)"
else
  CALLER_NL_THEIRS="$(_compose_value POSTGRES_DB "$CALLER_NL_ENV" && printf x)" || {
    bad "POSTGRES_DB with a trailing decoded newline, resolved through env_value_into (docker compose config itself failed to resolve POSTGRES_DB)"
  }
  CALLER_NL_THEIRS="${CALLER_NL_THEIRS%x}"

  if [ "$CALLER_NL_OURS" = "$CALLER_NL_THEIRS" ]; then
    ok "POSTGRES_DB with a trailing decoded newline, resolved through env_value_into (the ACTUAL caller path restore.sh uses), equals the oracle byte for byte"
  else
    bad "POSTGRES_DB with a trailing decoded newline, resolved through env_value_into (ours=[$CALLER_NL_OURS] Compose=[$CALLER_NL_THEIRS])"
  fi
fi


# ============================================================================
# Round 15 (review 5104520795) P2 #2 -- the fixed recursion cap (5) used
# to truncate a valid ACYCLIC chain longer than that, and did not actually
# protect against the one case that genuinely can loop forever: a value
# sourced from the PROCESS ENVIRONMENT, which has no file line number to
# bound recursion against. Replaced with real cycle detection (a
# space-delimited chain of names currently being expanded, threaded
# through _env_interp_resolve/_env_resolve_name) -- a chain now resolves
# to any depth, and only an ACTUAL name recurring in its own resolution
# stops it.
# ============================================================================

# A chain of 8 hops, all acyclic -- the old fixed cap of 5 truncated this
# and returned the literal, unresolved ${C7} instead of the real value.
CHAIN8_ENV="$WORK/.env.chain8"
cat > "$CHAIN8_ENV" <<'EOF'
C1=leafval
C2=${C1}
C3=${C2}
C4=${C3}
C5=${C4}
C6=${C5}
C7=${C6}
POSTGRES_DB=${C7}
EOF
_assert_matches_compose POSTGRES_DB "$CHAIN8_ENV" \
  "a chain of 8 acyclic hops (C1..C7 -> POSTGRES_DB) resolves fully, not truncated by a fixed pass count"

# Same shape, but the chain ends in a ${VAR:-default} whose VAR is unset --
# the default itself has to survive all 8 hops back out too.
CHAIN8_DEFAULT_ENV="$WORK/.env.chain8default"
cat > "$CHAIN8_DEFAULT_ENV" <<'EOF'
C2=${CHAIN8_UNSET_XYZ:-defaultatend}
C3=${C2}
C4=${C3}
C5=${C4}
C6=${C5}
C7=${C6}
C8=${C7}
POSTGRES_DB=${C8}
EOF
_assert_matches_compose POSTGRES_DB "$CHAIN8_DEFAULT_ENV" \
  "a chain of 8 hops ending in a \${VAR:-default} resolves the default all the way back out"

# A diamond (A=${B}${C}, B=${D}, C=${D}) is NOT a cycle -- D is referenced
# via two INDEPENDENT sibling paths, not nested inside itself. Cycle
# detection must not confuse "the same name resolved twice, at different
# points" with "the same name resolved from inside its own resolution".
DIAMOND_ENV="$WORK/.env.diamond"
cat > "$DIAMOND_ENV" <<'EOF'
D=leafval
B=${D}
C=${D}
A=${B}${C}
EOF
_assert_matches_compose A "$DIAMOND_ENV" \
  "a diamond reference (A=\${B}\${C}, B=\${D}, C=\${D}) is not a cycle and resolves fully"

# A self-cycle with an operator that has its own "not found" fallback
# ALREADY matches Compose exactly -- verified via the oracle, a cycle is
# NOT an error there; Compose treats a cyclic reference exactly like an
# ordinary never-defined one (a stderr warning, "the X variable is not
# set"), so whatever that operator already does for "not found" is what
# it does for a cycle too.
SELF_DEFAULT_ENV="$WORK/.env.selfdefault"
printf 'A=${A:-fallback}\n' > "$SELF_DEFAULT_ENV"
_assert_matches_compose A "$SELF_DEFAULT_ENV" \
  "a direct self-cycle \${A:-fallback} resolves to the default, matching Compose exactly (a cycle is treated as unset, not an error)"

SELF_REQUIRED_ENV="$WORK/.env.selfrequired"
printf 'A=${A:?required message}\n' > "$SELF_REQUIRED_ENV"
_assert_errors_like_compose A "$SELF_REQUIRED_ENV" \
  "a direct self-cycle \${A:?msg} fails closed, matching Compose exactly (treated as required-and-unset)"

# A BARE (no-operator) cycle is the ONE place this parser's own
# already-established, deliberate divergence from Compose applies (see
# the top-of-file doc comment on _env_interp_resolve): Compose itself
# resolves an unresolved bare ${VAR} to an EMPTY string with a stderr
# warning; this parser leaves it as the literal, greppable token instead,
# since a caller has no channel to see that warning and a config value
# silently collapsing to empty is a worse failure mode. A cycle is just
# one more way a name can be "not found" via the SAME bare-form handling
# -- verified directly against get_env_value rather than the oracle,
# since the oracle's own answer here is the KNOWN, intentional
# divergence, not a target to match.
SELF_BARE_ENV="$WORK/.env.selfbare"
printf 'A=${A}\n' > "$SELF_BARE_ENV"
SELF_BARE_VAL="$(_our_value A "$SELF_BARE_ENV" && printf x)"
SELF_BARE_RC=$?
SELF_BARE_VAL="${SELF_BARE_VAL%x}"
if [ "$SELF_BARE_RC" -eq 0 ] && [ "$SELF_BARE_VAL" = '${A}' ]; then
  ok "a direct self-cycle \${A} (bare, no operator) leaves the literal token unchanged, this parser's own already-documented divergence from Compose's empty-string-with-warning"
else
  bad "a direct self-cycle \${A} (bare, no operator) regressed (rc=$SELF_BARE_RC val=[$SELF_BARE_VAL], want rc=0 val=[\${A}])"
fi

# A two-node file cycle (A=${B}, B=${A}) -- querying B is the direction
# that actually exercises the NEW chain-based cycle check (querying A
# alone was already safe before this round: B has no earlier-line
# definition relative to A's own line, so the existing bound-narrowing
# rule stops it without any help from cycle detection at all -- querying
# B is what needed the fix, since A DOES have an earlier definition
# relative to B, and resolving THAT exposes B again).
TWOCYCLE_ENV="$WORK/.env.twocycle"
cat > "$TWOCYCLE_ENV" <<'EOF'
A=${B}
B=${A}
EOF
TWOCYCLE_VAL="$(_our_value B "$TWOCYCLE_ENV" && printf x)"
TWOCYCLE_RC=$?
TWOCYCLE_VAL="${TWOCYCLE_VAL%x}"
if [ "$TWOCYCLE_RC" -eq 0 ] && [ "$TWOCYCLE_VAL" = '${B}' ]; then
  ok "a two-node file cycle (A=\${B}, B=\${A}), querying B, terminates instead of recursing forever"
else
  bad "a two-node file cycle, querying B, regressed (rc=$TWOCYCLE_RC val=[$TWOCYCLE_VAL], want rc=0 val=[\${B}])"
fi

# The one case a fixed depth cap actually protected against: a cycle
# sourced entirely from the PROCESS ENVIRONMENT, which has no file line
# number to bound recursion against at all. Two exported variables whose
# literal text values reference each other never terminated on bound
# alone before round 15's real cycle detection.
#
# fix(#1798 review round 18, P2, review 5105652413): the exact expected
# VALUE here was wrong in round 15 — that round only checked this against
# THIS parser's own (then-buggy) implementation, never the real oracle,
# because testing an exported-variable scenario through the oracle needs
# the SAME variables exported in the CURRENT shell before invoking
# `docker compose` as a subprocess, which round 15 didn't set up. Doing
# that now surfaces a real, previously-undiscovered fact: Compose does
# NOT recursively re-interpolate a process-environment-sourced value at
# all — verified directly (an exported `OUTER='${INNER}'` referenced via
# `${OUTER}`, with `INNER` ALSO exported to a real value, resolves to the
# literal `${INNER}`, not INNER's value). A shell env var's value is
# opaque, already-resolved data to Compose, never re-parsed as further
# `.env` syntax the way a FILE line's own value is. That is what actually
# terminates this cycle (each name resolves in exactly one hop, from the
# environment, with nothing left to recurse into) — cycle detection
# (chain tracking) is what protects the case where TWO OR MORE identical
# names would otherwise be resolved from the FILE forever; an
# environment-sourced hop was never actually going to recurse once this
# round's other fix landed, whether or not it happened to repeat a name.
# Uses _assert_matches_compose_dollar (not _assert_matches_compose):
# the expected value here is the literal text "${ENVCYCLE_B_XYZ}" — a
# literal `$`, exactly the content _compose_value/--format json is known
# (round 14) to misrepresent.
ENVCYCLE_ENV="$WORK/.env.envcycle"
printf 'USES="${ENVCYCLE_A_XYZ}"\n' > "$ENVCYCLE_ENV"
export ENVCYCLE_A_XYZ='${ENVCYCLE_B_XYZ}'
export ENVCYCLE_B_XYZ='${ENVCYCLE_A_XYZ}'
_assert_matches_compose_dollar USES "$ENVCYCLE_ENV" \
  "a two-node cycle sourced entirely from the process environment terminates (one substitution per name, never recursed into further)"
unset ENVCYCLE_A_XYZ ENVCYCLE_B_XYZ


# ============================================================================
# Round 16 (review 5104847831) P2 #2 -- Compose allows a quoted .env value
# to span physical lines; the parser used to validate/extract a quoted
# value against its OWN single line only, treating an unterminated same-
# line quote as malformed and returning it literally instead of gathering
# subsequent lines the way Compose itself does.
# ============================================================================

# A single-quoted value spanning two physical lines, joined by a real
# newline -- verified against the oracle byte-for-byte (not assumed).
MULTI_SINGLE_ENV="$WORK/.env.multi_single"
cat > "$MULTI_SINGLE_ENV" <<'EOF'
USES='line1
line2'
EOF
_assert_matches_compose USES "$MULTI_SINGLE_ENV" \
  "a single-quoted value spanning two physical lines joins with a real newline"

# A double-quoted value spanning THREE physical lines, with a literal \n
# escape ALSO present inside it -- both the escape and the real
# physical-line joins must decode to the identical newline byte.
MULTI_DOUBLE_ENV="$WORK/.env.multi_double"
cat > "$MULTI_DOUBLE_ENV" <<'EOF'
USES="alpha\nbeta
gamma
delta"
EOF
_assert_matches_compose USES "$MULTI_DOUBLE_ENV" \
  "a double-quoted value spanning three physical lines decodes its \\n escape and its physical-line joins to the same byte"

# `#` and `=` inside the multiline body are literal content -- never a
# comment or a new key -- and a KEY AFTER the multiline value must still
# resolve, proving the scanner resumed scanning at the right line instead
# of over- or under-consuming lines while gathering.
MULTI_HASHEQ_ENV="$WORK/.env.multi_hasheq"
cat > "$MULTI_HASHEQ_ENV" <<'EOF'
USES='line1 # not a comment
key=value inside
line3'
AFTER=resolved
EOF
_assert_matches_compose USES "$MULTI_HASHEQ_ENV" \
  "a multiline value's own body may contain '#' and '=' as literal content"
_assert_matches_compose AFTER "$MULTI_HASHEQ_ENV" \
  "a key AFTER a multiline value still resolves (the scanner resumed at the right line)"

# An escaped quote inside a multiline double-quoted value does not
# terminate it early -- the scan correctly continues past \" to the REAL
# close on a later line.
MULTI_ESCAPED_Q_ENV="$WORK/.env.multi_escaped_quote"
cat > "$MULTI_ESCAPED_Q_ENV" <<'EOF'
USES="line1 \"quoted\" more
line2"
EOF
_assert_matches_compose USES "$MULTI_ESCAPED_Q_ENV" \
  "an escaped quote inside a multiline double-quoted value does not close it early"

# A trailing comment after the closing quote on the FINAL line is still
# stripped, same as the single-line case.
MULTI_TRAILING_COMMENT_ENV="$WORK/.env.multi_trailing_comment"
cat > "$MULTI_TRAILING_COMMENT_ENV" <<'EOF'
USES="line1
line2" # trailing comment
EOF
_assert_matches_compose USES "$MULTI_TRAILING_COMMENT_ENV" \
  "a trailing comment after a multiline value's closing quote is stripped"

# A multiline value referenced elsewhere via ${VAR} threads the real
# newline through interpolation too, not just a direct lookup.
MULTI_INTERP_ENV="$WORK/.env.multi_interp"
cat > "$MULTI_INTERP_ENV" <<'EOF'
MULTIVAL='line1
line2'
USES="prefix-${MULTIVAL}-suffix"
EOF
_assert_matches_compose USES "$MULTI_INTERP_ENV" \
  "a multiline value referenced via \${VAR} threads its real newline through interpolation"

# An unterminated quote (EOF reached with the quote still open) -- verified
# against the oracle: Compose's own .env load hard-fails on this
# ("unterminated quoted value"), the same failure class round 14 already
# established for other malformed .env constructs.
MULTI_UNTERM_ENV="$WORK/.env.multi_unterminated"
cat > "$MULTI_UNTERM_ENV" <<'EOF'
USES='line1
line2
line3
EOF
_assert_errors_like_compose USES "$MULTI_UNTERM_ENV" \
  "an unterminated multiline quote (EOF reached, never closed) fails closed, matching Compose exactly"


# ============================================================================
# Round 17 (review 5105248083) -- closes the WHOLE dotenv LINE grammar the
# way round 14 closed the interpolation grammar. Two P2s, both in the
# line-locating scan: a key-shaped physical line INSIDE another key's
# multiline value could win the "last definition" lookup (P2 #1), and the
# scan never recognized Compose's optional `export ` prefix at all (P2
# #2). Fixed structurally with one tokenizer (_env_tokenize) that walks
# the file ONCE into logical records; every lookup below selects among
# those records instead of grepping physical lines itself. The REST of
# this corpus sweeps Compose's own dotenv grammar (the godotenv fork in
# compose-go/dotenv) case by case, each pinned against the oracle.
# ============================================================================

# P2 #1 -- a key-shaped line INSIDE another key's multiline value must
# never be mistaken for a real redefinition.
GRAM_P2A_ENV="$WORK/.env.grammar_p2a"
cat > "$GRAM_P2A_ENV" <<'EOF'
POSTGRES_DB='alpha
POSTGRES_DB=inner
omega'
EOF
_assert_matches_compose POSTGRES_DB "$GRAM_P2A_ENV" \
  "a key-shaped physical line inside another key's multiline value is never a new definition"

# P2 #2 -- the optional \`export \` prefix.
GRAM_P2B_ENV="$WORK/.env.grammar_p2b"
printf 'export USES=hello\n' > "$GRAM_P2B_ENV"
_assert_matches_compose USES "$GRAM_P2B_ENV" \
  "an export-prefixed assignment is recognized"

# Whitespace around \`=\`.
GRAM_EQ_WS_ENV="$WORK/.env.grammar_eq_ws"
printf 'USES = hello\n' > "$GRAM_EQ_WS_ENV"
_assert_matches_compose USES "$GRAM_EQ_WS_ENV" \
  "whitespace around '=' is trimmed from both the key and the value"

# Leading whitespace/tabs before KEY.
GRAM_LEAD_WS_ENV="$WORK/.env.grammar_lead_ws"
printf '   USES=hello\n' > "$GRAM_LEAD_WS_ENV"
_assert_matches_compose USES "$GRAM_LEAD_WS_ENV" \
  "leading whitespace before a key is skipped"
GRAM_LEAD_TAB_ENV="$WORK/.env.grammar_lead_tab"
printf '\tUSES=hello\n' > "$GRAM_LEAD_TAB_ENV"
_assert_matches_compose USES "$GRAM_LEAD_TAB_ENV" \
  "a leading tab before a key is skipped"

# A bare KEY line with no '=' -- Compose inherits from the process
# environment; verified both when unset there and when set (resolves to
# that value), exercising round 13b's env precedence too.
#
# fix(#1778 round 22, P2): case 74's ORIGINAL assertion here (via
# _assert_matches_compose, a direct ${KEY} query) claimed a bare KEY line
# with nothing to inherit "resolves to empty, not absent" -- that value
# was correct (both sides really do produce "") but the CONCLUSION drawn
# from it was wrong, because a direct query cannot tell "empty" and
# "absent" apart in the first place (see _compose_presence's own comment
# above). The `-`/`:-` probe pair can, and says the opposite: the name is
# genuinely UNSET. Corrected to assert presence via that pair instead,
# and to require get_env_value's OWN contract to match (absent -> rc 1,
# not rc 0 with empty output).
GRAM_BARE_UNSET_ENV="$WORK/.env.grammar_bare_unset"
printf 'USES\n' > "$GRAM_BARE_UNSET_ENV"

GRAM_BARE_UNSET_PRESENCE="$(_compose_presence USES "$GRAM_BARE_UNSET_ENV")"
if [ "$GRAM_BARE_UNSET_PRESENCE" = "unset" ]; then
  ok "compose oracle: a bare KEY line with no process-environment value is genuinely UNSET, not set-to-empty (the -/:- probe pair agrees)"
else
  bad "compose oracle: expected a bare KEY line with no process-environment value to be UNSET, probe pair says [$GRAM_BARE_UNSET_PRESENCE]"
fi

if _our_value USES "$GRAM_BARE_UNSET_ENV" >/dev/null 2>&1; then
  bad "get_env_value reports FOUND for a bare KEY line the oracle says is UNSET (value=[$(_our_value USES "$GRAM_BARE_UNSET_ENV" 2>/dev/null)])"
else
  ok "get_env_value reports ABSENT (nonzero exit) for a bare KEY line with no process-environment value, matching the oracle's UNSET"
fi

# Twin: the REAL caller path (env_value_into) must not overwrite an
# existing shell value with an empty string for this case either -- it
# has to behave exactly like the key being absent from the file, per
# get_env_value's own now-corrected found/absent contract.
if _our_value_via_env_value_into USES "$GRAM_BARE_UNSET_ENV" >/dev/null 2>&1; then
  bad "env_value_into reports success for a bare KEY line the oracle says is UNSET (would have assigned an empty string)"
else
  ok "env_value_into reports failure too for a bare KEY line with no process-environment value (a caller's existing/default value survives)"
fi

GRAM_BARE_SET_ENV="$WORK/.env.grammar_bare_set"
printf 'USES\n' > "$GRAM_BARE_SET_ENV"
export USES=frominherit
_assert_matches_compose USES "$GRAM_BARE_SET_ENV" \
  "a bare KEY line (no '=') inherits its value from the process environment"

GRAM_BARE_SET_PRESENCE="$(_compose_presence USES "$GRAM_BARE_SET_ENV")"
if [ "$GRAM_BARE_SET_PRESENCE" = "nonempty" ]; then
  ok "compose oracle: a bare KEY line with a real inherited value is genuinely SET (the -/:- probe pair agrees)"
else
  bad "compose oracle: expected a bare KEY line with a real inherited value to be SET/nonempty, probe pair says [$GRAM_BARE_SET_PRESENCE]"
fi
unset USES

# CRLF line endings -- a trailing \r is line-terminator, never content.
GRAM_CRLF_ENV="$WORK/.env.grammar_crlf"
printf 'USES=hello\r\n' > "$GRAM_CRLF_ENV"
_assert_matches_compose USES "$GRAM_CRLF_ENV" \
  "a CRLF line ending is not part of the value"

# A comment line may have leading whitespace before its '#'.
GRAM_COMMENT_WS_ENV="$WORK/.env.grammar_comment_ws"
printf '  # a comment\nUSES=hello\n' > "$GRAM_COMMENT_WS_ENV"
_assert_matches_compose USES "$GRAM_COMMENT_WS_ENV" \
  "a comment line with leading whitespace is still a comment, not a key"

# '#' directly after an unquoted value with NO preceding space is literal
# (Compose requires a space before an inline comment).
GRAM_HASH_NOSPACE_ENV="$WORK/.env.grammar_hash_nospace"
printf 'USES=hello#nospace\n' > "$GRAM_HASH_NOSPACE_ENV"
_assert_matches_compose USES "$GRAM_HASH_NOSPACE_ENV" \
  "'#' immediately after an unquoted value with no preceding space is literal, not a comment"

# Trailing whitespace: trimmed when unquoted, kept when quoted.
GRAM_TRAIL_WS_ENV="$WORK/.env.grammar_trail_ws"
printf 'USES=hello   \n' > "$GRAM_TRAIL_WS_ENV"
_assert_matches_compose USES "$GRAM_TRAIL_WS_ENV" \
  "trailing whitespace on an unquoted value is trimmed"
GRAM_TRAIL_WS_Q_ENV="$WORK/.env.grammar_trail_ws_quoted"
printf "USES='hello   '\n" > "$GRAM_TRAIL_WS_Q_ENV"
_assert_matches_compose USES "$GRAM_TRAIL_WS_Q_ENV" \
  "trailing whitespace INSIDE a quoted value is content, kept verbatim"

# An empty value.
GRAM_EMPTY_ENV="$WORK/.env.grammar_empty"
printf 'USES=\n' > "$GRAM_EMPTY_ENV"
_assert_matches_compose USES "$GRAM_EMPTY_ENV" \
  "KEY= (nothing after '=') is a present, empty value"

# A key defined twice where the SECOND is a genuine later definition
# (not a multiline continuation) -- last wins, must not be confused with
# the P2 #1 fix that makes a continuation line NOT count as a definition.
GRAM_DUP_REAL_ENV="$WORK/.env.grammar_dup_real"
printf 'USES=first\nUSES=second\n' > "$GRAM_DUP_REAL_ENV"
_assert_matches_compose USES "$GRAM_DUP_REAL_ENV" \
  "a genuine later duplicate definition (not a multiline continuation) wins, last-write rule preserved"

# An export-prefixed redefinition after a plain one.
GRAM_EXPORT_REDEF_ENV="$WORK/.env.grammar_export_redef"
printf 'USES=first\nexport USES=second\n' > "$GRAM_EXPORT_REDEF_ENV"
_assert_matches_compose USES "$GRAM_EXPORT_REDEF_ENV" \
  "an export-prefixed redefinition after a plain one still wins (export doesn't change last-write)"

# A key whose name is a literal prefix of another -- must not cross-match.
GRAM_PREFIX_ENV="$WORK/.env.grammar_prefix"
printf 'DB=short\nDB_NAME=long\n' > "$GRAM_PREFIX_ENV"
_assert_matches_compose DB "$GRAM_PREFIX_ENV" \
  "a key name that is a literal prefix of another key resolves to its own value"
_assert_matches_compose DB_NAME "$GRAM_PREFIX_ENV" \
  "the longer key is not swallowed by the shorter one it starts with"


# ============================================================================
# Round 18 (review 5105652413) -- two P2s, both in the interpolation core.
# ============================================================================

# P2 #1 -- the process environment must be consulted BEFORE the cycle
# check for every name, not after. POSTGRES_DB="${POSTGRES_DB:-geolens}"
# with POSTGRES_DB exported is not a cycle Compose ever has to break: the
# shell environment already answers the question before the .env file's
# own text is even considered.
SELFENV_SET_ENV="$WORK/.env.selfenv_set"
printf 'POSTGRES_DB=${POSTGRES_DB:-geolens}\n' > "$SELFENV_SET_ENV"
export POSTGRES_DB=production
_assert_matches_compose POSTGRES_DB "$SELFENV_SET_ENV" \
  "a self-reference with the SAME name exported resolves to the exported value, not the default (env checked before the cycle check)"
unset POSTGRES_DB

SELFENV_UNSET_ENV="$WORK/.env.selfenv_unset"
printf 'POSTGRES_DB=${POSTGRES_DB:-geolens}\n' > "$SELFENV_UNSET_ENV"
_assert_matches_compose POSTGRES_DB "$SELFENV_UNSET_ENV" \
  "a self-reference with the same name NOT exported still falls through to the default (a genuine cycle, unaffected by this fix)"

TWOCYCLE_ENVEXP_ENV="$WORK/.env.twocycle_envexported"
cat > "$TWOCYCLE_ENVEXP_ENV" <<'EOF'
A=${B}
B=${A}
EOF
export B=fromenv
_assert_matches_compose A "$TWOCYCLE_ENVEXP_ENV" \
  "a two-node file cycle where ONE node is also exported resolves via the environment (query A)"
_assert_matches_compose B "$TWOCYCLE_ENVEXP_ENV" \
  "a two-node file cycle where ONE node is also exported resolves via the environment (query B)"
unset B

# P2 #2 -- the escape grammar, single- and double-quoted. Read
# compose-go/dotenv (the godotenv fork) for the escape tables, then let
# the oracle decide every value -- one summary of that source (used only
# to steer which cases to test) claimed single-quoted `\'` does NOT
# escape and the quote still closes; the oracle disagrees and this corpus
# matches the ORACLE, not the doc summary (see the reply on this
# review's P2 #2 thread for the full note).
ESCAPE_SQ_APOS_ENV="$WORK/.env.escape_sq_apostrophe"
printf "USES='geo\\\\'lens'\n" > "$ESCAPE_SQ_APOS_ENV"
_assert_matches_compose USES "$ESCAPE_SQ_APOS_ENV" \
  "single-quoted \\' is an escaped apostrophe (backslash dropped, quote does NOT close there)"

ESCAPE_SQ_BS_ENV="$WORK/.env.escape_sq_backslash"
printf "USES='a\\\\\\\\b'\n" > "$ESCAPE_SQ_BS_ENV"
_assert_matches_compose USES "$ESCAPE_SQ_BS_ENV" \
  "single-quoted \\\\ (backslash-backslash) stays as two literal backslashes -- only \\' is a recognized escape"

ESCAPE_DQ_DOLLAR_ENV="$WORK/.env.escape_dq_dollar"
printf 'USES="pre\\$RANDOM_XYZ_UNSET"\n' > "$ESCAPE_DQ_DOLLAR_ENV"
# _assert_matches_compose_dollar (not _assert_matches_compose): the
# expected value contains a literal $, exactly the content
# _compose_value/--format json is known (round 14) to misrepresent (it
# doubles a literal, non-interpolated $ in its own output).
_assert_matches_compose_dollar USES "$ESCAPE_DQ_DOLLAR_ENV" \
  "double-quoted \\\$ decodes to a literal \$ AND suppresses interpolation of what follows"

ESCAPE_DQ_UNKNOWN_ENV="$WORK/.env.escape_dq_unknown"
printf 'USES="a\\qb"\n' > "$ESCAPE_DQ_UNKNOWN_ENV"
_assert_matches_compose USES "$ESCAPE_DQ_UNKNOWN_ENV" \
  "an unrecognized double-quoted escape (\\q) keeps its backslash, unlike the documented ones"

ESCAPE_DQ_TRAILING_BS_ENV="$WORK/.env.escape_dq_trailing_bs"
printf 'USES="ab\\"\n' > "$ESCAPE_DQ_TRAILING_BS_ENV"
_assert_errors_like_compose USES "$ESCAPE_DQ_TRAILING_BS_ENV" \
  "a trailing lone backslash right before what would be the closing double quote escapes THAT quote too, leaving the value unterminated"

ESCAPE_UNQUOTED_BS_ENV="$WORK/.env.escape_unquoted_bs"
printf 'USES=a\\\\b\n' > "$ESCAPE_UNQUOTED_BS_ENV"
_assert_matches_compose USES "$ESCAPE_UNQUOTED_BS_ENV" \
  "an unquoted value gets no backslash processing at all"

# fix(#1778 round 20, P1 class) at scripts/restore.sh:41: a FORWARD
# reference — a key whose OWN value interpolates ${OTHER}, where OTHER is
# defined LATER in the same file — must resolve OTHER as if it did not
# exist in the file at all (an earlier line can never see a later one),
# falling back to the environment or the interpolation's own default.
# This is the single-call core of the bug: _env_resolve_name's "process
# environment wins" check used to test the LIVE shell variable table,
# which a glancing read makes it easy to conflate with "this name has no
# definition visible yet" -- they are different questions, and this
# corpus pins the FILE-only half of that distinction directly (the
# sequential-env_value_into half that actually triggered the reported bug
# is covered by scripts/tests/test-restore-env-sourcing-safety.sh's own
# CASE 10, which needs to control call order and cannot live here).
FWDREF_ENV="$WORK/.env.fwdref"
cat > "$FWDREF_ENV" <<'EOF'
POSTGRES_DB=${POSTGRES_USER:-dbfallback}
POSTGRES_USER=admin
EOF
_assert_matches_compose POSTGRES_DB "$FWDREF_ENV" \
  "a forward reference to a name defined LATER in the file falls through to the default (POSTGRES_USER is invisible to POSTGRES_DB's own line)"

# Same file, but POSTGRES_USER is genuinely exported first: the reference
# resolves via the environment, regardless of the file's own (later,
# unrelated) redefinition of the same name.
export POSTGRES_USER=realuser
_assert_matches_compose POSTGRES_DB "$FWDREF_ENV" \
  "the same forward reference resolves via a genuinely exported value regardless of the file's own later redefinition"
unset POSTGRES_USER

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

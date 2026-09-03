# shellcheck shell=sh
# GeoLens shared shell helpers — sourced by scripts/upgrade.sh (and any future
# operator script). NOT sourced by scripts/install.sh: install.sh is a
# self-contained single file streamed over `curl ... | sh` and byte-synced to the
# getgeolens.com mirror, so it deliberately inlines its own copies of these
# helpers. Keep the COMPOSE wrapper / update_env_value logic here in lockstep
# with install.sh's inlined versions. wait_for_healthy deliberately diverges:
# install.sh's copy budgets 300s and returns a non-fatal rc=2 on timeout (first
# boot under QEMU emulation), while this copy keeps a 90s budget for the
# upgrade path where images and volumes already exist locally.
#
# This file has NO side effects on source: it only defines functions and the few
# constants below. The caller sets COMPOSE_FILE before invoking compose().

# COMPOSE_FILE is selected by the caller (upgrade.sh reads it from .env). Default
# to the source-build file so a bare source still works.
: "${COMPOSE_FILE:=docker-compose.yml}"

# Wrap every compose call so the selected -f file is used consistently.
compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

say() {
  printf '%s\n' "$*"
}

warn() {
  printf 'Warning: %s\n' "$*" >&2
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required but was not found"
}

# fix(#1778 review round 3, P2): Compose-compatible ${VAR} interpolation for
# unquoted and double-quoted .env values, without executing the file (the
# whole point of get_env_value existing). A valid Compose .env may write
# `COMPOSE_FILE="${DEPLOY_FILE}"`, and the plain awk extraction returned that
# literally — `${DEPLOY_FILE}` and all — instead of the value real Compose
# would resolve there.
#
# Supports ${VAR}, $VAR, ${VAR:-default}, ${VAR-default}, and ${VAR:?msg}.
# Resolution precedence per reference, matching a top-to-bottom read of the
# file: a value already parsed from an EARLIER line in the SAME .env file,
# then the process environment. Bounded to a few passes so a chain
# (A references B references C) resolves without looping forever on a
# genuinely circular or unresolvable reference.
#
# A reference unresolved in both sources is left COMPLETELY UNCHANGED in the
# output. Real Compose expands an unresolved reference to empty, with a
# warning on stderr. This parser deliberately does NOT match that: it has no
# channel to raise that warning where an operator driving `restore.sh` or
# `check-env.sh` would see it, and silently collapsing a config value like
# COMPOSE_FILE to empty on a typo'd reference is a worse failure mode (an
# unreadable compose invocation, or a compose call against the wrong file)
# than leaving the operator's literal, greppable `${TYPO}` in the value read
# back — the same "don't guess at malformed input" policy the quote parsing
# above already follows. `${VAR:?msg}` is resolved the same way as
# `${VAR:-}` when VAR is unresolved (substituted with nothing) rather than
# reproducing Compose's "abort the whole file load with `msg`" behavior —
# that behavior has no meaning for a function that reads ONE key at a time,
# and none of the keys these scripts read plausibly use this form.
#
# fix(#1798 review round 13, P2, review 5103870781): _env_interpolate used to
# be a FLAT multi-pass loop over a single mutable `before_line`, re-derived
# after each substitution from whichever key was substituted LAST. That
# meant a SIBLING token later in the same value inherited a bound narrowed
# by an EARLIER token's own resolution instead of the value's own original
# bound: `A=alpha` / `B=beta` / `POSTGRES_DB="${A}_${B}"` resolved `${A}` to
# "alpha" first, narrowed the shared `before_line` to A's own line, and then
# looked up `${B}` as if it could only see definitions before THAT line —
# `${B}` is on the SAME line as `${A}` in the source value, so this is
# wrong; the fix returned "alpha_${B}" instead of "alpha_beta". The
# resolver is now recursive instead of flat: `_env_interp_resolve(text,
# bound)` scans `text` for each `${X}` token in turn, and ONLY narrows the
# bound for the RECURSIVE resolution of that token's OWN substituted value
# (to X's own defining line) — sibling tokens elsewhere in the SAME `text`
# keep scanning against the outer, unnarrowed `bound`, because they were
# never introduced by any substitution. `_ENV_INTERP_MAX_PASSES` now caps
# recursion DEPTH (chain length: A -> B -> C -> ...) rather than a flat pass
# count; a value with many sibling references costs no extra depth, only a
# chain of substitutions-within-substitutions does.
_ENV_INTERP_MAX_PASSES=5

# fix(#1798 CI on round 11, P2): the raw 3-byte UTF-8 BOM (EF BB BF),
# computed ONCE here via a shell printf octal escape — always exactly
# those 3 bytes regardless of the invoking shell's own locale. Passed
# into every `^KEY=` awk scan below via `-v bom="$_ENV_BOM"`, with the
# awk invocation ITSELF run under `LC_ALL=C` so its `index`/`substr`
# operate byte-wise. The prior approach built the BOM INSIDE awk via
# `sprintf("%c%c%c", 239, 187, 191)`: correct on the two awk builds this
# was checked against locally (BWK awk on macOS, mawk in the postgres:18
# image under an unset/C-ish locale) but wrong on gawk under a UTF-8
# locale (confirmed on CI, gawk 5.x) — gawk's `%c` there encodes each
# numeric argument as the UTF-8 bytes for that CODE POINT, not the raw
# byte value, so `sprintf("%c", 239)` becomes the two bytes 0xC3 0xAF
# (U+00EF) instead of the single byte 0xEF, and the 3-`%c` BOM never
# equals the file's real 3-byte BOM. Building the BOM in the SHELL and
# forcing `LC_ALL=C` on awk sidesteps any awk implementation's own
# locale-aware `%c`/string handling entirely.
_ENV_BOM="$(printf '\357\273\277')"

# fix(#1798 review round 10, P2): decodes the escape sequences Compose's
# own env-file reference documents for a double-quoted value —
# https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax
# ("`.env` file syntax": "Common shell escape sequences including `\n`,
# `\r`, `\t`, and `\\` are supported in double-quoted values" — quotes
# are escaped the same way, `\"`). The previous blanket
# `sed -E 's/\\(.)/\1/g'` unescaped ANY `\X` to its bare `X`, so
# `POSTGRES_DB="geo\tlens"` (a literal tab, per Compose) came back as
# "geotlens" — a different database than the one the app containers
# actually connect to. Every other `\X` Compose does NOT document (e.g.
# `\d`) is left completely unchanged here too, matching Compose's own
# behavior of only special-casing the sequences it lists.
#
# A naive SEQUENTIAL decode (replace `\\`, then `\"`, then `\n`, ...) is
# unsafe on its own: decoding `\\` FIRST can hand a LATER pass a
# backslash it never earned. Content `\\t` (an escaped backslash, `\\`,
# followed by a literal `t`) must decode to "backslash + t" (2 chars),
# NOT a tab — but a later `\t -> TAB` pass, run against text that still
# has the original `\\` intact, sees the SAME 2-byte `\t` substring
# straddling the pair boundary and wrongly decodes it. The regex that
# validates a well-formed double-quoted value before this function ever
# runs (`([^"\\]|\\.)*`) guarantees every backslash in the content
# starts EXACTLY one 2-char escape pair, so `\\` is protected first
# behind an inert sentinel byte, the other escapes are decoded (none of
# their REPLACEMENTS contain a backslash, so no new ambiguity is
# created), and only then is the sentinel turned back into a literal
# single backslash. `\n`/`\r` go through their own sentinel bytes and a
# final `tr`, not a direct sed replacement — POSIX/BSD sed's `s///` does
# not portably accept a literal newline in the replacement text within a
# single-line script the way GNU sed does.
_env_unescape_double_quoted() {
  _content="$1"
  _s_bs="$(printf '\001')"
  _s_nl="$(printf '\002')"
  _s_cr="$(printf '\003')"
  printf '%s' "$_content" \
    | sed "s/\\\\\\\\/${_s_bs}/g" \
    | sed 's/\\"/"/g' \
    | sed "s/\\\\n/${_s_nl}/g" \
    | sed "s/\\\\r/${_s_cr}/g" \
    | sed "s/\\\\t/$(printf '\t')/g" \
    | sed "s/${_s_bs}/\\\\/g" \
    | tr "${_s_nl}${_s_cr}" '\n\r'
}

# The 1-based line number of key's LAST `key=` definition in file, or 0 if
# absent. A repeated key follows "last write wins", the same assumption
# get_env_value's own single-match awk scan already makes implicitly for the
# top-level lookup (it keeps scanning and only the last match survives via
# `exit` never firing early... no — see get_env_value: it DOES exit on the
# first match. This bound-lookup helper intentionally takes the LAST match
# instead, so a same-cycle interpolation lookup and the top-level lookup
# could in principle disagree on a file with a duplicate key; not a
# realistic shape for this repo's .env, so left as the simpler behavior.)
_env_line_of() {
  key="$1"
  file="$2"
  # fix(#1798 review round 11 audit, P2; corrected on CI, round 12): a
  # leading UTF-8 BOM (bytes EF BB BF — common from PowerShell's default
  # UTF-8 output or some Windows editors saving .env) sits BEFORE the
  # first line's own text, so `^KEY=` never matched a key on line 1 at
  # all: every guarded caller's fallback then read that as "key absent"
  # and silently kept the inherited/unset value instead of the operator's
  # actual line-1 setting. Stripped once, on NR==1 only, before the
  # match, using the shell-built $_ENV_BOM under `LC_ALL=C` — see its own
  # comment above for why building the BOM INSIDE awk via
  # `sprintf("%c%c%c", ...)` is not locale-independent.
  LC_ALL=C awk -v k="$key" -v bom="$_ENV_BOM" '
    NR==1 && index($0, bom) == 1 { $0 = substr($0, length(bom) + 1) }
    { pat = "^" k "="; if ($0 ~ pat) { n = NR } }
    END { print n + 0 }
  ' "$file"
}

# Raw (unprocessed — no quote/comment stripping) value of key, from the
# LAST line strictly before line `before` (before=0 disables the bound).
# Exits 1 (prints nothing) if key has no such definition, so the caller can
# tell "defined here, value empty" apart from "not defined before this
# line" and correctly fall through to the process environment.
_env_raw_before() {
  key="$1"
  file="$2"
  before="$3"
  # fix(#1798 review round 11 audit, P2; corrected on CI, round 12): same
  # leading-BOM strip as _env_line_of above, and for the same reason.
  LC_ALL=C awk -v k="$key" -v before="$before" -v bom="$_ENV_BOM" '
    NR==1 && index($0, bom) == 1 { $0 = substr($0, length(bom) + 1) }
    {
      pat = "^" k "="
      if ($0 ~ pat && (before == 0 || NR < before)) {
        found = 1
        val = substr($0, length(k) + 2)
      }
    }
    END { if (found) { print val; exit 0 } else { exit 1 } }
  ' "$file"
}

# The 1-based line number of key's LAST definition strictly before line
# `before` (before=0 disables the bound), or 0 if none — the same bound
# _env_raw_before applies, exposed on its own so _env_interpolate can
# re-derive a fresh "before" bound scoped to THIS key's own defining line
# (see the fix(#1798 review round 11 audit, P2) comment on _env_interpolate
# below for why reusing the outer key's original before_line for every
# substitution pass is wrong).
_env_line_of_before() {
  key="$1"
  file="$2"
  before="$3"
  # fix(#1798 review round 11 audit, P2; corrected on CI, round 12): same
  # leading-BOM strip as _env_line_of above, and for the same reason.
  LC_ALL=C awk -v k="$key" -v before="$before" -v bom="$_ENV_BOM" '
    NR==1 && index($0, bom) == 1 { $0 = substr($0, length(bom) + 1) }
    {
      pat = "^" k "="
      if ($0 ~ pat && (before == 0 || NR < before)) { n = NR }
    }
    END { print n + 0 }
  ' "$file"
}

# Strips Compose .env quoting/escaping from a raw value — the same rules
# get_env_value documents above, factored out so the interpolation
# resolver below can apply them to an earlier-line value it looks up on
# key's behalf. Unlike get_env_value, a malformed quote here is returned
# as-is rather than specially flagged; the interpolation resolver treats a
# reference to a malformed value as "resolved to this literal text", which
# is the least surprising behavior available without a way to report the
# malformed line separately from the reference that pointed at it.
_env_dequote() {
  raw="$1"
  case "$raw" in
    \"*)
      if printf '%s' "$raw" | grep -qE '^"([^"\\]|\\.)*"[[:space:]]*(#.*)?$'; then
        _env_quoted_content="$(printf '%s' "$raw" | sed -E 's/^"(([^"\\]|\\.)*)".*$/\1/')"
        _env_unescape_double_quoted "$_env_quoted_content"
      else
        printf '%s' "$raw"
      fi
      ;;
    \'*)
      # fix(#1798 review round 9, P2): `(.*)` is greedy — for a trailing
      # comment that itself contains a `'` (`KEY='geolens' # use
      # 'production'`), it backtracks all the way to the LAST `'` on the
      # line, capturing "geolens' # use 'production" instead of stopping
      # at the value's own closing quote right after "geolens". Compose
      # single-quoted values have no escaping at all, so a literal `'`
      # can never legally appear inside one — `[^']*` encodes that
      # directly: it can only match up to the FIRST `'`, which is always
      # the real close, comment or no comment.
      if printf '%s' "$raw" | grep -qE "^'[^']*'[[:space:]]*(#.*)?\$"; then
        printf '%s' "$raw" | sed -E "s/^'([^']*)'[[:space:]]*(#.*)?\$/\1/"
      else
        printf '%s' "$raw"
      fi
      ;;
    *)
      printf '%s' "$raw" | sed -E -e 's/ #.*$//' -e 's/[[:space:]]+$//' -e 's/^[[:space:]]+//'
      ;;
  esac
}

# fix(#1798 review round 13, P2, review 5103870781): substitution used to be
# built as a sed program from DATA (`_env_sed_escape_pattern`/
# `_env_sed_escape_replacement` escaping the token/replacement for use
# inside `sed "s/${pat}/${rep}/"`). A REPLACEMENT containing a literal
# newline — reachable once a double-quoted value's `\n` escape has already
# been decoded, e.g. `DB_NAME="prod\narchive"` referenced elsewhere as
# `${DB_NAME}` — breaks that sed PROGRAM itself (a `s///` expression cannot
# contain a raw embedded newline on a single logical line), so `sed` errored
# out; because callers invoke this through `get_env_value` inside an `if
# _v="$(get_env_value ...)"` assignment, that failure surfaced as SUCCESS
# with an EMPTY value, and `restore.sh` silently fell back to its hardcoded
# `geolens` default instead of the operator's real database name. Splitting
# `remaining` around a literal `$token` via shell parameter expansion
# (`${remaining%%"$token"*}` / `${remaining#*"$token"}`) never builds a
# regex or a sed program from data at all — it is plain substring matching,
# and both forms are byte-for-byte safe with an embedded newline in either
# the text being scanned or the token itself (`%%pattern`/`#pattern`
# quoting a parameter inside the pattern matches it LITERALLY, not as a
# glob, per POSIX quote-removal-before-matching rules).
#
# Splits `remaining` on the FIRST occurrence of the literal string `token`.
# Returns via two globals instead of a single stdout stream, because the
# text either side of `token` may itself contain a real embedded newline
# (a decoded `\n`) that a single delimited stdout format could not encode
# unambiguously: `_env_split_before`/`_env_split_after`. Not reentrant
# across a single call site, which is fine — every caller consumes both
# immediately.
_env_split_on_token() {
  _est_text="$1"
  _est_token="$2"
  _env_split_before="${_est_text%%"$_est_token"*}"
  _env_split_after="${_est_text#*"$_est_token"}"
}

# Resolves NAME per Compose's own precedence (round 13b: process
# environment first — even set-but-empty counts as "set" here — falling
# back to an earlier line in FILE strictly before BOUND only when the
# environment has no NAME at all). Sets three globals: _ern_have_value (1
# if resolved from either source, 0 if neither has it), _ern_resolved (the
# resolved value; meaningless when _ern_have_value=0), and _ern_ref_bound
# (the line to bound a FURTHER reference found INSIDE this value's own
# text against — NAME's own defining line for a file-sourced value, 0/
# unbounded for a process-environment value, since it has no line in this
# file at all). Returns non-zero only on a genuine internal failure
# (propagated from _env_dequote); "NAME not found anywhere" is NOT a
# failure — that is _ern_have_value=0, a normal outcome the caller decides
# how to handle (literal token, a fallback, or its own hard error for
# `:?`/`?`).
_env_resolve_name() {
  _ern_name="$1"
  _ern_file="$2"
  _ern_bound="$3"
  _ern_have_value=0
  _ern_resolved=""
  _ern_ref_bound=0
  if eval "[ \"\${${_ern_name}+set}\" = set ]" 2>/dev/null; then
    eval "_ern_resolved=\"\${${_ern_name}}\""
    _ern_have_value=1
    _ern_ref_bound=0
  elif _ern_earlier="$(_env_raw_before "$_ern_name" "$_ern_file" "$_ern_bound")"; then
    # fix(#1798 review round 13, P2, review 5103870781): a value decoded
    # from a double-quoted `\n`/`\r`/`\t` escape can end in a real,
    # trailing control byte — `$(...)` unconditionally strips trailing
    # newlines, so capturing _env_dequote's output directly would
    # silently truncate exactly that byte before it ever reaches the
    # substitution. Sentinel-protect the capture: append a marker byte
    # inside the SAME command substitution (so it rides along with
    # whatever trailing bytes the real value has) and strip only the
    # marker back off afterward. `&&` (not `;`) between the decode and
    # the marker means a failure inside _env_dequote is never masked as
    # success with an empty value — it aborts the marker, the
    # substitution's own exit status reflects the failure, and this
    # function fails closed via `|| return 1` instead of quietly
    # returning less text than the input actually had.
    _ern_resolved="$(_env_dequote "$_ern_earlier" && printf x)" || return 1
    _ern_resolved="${_ern_resolved%x}"
    _ern_have_value=1
    _ern_ref_bound="$(_env_line_of_before "$_ern_name" "$_ern_file" "$_ern_bound")"
  fi
  return 0
}

# fix(#1798 review round 14, review 5104197320): finds the `}` that closes
# a `${...}` expression whose content (everything between the opening `${`
# and that close) begins at $1, counting EVERY literal `{`/`}` toward a
# depth that starts at 1 (already representing the consumed opening `${`)
# — this is what lets a nested reference like `${A:-${B:-x}}` find the
# OUTER close correctly instead of stopping at the first `}` belonging to
# the inner one.
#
# Verified empirically against real `docker compose config` rather than
# assumed: when depth genuinely never returns to 0 before $1 runs out (an
# unbalanced literal `{` sitting inside a default/alt-value's own text,
# with no operator-syntax reason for it — an obscure but real shape),
# Compose does NOT hard-fail — it recovers leniently at the LAST `}` it
# saw anywhere during the scan, using everything up to that point as the
# expression's content. Only when $1 contains NO `}` at all — truly
# unterminated, e.g. a `${VAR` with nothing left to close it — does
# Compose hard-fail ("Invalid template" on both a live `docker compose
# config` and its own .env-file load).
#
# Sets three globals: _ebm_inside (the expression's content, exclusive of
# the opening `${` and the resolved closing `}`), _ebm_after (everything
# in $1 following that closing `}`), and _ebm_found (1 if a close was
# located at all — by depth reaching 0, or by the lenient last-`}`
# recovery — 0 if $1 held no `}` whatsoever).
_env_brace_match() {
  _ebm_text="$1"
  _ebm_depth=1
  _ebm_inside=""
  _ebm_last_inside=""
  _ebm_last_after=""
  _ebm_have_last=0
  while [ -n "$_ebm_text" ]; do
    _ebm_c="${_ebm_text%"${_ebm_text#?}"}"
    _ebm_text="${_ebm_text#?}"
    case "$_ebm_c" in
      "{")
        _ebm_depth=$((_ebm_depth + 1))
        _ebm_inside="${_ebm_inside}${_ebm_c}"
        ;;
      "}")
        _ebm_depth=$((_ebm_depth - 1))
        if [ "$_ebm_depth" -eq 0 ]; then
          _ebm_after="$_ebm_text"
          _ebm_found=1
          return 0
        fi
        # Not the definitive close — remember this position in case depth
        # never reaches 0 and Compose's lenient last-`}` recovery applies.
        _ebm_last_inside="$_ebm_inside"
        _ebm_last_after="$_ebm_text"
        _ebm_have_last=1
        _ebm_inside="${_ebm_inside}${_ebm_c}"
        ;;
      *)
        _ebm_inside="${_ebm_inside}${_ebm_c}"
        ;;
    esac
  done
  if [ "$_ebm_have_last" -eq 1 ]; then
    _ebm_inside="$_ebm_last_inside"
    _ebm_after="$_ebm_last_after"
    _ebm_found=1
    return 0
  fi
  _ebm_found=0
  _ebm_after=""
  return 0
}

# Recursively resolves Compose's full interpolation grammar in `text` —
# $VAR, ${VAR}, ${VAR:-d}, ${VAR-d}, ${VAR:?m}, ${VAR?m}, ${VAR:+a},
# ${VAR+a}, and the `$$` literal-dollar escape — per the precedence and
# unresolved-reference policy documented on _ENV_INTERP_MAX_PASSES above.
# `bound` is the line strictly before which a reference may resolve
# against THIS file (the referencing key's own line, from _env_line_of, so
# a key can never resolve a reference against itself or a later line);
# `depth` counts the chain length so far and is capped by
# _ENV_INTERP_MAX_PASSES to guarantee termination on a cyclic or
# pathologically long reference chain.
#
# fix(#1798 review round 13, P2, review 5103870781): resolves each token IN
# PLACE by scanning `text` left to right, rather than a flat loop that
# re-scanned the WHOLE value for "the first token" after every single
# substitution. Critically, `bound` is passed UNCHANGED to every sibling
# token found in the SAME `text` — it is narrowed ONLY for the recursive
# call that resolves a substituted token's OWN value (to that token's own
# defining line), never for tokens that were already sitting in `text`
# before this call started. That is what makes
# `POSTGRES_DB="${A}_${B}"` resolve `${B}` against the SAME outer bound
# `${A}` used, instead of the narrower bound left over from resolving `${A}`
# first. A default/alt-value's OWN text (e.g. the `x` in `${A:-x}`) is
# recursively resolved the SAME way, but against the outer `bound` too —
# it sits in the referencing key's own value, not the referenced name's.
#
# fix(#1798 review round 14, review 5104197320): the previous version
# found a whole `${...}`/`$VAR` token with a single `grep -oE` regex whose
# fallback/error-message class was `[^}]*` — a single non-nesting run that
# cannot support `${A:-${B:-x}}`, and had no `+`/`:+` alternative-value
# forms at all (`COMPOSE_FILE=${USE_PROD:+docker-compose.prod.yml}` came
# back completely literal). Replaced with a character-scanning loop that
# finds the next `$` in the text (a literal search — see
# _env_split_on_token — safe with an embedded real newline either side),
# and dispatches on what follows it, entirely per real Compose's own
# behavior (verified empirically, never assumed — see the oracle test's
# corpus for every case this round closed):
#   $$          -> a literal single $, consumed whole; nothing after it is
#                  re-scanned as a fresh reference (verified: `docker
#                  compose config --format json` does NOT resolve `$$` at
#                  all — it appears to round-trip-normalize literal dollar
#                  signs in its own output rather than show the final
#                  value — so this was verified against `docker compose
#                  config --environment` AND a real running container's
#                  own environment, which agree with each other and NOT
#                  with `--format json`; the oracle test's own
#                  _compose_dollar_value helper documents this and is used
#                  only for this corpus).
#   ${...}      -> _env_brace_match finds the matching close (see its own
#                  doc comment for the depth-counting + lenient-recovery
#                  rule); a name with no `}` anywhere at all fails this
#                  function closed (return 1) rather than guessing, since
#                  Compose itself hard-fails loading a file with a
#                  genuinely unterminated `${VAR`.
#   $NAME       -> the longest [A-Za-z0-9_]* run starting right after the
#                  $; unresolved is left COMPLETELY unchanged (policy
#                  above), same as a bare unresolved ${NAME}.
#   anything else (including `$` at the very end of the text) -> a bare
#   literal $, left completely unchanged (verified: `$5`, `$ `, a trailing
#   `$` all pass through untouched).
_env_interp_resolve() {
  _eir_text="$1"
  _eir_file="$2"
  _eir_bound="$3"
  _eir_depth="$4"

  if [ "$_eir_depth" -ge "$_ENV_INTERP_MAX_PASSES" ]; then
    printf '%s' "$_eir_text"
    return 0
  fi

  _eir_result=""
  _eir_remaining="$_eir_text"
  while :; do
    case "$_eir_remaining" in
      *'$'*) : ;;
      *)
        _eir_result="${_eir_result}${_eir_remaining}"
        break
        ;;
    esac

    _env_split_on_token "$_eir_remaining" '$'
    _eir_prefix="$_env_split_before"
    _eir_rest="$_env_split_after"
    _eir_result="${_eir_result}${_eir_prefix}"

    _eir_c1="${_eir_rest%"${_eir_rest#?}"}"

    case "$_eir_c1" in
      '$')
        # $$ -> a literal single $ (see the doc comment above for why
        # this is verified against real container runtime / --environment
        # rather than `--format json`).
        _eir_result="${_eir_result}\$"
        _eir_remaining="${_eir_rest#?}"
        continue
        ;;
      '{')
        _env_brace_match "${_eir_rest#?}"
        if [ "$_ebm_found" -eq 0 ]; then
          # Genuinely unterminated ${... — no } anywhere. Compose itself
          # hard-fails loading a file shaped like this; get_env_value
          # fails closed for this key rather than guessing at a value.
          return 1
        fi
        _eir_inside="$_ebm_inside"
        _eir_remaining="$_ebm_after"

        # fix(#1798 review round 14, review 5104197320): a name must START
        # with [A-Za-z_] — verified empirically: `${5abc}` (digit-leading)
        # is a hard "Invalid template" failure on real `docker compose
        # config`, the SAME failure class as `${}` (empty name) and
        # `${A!x}` (an operator character Compose does not document).
        # Checking the first character SEPARATELY from the continuation
        # class below (which does allow digits, same as the bare $NAME
        # dispatch above) is what keeps a digit-leading name out of
        # _eir_iname instead of being silently accepted as one.
        _eir_iname=""
        _eir_iscan="$_eir_inside"
        _eir_ifirst="${_eir_iscan%"${_eir_iscan#?}"}"
        case "$_eir_ifirst" in
          [A-Za-z_])
            while [ -n "$_eir_iscan" ]; do
              _eir_inc="${_eir_iscan%"${_eir_iscan#?}"}"
              case "$_eir_inc" in
                [A-Za-z0-9_]) _eir_iname="${_eir_iname}${_eir_inc}"; _eir_iscan="${_eir_iscan#?}" ;;
                *) break ;;
              esac
            done
            ;;
        esac

        case "$_eir_iscan" in
          ":-"*) _eir_op=":-"; _eir_arg="${_eir_iscan#:-}" ;;
          ":+"*) _eir_op=":+"; _eir_arg="${_eir_iscan#:+}" ;;
          ":?"*) _eir_op=":?"; _eir_arg="${_eir_iscan#:?}" ;;
          "-"*) _eir_op="-"; _eir_arg="${_eir_iscan#-}" ;;
          "+"*) _eir_op="+"; _eir_arg="${_eir_iscan#+}" ;;
          "?"*) _eir_op="?"; _eir_arg="${_eir_iscan#\?}" ;;
          "") _eir_op=""; _eir_arg="" ;;
          *)
            # A digit-leading/empty name, or an operator character Compose
            # does not document.
            _eir_op="_unrecognized"
            ;;
        esac

        if [ -z "$_eir_iname" ] || [ "$_eir_op" = "_unrecognized" ]; then
          # fix(#1798 review round 14, review 5104197320): verified against
          # real `docker compose config` — `${}`, `${5abc}`, and `${A!x}`
          # are ALL hard "Invalid template" failures (the same class as a
          # genuinely unterminated `${VAR`), not literal-unchanged
          # pass-through. get_env_value fails closed for this key to
          # match, rather than guessing at malformed input.
          return 1
        fi

        _env_resolve_name "$_eir_iname" "$_eir_file" "$_eir_bound" || return 1

        case "$_eir_op" in
          "")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
            else
              _eir_result="${_eir_result}\${${_eir_iname}}"
              continue
            fi
            ;;
          ":-")
            if [ "$_ern_have_value" -eq 1 ] && [ -n "$_ern_resolved" ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
            else
              _eir_replacement="$_eir_arg"
              _eir_rep_bound="$_eir_bound"
            fi
            ;;
          "-")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
            else
              _eir_replacement="$_eir_arg"
              _eir_rep_bound="$_eir_bound"
            fi
            ;;
          ":+")
            if [ "$_ern_have_value" -eq 1 ] && [ -n "$_ern_resolved" ]; then
              _eir_replacement="$_eir_arg"
            else
              _eir_replacement=""
            fi
            _eir_rep_bound="$_eir_bound"
            ;;
          "+")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_eir_arg"
            else
              _eir_replacement=""
            fi
            _eir_rep_bound="$_eir_bound"
            ;;
          ":?")
            if [ "$_ern_have_value" -eq 1 ] && [ -n "$_ern_resolved" ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
            else
              # required-and-missing/empty — Compose itself hard-fails
              # loading a file shaped like this ("required variable ... is
              # missing a value"); get_env_value fails closed to match,
              # not a value substitution.
              return 1
            fi
            ;;
          "?")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
            else
              return 1
            fi
            ;;
        esac

        _eir_sub="$(_env_interp_resolve "$_eir_replacement" "$_eir_file" "$_eir_rep_bound" "$((_eir_depth + 1))" && printf x)" || return 1
        _eir_sub="${_eir_sub%x}"
        _eir_result="${_eir_result}${_eir_sub}"
        continue
        ;;
      [A-Za-z_])
        _eir_name=""
        _eir_scan="$_eir_rest"
        while [ -n "$_eir_scan" ]; do
          _eir_nc="${_eir_scan%"${_eir_scan#?}"}"
          case "$_eir_nc" in
            [A-Za-z0-9_]) _eir_name="${_eir_name}${_eir_nc}"; _eir_scan="${_eir_scan#?}" ;;
            *) break ;;
          esac
        done
        _eir_remaining="$_eir_scan"

        _env_resolve_name "$_eir_name" "$_eir_file" "$_eir_bound" || return 1
        if [ "$_ern_have_value" -eq 1 ]; then
          _eir_sub="$(_env_interp_resolve "$_ern_resolved" "$_eir_file" "$_ern_ref_bound" "$((_eir_depth + 1))" && printf x)" || return 1
          _eir_sub="${_eir_sub%x}"
          _eir_result="${_eir_result}${_eir_sub}"
        else
          _eir_result="${_eir_result}\$${_eir_name}"
        fi
        continue
        ;;
      *)
        # A bare $ followed by anything that isn't `$`, `{`, or a
        # name-start character — including end-of-string — is left
        # completely unchanged (verified: $5, $ , a trailing $).
        _eir_result="${_eir_result}\$"
        _eir_remaining="$_eir_rest"
        continue
        ;;
    esac
  done

  printf '%s' "$_eir_result"
}

_env_interpolate() {
  _env_interp_resolve "$1" "$2" "$3" 0
}

# Read a value from .env. Handles values containing `=` correctly (returns the
# full remainder after the first `=`). Reads from "$1" if given, else ./.env.
#
# fix(#1778 review round 6, P2): returns 1 (and prints nothing) when the file
# does not exist or the key has no `key=` line in it at all — DISTINCT from
# printing an empty string with exit 0, which means the key IS defined with
# an empty value. Before this, both shapes were indistinguishable: a key a
# `.env` simply never mentions (relying on Compose's own
# `POSTGRES_DB=prod scripts/restore.sh ...` process-environment override,
# which Compose supports) came back as "" exit 0, same as `POSTGRES_DB=` on
# its own line — so `POSTGRES_DB="$(get_env_value POSTGRES_DB .env)"`
# unconditionally overwrote the inherited process value with an empty
# string. Callers that want "fall back to whatever is already in the
# environment" must guard the assignment on this exit status themselves,
# e.g. `if _v="$(get_env_value POSTGRES_DB "$file")"; then POSTGRES_DB="$_v";
# fi` — assigning only inside the `if` (never to the real target variable
# on the failure path) is what actually preserves the inherited value; `if`
# conditions are exempt from `set -e`, so this does not abort the caller
# even though the function itself may `return 1`.
#
# fix(#1778 review round 6, P2): the top-level scan used to `exit` on the
# FIRST `key=` line it found. Compose reads an env file top-to-bottom and
# lets a later definition of the same key win — the interpolation helpers
# above (_env_line_of, _env_raw_before) already implement that "last
# definition wins" rule for resolving a ${VAR} reference, but this
# function's own direct lookup disagreed with them on a file containing a
# duplicate key. It now scans the whole file and keeps the LAST match,
# consistent with both the interpolation helpers and Compose itself.
#
# Interpolation precedence inside a resolved value (earlier line in this
# same file, then the process environment) is unchanged by either fix above
# — see _env_interpolate's doc comment; this is only about whether the KEY
# ITSELF appears in the file, not about resolving a ${VAR} reference nested
# inside a value that does.
#
# fix(#1778 review, P2): the awk extraction returns everything after the
# first `=` VERBATIM — but Docker Compose's own .env parser (the one
# `docker compose` itself uses to fill ${COMPOSE_FILE} etc. in the compose
# files) does not treat that text as a bare string. A `.env` an operator
# hand-edits with `COMPOSE_FILE="docker-compose.prod.yml"` or
# `POSTGRES_USER="geolens"` is valid Compose syntax and resolves to the
# unquoted value there, but used to come back from this function WITH the
# quote characters attached, silently breaking every caller that put the
# result in a path or SQL identifier. Apply the same rules Compose's
# env-file reference documents:
#   - a value wrapped in one matching pair of double or single quotes has
#     the quotes stripped;
#   - inside DOUBLE quotes, `\"` unescapes to `"` and `\\` unescapes to `\`
#     (a single left-to-right `\X -> X` pass handles both without an
#     ordering hazard between the two substitutions); single-quoted values
#     are literal — Compose applies no escape processing inside them;
#   - an UNQUOTED value's inline comment (a literal space then `#`, to end
#     of line) is stripped and the result is whitespace-trimmed, matching
#     Compose's own "inline comments for unquoted values must be preceded
#     by a space" rule. A quoted value's `#` is always literal; comment
#     stripping never applies once a value is quoted — BUT the comment may
#     still follow the closing quote (fix(#1778 review round 2, P2)):
#     `COMPOSE_FILE="docker-compose.prod.yml" # production` is valid Compose
#     syntax. The raw text does not END in a quote (it ends in the comment),
#     so the original "starts and ends with a quote" dispatch took the
#     unquoted branch, stripped the trailing comment, and returned the value
#     WITH its quotes still attached. Detecting "is this quoted" now only
#     checks the FIRST character; where the closing quote actually falls,
#     and whether only whitespace/a comment trails it, is resolved by the
#     regex below instead of by the raw string's last character.
# A malformed quote (opens but never closes, or has non-comment content
# after the closing quote) is left completely alone rather than guessed at,
# the same policy this repo's content-vs-blob sync comparisons already use
# for unparseable input.
get_env_value() {
  key="$1"
  file="${2:-.env}"

  [ -f "$file" ] || return 1

  # Last matching `key=` line wins (Compose's own duplicate-key rule); END
  # reports "no such key" as its own failure so the caller can tell that
  # apart from "key present, value empty" (found=1, empty val, exit 0).
  #
  # fix(#1798 review round 11 audit, P2; corrected on CI, round 12): same
  # leading-BOM strip as _env_line_of/_env_raw_before above — a
  # BOM-prefixed .env with its FIRST key on line 1 made that key invisible
  # here too, and every guarded caller's fallback then treated a
  # genuinely PRESENT key as absent, silently keeping the inherited/unset
  # value.
  raw="$(LC_ALL=C awk -v k="$key" -v bom="$_ENV_BOM" '
    NR==1 && index($0, bom) == 1 { $0 = substr($0, length(bom) + 1) }
    {
      pat = "^" k "="
      if ($0 ~ pat) {
        val = substr($0, length(k) + 2)
        found = 1
      }
    }
    END {
      if (found) { print val; exit 0 }
      exit 1
    }
  ' "$file")" || return 1

  case "$raw" in
    \"*)
      # `([^"\\]|\\.)*` walks escape-aware to the first UNescaped closing
      # quote: any run of chars that are neither `"` nor `\`, or a
      # backslash-escaped pair, consumed greedily — so an embedded `\"`
      # cannot be mistaken for the close. What follows that quote must be
      # nothing, whitespace, or a `#comment`; anything else (including a
      # second, unrelated quoted chunk) is left alone as malformed.
      if printf '%s' "$raw" | grep -qE '^"([^"\\]|\\.)*"[[:space:]]*(#.*)?$'; then
        _env_quoted_content="$(printf '%s' "$raw" | sed -E 's/^"(([^"\\]|\\.)*)".*$/\1/')"
        # fix(#1798 review round 13, P2, review 5103870781): a value whose
        # `\n`/`\r`/`\t` escape decodes to a TRAILING control byte (e.g.
        # `DB_NAME="prod\n"`) would silently lose that byte here — plain
        # `$(...)` always strips trailing newlines regardless of whether
        # they were literal in the file or produced by decoding an escape.
        # Sentinel-protect the capture (append a marker inside the SAME
        # substitution, strip only the marker back off) so a real trailing
        # byte from the decoder survives; `&&` (not `;`) means a failure
        # inside the decoder is never masked as success with an empty
        # value — this function fails closed via `|| return 1` instead.
        _env_value="$(_env_unescape_double_quoted "$_env_quoted_content" && printf x)" || return 1
        _env_value="${_env_value%x}"
        # fix(#1778 review round 3, P2): double-quoted values interpolate
        # ${VAR}/$VAR references, matching Compose (only single-quoted
        # values are literal there).
        _env_interpolate "$_env_value" "$file" "$(_env_line_of "$key" "$file")"
      else
        printf '%s' "$raw"
      fi
      ;;
    \'*)
      # Single-quoted values are literal in Compose — no escaping and no
      # interpolation, so a single quote cannot appear inside one at all.
      # fix(#1798 review round 9, P2): that fact is exactly what makes
      # `[^']*` the correct (not just convenient) content class — it can
      # only match up to the FIRST `'`, which is always the real close.
      # The prior `(.*)` was greedy and backtracked to the LAST `'` the
      # trailing `[[:space:]]*(#.*)?$` could still match against — a
      # trailing comment containing its own `'`
      # (`KEY='geolens' # use 'production'`) matched all the way to
      # THAT quote instead, returning "geolens' # use 'production".
      if printf '%s' "$raw" | grep -qE "^'[^']*'[[:space:]]*(#.*)?\$"; then
        printf '%s' "$raw" | sed -E "s/^'([^']*)'[[:space:]]*(#.*)?\$/\1/"
      else
        printf '%s' "$raw"
      fi
      ;;
    *)
      _env_value="$(
        printf '%s' "$raw" | sed -E -e 's/ #.*$//' -e 's/[[:space:]]+$//' -e 's/^[[:space:]]+//'
      )"
      # fix(#1778 review round 3, P2): unquoted values interpolate too.
      _env_interpolate "$_env_value" "$file" "$(_env_line_of "$key" "$file")"
      ;;
  esac
}

# Replace `KEY=...` in .env (or append if missing). Pass the value via ENVIRON
# rather than `awk -v` so backslashes in values are preserved verbatim.
update_env_value() {
  key="$1"
  value="$2"
  tmp=".env.tmp.$$"

  __VAL="$value" awk -v key="$key" '
    BEGIN { val = ENVIRON["__VAL"]; updated = 0 }
    $0 ~ "^" key "=" {
      print key "=" val
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print key "=" val
      }
    }
  ' .env > "$tmp"
  mv "$tmp" .env
}

# Resolve the highest semver release tag (vX.Y.Z) from a remote, matching the
# FULL refs/tags/<name> ref so a nested decoy tag (refs/tags/evil/v9.9.9) cannot
# masquerade as a top-level release. Numeric semver sort (v1.10.0 > v1.9.0).
# Prints the tag (with leading v) or empty. Mirrors install.sh :250.
resolve_latest_remote_tag() {
  _url="$1"
  git ls-remote --tags --refs "$_url" 2>/dev/null \
    | awk '{print $2}' \
    | grep -E '^refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sed 's#^refs/tags/##' \
    | sort -t. -k1.2,1n -k2,2n -k3,3n \
    | tail -n 1
}

# Compare two bare semver strings (no leading v). Prints "newer" if $1 > $2,
# "same" if equal, "older" if $1 < $2. Pure numeric field comparison.
semver_compare() {
  _a="$1"
  _b="$2"
  __A="$_a" __B="$_b" awk '
    BEGIN {
      n = split(ENVIRON["__A"], a, ".")
      m = split(ENVIRON["__B"], b, ".")
      max = (n > m) ? n : m
      for (i = 1; i <= max; i++) {
        ai = (i <= n) ? a[i] + 0 : 0
        bi = (i <= m) ? b[i] + 0 : 0
        if (ai > bi) { print "newer"; exit }
        if (ai < bi) { print "older"; exit }
      }
      print "same"
    }
  '
}

# Parse an RFC3339 UTC timestamp (docker's `.State.StartedAt`, e.g.
# 2026-07-27T01:07:52.269425417Z) to a unix epoch. GNU date first (Linux
# operator hosts), BSD date as the fallback (macOS dev; -j -u -f parses the
# fraction-stripped form as UTC). Prints nothing when the input does not look
# like a timestamp or neither date can parse it — callers must fail open.
# Always returns 0 so `set -e` callers never abort on an unparseable input.
iso_to_epoch() {
  _ts="$1"
  case "$_ts" in
    [0-9][0-9][0-9][0-9]-*) : ;;
    # Guard against non-timestamps BEFORE date sees them: GNU `date -d ""`
    # parses the empty string as today's midnight and exits 0, which would
    # turn "unreadable" into a wildly wrong age instead of failing open.
    *) return 0 ;;
  esac
  if _e=$(date -u -d "$_ts" +%s 2>/dev/null); then
    printf '%s\n' "$_e"
    return 0
  fi
  _t="${_ts%%.*}"
  _t="${_t%Z}"
  date -u -j -f '%Y-%m-%dT%H:%M:%S' "$_t" +%s 2>/dev/null || true
}

# Wait up to 90s for the stack to become healthy. The migrate one-shot must exit
# 0; every healthcheck-having service must report (healthy). Surfaces the failing
# service with a log tail on timeout/failure. Diverges from install.sh's inlined
# copy (300s budget, non-fatal rc=2 timeout) — see the header note above.
#
# Services still in `(health: starting)` when the budget runs out are treated
# as converging ONLY while they sit inside their own declared start_period
# (e.g. the backup service allows 10m for its first pg_dump of a large DB,
# far beyond this 90s budget) — there Docker has not judged them yet, and
# neither should we. test(#826): that claim is now VERIFIED per service, not
# assumed. The full tolerance Docker grants is start_period PLUS one
# in-flight probe's timeout (grace is judged by probe START time, so a probe
# launched just inside start_period may run `timeout` past the boundary)
# PLUS retries consecutive failing probes, each taking up to interval +
# timeout (a service stays `starting` through that whole streak — Codex P2
# rounds 1+3 on #867). A service
# whose container age (now - .State.StartedAt — NOT the wait budget, which
# overstates the age of a restart-policy container that restarted mid-wait
# with a freshly reset health clock; Codex P2 round 2) exceeds that entire
# window has outlived every verdict Docker could still be working on and
# fails the wait. The tolerance math only applies while the LIVE
# .State.Health.Status (read in the same inspect) still says `starting` —
# a container that flipped to (un)healthy between the compose ps snapshot
# and the inspect is judged by that verdict instead (round 4). Anything
# (unhealthy), restarting, or exited non-zero fails as before; an unreadable
# healthcheck config, StartedAt, or live status fails open (treated as
# converging), matching this script's other best-effort probes.
wait_for_healthy() {
  attempts=18
  sleep_s=5
  i=0
  while [ "$i" -lt "$attempts" ]; do
    i=$((i + 1))

    migrate_cid=$(compose ps -aq migrate 2>/dev/null | head -n 1)
    if [ -n "$migrate_cid" ]; then
      migrate_state=$(docker inspect --format '{{.State.Status}}' "$migrate_cid" 2>/dev/null || printf '')
      if [ "$migrate_state" = "exited" ]; then
        migrate_exit=$(docker inspect --format '{{.State.ExitCode}}' "$migrate_cid" 2>/dev/null || printf '?')
        if [ "$migrate_exit" != "0" ]; then
          printf '\n' >&2
          warn "migrate one-shot exited with code $migrate_exit. Last 30 log lines:"
          compose logs --tail 30 migrate 2>&1 | sed 's/^/  /' >&2
          return 1
        fi
      fi
    fi

    unhealthy=$(compose ps --format '{{.Service}}|{{.Status}}' 2>/dev/null | grep -v '|.*(healthy)' | grep -v '|Exited (0)' | grep -v '^$' || true)
    if [ -z "$unhealthy" ]; then
      printf '\n'
      return 0
    fi

    if [ "$i" -eq 1 ]; then
      printf 'Waiting for services to become healthy'
    else
      printf '.'
    fi
    sleep "$sleep_s"
  done

  # Budget spent — classify what is left. `(health: starting)` means the
  # service is within its declared start_period and Docker has not ruled on it;
  # failing the upgrade here would tell the operator to roll back a stack that
  # is converging fine (a pre-existing install whose first backup pg_dump
  # outlasts 90s hit exactly that). Warn and succeed when ONLY such services
  # remain; anything (unhealthy)/restarting/exited-nonzero is a real failure.
  remaining=$(compose ps --format '{{.Service}}|{{.Status}}' 2>/dev/null | grep -v '|.*(healthy)' | grep -v '|Exited (0)' | grep -v '^$' || true)
  if [ -z "$remaining" ]; then
    printf '\n'
    return 0
  fi
  broken=$(printf '%s\n' "$remaining" | grep -v '(health: starting)' || true)
  if [ -z "$broken" ]; then
    budget=$((attempts * sleep_s))
    # test(#826): verify each straggler really is inside its healthcheck's
    # DECLARED tolerance before letting it pass. `(health: starting)` only
    # means Docker has not ruled yet — a service with a broken healthcheck can
    # sit there long after its grace ran out. Codex P2 (#867): start_period
    # alone is NOT the boundary — after it ends, Docker still tolerates
    # `retries` consecutive failing probes (each taking up to interval +
    # timeout) before flipping to (unhealthy), and the service honestly
    # reports `starting` for that whole streak. Plus one in-flight probe's
    # timeout (Codex P2 round 3): moby grace-ignores a probe by its START
    # time, so one launched just inside start_period can run up to `timeout`
    # beyond the grace boundary before the counted retry cycles even begin.
    # So the full allowance is start_period + timeout + retries x (interval +
    # timeout); zero config values mean the daemon defaults (interval/timeout
    # 30s, retries 3).
    #
    # Codex P2 round 2 (#867): compare that allowance against the container's
    # ACTUAL age (now - .State.StartedAt), not the spent budget. A
    # restart-policy service that crashed and restarted mid-wait is seconds
    # old with a freshly reset health clock — legitimately inside its
    # start_period — and must not be classified overdue by a wait that
    # started before its life did. Unparseable StartedAt fails open, same as
    # unreadable healthcheck config.
    #
    # Codex P2 round 4 (#867): the `remaining` table is a SNAPSHOT — a probe
    # can complete between that `compose ps` and this inspect and flip the
    # container out of `starting`. Read the LIVE .State.Health.Status in the
    # same inspect and apply the tolerance math only while it still says
    # `starting`: a flip to `unhealthy` fails the service outright (Docker
    # has ruled; age math must not overrule it), a flip to `healthy` counts
    # as converged, and an unreadable status fails open like the rest.
    now_epoch=$(date -u +%s)
    overdue=""
    for svc in $(printf '%s\n' "$remaining" | cut -d'|' -f1); do
      cid=$(compose ps -q "$svc" 2>/dev/null | head -n 1)
      hc_line=""
      if [ -n "$cid" ]; then
        hc_line=$(docker inspect --format \
          '{{.State.StartedAt}} {{.Config.Healthcheck.StartPeriod.Seconds}} {{.Config.Healthcheck.Interval.Seconds}} {{.Config.Healthcheck.Timeout.Seconds}} {{.Config.Healthcheck.Retries}} {{.State.Health.Status}}' \
          "$cid" 2>/dev/null | head -n 1)
      fi
      live_status="${hc_line##* }"
      case "$live_status" in
        healthy)
          # Raced to healthy between the snapshot and this inspect: converged.
          continue ;;
        unhealthy)
          # Raced to unhealthy: Docker has ruled — fail it outright, no
          # tolerance math (age inside the window must not overrule a verdict).
          overdue="${overdue}  ${svc}: reported (health: starting) in the status snapshot but is (unhealthy) on inspection
"
          continue ;;
        starting) : ;;
        *)
          # Unreadable live status — fail open like the rest.
          continue ;;
      esac
      allowed=$(printf '%s\n' "$hc_line" | awk 'NF==6 {
        sp = int($2); iv = int($3); to = int($4); rt = int($5)
        if (iv <= 0) iv = 30
        if (to <= 0) to = 30
        if (rt <= 0) rt = 3
        # + to: a probe started just inside start_period is grace-ignored by
        # its START time and may run `timeout` past the boundary (round 3)
        print sp + to + rt * (iv + to)
      }')
      age=""
      start_epoch=$(iso_to_epoch "${hc_line%% *}")
      [ -n "$start_epoch" ] && age=$((now_epoch - start_epoch))
      if [ -n "$allowed" ] && [ -n "$age" ] && [ "$age" -ge "$allowed" ]; then
        overdue="${overdue}  ${svc}: still (health: starting) ${age}s after its last start, but its healthcheck tolerance (start_period + timeout + retries x (interval + timeout)) ended at ${allowed}s
"
      fi
    done
    if [ -z "$overdue" ]; then
      printf '\n'
      warn "these services are still starting after ${budget}s but remain within their healthcheck's tolerance (start_period + timeout + retries x (interval + timeout)):"
      printf '%s\n' "$remaining" | sed 's/^/  /' >&2
      warn "Docker will flag them (unhealthy) if they fail to converge; check later with: docker compose ps"
      return 0
    fi
    printf '\n' >&2
    warn "timed out after ${budget}s; these services are not converging (outlived their healthcheck tolerance, or already ruled unhealthy):"
    printf '%s' "$overdue" >&2
    warn "Inspect with: docker compose ps  /  docker compose logs <service>"
    return 1
  fi
  printf '\n' >&2
  warn "timed out after $((attempts * sleep_s))s waiting for services. Current status:"
  compose ps 2>&1 | sed 's/^/  /' >&2
  warn "Inspect with: docker compose ps  /  docker compose logs <service>"
  return 1
}

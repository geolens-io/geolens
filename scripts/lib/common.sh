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

# Escapes a literal string for use as a sed BRE search pattern with `/` as
# the delimiter.
_env_sed_escape_pattern() {
  printf '%s' "$1" | sed -e 's/[.[\*^$\/]/\\&/g'
}

# Escapes a literal string for use as a sed replacement with `/` as the
# delimiter.
_env_sed_escape_replacement() {
  printf '%s' "$1" | sed -e 's/[&\/\\]/\\&/g'
}

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

# Resolves ${VAR...}/$VAR references in value per the precedence and the
# unresolved-reference policy documented above. `file`/`before_line` scope
# the "earlier lines in this file" half of that precedence — before_line is
# the referencing key's OWN line, from _env_line_of, so a key can never
# resolve a reference against itself or a later line.
_env_interpolate() {
  value="$1"
  file="$2"
  before_line="$3"
  pass=0
  while [ "$pass" -lt "$_ENV_INTERP_MAX_PASSES" ]; do
    token="$(printf '%s' "$value" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*(:?[-?][^}]*)?\}|\$[A-Za-z_][A-Za-z0-9_]*' | head -n 1)"
    [ -n "$token" ] || break

    body="${token#\$}"
    case "$body" in
      "{"*"}")
        body="${body#\{}"
        body="${body%\}}"
        ;;
    esac
    case "$body" in
      *:-*) name="${body%%:-*}"; op=":-"; fallback="${body#*:-}" ;;
      *:\?*) name="${body%%:\?*}"; op=":?"; fallback="${body#*:\?}" ;;
      *-*) name="${body%%-*}"; op="-"; fallback="${body#*-}" ;;
      *) name="$body"; op=""; fallback="" ;;
    esac

    have_value=0
    resolved=""
    # fix(#1798 review round 11 audit, P2): defaults to the CURRENT
    # before_line (unchanged) unless this pass's resolution narrows it —
    # see below.
    next_before_line="$before_line"
    if earlier="$(_env_raw_before "$name" "$file" "$before_line")"; then
      resolved="$(_env_dequote "$earlier")"
      have_value=1
      # fix(#1798 review round 11 audit, P2): the multi-pass loop below
      # re-scans $value for a NEW ${VAR} token after every substitution —
      # including one exposed by substituting IN "$name"'s own value,
      # which used to be resolved against the OUTER key's before_line
      # unconditionally. With C=orig / B="${C}" / C=updated / A="${B}":
      # resolving B directly correctly bounds the ${C} it exposes to
      # "before B's own line" and gets "orig" — but resolving A reused
      # A's OWN (later) before_line for that same ${C} token, so it saw
      # C's redefinition on the intervening line too and returned
      # "updated" — two different answers for what is meant to be the
      # same reference. Re-deriving the bound to "before name's own
      # winning line" here makes every subsequent pass see exactly what a
      # direct lookup of "$name" would have seen.
      next_before_line="$(_env_line_of_before "$name" "$file" "$before_line")"
    elif eval "[ \"\${${name}+set}\" = set ]" 2>/dev/null; then
      eval "resolved=\"\${${name}}\""
      have_value=1
      # A process-environment value has no defining line in this file at
      # all — a ${VAR} reference it happens to contain is not scoped to
      # any point in the file, so no bound applies to what it can see.
      next_before_line=0
    fi

    if [ "$have_value" -eq 1 ]; then
      # ${VAR:-default}: fall back only when VAR is set but EMPTY.
      if [ "$op" = ":-" ] && [ -z "$resolved" ]; then
        resolved="$fallback"
      fi
      # ${VAR-default} and ${VAR:?msg}: VAR is set (possibly to ""), so its
      # value is used as-is — Compose's ${VAR-default} falls back only when
      # VAR is UNSET, and ${VAR:?msg} only errors when VAR is unset/empty,
      # neither of which applies once a value was actually found.
      replacement="$resolved"
    else
      case "$op" in
        ":-" | "-") replacement="$fallback" ;;
        *) replacement="$token" ;; # bare ${VAR}/$VAR or ${VAR:?msg}: see policy above
      esac
    fi

    if [ "$replacement" = "$token" ]; then
      # Nothing left to substitute for this occurrence — stop instead of
      # re-matching the same unresolved token every remaining pass.
      break
    fi

    pat="$(_env_sed_escape_pattern "$token")"
    rep="$(_env_sed_escape_replacement "$replacement")"
    value="$(printf '%s' "$value" | sed "s/${pat}/${rep}/")"
    before_line="$next_before_line"
    pass=$((pass + 1))
  done
  printf '%s' "$value"
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
        _env_value="$(_env_unescape_double_quoted "$_env_quoted_content")"
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

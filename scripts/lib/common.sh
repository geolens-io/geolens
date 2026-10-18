# shellcheck shell=sh
# GeoLens shared shell helpers, sourced by scripts/upgrade.sh (and any future
# operator script). Not sourced by scripts/install.sh: install.sh is a
# self-contained single file streamed over `curl ... | sh` and byte-synced to
# the getgeolens.com mirror, so it inlines its own copies of these helpers.
# Keep the COMPOSE wrapper / update_env_value logic here in lockstep with
# install.sh's inlined versions. wait_for_healthy deliberately diverges:
# install.sh's copy budgets 300s and returns a non-fatal rc=2 on timeout
# (first boot under QEMU emulation), while this copy keeps a 90s budget for
# the upgrade path where images and volumes already exist locally.
#
# This file has one side effect on source: the snapshot block below `fail()`'s
# definition, which needs `fail` to exist first. Everything else only defines
# functions. COMPOSE_FILE's default assignment sits after the snapshot block;
# see that block's comment for why.

# Compose needs the project directory stated explicitly for its own purposes:
# reading `.env` for COMPOSE_PROJECT_NAME/COMPOSE_PROFILES and interpolating
# ${VAR} references in the compose file. Compose's default project directory
# is the path of the first Compose file (`docker compose --help`), so a caller
# passing an absolute `$PROJECT_ROOT/...` `-f` (restore.sh, check-env.sh) or
# `cd`-ing to PROJECT_ROOT before building a relative `-f` (upgrade.sh) got
# the right `.env` through two different undeclared mechanisms. Both are one
# refactor away from silently breaking.
#
# `--project-directory "$PROJECT_ROOT"` replaces both with one explicit
# mechanism for every script that sources common.sh: Compose reads `DIR/.env`
# for both `${VAR}` interpolation and its own
# COMPOSE_PROJECT_NAME/COMPOSE_PROFILES controls, from any cwd, with an
# absolute `-f` alongside it and no `--env-file`. A caller that wants a .env
# value in its own shell logic still reads it via
# get_env_value/env_value_into, matching the policy of never letting Compose
# or the shell touch .env on our behalf for control flow. The wrapper still
# builds an absolute `-f` itself, because a relative `-f` resolves against the
# process cwd, not `--project-directory`.
#
# PROJECT_ROOT is not computed here: every caller resolves it from its own
# `$0`/`${BASH_SOURCE[0]}` before sourcing (a `#!/bin/sh` script has no
# `BASH_SOURCE`), and the codebase relies on that convention for `.env`
# lookups elsewhere.
#
# A COMPOSE_FILE entry as an absolute path with "." and ".." resolved
# lexically, the way Compose records it in container labels.
compose_clean_path() {
  case "$1" in
    /*) _ccp_path=$1 ;;
    *) _ccp_path=$PROJECT_ROOT/$1 ;;
  esac
  _ccp_dir="$(cd "$(dirname "$_ccp_path")" 2>/dev/null && pwd)" || {
    printf '%s' "$_ccp_path"
    return 0
  }
  printf '%s/%s' "${_ccp_dir%/}" "$(basename "$_ccp_path")"
}

compose() {
  [ -n "${PROJECT_ROOT:-}" ] || fail "compose(): PROJECT_ROOT must be set by the caller before sourcing common.sh"
  # COMPOSE_FILE is a list, as Compose itself reads it: each entry becomes its
  # own -f, so overrides stay in effect.
  _cf_argc=$#
  _cf_ifs=$IFS
  IFS=:
  set -f
  for _cf_entry in $COMPOSE_FILE; do
    case "$_cf_entry" in
      "") ;;
      /*) set -- "$@" -f "$_cf_entry" ;;
      *) set -- "$@" -f "$PROJECT_ROOT/$_cf_entry" ;;
    esac
  done
  set +f
  IFS=$_cf_ifs
  set -- "$@" --project-directory "$PROJECT_ROOT"
  while [ "$_cf_argc" -gt 0 ]; do
    set -- "$@" "$1"
    shift
    _cf_argc=$((_cf_argc - 1))
  done
  docker compose "$@"
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

# The snapshot of inherited variables must not silently come up empty. A
# capture built on `env -0 | xargs -0 sh -c '...' ... 2>/dev/null || true`
# depends on an external GNU-flavored `env -0` that is not guaranteed
# everywhere these scripts run (some `/usr/bin/env` builds do not accept
# `-0`), and the stderr redirect plus `|| true` would swallow that failure. An
# empty snapshot is indistinguishable, from every call site, from "this
# operator genuinely has nothing exported", so every inherited setting would
# silently be treated as absent. With POSTGRES_USER=production exported and
# .env holding POSTGRES_DB=${POSTGRES_USER:-fallback}, restore.sh would
# resolve "fallback" and could run `pg_restore --clean` against the wrong
# database.
#
# The capture is therefore built two ways:
#
#   1. No external tool for the snapshot. Where bash is running this file
#      ($BASH_VERSION set; true whenever invoked as `bash script.sh`, and also
#      on macOS even for a `#!/bin/sh` script, since macOS's /bin/sh is bash in
#      POSIX mode), `compgen -e` (a builtin) enumerates every exported name and
#      `printf '%s' "${!name}"` reads each one straight out of the shell's own
#      variable table. There is no serialization step to misread, so an
#      inherited value's embedded newline is not a question.
#
#      This file is also dash-compatible: upgrade.sh and scripts/env-value.sh
#      run it under `#!/bin/sh`, which is dash on a Debian/Ubuntu operator host
#      (the self-hosted target). dash has neither `compgen` nor `${!name}`, so
#      both are gated on `[ -n "${BASH_VERSION:-}" ]`. The dash branch uses the
#      `export -p` builtin to enumerate names only. Its quoting dialect differs
#      by shell (dash: `export NAME='value'`; bash: `declare -x NAME="value"`),
#      so it is never parsed for the value, only to find where each name starts
#      (the identifier between "export " and the line's first `=`). Every name
#      found is re-read via `eval`, the indirect-access idiom used throughout
#      this file (_env_resolve_name and others). Known, accepted limitation: a
#      name is identified per physical line of `export -p`'s output, so an
#      inherited value containing a real newline followed by text that looks
#      like `export SOMENAME=` could be misread as a second, phantom name. That
#      is a narrow, low-severity edge (a fabricated name, not a misresolution
#      of a real one) not worth a full shell-quoting parser.
#
#   2. Fails closed. The capture has no `|| true` or `2>/dev/null`: a failing
#      `mktemp -d` or write calls `fail` (defined just above) instead of
#      continuing with an empty directory. A positive control right after
#      capture asserts that PATH, which every process has, landed in the
#      snapshot; if not, the mechanism is broken and this fails closed too,
#      rather than treating every other inherited value as absent.
if [ -z "${_ENV_SNAPSHOT_DIR:-}" ]; then
  _ENV_SNAPSHOT_DIR="$(mktemp -d)" || fail "could not create a temp directory for the environment snapshot"
  [ -d "$_ENV_SNAPSHOT_DIR" ] || fail "environment snapshot directory does not exist after mktemp: $_ENV_SNAPSHOT_DIR"

  if [ -n "${BASH_VERSION:-}" ]; then
    # shellcheck disable=SC3044,SC3053
    # SC3044/SC3053: compgen and ${!name} are bash-only,
    # and this file is checked as POSIX sh (`shellcheck shell=sh` at the
    # top) because real dash also sources it, but this branch is gated on
    # $BASH_VERSION, so a POSIX-only shell never reaches either construct.
    for _ess_name in $(compgen -e); do
      case "$_ess_name" in
        *[!A-Za-z0-9_]*) continue ;;
        "") continue ;;
      esac
      printf '%s' "${!_ess_name}" > "${_ENV_SNAPSHOT_DIR}/${_ess_name}" \
        || fail "could not write the environment snapshot for ${_ess_name}"
    done
  else
    export -p | {
      _ess_saw_name=0
      while IFS= read -r _ess_line; do
        case "$_ess_line" in
          "export "[A-Za-z_]*=*) : ;;
          *) continue ;;
        esac
        _ess_rest="${_ess_line#export }"
        _ess_name="${_ess_rest%%=*}"
        case "$_ess_name" in
          *[!A-Za-z0-9_]*) continue ;;
          "") continue ;;
        esac
        # A name is identified per physical line of `export -p`'s
        # output, so an inherited value containing a real newline
        # followed by text that looks like "export SOMENAME=" produces
        # a phantom name that was never exported. Blindly
        # `eval`-reading it under `set -u` aborts the whole capture (a
        # bare `${PHANTOM}` reference to an unset name is a hard
        # nounset error that this loop's `|| fail` never sees).
        # `${name+set}` is the nounset-safe existence test (POSIX
        # exempts `+`/`:+`), so confirm the candidate is really set
        # first; a phantom is skipped like any other non-matching
        # line. A phantom that collides with a different real name is
        # harmless too: this reads that name's own live value via the
        # same safe indirection, never the crafted line's text.
        if eval "[ \"\${${_ess_name}+set}\" = set ]" 2>/dev/null; then
          _ess_saw_name=1
          eval "printf '%s' \"\${${_ess_name}}\"" > "${_ENV_SNAPSHOT_DIR}/${_ess_name}" \
            || fail "could not write the environment snapshot for ${_ess_name}"
        fi
      done
      [ "$_ess_saw_name" -eq 1 ] \
        || fail "export -p produced no recognizable NAME= line -- cannot build an environment snapshot"
    } || fail "could not enumerate the process environment (export -p failed)"
  fi

  # Positive control: PATH is set in every process this file runs in, so its
  # absence means the capture above is broken. Never proceed with a snapshot
  # that might be empty.
  [ -f "${_ENV_SNAPSHOT_DIR}/PATH" ] \
    || fail "environment snapshot sanity check failed: PATH is not present (expected in every process) -- refusing to proceed with a possibly-empty snapshot"

  # Best-effort cleanup, correct as-is for scripts that never replace the
  # EXIT trap (check-env.sh, env-value.sh). `trap` holds one handler per
  # signal, so a script that sets its own later `trap ... EXIT`
  # (restore.sh's _cleanup, upgrade.sh's rollback_trap) replaces this one;
  # both call _env_snapshot_cleanup from their own handler instead.
  trap '_env_snapshot_cleanup' EXIT
fi

# COMPOSE_FILE is selected by the caller (upgrade.sh/restore.sh/check-env.sh
# read it from .env via env_value_into). Default to the source-build file so a
# bare source still works. Always relative to PROJECT_ROOT (Compose's
# convention for this variable), never an absolute path a caller might set.
#
# This default must run after the snapshot block above, never before it. A
# default assigned earlier would make COMPOSE_FILE a locally-set (never
# exported) variable by the time the snapshot is captured. On the dash branch,
# a phantom name from a mis-split multi-line value that read as "COMPOSE_FILE"
# would then find it set via this default, not via inheritance, and write
# "docker-compose.yml" into the snapshot as if an operator had exported it.
# env_value_into's interpolation-reference path (_env_resolve_name) would then
# prefer that phantom "inherited" value over .env's own COMPOSE_FILE line,
# silently pointing compose at the wrong file.
: "${COMPOSE_FILE:=docker-compose.yml}"

# Removes the snapshot directory. Exposed (not just the bare trap above) so a
# caller that installs its own later EXIT trap, replacing this file's, can
# call it from that trap instead of leaking the directory.
_env_snapshot_cleanup() {
  [ -n "${_ENV_SNAPSHOT_DIR:-}" ] && rm -rf "${_ENV_SNAPSHOT_DIR:?}" 2>/dev/null
}

# True if NAME was present in the environment snapshot taken when this file
# was sourced -- regardless of what the live shell variable of the same name
# holds right now.
_env_snapshot_has() {
  [ -n "${_ENV_SNAPSHOT_DIR:-}" ] && [ -f "${_ENV_SNAPSHOT_DIR}/$1" ]
}

# Prints NAME's snapshotted value. Caller must have already confirmed
# _env_snapshot_has "NAME". Sentinel-protected the same way every other
# value read in this file is (see _env_resolve_name/_env_dequote): a
# bare `$(cat file)` would silently strip a real trailing newline the
# value legitimately ends in.
_env_snapshot_value() {
  _esv_raw="$(cat "${_ENV_SNAPSHOT_DIR}/$1" 2>/dev/null && printf x)"
  printf '%s' "${_esv_raw%x}"
}

# Compose-compatible ${VAR} interpolation for unquoted and double-quoted .env
# values, without executing the file (the point of get_env_value). A valid
# Compose .env may write `COMPOSE_FILE="${DEPLOY_FILE}"`, which plain awk
# extraction would return literally instead of the value Compose resolves.
#
# Supports ${VAR}, $VAR, ${VAR:-default}, ${VAR-default}, ${VAR:?msg},
# ${VAR?msg}, ${VAR:+alt}, and ${VAR+alt}; see _env_interp_resolve's doc
# comment for the grammar. Each form was checked against real `docker compose
# config`.
#
# Resolution precedence per reference, matching a top-to-bottom read of the
# file: a value already parsed from an EARLIER line in the SAME .env file,
# then the process environment.
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
# above already follows. `${VAR:?msg}`/`${VAR?msg}` do NOT follow this
# policy: Compose itself hard-fails loading a file shaped like
# that, so get_env_value fails closed too — see _env_interp_resolve.
#
# Substitution is recursive: `_env_interp_resolve(text, bound)` scans `text`
# for each `${X}` token in turn and narrows the bound only for the recursive
# resolution of that token's own substituted value (to X's defining line).
# Sibling tokens in the same `text` keep scanning against the outer,
# unnarrowed `bound`, because no substitution introduced them. With `A=alpha`,
# `B=beta` and `POSTGRES_DB="${A}_${B}"`, a shared bound narrowed by resolving
# `${A}` would hide `${B}`, which sits on the same line, and yield
# "alpha_${B}" instead of "alpha_beta".
#
# A reference chain (A references B references C ...) has no depth cap. A
# chain sourced purely from file lines cannot loop: every hop's bound strictly
# narrows to an earlier line, and `_env_resolve_name` already reports "not
# found" for `A=${A}` or a two-key `A=${B}`/`B=${A}` file. A value sourced
# from the process environment has no line to narrow against
# (`_ern_ref_bound=0`, unbounded), so two exported variables referencing each
# other (`export A='${B}'; export B='${A}'`) would never terminate on bound
# alone.
#
# Cycles are detected instead: a space-delimited CHAIN of the names currently
# being expanded is threaded through every recursive call (see
# _env_resolve_name), seeded with the top-level key's own name. A name already
# in CHAIN is reported as unresolved (`_ern_have_value=0`) without a lookup,
# which breaks both the file- and environment-sourced cases the same way, and
# every per-operator "not found" handler downstream (literal passthrough for a
# bare `${VAR}`, a `:-`/`-` fallback, `:+`/`+`'s "not set", `:?`/`?`'s hard
# failure) already does the right thing with that. Verified against real
# `docker compose config`: a cycle is not an error there either. `A=${A}`
# warns and resolves to "" as a bare form (this parser diverges the same
# documented way it does for any unresolved bare reference);
# `A=${A:-fallback}` resolves to "fallback"; `A=${A:?msg}` fails closed.

# The raw 3-byte UTF-8 BOM (EF BB BF), computed once via a shell printf octal
# escape so it is always exactly those 3 bytes regardless of the invoking
# shell's locale. It is passed into every `^KEY=` awk scan via `-v
# bom="$_ENV_BOM"`, with awk itself run under `LC_ALL=C` so `index`/`substr`
# operate byte-wise. Building the BOM inside awk with `sprintf("%c%c%c", 239,
# 187, 191)` is wrong on gawk under a UTF-8 locale: gawk's `%c` encodes each
# numeric argument as the UTF-8 bytes for that code point, so `sprintf("%c",
# 239)` becomes the two bytes 0xC3 0xAF instead of 0xEF.
_ENV_BOM="$(printf '\357\273\277')"

# A raw carriage return and a raw tab, built the same shell-printf-octal way
# as the BOM and for the same reason (locale-independent, exactly one byte).
# _ENV_CR strips a trailing \r from every physical line the tokenizer reads
# (Compose accepts CRLF .env files: `KEY=v\r\n` resolves to `v`, not `v\r`).
# _ENV_TAB joins a literal space as whitespace everywhere Compose's dotenv
# grammar allows it: leading indentation before a key, around `=`, and after
# an `export ` prefix.
_ENV_CR="$(printf '\r')"
_ENV_TAB="$(printf '\t')"
# A literal newline character, for splitting file content into physical lines.
# Built with the same sentinel technique used throughout this file for a
# decoded value that might end in a real newline: plain `$(printf '\n')` would
# strip its own trailing newline and leave an empty string. `x` survives the
# strip (it is not a newline), then parameter expansion removes it, which does
# not re-trigger command substitution's trailing-newline stripping.
_ENV_NL="$(printf '\nx')"
_ENV_NL="${_ENV_NL%x}"

# Decodes the escape sequences Compose's env-file reference documents for a
# double-quoted value
# (https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax):
# "Common shell escape sequences including `\n`, `\r`, `\t`, and `\\` are
# supported in double-quoted values", and quotes are escaped the same way,
# `\"`. A blanket `sed -E 's/\\(.)/\1/g'` would unescape any `\X` to bare `X`,
# so `POSTGRES_DB="geo\tlens"` (a literal tab, per Compose) would come back as
# "geotlens", a different database than the app containers connect to. Every
# other `\X` Compose does not document (e.g. `\d`) is left unchanged, matching
# Compose.
#
# A naive sequential decode (replace `\\`, then `\"`, then `\n`, ...) is
# unsafe: decoding `\\` first can hand a later pass a backslash it never
# earned. Content `\\t` (an escaped backslash followed by a literal `t`) must
# decode to backslash + `t`, not a tab, but a later `\t -> TAB` pass run
# against text that still holds the original `\\` sees the same 2-byte `\t`
# substring straddling the pair boundary and wrongly decodes it. The regex
# that validates a double-quoted value before this function runs
# (`([^"\\]|\\.)*`) guarantees every backslash starts exactly one 2-char
# escape pair, so `\\` is protected first behind an inert sentinel byte, the
# other escapes are decoded (none of their replacements contain a backslash),
# and only then is the sentinel turned back into a single backslash. `\n`/`\r`
# go through their own sentinel bytes and a final `tr`, not a direct sed
# replacement, because POSIX/BSD sed's `s///` does not portably accept a
# literal newline in the replacement the way GNU sed does.
_env_unescape_double_quoted() {
  _content="$1"
  _s_bs="$(printf '\001')"
  _s_nl="$(printf '\002')"
  _s_cr="$(printf '\003')"
  printf '%s' "$_content" \
    | sed "s/\\\\\\\\/${_s_bs}/g" \
    | sed 's/\\"/"/g' \
    | sed 's/\\\$/\$\$/g' \
    | sed "s/\\\\n/${_s_nl}/g" \
    | sed "s/\\\\r/${_s_cr}/g" \
    | sed "s/\\\\t/$(printf '\t')/g" \
    | sed "s/${_s_bs}/\\\\/g" \
    | tr "${_s_nl}${_s_cr}" '\n\r'
}

# The whole dotenv line grammar lives in two places:
# _env_parse_assignment_line (what one physical line means in isolation: a
# comment, blank, an `export`-prefixed or plain assignment, a bare
# inherit-from-environment key, or nothing that matches) and _env_tokenize
# (walk every physical line of the file once, in order, using
# _env_parse_assignment_line for every line that is not a multiline quote's
# continuation and _env_quote_scan to decide when one is). Every lookup calls
# _env_tokenize and then selects among its records (_env_select_record), so a
# key-shaped physical line inside a multiline value's body
# (`POSTGRES_DB='alpha\nPOSTGRES_DB=inner\nomega'`) is never mistaken for a
# redefinition: the tokenizer only asks _env_parse_assignment_line about a
# line once _env_quote_scan on the preceding lines shows it is not inside an
# open quote.
#
# Every rule below was verified against a live `docker compose config`,
# not assumed (compose's dotenv parser is the godotenv fork in
# compose-go/dotenv):
#   - leading whitespace (spaces AND tabs) before KEY is skipped.
#   - an optional `export` + whitespace prefix is stripped before KEY.
#   - whitespace around `=` is trimmed (`KEY = v` and `KEY=v` are the
#     same key/value).
#   - a bare `KEY` line (no `=` at all) means "inherit from the process
#     environment" — resolves to that value, or "" if the environment
#     doesn't have it either (with a warning on real Compose's side this
#     parser has no channel to raise, matching the policy already
#     documented on the interpolation resolver above for the same
#     reason). This DOES count as `key=file` for a top-level
#     get_env_value/env_value_into lookup (rc 0), unlike a key genuinely
#     absent from the file altogether (rc 1) — Compose treats them
#     differently too (an inherited key can still be queried; an absent
#     one has nothing to inherit FROM).
#   - CRLF line endings: a trailing \r is part of the line terminator,
#     never the value (`KEY=v\r\n` resolves to `v`, not `v\r`).
#   - a comment line may have leading whitespace before its `#`.
#   - `#` immediately after an unquoted value with NO preceding space is
#     literal, not a comment (`FOO=bar#baz` -> `bar#baz`) — the space
#     before `#` is required, matching the policy already
#     documented on get_env_value below.
#   - trailing whitespace on an UNQUOTED value is trimmed; a QUOTED
#     value's trailing whitespace is content and kept (both already
#     documented on get_env_value below; unaffected by the line grammar).
#   - `KEY=` (nothing after `=`) is a present, empty value — rc 0, "".
#   - duplicate definitions: the LAST one wins, whether or not either is
#     `export`-prefixed, and regardless of whether an earlier series of
#     physical lines sat inside an unrelated key's multiline value (which the
#     tokenizer handles). A genuine later top-level redefinition still wins.
#   - a key name that is a literal prefix of another (`DB=` vs
#     `DB_NAME=`) never cross-matches — key extraction stops at the
#     first non-identifier character, so `DB_NAME` is never mistaken for
#     `DB` followed by literal text.
# Scans $1 for the first unescaped occurrence of quote character $2.
# Escape-aware for both quote types: any backslash unconditionally pairs with
# whatever character follows it, consumed together, so a paired quote
# character never closes the string early. This disagrees with the docs
# summary (which claims single-quoted `\'` does not escape); a real `docker
# compose config` on `'geo\'lens'` returns `geo'lens`: the backslash is
# consumed and the apostrophe becomes literal content. This matches the
# oracle, not the docs. Also verified: `\\` in a single-quoted value stays as
# two literal backslashes; single-quoted escaping recognizes only `\'`, and a
# backslash before anything else (including another backslash) is literal. A
# recognized single-quoted `\'` pair is decoded to a bare `'` during the scan,
# unlike double-quoted values, whose escape pairs are consumed here verbatim
# and unescaped afterward by _env_unescape_double_quoted; single-quoted values
# have no separate unescape step, so this is the only place that can decode
# without re-deriving where the escape pairs were.
#
# Character-scanning (like _env_brace_match) rather than a `grep -qE`/`sed -E`
# regex, because $1 can be a multi-line string (a value gathered across
# physical lines) and grep/sed apply `^`/`$` per physical line, which cannot
# validate or extract a multi-line quoted value as one logical unit. Used by
# _env_tokenize (deciding whether a value's quote closes on its own line or
# needs more) and by _env_dequote/get_env_value's dequoting dispatch.
#
# Sets three globals: _eqs_found (1 if a close was located, 0 if $1 ran out
# first), _eqs_before (the quoted content, exclusive of both quote characters,
# single-quoted `\'` pairs already decoded to `'`), and _eqs_after (everything
# in $1 following the close). A caller validates that _eqs_after is empty,
# whitespace or a comment before trusting _eqs_before.
_env_quote_scan() {
  _eqs_text="$1"
  _eqs_quote="$2"
  _eqs_found=0
  _eqs_before=""
  _eqs_after=""
  _eqs_scan="$_eqs_text"
  while [ -n "$_eqs_scan" ]; do
    _eqs_c="${_eqs_scan%"${_eqs_scan#?}"}"
    _eqs_scan="${_eqs_scan#?}"
    if [ "$_eqs_c" = "\\" ] && [ -n "$_eqs_scan" ]; then
      _eqs_nc="${_eqs_scan%"${_eqs_scan#?}"}"
      _eqs_scan="${_eqs_scan#?}"
      if [ "$_eqs_quote" = "'" ] && [ "$_eqs_nc" = "'" ]; then
        _eqs_before="${_eqs_before}${_eqs_nc}"
      else
        _eqs_before="${_eqs_before}${_eqs_c}${_eqs_nc}"
      fi
      continue
    fi
    if [ "$_eqs_c" = "$_eqs_quote" ]; then
      _eqs_found=1
      _eqs_after="$_eqs_scan"
      return 0
    fi
    _eqs_before="${_eqs_before}${_eqs_c}"
  done
  return 0
}

_env_lstrip_ws() {
  _elw_s="$1"
  while :; do
    case "$_elw_s" in
      " "*) _elw_s="${_elw_s# }" ;;
      "$_ENV_TAB"*) _elw_s="${_elw_s#"$_ENV_TAB"}" ;;
      *) break ;;
    esac
  done
  printf '%s' "$_elw_s"
}

# Parses one physical line (already CR-stripped by the caller) in isolation,
# per the grammar documented above. Sets _epa_is_record (1 for an assignment
# or bare key; 0 for a comment, blank or unrecognized line such as leading
# punctuation, all of which _env_tokenize skips alike). For a record it also
# sets _epa_key, _epa_bare (1 for a bare inherit-from-environment key, 0 for a
# real `=` assignment) and _epa_value (the assignment's raw value, with
# `=`-adjacent whitespace already trimmed; meaningless when _epa_bare=1).
_env_parse_assignment_line() {
  _epa_line="$1"
  _epa_is_record=0
  _epa_key=""
  _epa_bare=0
  _epa_value=""

  _epa_s="$(_env_lstrip_ws "$_epa_line")"
  case "$_epa_s" in
    ""|"#"*) return 0 ;;
  esac

  case "$_epa_s" in
    "export "*|"export$_ENV_TAB"*)
      _epa_s="${_epa_s#export}"
      _epa_s="$(_env_lstrip_ws "$_epa_s")"
      ;;
  esac

  # Compose's key grammar: letters, digits and `_.-[]`, ended by
  # `=` or `:`; whitespace ends the scan too and the parse phase judges it.
  _epa_first="${_epa_s%"${_epa_s#?}"}"
  case "$_epa_first" in
    []A-Za-z0-9_.[-]) : ;;
    *) return 0 ;;
  esac

  _epa_scan="$_epa_s"
  while [ -n "$_epa_scan" ]; do
    _epa_c="${_epa_scan%"${_epa_scan#?}"}"
    case "$_epa_c" in
      []A-Za-z0-9_.[-]) _epa_key="${_epa_key}${_epa_c}"; _epa_scan="${_epa_scan#?}" ;;
      *) break ;;
    esac
  done

  _epa_scan="$(_env_lstrip_ws "$_epa_scan")"
  case "$_epa_scan" in
    "="*|":"*)
      _epa_value="$(_env_lstrip_ws "${_epa_scan#?}")"
      _epa_bare=0
      ;;
    *)
      _epa_bare=1
      ;;
  esac
  _epa_is_record=1
  return 0
}

# Walks EVERY physical line of `$1` exactly once, in order, producing a
# stream of records — one line per record, "TYPE START END KEY" — that
# every lookup below selects among (_env_select_record) instead of
# grepping the file itself. TYPE is `A` (a real `key=value` assignment,
# possibly spanning START..END physical lines if it opens a multiline
# quote), `B` (a bare inherit-from-environment key — always START==END),
# or `U` (an assignment that opens a quote which never closes before
# EOF — always the LAST record, since nothing after it can be parsed).
# CR/BOM stripping happens ONCE here, on this one read of the file, and
# nowhere else needs to repeat it.
_env_tokenize() {
  _etk_file="$1"
  _etk_content="$(cat "$_etk_file" && printf x)" || return 1
  _etk_content="${_etk_content%x}"
  case "$_etk_content" in
    "$_ENV_BOM"*) _etk_content="${_etk_content#"$_ENV_BOM"}" ;;
  esac

  _etk_lineno=0
  _etk_in_quote=0
  _etk_quote_char=""
  _etk_cur_key=""
  _etk_cur_start=0
  _etk_result=""
  _etk_remaining="$_etk_content"

  while :; do
    _etk_lineno=$((_etk_lineno + 1))
    case "$_etk_remaining" in
      *"$_ENV_NL"*)
        _env_split_on_token "$_etk_remaining" "$_ENV_NL"
        _etk_line="$_env_split_before"
        _etk_remaining="$_env_split_after"
        _etk_at_eof=0
        ;;
      *)
        _etk_line="$_etk_remaining"
        _etk_remaining=""
        _etk_at_eof=1
        ;;
    esac
    case "$_etk_line" in
      *"$_ENV_CR") _etk_line="${_etk_line%"$_ENV_CR"}" ;;
    esac

    if [ "$_etk_in_quote" -eq 1 ]; then
      _env_quote_scan "$_etk_line" "$_etk_quote_char"
      if [ "$_eqs_found" -eq 1 ]; then
        _etk_in_quote=0
        _etk_result="${_etk_result}A ${_etk_cur_start} ${_etk_lineno} ${_etk_cur_key}
"
      fi
    else
      _env_parse_assignment_line "$_etk_line"
      if [ "$_epa_is_record" -eq 1 ]; then
        _etk_cur_key="$_epa_key"
        _etk_cur_start="$_etk_lineno"
        if [ "$_epa_bare" -eq 1 ]; then
          _etk_result="${_etk_result}B ${_etk_lineno} ${_etk_lineno} ${_epa_key}
"
        else
          case "$_epa_value" in
            \"*|\'*)
              _etk_quote_char="${_epa_value%"${_epa_value#?}"}"
              _env_quote_scan "${_epa_value#?}" "$_etk_quote_char"
              if [ "$_eqs_found" -eq 1 ]; then
                _etk_result="${_etk_result}A ${_etk_cur_start} ${_etk_lineno} ${_etk_cur_key}
"
              else
                _etk_in_quote=1
              fi
              ;;
            *)
              _etk_result="${_etk_result}A ${_etk_cur_start} ${_etk_lineno} ${_etk_cur_key}
"
              ;;
          esac
        fi
      fi
    fi

    [ "$_etk_at_eof" -eq 0 ] || break
  done

  if [ "$_etk_in_quote" -eq 1 ]; then
    _etk_result="${_etk_result}U ${_etk_cur_start} ${_etk_lineno} ${_etk_cur_key}
"
  fi

  printf '%s' "$_etk_result"
}

# Selects the LAST record for `key` in the `records` stream (from
# _env_tokenize) whose start line is strictly before `before` (before=0
# disables the bound) — Compose's own "last definition wins" rule,
# applied only to REAL records the tokenizer identified, never to a
# key-shaped line inside another key's multiline value. Sets
# _esr_found (0 none, 1 found, 2 found but it is a `U` — unterminated —
# record: a DIFFERENT outcome than "not found", callers must not treat
# this as though the key were simply undefined), _esr_type (A/B),
# _esr_start, _esr_end.
_env_select_record() {
  _esr_records="$1"
  _esr_key="$2"
  _esr_before="$3"
  _esr_found=0
  _esr_type=""
  _esr_start=0
  _esr_end=0

  _esr_remaining="$_esr_records"
  while [ -n "$_esr_remaining" ]; do
    case "$_esr_remaining" in
      *"$_ENV_NL"*)
        _env_split_on_token "$_esr_remaining" "$_ENV_NL"
        _esr_rec="$_env_split_before"
        _esr_remaining="$_env_split_after"
        ;;
      *)
        _esr_rec="$_esr_remaining"
        _esr_remaining=""
        ;;
    esac
    [ -n "$_esr_rec" ] || continue
    # A key may hold `[` or `]`, which glob under an unquoted
    # expansion, so the "TYPE START END KEY" record is split by expansion.
    _esr_rtype="${_esr_rec%% *}"
    _esr_rest="${_esr_rec#* }"
    _esr_rstart="${_esr_rest%% *}"
    _esr_rest="${_esr_rest#* }"
    _esr_rend="${_esr_rest%% *}"
    _esr_rkey="${_esr_rest#* }"
    if [ "$_esr_rkey" = "$_esr_key" ] && { [ "$_esr_before" = "0" ] || [ "$_esr_rstart" -lt "$_esr_before" ]; }; then
      _esr_type="$_esr_rtype"
      _esr_start="$_esr_rstart"
      _esr_end="$_esr_rend"
      if [ "$_esr_rtype" = "U" ]; then
        _esr_found=2
      else
        _esr_found=1
      fi
    fi
  done
}

# Re-derives the raw value of a KNOWN `A`-type record (start/end already
# located by _env_tokenize + _env_select_record) — the opening line's own
# value (via _env_parse_assignment_line, so `export`/whitespace-around-`=`
# are handled identically to how the record was FOUND, not re-guessed)
# plus every physical line start+1..end verbatim, newline-joined. Never
# called for a `B` (bare) or `U` (unterminated) record — callers handle
# those themselves.
_env_extract_record_raw() {
  _eer_file="$1"
  _eer_start="$2"
  _eer_end="$3"

  _eer_content="$(cat "$_eer_file" && printf x)" || return 1
  _eer_content="${_eer_content%x}"
  case "$_eer_content" in
    "$_ENV_BOM"*) _eer_content="${_eer_content#"$_ENV_BOM"}" ;;
  esac

  _eer_lineno=0
  _eer_remaining="$_eer_content"
  _eer_acc=""
  while :; do
    _eer_lineno=$((_eer_lineno + 1))
    case "$_eer_remaining" in
      *"$_ENV_NL"*)
        _env_split_on_token "$_eer_remaining" "$_ENV_NL"
        _eer_line="$_env_split_before"
        _eer_remaining="$_env_split_after"
        _eer_at_eof=0
        ;;
      *)
        _eer_line="$_eer_remaining"
        _eer_remaining=""
        _eer_at_eof=1
        ;;
    esac
    case "$_eer_line" in
      *"$_ENV_CR") _eer_line="${_eer_line%"$_ENV_CR"}" ;;
    esac

    if [ "$_eer_lineno" -eq "$_eer_start" ]; then
      _env_parse_assignment_line "$_eer_line"
      _eer_acc="$_epa_value"
    elif [ "$_eer_lineno" -gt "$_eer_start" ] && [ "$_eer_lineno" -le "$_eer_end" ]; then
      _eer_acc="${_eer_acc}
${_eer_line}"
    fi

    if [ "$_eer_lineno" -ge "$_eer_end" ] || [ "$_eer_at_eof" -eq 1 ]; then
      break
    fi
  done
  printf '%s' "$_eer_acc"
}

# The 1-based line number of key's last definition (of any type) strictly
# before line `before` (before=0 disables the bound), or 0 if none. A thin
# _env_select_record wrapper; see _env_interpolate's doc comment for why a
# fresh bound is re-derived per substitution rather than reusing the outer
# key's.
_env_line_of_before() {
  key="$1"
  file="$2"
  before="$3"
  _elob_records="$(_env_tokenize "$file")" || { echo 0; return 0; }
  _env_select_record "$_elob_records" "$key" "$before"
  echo "$_esr_start"
}

# The 1-based line number of key's LAST definition (of any type) in file,
# or 0 if absent — _env_line_of_before with no bound.
_env_line_of() {
  _env_line_of_before "$1" "$2" 0
}

# Raw (unprocessed — no quote/comment stripping) LOGICAL value of key,
# from the LAST record strictly before line `before` (before=0 disables
# the bound) — possibly spanning several physical lines (a multiline
# quote) or resolved directly from the process environment (a bare key).
# Exit status: 0 found (prints the value); 1 key has no such record at
# all, so the caller can tell "defined here, value empty" apart from "not
# defined before this line" and correctly fall through to the process
# environment; 2 key IS defined here, but its value is an unterminated
# multiline quote — DIFFERENT from "not found", a caller must not
# silently fall through to the process environment on this one (see
# _env_resolve_name).
_env_raw_before() {
  key="$1"
  file="$2"
  before="$3"
  _erb_records="$(_env_tokenize "$file")" || return 1
  _env_select_record "$_erb_records" "$key" "$before"
  case "$_esr_found" in
    0) return 1 ;;
    2) return 2 ;;
  esac
  if [ "$_esr_type" = "B" ]; then
    # Checks the frozen snapshot, not the
    # live "${key+set}" — see the snapshot block's own comment near the
    # top of this file for why a live check is unsafe here.
    if _env_snapshot_has "$key"; then
      _env_snapshot_value "$key"
    fi
    return 0
  fi
  _env_extract_record_raw "$file" "$_esr_start" "$_esr_end"
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
      _env_quote_scan "${raw#?}" '"'
      if [ "$_eqs_found" -eq 1 ] && printf '%s\n' "$_eqs_after" | grep -qE '^[[:space:]]*(#.*)?$'; then
        _env_unescape_double_quoted "$_eqs_before"
      else
        printf '%s' "$raw"
      fi
      ;;
    \'*)
      # A single-quoted value is literal apart from the `\'` escape;
      # _env_quote_scan locates the real close and decodes it.
      _env_quote_scan "${raw#?}" "'"
      if [ "$_eqs_found" -eq 1 ] && printf '%s\n' "$_eqs_after" | grep -qE '^[[:space:]]*(#.*)?$'; then
        printf '%s' "$_eqs_before"
      else
        printf '%s' "$raw"
      fi
      ;;
    *)
      printf '%s' "$raw" | sed -E -e 's/ #.*$//' -e 's/[[:space:]]+$//' -e 's/^[[:space:]]+//'
      ;;
  esac
}

# Substitution splits `remaining` around the literal `$token` with shell
# parameter expansion (`${remaining%%"$token"*}` / `${remaining#*"$token"}`)
# rather than building a sed program from data. A replacement containing a
# literal newline (reachable once a double-quoted value's `\n` escape is
# decoded, e.g. `DB_NAME="prod\narchive"` referenced as `${DB_NAME}`) would
# break a `sed "s/${pat}/${rep}/"` program. Callers invoke this through
# `get_env_value` inside `if _v="$(get_env_value ...)"`, so that failure would
# surface as success with an empty value, and restore.sh would silently fall
# back to its hardcoded `geolens` default instead of the operator's database
# name. Plain substring matching is byte-for-byte safe with an embedded
# newline in either the text or the token (quoting a parameter inside the
# pattern matches it literally, not as a glob, per POSIX quote removal before
# matching).
#
# Splits `remaining` on the first occurrence of the literal string `token`.
# Returns via two globals, `_env_split_before` and `_env_split_after`, instead
# of a single stdout stream, because the text either side of `token` may
# contain a real embedded newline (a decoded `\n`) that a single delimited
# stdout format could not encode unambiguously. Not reentrant across a call
# site, which is fine: every caller consumes both immediately.
_env_split_on_token() {
  _est_text="$1"
  _est_token="$2"
  _env_split_before="${_est_text%%"$_est_token"*}"
  _env_split_after="${_est_text#*"$_est_token"}"
}

# Resolves NAME per Compose's precedence: process environment first (even
# set-but-empty counts as set), falling back to an earlier line in FILE
# strictly before BOUND only when the environment has no NAME at all. Sets
# three globals: _ern_have_value (1 if resolved from either source, 0 if
# neither has it), _ern_resolved (the resolved value; meaningless when
# _ern_have_value=0), and _ern_ref_bound (the line to bound a further
# reference found inside this value's text against: NAME's defining line for a
# file-sourced value, 0/unbounded for a process-environment value, which has
# no line in this file). Returns non-zero only on a genuine internal failure
# (propagated from _env_dequote); "NAME not found anywhere" is
# _ern_have_value=0, a normal outcome the caller handles (literal token, a
# fallback, or its own hard error for `:?`/`?`).
#
# CHAIN is the space-delimited list of names whose value is currently being
# expanded up the call stack (seeded with the top-level key; see
# _env_interpolate). If NAME is already in CHAIN this is a cycle (`A=${A}`, or
# `A=${B}` / `B=${A}`), reported as _ern_have_value=0 without attempting the
# FILE lookup, as if NAME did not exist. Verified against real `docker compose
# config`: a cycle is not a hard failure there. Compose warns ("the X variable
# is not set") and resolves it like any unset variable, so `${A:-fallback}` on
# a self-cycle returns "fallback" and `${A:?msg}` fails closed, the same
# outcomes an ordinary never-defined NAME gets from the per-operator handling
# in _env_interp_resolve.
#
# The process environment check must run before the cycle check: the
# precedence rule applies to every name, including one currently being
# expanded. `POSTGRES_DB="${POSTGRES_DB:-geolens}"` with
# `POSTGRES_DB=production` exported is not a cycle Compose has to break,
# because the shell environment answers before Compose looks at the file's
# text for POSTGRES_DB. Checking CHAIN first would treat it as a self-cycle
# and yield the `:-` fallback ("geolens") instead of the exported
# "production". This holds for a two-node cycle where only one name is
# exported too, from either query direction.
_env_resolve_name() {
  _ern_name="$1"
  _ern_file="$2"
  _ern_bound="$3"
  _ern_chain="$4"
  _ern_have_value=0
  _ern_resolved=""
  _ern_ref_bound=0
  _ern_from_env=0

  # Checks the frozen snapshot, not the live "${_ern_name+set}"; see the
  # snapshot block's comment near the top of this file. A live check would
  # let a prior env_value_into call in the same script (assigning some other
  # key) masquerade as an inherited override for whatever name an
  # interpolation reference asks about next.
  if _env_snapshot_has "$_ern_name"; then
    _ern_resolved="$(_env_snapshot_value "$_ern_name" && printf x)"
    _ern_resolved="${_ern_resolved%x}"
    _ern_have_value=1
    _ern_ref_bound=0
    # A value sourced from the process environment is used verbatim, never
    # recursively re-interpolated. Verified against the oracle: an
    # exported OUTER='${INNER}' referenced as ${OUTER}, with INNER also
    # exported as "leafval", resolves to the literal "${INNER}", not
    # "leafval". Compose only interpolates ${...} references in the .env
    # file's own text; a process environment value is opaque,
    # already-resolved data. _ern_from_env tells the caller
    # (_env_interp_resolve) not to recurse into this value.
    _ern_from_env=1
    return 0
  fi

  case " ${_ern_chain} " in
    *" ${_ern_name} "*) return 0 ;;
  esac

  # Calls _env_tokenize/_env_select_record directly (rather than
  # _env_raw_before) so _esr_type is read in this function's own process:
  # _env_raw_before runs in a `$(...)` subshell at its call site, whose
  # variable assignments never propagate back.
  _ern_records="$(_env_tokenize "$_ern_file")" || return 1
  _env_select_record "$_ern_records" "$_ern_name" "$_ern_bound"
  case "$_esr_found" in
    0) return 0 ;;
    2)
      # NAME is defined here, but its value is an unterminated multiline
      # quote, which Compose's own .env load hard-fails on. Propagate a
      # real failure instead of falling through to have_value=0, which
      # would treat a malformed value as though NAME were never defined
      # and quietly resolve a reference via the process environment or a
      # `:-`/`-` fallback.
      return 1
      ;;
  esac

  if [ "$_esr_type" = "B" ]; then
    # A bare `KEY` line (no `=`) referenced via ${NAME} — Compose treats
    # this as "inherit from the process environment", but we already
    # checked the snapshot above and it did not have NAME.
    #
    # A bare line with nothing to inherit is genuinely unset, not "set to
    # empty". Verified against the oracle:
    # POSTGRES_DB=${SOMEBARE-fallback} with SOMEBARE a bare, uninherited
    # line resolves to "fallback" (the `-` operator substitutes its
    # default only for a truly unset name). Leaving _ern_have_value at its
    # function-entry default of 0, the same outcome as "no record for this
    # name", makes every presence-testing operator
    # (`-`/`:-`/`+`/`:+`/`?`/`:?`) treat it like any other never-defined
    # name.
    return 0
  fi

  # A value decoded from a double-quoted `\n`/`\r`/`\t` escape can end in a
  # real trailing control byte, and `$(...)` strips trailing newlines, so
  # capturing _env_dequote's output directly would truncate exactly that
  # byte before the substitution. Sentinel-protect the capture: append a
  # marker byte inside the same command substitution and strip only the
  # marker afterward. `&&` (not `;`) between the decode and the marker means
  # a failure inside _env_dequote is never masked as success with an empty
  # value: it aborts the marker, the substitution's exit status reflects the
  # failure, and `|| return 1` fails closed.
  _ern_earlier="$(_env_extract_record_raw "$_ern_file" "$_esr_start" "$_esr_end")" || return 1
  _ern_resolved="$(_env_dequote "$_ern_earlier" && printf x)" || return 1
  _ern_resolved="${_ern_resolved%x}"
  _ern_have_value=1
  _ern_ref_bound="$_esr_start"
  _ern_from_env=0
  return 0
}

# Finds the `}` that closes
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

# Recursively resolves Compose's full interpolation grammar in `text`: $VAR,
# ${VAR}, ${VAR:-d}, ${VAR-d}, ${VAR:?m}, ${VAR?m}, ${VAR:+a}, ${VAR+a}, and
# the `$$` literal-dollar escape, per the precedence and unresolved-reference
# policy documented above `_env_resolve_name`. `bound` is the line strictly
# before which a reference may resolve against this file (the referencing
# key's own line, from _env_line_of, so a key never resolves a reference
# against itself or a later line); `chain` is the space-delimited list of
# names currently being expanded, threaded down so _env_resolve_name can
# detect a name recurring in its own resolution and treat it as unresolved
# instead of looping.
#
# Each token is resolved in place by scanning `text` left to right. `bound` is
# passed unchanged to every sibling token in the same `text` and narrowed only
# for the recursive call that resolves a substituted token's own value (to
# that token's defining line). That is what makes `POSTGRES_DB="${A}_${B}"`
# resolve `${B}` against the same outer bound `${A}` used. A
# default/alt-value's own text (the `x` in `${A:-x}`) is resolved the same
# way, against the outer `bound`, since it sits in the referencing key's own
# value.
#
# The scanner finds the next `$` in the text (a literal search; see
# _env_split_on_token, safe with an embedded real newline either side) and
# dispatches on what follows, per real Compose's behavior (verified
# empirically; the oracle test's corpus covers every case):
#   $$          -> a literal single $, consumed whole; nothing after it is
#                  re-scanned as a fresh reference. Verified against
#                  `docker compose config --environment` and a real running
#                  container's environment, which agree; `--format json` does
#                  not resolve `$$` (it round-trip-normalizes literal dollar
#                  signs in its output). The oracle test's _compose_dollar_value
#                  helper documents this.
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
  _eir_chain="$4"

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
        # $$ is a literal single $ (see the doc comment above).
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

        # A name must start with [A-Za-z_]: `${5abc}` (digit-leading)
        # is a hard "Invalid template" failure on real `docker compose
        # config`, the same class as `${}` (empty name) and `${A!x}`
        # (an undocumented operator character). Checking the first
        # character separately from the continuation class below
        # (which allows digits, as the bare $NAME dispatch does) keeps
        # a digit-leading name out of _eir_iname.
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
          # Verified against real `docker compose config`: `${}`,
          # `${5abc}` and `${A!x}` are all hard "Invalid template"
          # failures (the same class as an unterminated `${VAR`),
          # not literal pass-through. get_env_value fails closed for
          # this key to match.
          return 1
        fi

        _env_resolve_name "$_eir_iname" "$_eir_file" "$_eir_bound" "$_eir_chain" || return 1

        case "$_eir_op" in
          "")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
              _eir_rep_from_env="$_ern_from_env"
            else
              _eir_result="${_eir_result}\${${_eir_iname}}"
              continue
            fi
            ;;
          ":-")
            if [ "$_ern_have_value" -eq 1 ] && [ -n "$_ern_resolved" ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
              _eir_rep_from_env="$_ern_from_env"
            else
              _eir_replacement="$_eir_arg"
              _eir_rep_bound="$_eir_bound"
              _eir_rep_from_env=0
            fi
            ;;
          "-")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
              _eir_rep_from_env="$_ern_from_env"
            else
              _eir_replacement="$_eir_arg"
              _eir_rep_bound="$_eir_bound"
              _eir_rep_from_env=0
            fi
            ;;
          ":+")
            if [ "$_ern_have_value" -eq 1 ] && [ -n "$_ern_resolved" ]; then
              _eir_replacement="$_eir_arg"
            else
              _eir_replacement=""
            fi
            _eir_rep_bound="$_eir_bound"
            _eir_rep_from_env=0
            ;;
          "+")
            if [ "$_ern_have_value" -eq 1 ]; then
              _eir_replacement="$_eir_arg"
            else
              _eir_replacement=""
            fi
            _eir_rep_bound="$_eir_bound"
            _eir_rep_from_env=0
            ;;
          ":?")
            if [ "$_ern_have_value" -eq 1 ] && [ -n "$_ern_resolved" ]; then
              _eir_replacement="$_ern_resolved"
              _eir_rep_bound="$_ern_ref_bound"
              _eir_rep_from_env="$_ern_from_env"
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
              _eir_rep_from_env="$_ern_from_env"
            else
              return 1
            fi
            ;;
        esac

        # Extends a separate chain variable for the recursive call and
        # never mutates `_eir_chain`, which stays the outer call's
        # chain for every remaining sibling token in this loop (the
        # same never-mutate-the-shared-parameter rule `bound`
        # follows).
        #
        # A process-environment-sourced replacement
        # (_eir_rep_from_env=1) is used verbatim, never fed back
        # through _env_interp_resolve; see _env_resolve_name for why.
        # That is what makes checking the environment before the cycle
        # chain safe: an env-sourced value never triggers further
        # recursion, so a multi-hop cycle sourced entirely from
        # exported variables still terminates after one substitution
        # per name.
        if [ "$_eir_rep_from_env" -eq 1 ]; then
          _eir_result="${_eir_result}${_eir_replacement}"
        else
          _eir_sub_chain="${_eir_chain} ${_eir_iname}"
          _eir_sub="$(_env_interp_resolve "$_eir_replacement" "$_eir_file" "$_eir_rep_bound" "$_eir_sub_chain" && printf x)" || return 1
          _eir_sub="${_eir_sub%x}"
          _eir_result="${_eir_result}${_eir_sub}"
        fi
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

        _env_resolve_name "$_eir_name" "$_eir_file" "$_eir_bound" "$_eir_chain" || return 1
        if [ "$_ern_have_value" -eq 1 ]; then
          if [ "$_ern_from_env" -eq 1 ]; then
            _eir_result="${_eir_result}${_ern_resolved}"
          else
            _eir_sub_chain="${_eir_chain} ${_eir_name}"
            _eir_sub="$(_env_interp_resolve "$_ern_resolved" "$_eir_file" "$_ern_ref_bound" "$_eir_sub_chain" && printf x)" || return 1
            _eir_sub="${_eir_sub%x}"
            _eir_result="${_eir_result}${_eir_sub}"
          fi
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

# $4 seeds the cycle-detection chain with the top-level key's own name
# (get_env_value's `$key`), so a value that references its own key directly
# (`POSTGRES_DB="${POSTGRES_DB}_suffix"`) is caught as a cycle from the first
# token.
_env_interpolate() {
  _env_interp_resolve "$1" "$2" "$3" "$4"
}

# Read a value from .env. Handles values containing `=` correctly (returns the
# full remainder after the first `=`). Reads from "$1" if given, else ./.env.
#
# Returns 1 (and prints nothing) when the file does not exist or the key has
# no `key=` line in it at all, distinct from printing an empty string with
# exit 0, which means the key is defined with an empty value. A key a `.env`
# never mentions (relying on Compose's `POSTGRES_DB=prod scripts/restore.sh
# ...` process-environment override) must not look like `POSTGRES_DB=` on its
# own line, or `POSTGRES_DB="$(get_env_value POSTGRES_DB .env)"` would
# overwrite the inherited process value with an empty string. Callers that
# want "fall back to whatever is already in the environment" guard the
# assignment on this exit status, e.g. `if _v="$(get_env_value POSTGRES_DB
# "$file")"; then POSTGRES_DB="$_v"; fi`. Assigning only inside the `if`
# (never to the real target on the failure path) is what preserves the
# inherited value; `if` conditions are exempt from `set -e`, so this does not
# abort the caller even though the function may `return 1`.
#
# The top-level lookup keeps the last `key=` match: Compose reads an env file
# top-to-bottom and lets a later definition of the same key win, as the
# interpolation helpers (_env_line_of, _env_raw_before) already implement for
# ${VAR} references. Interpolation precedence inside a resolved value (earlier
# line in this file, then the process environment) is covered in
# _env_interpolate's doc comment; this is only about whether the key itself
# appears in the file.
#
# The awk extraction returns everything after the first `=` verbatim, but
# Docker Compose's own .env parser does not treat that text as a bare string.
# `COMPOSE_FILE="docker-compose.prod.yml"` or `POSTGRES_USER="geolens"` is
# valid Compose syntax and resolves to the unquoted value, so quotes attached
# to the result would break every caller that put it in a path or SQL
# identifier. Apply the rules Compose's env-file reference documents:
#   - a value wrapped in one matching pair of double or single quotes has
#     the quotes stripped;
#   - inside DOUBLE quotes, Compose's documented escapes are decoded (`\"`,
#     `\\`, `\n`, `\r`, `\t`; see _env_unescape_double_quoted); single-quoted
#     values are literal apart from `\'`, with no interpolation;
#   - an UNQUOTED value's inline comment (a literal space then `#`, to end
#     of line) is stripped and the result is whitespace-trimmed, matching
#     Compose's own "inline comments for unquoted values must be preceded
#     by a space" rule. A quoted value's `#` is always literal; comment
#     stripping never applies once a value is quoted, but the comment may
#     still follow the closing quote:
#     `COMPOSE_FILE="docker-compose.prod.yml" # production` is valid Compose
#     syntax. Whether a value is quoted is decided by its first character
#     only; where the closing quote falls, and whether only whitespace or a
#     comment trails it, is resolved by the quote scan below rather than by
#     the raw string's last character.
# A malformed quote (opens but never closes, or has non-comment content after
# the closing quote) is left completely alone rather than guessed at.
get_env_value() {
  key="$1"
  file="${2:-.env}"

  [ -f "$file" ] || return 1

  # Selects among the records _env_tokenize identified for the whole file in
  # one pass, instead of a standalone `^key=` scan, which is blind to
  # multiline continuations (a key-shaped line inside another key's
  # multiline value could win the "last definition" lookup) and to
  # `export`/bare-key/CRLF/whitespace-around-`=` lines (see _env_tokenize's
  # doc comment; each verified against the oracle). BEFORE ($3, default 0)
  # keeps only records that start before that line, as _env_select_record
  # does; RECORDS ($4) is _env_tokenize's stream for FILE when the caller
  # already holds it, so FILE is read once.
  _gev_records="${4:-}"
  [ -n "$_gev_records" ] || _gev_records="$(_env_tokenize "$file")" || return 1
  _env_select_record "$_gev_records" "$key" "${3:-0}"
  case "$_esr_found" in
    0) return 1 ;;
    2) return 1 ;;
  esac
  _gev_line="$_esr_start"

  if [ "$_esr_type" = "B" ]; then
    # A bare `KEY` line (no `=`): Compose treats this as "inherit from the
    # process environment", so no quoting, escaping or interpolation
    # applies. Checks the frozen snapshot, not the live "${key+set}"; see
    # the snapshot block's comment near the top of this file.
    #
    # When the snapshot has nothing to inherit, the key is genuinely
    # absent (rc 1), not present with an empty string (rc 0). Verified
    # against the oracle: with no process value, ${KEY-fallback} and
    # ${KEY:-fallback} both resolve to "fallback" (docker compose config
    # --format json), so Compose treats KEY as unset; only a set value
    # (even an empty one) makes `-` skip the fallback. Returning rc 1
    # leaves env_value_into's target untouched, exactly like a key absent
    # from the file.
    if _env_snapshot_has "$key"; then
      _env_snapshot_value "$key"
      return 0
    fi
    return 1
  fi

  # raw is the logical value: a single physical line for an unquoted value
  # or a quote that closes on its own line, several newline-joined physical
  # lines for a quote that does not (see _env_extract_record_raw). The
  # unterminated-quote case (_esr_found=2) was caught above: Compose's own
  # .env load hard-fails on that shape, so get_env_value fails closed to
  # match, as for an unterminated `${VAR` interpolation reference.
  raw="$(_env_extract_record_raw "$file" "$_esr_start" "$_esr_end")" || return 1

  case "$raw" in
    \"*)
      # _env_quote_scan (a character scan, not a `grep -qE`/`sed -E`
      # regex, whose `^`/`$` anchor to physical lines and cannot
      # validate a multi-line quoted value as one logical unit) decides
      # where the quote closes. What follows the close must be nothing,
      # whitespace, or a `#comment`; anything else (including a second,
      # unrelated quoted chunk) is left alone as malformed.
      _env_quote_scan "${raw#?}" '"'
      if [ "$_eqs_found" -eq 1 ] && printf '%s\n' "$_eqs_after" | grep -qE '^[[:space:]]*(#.*)?$'; then
        # A value whose `\n`/`\r`/`\t` escape decodes to a trailing
        # control byte (e.g. `DB_NAME="prod\n"`) would lose that byte
        # to plain `$(...)`, which always strips trailing newlines.
        # Sentinel-protect the capture (append a marker inside the
        # same substitution, strip only the marker afterward); `&&`
        # (not `;`) means a failure inside the decoder is never masked
        # as success with an empty value, and this function fails
        # closed via `|| return 1`.
        _env_value="$(_env_unescape_double_quoted "$_eqs_before" && printf x)" || return 1
        _env_value="${_env_value%x}"
        # double-quoted values interpolate
        # ${VAR}/$VAR references, matching Compose (only single-quoted
        # values are literal there).
        _env_interpolate "$_env_value" "$file" "$_gev_line" "$key"
      else
        printf '%s' "$raw"
      fi
      ;;
    \'*)
      # Single-quoted values are literal in Compose: no interpolation,
      # and the only escape is `\'`, which _env_quote_scan decodes while
      # locating the real close.
      _env_quote_scan "${raw#?}" "'"
      if [ "$_eqs_found" -eq 1 ] && printf '%s\n' "$_eqs_after" | grep -qE '^[[:space:]]*(#.*)?$'; then
        printf '%s' "$_eqs_before"
      else
        printf '%s' "$raw"
      fi
      ;;
    *)
      _env_value="$(
        printf '%s' "$raw" | sed -E -e 's/ #.*$//' -e 's/[[:space:]]+$//' -e 's/^[[:space:]]+//'
      )"
      # Unquoted values interpolate too.
      _env_interpolate "$_env_value" "$file" "$_gev_line" "$key"
      ;;
  esac
}

# env_value_into resolves KEY as get_env_value does (same found/absent/error
# contract) but assigns the result directly into the variable named by $1, so
# no `$(...)` boundary at the call site strips a trailing decoded newline
# (`POSTGRES_DB="geo\n"`). Callers assigning via `_v="$(get_env_value KEY
# FILE)"` lose that byte even though get_env_value preserves it.
#
# `$1` is validated against `^[A-Za-z_][A-Za-z0-9_]*$` first and
# unconditionally. The indirect assignment uses `eval` (common.sh is sourced
# by both `#!/bin/sh` and `#!/usr/bin/env bash` scripts, so it must stay
# POSIX-sh compatible; bash's `printf -v` is not an option), and an
# unvalidated target name handed to `eval` is an injection primitive. Every
# call site passes a literal identifier written by the script's author, but
# the check costs nothing and turns misuse into a loud `fail`.
#
# On success (get_env_value found the key) the target is set and this returns
# 0. On "absent" (rc=1, as get_env_value) the target is left completely
# untouched, not even assigned empty, so a caller preserving an inherited
# value only has to guard the call (`if env_value_into VAR KEY FILE; then
# ...`) and does not have to avoid clobbering VAR on the failure path.
env_value_into() {
  _evi_var="$1"
  _evi_key="$2"
  _evi_file="$3"

  _env_assert_var_name "$_evi_var" env_value_into

  # Sentinel-protected for the same reason as every decode capture in this
  # file (see _env_dequote's callers): a bare `$(...)` would strip the
  # trailing newline this function exists to preserve before eval sees it.
  # `&&` (not `;`) between get_env_value and the marker means
  # get_env_value's failure is never masked as success with an empty value;
  # the `|| return 1` below fails closed on it.
  _evi_val="$(get_env_value "$_evi_key" "$_evi_file" && printf x)" || return 1
  _evi_val="${_evi_val%x}"
  eval "$_evi_var=\$_evi_val"
}

# Aborts unless $1 is a valid shell identifier; $2 names the caller for the
# message. Guards every `eval "$name=..."` in this file.
_env_assert_var_name() {
  case "$1" in
    [A-Za-z_]*) : ;;
    *) fail "$2: invalid target variable name: '$1'" ;;
  esac
  case "$1" in
    *[!A-Za-z0-9_]*) fail "$2: invalid target variable name: '$1'" ;;
  esac
}

# True when NAME was in the exported environment this file was sourced
# under, which is the environment Compose itself interpolates from.
env_is_exported() {
  _env_snapshot_has "$1"
}

# True when FILE's KEY= line is one Compose refuses to load: an unterminated
# quote, or a value whose interpolation fails (`${NAME:?msg}` on an unset
# NAME). A bare `KEY` line inherits from the environment and never counts.
env_file_refuses_key() {
  [ -f "$2" ] || return 1
  _efrk_records="$(_env_tokenize "$2")" || return 1
  _env_select_record "$_efrk_records" "$1" 0
  case "${_esr_found}${_esr_type}" in
    2*) return 0 ;;
    1A) ! get_env_value "$1" "$2" >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# Assigns into $1 what a plain ${KEY} interpolates to under
# Compose (the export when set, even to "", else FILE's last KEY= line);
# rc 1 when neither has KEY, rc 2 when FILE's line is one Compose refuses.
effective_env_value_into() {
  _eevi_var="$1"
  _eevi_key="$2"
  _eevi_file="$3"

  _env_assert_var_name "$_eevi_var" effective_env_value_into

  # Compose loads the whole file before any override applies, so a refused
  # line fails here exported or not; the target stays untouched on rc 2.
  _eevi_in_file=0
  if env_value_into "$_eevi_var" "$_eevi_key" "$_eevi_file"; then
    _eevi_in_file=1
  elif env_file_refuses_key "$_eevi_key" "$_eevi_file"; then
    return 2
  fi

  if env_is_exported "$_eevi_key"; then
    _eevi_val="$(_env_snapshot_value "$_eevi_key" && printf x)"
    _eevi_val="${_eevi_val%x}"
    eval "$_eevi_var=\$_eevi_val"
    return 0
  fi
  [ "$_eevi_in_file" -eq 1 ]
}

# Prints "LINE KEY REASON" for the first line of FILE that Compose
# refuses to load (whitespace-in-key, unexpected-character, unterminated-quote
# or unresolvable) with rc 0; rc 1 and no output when every line loads.
env_file_first_refused_line() {
  _efrl_file="$1"
  [ -f "$_efrl_file" ] || return 1

  # An empty key (`export` prefix or not) and a key holding a tab
  # load under Compose but fit no record, so the file is judged from a copy naming
  # each such key with `-` (no `${}` can reference it) and a hit is renamed from FILE.
  _efrl_copy="${_ENV_SNAPSHOT_DIR:?}/env-file-copy.$$"
  _efrl_renamed="$(LC_ALL=C awk -v copy="$_efrl_copy" '
    BEGIN { printf "" > copy }
    { line = $0; bom = "" }
    NR == 1 && substr(line, 1, 3) == "\357\273\277" { bom = substr(line, 1, 3); line = substr(line, 4) }
    match(line, /^[ \t]*(export[ \t]+)?[]A-Za-z0-9_.[\t-]*[ \t]*[=:]/) {
      key = substr(line, 1, RLENGTH - 1)
      rest = substr(line, RLENGTH)
      sub(/^[ \t]*(export[ \t]+)?/, "", key)
      pre = substr(line, 1, RLENGTH - 1 - length(key))
      trail = key
      sub(/[ \t]+$/, "", key)
      trail = substr(trail, length(key) + 1)
      if (key == "" || index(key, "\t") > 0) {
        name = key
        sub(/\t.*$/, "", name)
        print NR, (name == "" ? "?" : name)
        gsub(/\t/, "-", key)
        line = pre (key == "" ? "-" : key) trail rest
      }
    }
    { print bom line > copy }' "$_efrl_file")" || fail "env_file_first_refused_line: could not copy $_efrl_file"
  _efrl_hit=""
  _efrl_rc=0
  _env_file_first_refused_line "$_efrl_copy" "$_efrl_file" || _efrl_rc=$?
  rm -f "$_efrl_copy"
  [ "$_efrl_rc" -eq 0 ] || return "$_efrl_rc"
  _efrl_name="$(printf '%s\n' "$_efrl_renamed" | awk -v line="${_efrl_hit%% *}" '$1 == line { print $2; exit }')"
  [ -z "$_efrl_name" ] || _efrl_hit="${_efrl_hit%% *} $_efrl_name ${_efrl_hit##* }"
  printf '%s' "$_efrl_hit"
}

# Sets _efrl_hit to "LINE KEY REASON" for the first line of COPY that Compose
# refuses to load with rc 0; rc 1 when every line loads. Messages name FILE.
_env_file_first_refused_line() {
  _efrl_read="$1"
  _efrl_file="$2"
  _efrl_records="$(_env_tokenize "$_efrl_read")" || return 1

  # Compose's parse phase: a key ends at `=` or `:`, holds letters, digits,
  # `_.-[]` or a tab, never a space; a multiline value's continuation lines
  # are exempt; bytes above 0x7f pass. ENVIRON carries the records, -v cannot.
  _efrl_hit="$(_EFRL_RECORDS="$_efrl_records" LC_ALL=C awk '
    BEGIN {
      n = split(ENVIRON["_EFRL_RECORDS"], r, "\n")
      for (i = 1; i <= n; i++) {
        split(r[i], f, " ")
        if (f[1] != "" && f[1] != "B" && f[3] > f[2]) { m++; lo[m] = f[2] + 1; hi[m] = f[3] }
      }
    }
    {
      line = $0
      sub(/\r$/, "", line)
      if (NR == 1 && substr(line, 1, 3) == "\357\273\277") line = substr(line, 4)
      sub(/^[ \t]+/, "", line)
      if (line == "" || substr(line, 1, 1) == "#") next
      for (i = 1; i <= m; i++) if (NR >= lo[i] && NR <= hi[i]) next
      sub(/^export[ \t]+/, "", line)
      key = line
      if (match(key, /[=:]/)) key = substr(key, 1, RSTART - 1)
      sub(/[ \t]+$/, "", key)
      name = key
      sub("[ \t#\"$].*$", "", name)
      if (name == "") name = "?"
      if (index(key, " ") > 0) { print NR, name, "whitespace-in-key"; exit }
      bad = key
      gsub(/[]A-Za-z0-9_.[\t-]/, "", bad)
      for (j = 1; j <= length(bad); j++) {
        if (substr(bad, j, 1) < "\200") { print NR, name, "unexpected-character"; exit }
      }
    }' "$_efrl_read")" || fail "env_file_first_refused_line: could not scan $_efrl_file"
  [ -z "$_efrl_hit" ] || return 0

  _efrl_hit="$(printf '%s' "$_efrl_records" | awk '$1 == "U" { print $2, $4, "unterminated-quote"; exit }')" \
    || fail "env_file_first_refused_line: could not scan the records of $_efrl_file"
  [ -z "$_efrl_hit" ] || return 0

  # Compose's interpolation phase. Only a value holding `$` can fail it, so
  # only those records are resolved, each bounded by its own start line.
  _efrl_list="$(_EFRL_RECORDS="$_efrl_records" LC_ALL=C awk '
    BEGIN {
      n = split(ENVIRON["_EFRL_RECORDS"], r, "\n")
      for (i = 1; i <= n; i++) {
        split(r[i], f, " ")
        if (f[1] == "A") { m++; lo[m] = f[2]; hi[m] = f[3]; key[m] = f[4] }
      }
    }
    index($0, "$") > 0 { for (i = 1; i <= m; i++) if (NR >= lo[i] && NR <= hi[i]) seen[i] = 1 }
    END { for (i = 1; i <= m; i++) if (seen[i]) print lo[i], key[i] }' "$_efrl_read")" \
    || fail "env_file_first_refused_line: could not scan the values of $_efrl_file"
  _efrl_hit="$(printf '%s\n' "$_efrl_list" | while read -r _efrl_start _efrl_key; do
      [ -n "$_efrl_start" ] || continue
      get_env_value "$_efrl_key" "$_efrl_read" "$((_efrl_start + 1))" "$_efrl_records" >/dev/null 2>&1 \
        || { printf '%s %s unresolvable' "$_efrl_start" "$_efrl_key"; break; }
    done)"
  [ -z "$_efrl_hit" ] || return 0
  return 1
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
# Prints the tag (with leading v) or empty. Mirrors the install.sh copy.
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
# as converging only while they sit inside their own declared start_period
# (e.g. the backup service allows 10m for its first pg_dump of a large DB, far
# beyond this 90s budget); there Docker has not judged them yet, and neither
# should we. That is verified per service. The full tolerance Docker grants is
# start_period plus one in-flight probe's timeout (grace is judged by probe
# start time, so a probe launched just inside start_period may run `timeout`
# past the boundary) plus `retries` consecutive failing probes, each taking up
# to interval + timeout (a service stays `starting` through that streak). A
# service whose container age (now - .State.StartedAt, not the wait budget,
# which overstates the age of a restart-policy container that restarted
# mid-wait with a freshly reset health clock) exceeds that window has outlived
# every verdict Docker could still be working on and fails the wait. The
# tolerance math applies only while the live .State.Health.Status (read in the
# same inspect) still says `starting`; a container that flipped to (un)healthy
# between the compose ps snapshot and the inspect is judged by that verdict.
# Anything (unhealthy), restarting, or exited non-zero fails; an unreadable
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

  # Budget spent: classify what is left. `(health: starting)` means the
  # service is within its declared start_period and Docker has not ruled on
  # it; failing the upgrade would tell the operator to roll back a stack
  # that is converging (an install whose first backup pg_dump outlasts 90s
  # hits this). Warn and succeed when only such services remain; anything
  # (unhealthy)/restarting/exited-nonzero is a real failure.
  remaining=$(compose ps --format '{{.Service}}|{{.Status}}' 2>/dev/null | grep -v '|.*(healthy)' | grep -v '|Exited (0)' | grep -v '^$' || true)
  if [ -z "$remaining" ]; then
    printf '\n'
    return 0
  fi
  broken=$(printf '%s\n' "$remaining" | grep -v '(health: starting)' || true)
  if [ -z "$broken" ]; then
    budget=$((attempts * sleep_s))
    # Verify each straggler is inside its healthcheck's declared tolerance
    # before letting it pass. `(health: starting)` only means Docker has
    # not ruled yet; a service with a broken healthcheck can sit there
    # long after its grace ran out. start_period alone is not the
    # boundary: after it ends, Docker still tolerates `retries`
    # consecutive failing probes (each taking up to interval + timeout)
    # before flipping to (unhealthy), and the service reports `starting`
    # for that streak. Plus one in-flight probe's timeout: moby
    # grace-ignores a probe by its start time, so one launched just inside
    # start_period can run up to `timeout` beyond the grace boundary
    # before the counted retries begin. The full allowance is start_period
    # + timeout + retries x (interval + timeout); zero config values mean
    # the daemon defaults (interval/timeout 30s, retries 3).
    #
    # Compare that allowance against the container's actual age (now -
    # .State.StartedAt), not the spent budget. A restart-policy service
    # that crashed and restarted mid-wait is seconds old with a freshly
    # reset health clock, legitimately inside its start_period, and must
    # not be classified overdue by a wait that started before its life
    # did. An unparseable StartedAt fails open, as does unreadable
    # healthcheck config.
    #
    # The `remaining` table is a snapshot: a probe can complete between
    # that `compose ps` and this inspect and flip the container out of
    # `starting`. Read the live .State.Health.Status in the same inspect
    # and apply the tolerance math only while it still says `starting`: a
    # flip to `unhealthy` fails the service outright (Docker has ruled;
    # age math must not overrule it), a flip to `healthy` counts as
    # converged, and an unreadable status fails open.
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
        # its START time and may run `timeout` past the boundary
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

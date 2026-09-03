#!/bin/sh
# fix(#1778 round 21, extended round 22): permanent lint gate against
# reintroducing a GNU-only flag on a tool whose BSD-shipped build (macOS,
# and other non-Linux operator hosts) diverges. Round 21 found ONE live
# instance: `env -0` in scripts/lib/common.sh's environment-snapshot
# capture, which some `/usr/bin/env` builds do not accept, combined with
# a `2>/dev/null ... || true` that swallowed the failure and left an
# apparently-valid but EMPTY snapshot -- every inherited environment
# variable then read as absent (see that file's own comment for the full
# mechanism and the fix: bash builtins / a POSIX `export -p` name scan,
# no external tool for the snapshot at all).
#
# Round 21's sweep also checked scripts/ for the rest of the class below
# and found nothing live at the time; round 22 turns that sweep into a
# permanent, per-pattern gate (each with its own self-proving positive
# control) so none of them can silently come back either:
#   - `sed -i` with no backup-suffix argument (BSD sed requires one; GNU
#     sed's bare `-i` needs none)
#   - `date -d` (GNU-only). This repo's OWN `iso_to_epoch` in
#     scripts/lib/common.sh already calls it, deliberately, as the first
#     half of a working GNU-try-then-BSD-fallback (`date -u -d ...`,
#     falling back to `date -u -j -f ...` on failure) -- that ONE call is
#     allowlisted by exact line content below; removing the GNU attempt
#     there would regress the Linux fast path, so the gate is scoped to
#     catch any OTHER `date -d`, not that one.
#   - `readlink -f`, `stat -c`, `grep -P`, `xargs -d`, `sort -z`,
#     `find -printf` -- all GNU-only extensions with no BSD equivalent
#     flag of the same name.
#
# Self-proving (matching test-backup-s3-signature.sh's own discipline):
# each pattern below must both catch a known-bad fixture and NOT
# false-positive on a comment merely mentioning the banned form (as this
# very file, and scripts/lib/common.sh's own explanatory comments,
# legitimately do for several of these).
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

pass=0
fail=0
check() {
    label="$1"; result="$2"
    if [ "$result" = "ok" ]; then
        printf "PASS: %s\n" "$label"
        pass=$((pass + 1))
    else
        printf "FAIL: %s\n" "$label"
        fail=$((fail + 1))
    fi
}

FIXTURE="$(mktemp)"
trap 'rm -f "$FIXTURE"' EXIT

# Each pattern excludes a `#`-prefixed comment the same way: `^[^#]*` before
# the match means any `#` earlier on the line (a comment, indented or not)
# blocks the rest of the pattern from ever matching, since there is no
# other position `^` can anchor to try again.
ENV_RE='^[^#]*\benv[[:space:]]+(-0|--null)\b'
SED_I_RE='^[^#]*\bsed\b[^#]*[[:space:]]-i([[:space:]]|$)'
DATE_D_RE='^[^#]*\bdate\b[^#]*[[:space:]]-d([[:space:]]|$)'
READLINK_F_RE='^[^#]*\breadlink\b[^#]*[[:space:]]-f([[:space:]]|$)'
STAT_C_RE='^[^#]*\bstat\b[^#]*[[:space:]]-c([[:space:]]|$)'
GREP_P_RE='^[^#]*\bgrep\b[^#]*[[:space:]]-P([[:space:]]|$)'
XARGS_D_RE='^[^#]*\bxargs\b[^#]*[[:space:]]-d([[:space:]]|$)'
SORT_Z_RE='^[^#]*\bsort\b[^#]*[[:space:]]-z([[:space:]]|$)'
FIND_PRINTF_RE='^[^#]*\bfind\b[^#]*-printf\b'

# --- Self-proof: each pattern catches a real, known-bad invocation ---

printf '    env -0 | xargs -0 sh -c '"'"'stuff'"'"'\n' > "$FIXTURE"
grep -qE "$ENV_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'env -0' invocation" "ok" \
    || check "self-proof: catches a real 'env -0' invocation" "fail"

printf '    env --null | xargs -0 sh -c '"'"'stuff'"'"'\n' > "$FIXTURE"
grep -qE "$ENV_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'env --null' invocation" "ok" \
    || check "self-proof: catches a real 'env --null' invocation" "fail"

printf "    sed -i 's/foo/bar/' file.txt\n" > "$FIXTURE"
grep -qE "$SED_I_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'sed -i' (no suffix) invocation" "ok" \
    || check "self-proof: catches a real 'sed -i' (no suffix) invocation" "fail"

printf "    sed -i.bak 's/foo/bar/' file.txt\n" > "$FIXTURE"
if grep -qE "$SED_I_RE" "$FIXTURE"; then
    check "self-proof: does NOT flag the portable 'sed -i.bak' (suffix attached) form" "fail"
else
    check "self-proof: does NOT flag the portable 'sed -i.bak' (suffix attached) form" "ok"
fi

printf '    ts=$(date -d "$foo" +%%s)\n' > "$FIXTURE"
grep -qE "$DATE_D_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'date -d' invocation" "ok" \
    || check "self-proof: catches a real 'date -d' invocation" "fail"

printf '    real=$(readlink -f "$path")\n' > "$FIXTURE"
grep -qE "$READLINK_F_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'readlink -f' invocation" "ok" \
    || check "self-proof: catches a real 'readlink -f' invocation" "fail"

printf '    size=$(stat -c %%s "$file")\n' > "$FIXTURE"
grep -qE "$STAT_C_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'stat -c' invocation" "ok" \
    || check "self-proof: catches a real 'stat -c' invocation" "fail"

printf "    grep -P '\\\\d+' file\n" > "$FIXTURE"
grep -qE "$GREP_P_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'grep -P' invocation" "ok" \
    || check "self-proof: catches a real 'grep -P' invocation" "fail"

printf "    xargs -d '\\\\n' -n1 cmd\n" > "$FIXTURE"
grep -qE "$XARGS_D_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'xargs -d' invocation" "ok" \
    || check "self-proof: catches a real 'xargs -d' invocation" "fail"

printf '    sort -z file\n' > "$FIXTURE"
grep -qE "$SORT_Z_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'sort -z' invocation" "ok" \
    || check "self-proof: catches a real 'sort -z' invocation" "fail"

printf "    find . -printf '%%p\\\\n'\n" > "$FIXTURE"
grep -qE "$FIND_PRINTF_RE" "$FIXTURE" \
    && check "self-proof: catches a real 'find -printf' invocation" "ok" \
    || check "self-proof: catches a real 'find -printf' invocation" "fail"

# --- Self-proof: none of the 9 patterns false-positive on a comment that
#     merely mentions the banned form, exactly as this file's own header
#     (and scripts/lib/common.sh's) legitimately does ---
cat > "$FIXTURE" <<'EOF'
# This comment mentions env -0, env --null, sed -i, date -d, readlink -f,
# stat -c, grep -P, xargs -d, sort -z, and find -printf without invoking
# any of them.
EOF
_comment_false_positive=0
for _re in "$ENV_RE" "$SED_I_RE" "$DATE_D_RE" "$READLINK_F_RE" "$STAT_C_RE" \
    "$GREP_P_RE" "$XARGS_D_RE" "$SORT_Z_RE" "$FIND_PRINTF_RE"; do
    if grep -qE "$_re" "$FIXTURE"; then
        _comment_false_positive=1
    fi
done
if [ "$_comment_false_positive" -eq 0 ]; then
    check "self-proof: no pattern false-positives on a comment merely mentioning the banned forms" "ok"
else
    check "self-proof: no pattern false-positives on a comment merely mentioning the banned forms" "fail"
fi

# --- Real gate: no shell script under scripts/ actually invokes any of
#     these, except the one allowlisted `date -d` inside iso_to_epoch's
#     own guarded GNU-then-BSD fallback. ---
#
# The loop below pipes into a subshell (POSIX `while read` has no
# NUL-safe form without bash's `-d`, and every filename here is a
# repo-controlled *.sh path, never adversarial/environment-derived data
# -- unlike the .env-value classes this whole PR otherwise guards
# against -- so plain newline-delimited `find` output is proportionate
# here), so hits are collected through a FILE rather than a variable,
# which a subshell's own assignments would not propagate back out of.
# Two lines are known-good, deliberate GNU-then-BSD fallbacks, not a
# reintroduction of the bug this gate exists for: common.sh's own
# iso_to_epoch, and test-upgrade-order.sh's iso_ago test helper (its own
# comment already says it mirrors iso_to_epoch's dual-branch strategy).
# Both are excluded by exact line content, not by file, so a genuinely
# NEW `date -d` added anywhere else -- including elsewhere in either of
# these same two files -- still trips the gate.
DATE_D_ALLOWLIST_1='_e=$(date -u -d "$_ts" +%s 2>/dev/null)'
DATE_D_ALLOWLIST_2='date -u -d "@${_e}" '"'"'+%Y-%m-%dT%H:%M:%SZ'"'"' 2>/dev/null \'

HITS_FILE="$(mktemp)"
: > "$HITS_FILE"
find "$REPO_ROOT" -name '*.sh' -type f | while IFS= read -r f; do
    case "$f" in
        */scripts/tests/test-no-gnu-only-flags.sh) continue ;;
    esac
    for _re in "$ENV_RE" "$SED_I_RE" "$READLINK_F_RE" "$STAT_C_RE" \
        "$GREP_P_RE" "$XARGS_D_RE" "$SORT_Z_RE" "$FIND_PRINTF_RE"; do
        hit="$(grep -nE "$_re" "$f" 2>/dev/null || true)"
        if [ -n "$hit" ]; then
            printf '%s\n%s\n' "$f" "$hit" >> "$HITS_FILE"
        fi
    done
    # date -d gets its own pass so the allowlisted lines can be excluded
    # by exact content rather than by file, which would also hide a
    # genuinely NEW `date -d` added anywhere else in the same file.
    date_hit="$(grep -nE "$DATE_D_RE" "$f" 2>/dev/null \
        | grep -vF "$DATE_D_ALLOWLIST_1" \
        | grep -vF "$DATE_D_ALLOWLIST_2" || true)"
    if [ -n "$date_hit" ]; then
        printf '%s\n%s\n' "$f" "$date_hit" >> "$HITS_FILE"
    fi
done

if [ ! -s "$HITS_FILE" ]; then
    check "no scripts/*.sh file invokes a banned GNU-only flag form" "ok"
else
    printf 'FAIL: a banned GNU-only flag form was found:\n' >&2
    cat "$HITS_FILE" >&2
    check "no scripts/*.sh file invokes a banned GNU-only flag form" "fail"
fi
rm -f "$HITS_FILE"

printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1

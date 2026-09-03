#!/bin/sh
# fix(#1778 round 21): permanent lint gate against reintroducing a
# GNU-only flag on a tool whose BSD-shipped build (macOS, and other
# non-Linux operator hosts) diverges. Round 21 found ONE live instance:
# `env -0` in scripts/lib/common.sh's environment-snapshot capture,
# which some `/usr/bin/env` builds do not accept, combined with a
# `2>/dev/null ... || true` that swallowed the failure and left an
# apparently-valid but EMPTY snapshot — every inherited environment
# variable then read as absent (see that file's own comment for the
# full mechanism and the fix: bash builtins / a POSIX `export -p` name
# scan, no external tool for the snapshot at all).
#
# The sweep also checked scripts/ for: `sed -i` with no backup-suffix
# argument (BSD sed requires one), `date -d` (GNU-only; this repo's own
# iso_to_epoch in scripts/lib/common.sh already tries it and falls back
# to BSD `date -j -f` on failure — a working fallback, not a bug, and
# deliberately NOT gated by this test since removing the GNU attempt
# would regress the Linux fast path), `readlink -f`, `stat -c`,
# `grep -P`, `xargs -d`, `sort -z`, `cp --`, and `awk`'s `RS='\0'` used
# anywhere other than the comment documenting why round 21 rejected it.
# All came back clean except the `env -0` site this test guards.
#
# Self-proving (matching test-backup-s3-signature.sh's own discipline):
# the pattern below must both catch a known-bad fixture and NOT
# false-positive on the kind of comment-only mention this very file (and
# scripts/lib/common.sh's own explanatory comment) legitimately contains.
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

# An actual invocation is `env -0` or `env --null` with no `#` anywhere
# earlier on the line (a `#`-prefixed comment, indented or not, always has
# a `#` before any text that follows it, so this correctly excludes a
# comment MENTIONING the banned flag while still catching real code).
BAD_RE='^[^#]*\benv[[:space:]]+(-0|--null)\b'

FIXTURE="$(mktemp)"
trap 'rm -f "$FIXTURE"' EXIT

# --- Self-proof: catches a real invocation ---
cat > "$FIXTURE" <<'EOF'
    env -0 | xargs -0 sh -c 'stuff'
EOF
if grep -qE "$BAD_RE" "$FIXTURE"; then
    check "self-proof: catches a real 'env -0' invocation" "ok"
else
    check "self-proof: catches a real 'env -0' invocation" "fail"
fi

cat > "$FIXTURE" <<'EOF'
    env --null | xargs -0 sh -c 'stuff'
EOF
if grep -qE "$BAD_RE" "$FIXTURE"; then
    check "self-proof: catches a real 'env --null' invocation" "ok"
else
    check "self-proof: catches a real 'env --null' invocation" "fail"
fi

# --- Self-proof: does NOT false-positive on a comment mentioning it ---
cat > "$FIXTURE" <<'EOF'
# fix(#1778 round 21): this file no longer calls `env -0` -- see the
# comment above for why (some /usr/bin/env builds reject it).
EOF
if grep -qE "$BAD_RE" "$FIXTURE"; then
    check "self-proof: does not flag a comment merely mentioning 'env -0'" "fail"
else
    check "self-proof: does not flag a comment merely mentioning 'env -0'" "ok"
fi

# --- Real gate: no shell script under scripts/ actually invokes it ---
# The loop below pipes into a subshell (POSIX `while read` has no NUL-safe
# form without bash's `-d`, and every filename here is a repo-controlled
# *.sh path, never adversarial/environment-derived data -- unlike the
# .env-value classes this whole PR otherwise guards against -- so plain
# newline-delimited `find` output is proportionate here), so hits are
# collected through a FILE rather than a variable, which a subshell's own
# assignments would not propagate back out of.
HITS_FILE="$(mktemp)"
: > "$HITS_FILE"
find "$REPO_ROOT" -name '*.sh' -type f | while IFS= read -r f; do
    case "$f" in
        */scripts/tests/test-no-gnu-only-flags.sh) continue ;;
    esac
    hit="$(grep -nE "$BAD_RE" "$f" 2>/dev/null || true)"
    if [ -n "$hit" ]; then
        printf '%s\n%s\n' "$f" "$hit" >> "$HITS_FILE"
    fi
done

if [ ! -s "$HITS_FILE" ]; then
    check "no scripts/*.sh file invokes 'env -0' / 'env --null'" "ok"
else
    printf 'FAIL: env -0/--null reintroduced:\n' >&2
    cat "$HITS_FILE" >&2
    check "no scripts/*.sh file invokes 'env -0' / 'env --null'" "fail"
fi
rm -f "$HITS_FILE"

printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1

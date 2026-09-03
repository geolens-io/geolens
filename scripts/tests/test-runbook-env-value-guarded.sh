#!/bin/sh
# fix(#1778 round 19, P2): every `scripts/env-value.sh KEY` invocation copy-
# pasted into RUNBOOK.md must assign through the guarded preserve-on-absence
# pattern restore.sh/check-env.sh/upgrade.sh already use internally via
# env_value_into (see the comment above env_value_into's definition in
# scripts/lib/common.sh):
#
#   if _v="$(scripts/env-value.sh KEY)"; then VAR="$_v"; fi
#
# scripts/env-value.sh exits 1 with no output when KEY has no line in .env at
# all — including the ordinary case of a value supplied purely through the
# process environment and deliberately left out of .env. An unconditional
#   VAR="$(scripts/env-value.sh KEY)"
# does not distinguish that from a real failure: it still runs, on exit 1,
# and blanks whatever VAR already held in this shell (or, under `set -e`,
# aborts the snippet outright). This is a permanent lint gate, not a one-time
# fix — it fails on ANY future unguarded `$(scripts/env-value.sh` assignment
# reintroduced into RUNBOOK.md, by whoever adds the next recovery snippet.
#
# Self-proving discipline (matching test-backup-s3-signature.sh): this test
# first proves its own grep actually catches the bad pattern, against a
# throwaway fixture, before trusting a clean result on the real file.
#
# Run: sh scripts/tests/test-runbook-env-value-guarded.sh
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
RUNBOOK="${REPO_ROOT}/RUNBOOK.md"
[ -f "$RUNBOOK" ] || { echo "FAIL: cannot find RUNBOOK.md at $RUNBOOK"; exit 1; }

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

# An unguarded assignment is a bare "VAR=$(scripts/env-value.sh KEY)" at the
# start of a line — no "if " before it. The guarded pattern always starts the
# line with "if _v=", so it can never match this.
UNGUARDED_RE='^[A-Za-z_][A-Za-z0-9_]*="\$\(scripts/env-value\.sh'

# --- 0. Self-proving: the grep must actually catch the bad pattern ---
FIXTURE="$(mktemp)"
trap 'rm -f "$FIXTURE"' EXIT
cat > "$FIXTURE" <<'EOF'
```bash
POSTGRES_DB="$(scripts/env-value.sh POSTGRES_DB)"
```
EOF
if grep -qE "$UNGUARDED_RE" "$FIXTURE"; then
    check "self-proof: the unguarded-assignment grep catches a known-bad fixture" "ok"
else
    check "self-proof: the unguarded-assignment grep does NOT catch a known-bad fixture — the gate below proves nothing" "fail"
fi

# The guarded pattern itself must NOT trip the same grep (else every legitimate
# use would also fail, and this test would be un-passable).
cat > "$FIXTURE" <<'EOF'
```bash
if _v="$(scripts/env-value.sh POSTGRES_DB)"; then POSTGRES_DB="$_v"; fi
```
EOF
if grep -qE "$UNGUARDED_RE" "$FIXTURE"; then
    check "self-proof: the guarded pattern itself does not false-positive" "fail"
else
    check "self-proof: the guarded pattern itself does not false-positive" "ok"
fi

# --- 1. RUNBOOK.md itself carries no unguarded assignment ---
BAD_LINES="$(grep -nE "$UNGUARDED_RE" "$RUNBOOK" || true)"
if [ -z "$BAD_LINES" ]; then
    check "RUNBOOK.md has no unguarded \"VAR=\$(scripts/env-value.sh ...)\" assignment" "ok"
else
    printf 'FAIL: unguarded scripts/env-value.sh assignment(s) in RUNBOOK.md:\n%s\n' "$BAD_LINES" >&2
    check "RUNBOOK.md has no unguarded \"VAR=\$(scripts/env-value.sh ...)\" assignment" "fail"
fi

# --- 2. Every env-value.sh invocation that DOES appear is inside the guarded
#        "if _v=...; then VAR=\"\$_v\"; fi" shape, one-per-line ---
INVOCATIONS="$(grep -cE 'scripts/env-value\.sh [A-Za-z_]' "$RUNBOOK" || true)"
GUARDED="$(grep -cE '^if _v="\$\(scripts/env-value\.sh [A-Za-z_][A-Za-z0-9_]*\)"; then [A-Za-z_][A-Za-z0-9_]*="\$_v"; fi$' "$RUNBOOK" || true)"
PROSE_MENTIONS=3  # the explanatory-prose backtick mentions above the fixed snippets
if [ "$((GUARDED + PROSE_MENTIONS))" -ge "$INVOCATIONS" ] && [ "$GUARDED" -ge 5 ]; then
    check "every code-block scripts/env-value.sh call uses the guarded if/then/fi shape (found ${GUARDED})" "ok"
else
    check "expected >=5 guarded scripts/env-value.sh calls accounting for ${PROSE_MENTIONS} prose mentions out of ${INVOCATIONS} total occurrences, found ${GUARDED} guarded" "fail"
fi

printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1

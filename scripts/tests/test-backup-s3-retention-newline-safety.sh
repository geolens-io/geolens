#!/usr/bin/env bash
# fix(#1778 round 19, P2): scripts/backup-entrypoint.sh's S3 retention pruning
# (prune_s3_prefix, s3_newest_complete_ts) extracted a dump/companion's
# embedded timestamp by piping the S3 object key through `sed -nE '...p'`.
# The key for a dump is `${POSTGRES_DB}_<timestamp>.dump`, and a POSTGRES_DB
# containing an embedded newline puts one inside the key. sed reads that key
# as TWO lines and, with `-n '...p'`, can print BOTH matches — so `ts`
# becomes a two-line string instead of a single timestamp. That value then
# never string-equals the single-line `protect` timestamp even when the real
# (second-line) part of it IS the protected one: the protected complete dump
# falls into the ordinary count-based candidate pool instead of being held
# back, and at BACKUP_RETENTION_DAILY=1 a newer partial-upload cycle (a dump
# with no paired globals) can evict it — the orphan pass right behind then
# deletes its now-unpaired globals file too.
#
# This test extracts the real log/s3_list_prefix/s3_newest_complete_ts/
# prune_s3_prefix function bodies out of the shipped script (the same
# function-range awk-extraction technique
# scripts/tests/test-install-secret-generation.sh already uses), sources
# them into an isolated harness, and drives prune_s3_prefix against a stub
# `aws` binary — no live S3/MinIO endpoint needed, no live Postgres either
# (this is pure retention-logic, no dump content involved).
#
# Fixture: an S3 listing with
#   - one dump key with an embedded newline, shaped exactly like what
#     `${POSTGRES_DB}_<timestamp>.dump` becomes when POSTGRES_DB itself
#     carries one: "evil_20240601_000000.dump\nreal_20260101_000000.dump" —
#     the REAL, protected timestamp (20260101_000000) is on the second line;
#   - its paired globals-20260101_000000.sql (the "complete set" marker);
#   - an older, unpaired dump (veryold, 20240101_000000);
#   - a newer, unpaired "partial upload" dump with no globals
#     (newpartial, 20260201_000000) — retention pressure.
#
# With BACKUP_RETENTION_DAILY=1, the correct outcome is: veryold is pruned
# (the genuine oldest unprotected dump), and the protected dump, its
# globals, and newpartial all survive. Run:
#   bash scripts/tests/test-backup-s3-retention-newline-safety.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/backup-entrypoint.sh"
[ -f "$SCRIPT" ] || { echo "FAIL: cannot find backup-entrypoint.sh at $SCRIPT"; exit 1; }

WORKDIR="$(mktemp -d)"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

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
die() {
    echo "FAIL: $1" >&2
    exit 1
}

# --- Extract the four functions under test, isolated from everything else
#     backup-entrypoint.sh does at parse-time (its own top-level statements
#     run unconditionally when sourced whole; see the file's own "Entry
#     point" comment) ---
HARNESS="${WORKDIR}/harness.sh"
{
    echo 'set -euo pipefail'
    awk '/^log\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^s3_list_prefix\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^s3_newest_complete_ts\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^prune_s3_prefix\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
} > "$HARNESS"

# Sanity: the extraction actually pulled non-trivial bodies (a silent empty
# extraction would make every assertion below vacuous).
for fn in log s3_list_prefix s3_newest_complete_ts prune_s3_prefix; do
    grep -q "^${fn}() {" "$HARNESS" \
        && check "extracted ${fn}() from the shipped script" "ok" \
        || check "extracted ${fn}() from the shipped script — not found in harness" "fail"
done
LINES="$(wc -l < "$HARNESS" | tr -d ' ')"
[ "$LINES" -gt 100 ] \
    && check "extracted harness is non-trivial (${LINES} lines)" "ok" \
    || check "extracted harness looks too small (${LINES} lines) — extraction likely broken" "fail"

# --- Fixture: the crafted S3 listing, JSON-escaped (a JSON \n decodes to a
#     real embedded newline byte in the Key string, exactly matching what
#     s3_list_prefix's own python3 parser hands back to bash) ---
LISTING_JSON="${WORKDIR}/listing.json"
cat > "$LISTING_JSON" <<'EOF'
{"Contents": [
  {"Key": "backups/daily/evil_20240601_000000.dump\nreal_20260101_000000.dump"},
  {"Key": "backups/daily/globals-20260101_000000.sql"},
  {"Key": "backups/daily/veryold_20240101_000000.dump"},
  {"Key": "backups/daily/newpartial_20260201_000000.dump"}
]}
EOF

# --- Stub aws: serves the crafted listing for list-objects-v2, records every
#     `aws s3 rm` target NUL-delimited (a target key may itself carry the
#     same embedded newline the fixture does), no-ops `aws configure set` ---
STUB_BIN="${WORKDIR}/stub-bin"
mkdir -p "$STUB_BIN"
RM_LOG="${WORKDIR}/rm.log"
: > "$RM_LOG"
cat > "${STUB_BIN}/aws" <<STUBEOF
#!/bin/sh
case "\$1" in
    configure)
        exit 0
        ;;
    s3api)
        cat "${LISTING_JSON}"
        exit 0
        ;;
    s3)
        if [ "\$2" = "rm" ]; then
            printf '%s\\0' "\$3" >> "${RM_LOG}"
            exit 0
        fi
        exit 1
        ;;
    *)
        exit 1
        ;;
esac
STUBEOF
chmod +x "${STUB_BIN}/aws"

run_prune() {
    local keep="$1"
    # shellcheck source=/dev/null
    PATH="${STUB_BIN}:${PATH}" \
        S3_BUCKET="test-bucket" S3_ACCESS_KEY_ID="test-key" S3_SECRET_ACCESS_KEY="test-secret" \
        S3_REGION="us-east-1" S3_ADDRESSING_STYLE="auto" \
        bash -c 'set -euo pipefail; . "$1"; prune_s3_prefix "daily" "$2"' _ "$HARNESS" "$keep"
}

# --- Run: BACKUP_RETENTION_DAILY=1 ---
: > "$RM_LOG"
if ! run_prune 1 2>"${WORKDIR}/prune.log"; then
    cat "${WORKDIR}/prune.log" >&2
    die "prune_s3_prefix exited non-zero against the fixture"
fi

# Read the NUL-delimited rm log into an array without a line-oriented tool.
RM_TARGETS=()
while IFS= read -r -d '' target; do
    RM_TARGETS+=("$target")
done < "$RM_LOG"

was_deleted() {
    local needle="$1" t
    for t in "${RM_TARGETS[@]:-}"; do
        [ "$t" = "$needle" ] && return 0
    done
    return 1
}

if was_deleted "s3://test-bucket/backups/daily/veryold_20240101_000000.dump"; then
    check "the genuine oldest unprotected dump (veryold) was pruned" "ok"
else
    check "the genuine oldest unprotected dump (veryold) was pruned — not found in: ${RM_TARGETS[*]:-<empty>}" "fail"
fi

if was_deleted $'s3://test-bucket/backups/daily/evil_20240601_000000.dump\nreal_20260101_000000.dump'; then
    check "the protected complete dump (embedded-newline key) survived retention-1 pruning" "fail"
else
    check "the protected complete dump (embedded-newline key) survived retention-1 pruning" "ok"
fi

if was_deleted "s3://test-bucket/backups/daily/globals-20260101_000000.sql"; then
    check "the protected dump's paired globals file survived the orphan pass" "fail"
else
    check "the protected dump's paired globals file survived the orphan pass" "ok"
fi

if was_deleted "s3://test-bucket/backups/daily/newpartial_20260201_000000.dump"; then
    check "the newer partial-upload dump (retention pressure) survived" "fail"
else
    check "the newer partial-upload dump (retention pressure) survived" "ok"
fi

[ "${#RM_TARGETS[@]}" -eq 1 ] \
    && check "exactly one object was pruned this cycle (veryold only)" "ok" \
    || check "exactly one object was pruned this cycle — got ${#RM_TARGETS[@]}: ${RM_TARGETS[*]:-<empty>}" "fail"

printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1

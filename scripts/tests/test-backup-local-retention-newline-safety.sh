#!/usr/bin/env bash
# fix(#1778 round 19, P2 class): the LOCAL half of retention pruning had the
# same "env-derived value fed through a line-oriented tool" shape as the S3
# half (see test-backup-s3-retention-newline-safety.sh), reached a different
# way: dump_listing (renamed dump_listing_arrays) used to build its listing
# via `find "$dir" -maxdepth 1 -name "*.dump" -type f | while IFS= read -r
# dump; do ...`. find's own output is one pathname per line, so a single
# on-disk dump file whose NAME contains a literal embedded newline byte —
# exactly what `${POSTGRES_DB}_<timestamp>.dump` becomes when POSTGRES_DB
# itself carries one — already reads back as TWO separate `dump` values from
# that while-read loop, before the (also-vulnerable) sed timestamp
# extraction downstream ever got a chance to make it worse. The resulting
# "<ts>\t<path>" text blob was then filtered with grep, counted with wc,
# and sliced with head/cut/while-read — every one of those tools able to
# re-split a record on a newline that was never meant to be a record
# boundary.
#
# Measured against the actual pre-round-19 `dump_listing`/`prune_old_backups`
# on this exact fixture (not assumed): find's line-splitting happens to break
# the compound name into a real leading fragment (with the true directory
# prefix) and a bogus TRAILING fragment with no directory prefix at all, so
# the phantom record's `rm -f` targets a path that does not exist and silently
# no-ops — the real file survives THIS particular fixture by that accident,
# not by correctness. What the old code demonstrably gets wrong regardless:
# it logs "Pruning 2 old backup(s)" while only removing 1 real file (the
# phantom fragment counts toward `to_remove` and toward the log message), a
# silently inaccurate audit trail, and `dump_listing`'s listing itself
# depends on find's per-line output for correctness at all — a differently
# shaped embedded newline (e.g. one whose bogus trailing fragment DOES
# resolve to another real file's name) is one text-processing accident away
# from acting on the wrong path. The class fix (NUL-safe array enumeration)
# closes that dependency entirely rather than leaving it correct by luck.
#
# This test extracts the real log/dump_listing_arrays/newest_complete_ts/
# prune_old_backups/prune_orphaned_companions function bodies out of the
# shipped script (same awk-extraction technique as the S3 sibling test and
# scripts/tests/test-install-secret-generation.sh) and drives them directly
# against a real directory of crafted files — no live Postgres needed, this
# is pure retention-logic over on-disk names.
#
# Fixture (mirrors the S3 test's, on a local filesystem instead of an S3
# listing):
#   - one dump FILE whose actual name contains an embedded newline:
#     "evil_20240601_000000.dump\nreal_20260101_000000.dump" — the real,
#     protected timestamp (20260101_000000) is on the second line;
#   - its paired globals-20260101_000000.sql;
#   - an older, unpaired dump (veryold, 20240101_000000);
#   - a newer, unpaired dump with no globals (newpartial, 20260201_000000).
#
# With keep=1, the correct outcome is: veryold is pruned, and the protected
# dump, its globals, and newpartial all survive. Run:
#   bash scripts/tests/test-backup-local-retention-newline-safety.sh
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

# --- Extract the five functions under test ---
HARNESS="${WORKDIR}/harness.sh"
{
    echo 'set -euo pipefail'
    awk '/^log\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^dump_listing_arrays\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^newest_complete_ts\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^prune_old_backups\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
    awk '/^prune_orphaned_companions\(\) \{/{f=1} f{print} f&&/^}/{exit}' "$SCRIPT"
} > "$HARNESS"

for fn in log dump_listing_arrays newest_complete_ts prune_old_backups prune_orphaned_companions; do
    grep -q "^${fn}() {" "$HARNESS" \
        && check "extracted ${fn}() from the shipped script" "ok" \
        || check "extracted ${fn}() from the shipped script — not found in harness" "fail"
done
LINES="$(wc -l < "$HARNESS" | tr -d ' ')"
[ "$LINES" -gt 60 ] \
    && check "extracted harness is non-trivial (${LINES} lines)" "ok" \
    || check "extracted harness looks too small (${LINES} lines) — extraction likely broken" "fail"

# --- Fixture: crafted on-disk filenames, one with a real embedded newline
#     byte (bash ANSI-C quoting: $'...\n...' is one string, one filename) ---
DIR="${WORKDIR}/daily"
mkdir -p "$DIR"
PROTECTED_NAME=$'evil_20240601_000000.dump\nreal_20260101_000000.dump'
touch -- "${DIR}/${PROTECTED_NAME}"
: > "${DIR}/globals-20260101_000000.sql"
touch -- "${DIR}/veryold_20240101_000000.dump"
touch -- "${DIR}/newpartial_20260201_000000.dump"

# Sanity: confirm the fixture itself really did land as ONE file with an
# embedded newline (not two files, which would prove nothing about the bug).
DUMP_COUNT="$(find "$DIR" -maxdepth 1 -name '*.dump' -type f -print0 | grep -zc . || true)"
[ "$DUMP_COUNT" = "3" ] \
    && check "fixture has exactly 3 *.dump dirents (1 crafted + veryold + newpartial)" "ok" \
    || check "fixture has exactly 3 *.dump dirents — found ${DUMP_COUNT}" "fail"
[ -e "${DIR}/${PROTECTED_NAME}" ] \
    && check "the crafted embedded-newline filename exists as a single dirent" "ok" \
    || check "the crafted embedded-newline filename exists as a single dirent" "fail"

# --- Run: dump_listing_arrays, then prune_old_backups(keep=1), then
#     prune_orphaned_companions, all via the real extracted functions ---
bash -c '
set -euo pipefail
. "$1"
dump_listing_arrays "$2"
printf "DL_COUNT=%s\n" "${#DL_TS[@]}"
prune_old_backups "$2" "$3"
prune_orphaned_companions "$2"
' _ "$HARNESS" "$DIR" 1 > "${WORKDIR}/run.log" 2>&1 \
    || { cat "${WORKDIR}/run.log" >&2; die "the extracted retention pipeline exited non-zero against the fixture"; }
cat "${WORKDIR}/run.log"

grep -q '^DL_COUNT=3$' "${WORKDIR}/run.log" \
    && check "dump_listing_arrays enumerated all 3 dumps as 3 array elements (the embedded-newline dump is ONE element, not two)" "ok" \
    || check "dump_listing_arrays enumerated all 3 dumps as 3 array elements — $(grep '^DL_COUNT=' "${WORKDIR}/run.log" || echo 'not found')" "fail"

[ ! -e "${DIR}/veryold_20240101_000000.dump" ] \
    && check "the genuine oldest unprotected dump (veryold) was pruned" "ok" \
    || check "the genuine oldest unprotected dump (veryold) was pruned" "fail"

[ -e "${DIR}/${PROTECTED_NAME}" ] \
    && check "the protected complete dump (embedded-newline filename) survived retention-1 pruning" "ok" \
    || check "the protected complete dump (embedded-newline filename) survived retention-1 pruning" "fail"

[ -e "${DIR}/globals-20260101_000000.sql" ] \
    && check "the protected dump's paired globals file survived the orphan pass" "ok" \
    || check "the protected dump's paired globals file survived the orphan pass" "fail"

[ -e "${DIR}/newpartial_20260201_000000.dump" ] \
    && check "the newer partial-upload dump (retention pressure) survived" "ok" \
    || check "the newer partial-upload dump (retention pressure) survived" "fail"

REMAINING="$(find "$DIR" -maxdepth 1 -type f -print0 | grep -zc . || true)"
[ "$REMAINING" = "3" ] \
    && check "exactly one file was pruned this cycle (veryold only; 3 of 4 remain)" "ok" \
    || check "exactly one file was pruned this cycle — ${REMAINING} of 4 remain" "fail"

printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1

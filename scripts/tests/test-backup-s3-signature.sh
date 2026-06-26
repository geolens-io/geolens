#!/bin/sh
# Regression guard for BKP-02: the backup S3 uploader must sign with AWS
# Signature V4 (awscli / s3v4) and surface upload failures as a visible
# non-zero error — not a swallowed "(non-fatal)" warning.
#
# All assertions run against the shipped scripts/backup-entrypoint.sh without
# a live S3 endpoint (pure structural / static analysis). The test runs in CI
# as the existing installer-test step: sh scripts/tests/test-backup-s3-signature.sh
#
# Self-proving discipline: each negative guard (no sha1, no Authorization: AWS)
# is written so it would FAIL on a script that (re)introduced SigV2 signing —
# i.e., any commit that puts back openssl dgst -sha1 or Authorization: AWS
# causes this test to exit 1.
set -eu

SCRIPT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/backup-entrypoint.sh"
[ -f "$SCRIPT" ] || { echo "FAIL: cannot find backup-entrypoint.sh at $SCRIPT"; exit 1; }

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

# --- 1. SigV4 signature version configured ---
grep -q 's3v4' "$SCRIPT" \
    && check "SigV4 signature_version (s3v4) present in uploader" "ok" \
    || check "SigV4 signature_version (s3v4) present in uploader — s3v4 not found" "fail"

# --- 2. awscli s3 cp used for upload ---
grep -q 'aws s3 cp' "$SCRIPT" \
    && check "awscli 'aws s3 cp' used for S3 upload" "ok" \
    || check "awscli 'aws s3 cp' not found — uploader must use awscli" "fail"

# --- 3. No SigV2 HMAC-SHA1 signing path (self-proving: these patterns would
#        trip if openssl dgst -sha1 / Authorization: AWS were reintroduced) ---
! grep -qiE 'openssl dgst -sha1|Authorization: AWS ' "$SCRIPT" \
    && check "No SigV2 HMAC-SHA1 or hand-built Authorization: AWS header" "ok" \
    || check "SigV2 path not removed — openssl dgst -sha1 or Authorization: AWS still present" "fail"

# Additional guard: the sigv2 label itself should not appear as a live code path.
# (Comments referencing it are OK only if they are in past-tense removal notes.)
! grep -qi 'sigv2' "$SCRIPT" \
    && check "No 'sigv2' identifier remaining in uploader" "ok" \
    || check "Stale 'sigv2' identifier found in uploader" "fail"

# --- 4. Upload failure is surfaced as ERROR (not swallowed) ---
grep -q 'ERROR.*S3 upload' "$SCRIPT" \
    && check "Failed upload logs ERROR-level message" "ok" \
    || check "Failed upload must log an ERROR — no ERROR.*S3 upload found" "fail"

! grep -qiE '\(non-fatal\).*[Uu]pload|[Uu]pload.*(non-fatal)' "$SCRIPT" \
    && check "No '(non-fatal)' suppression on S3 upload path" "ok" \
    || check "S3 upload path still marks failure as (non-fatal) — must surface error" "fail"

# --- 5. Credentials NOT passed on the aws s3 cp argv ---
! grep -qE 'aws s3 cp.*(S3_SECRET_ACCESS_KEY|S3_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID)' "$SCRIPT" \
    && check "S3 credentials passed via env, not on aws s3 cp argv" "ok" \
    || check "Secret key found on aws s3 cp argv — credential leakage risk" "fail"

# --- Summary ---
printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1

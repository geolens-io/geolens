#!/bin/sh
# Regression test for BUG-004: the backup S3 SigV2 signature must be computed
# over a string-to-sign containing REAL newlines, not the literal two-character
# sequence backslash-n.
#
# On main the string was built with bash double-quoted "PUT\n\n..." (which does
# NOT expand \n) and signed via `printf '%s'` (verbatim), so every PUT was
# rejected with SignatureDoesNotMatch — offsite backups silently never happened
# while a non-fatal log warning masked the failure.
set -eu

SCRIPT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/backup-entrypoint.sh"
[ -f "$SCRIPT" ] || { echo "FAIL: cannot find backup-entrypoint.sh at $SCRIPT"; exit 1; }

# The fixed construction uses bash ANSI-C quoting ($'\n'); evaluate it in bash.
command -v bash >/dev/null 2>&1 || { echo "SKIP: bash not available"; exit 0; }
command -v openssl >/dev/null 2>&1 || { echo "SKIP: openssl not available"; exit 0; }

content_type="application/octet-stream"
date_value="Thu, 01 Jan 1970 00:00:00 GMT"
resource="/test-bucket/backups/db.dump"
secret="test-secret-key"

# --- behavioral: extract the real string_to_sign + signature construction -----
# Pull the two assignment lines (string_to_sign=..., signature=...) straight
# from the shipped script, strip the function-local `local ` prefix, and run
# them so we exercise the ACTUAL signing code, not a copy.
snippet="$(mktemp)"
awk '
  /string_to_sign=/ { f = 1 }
  f && /=/ { line = $0; sub(/^[[:space:]]*local /, "", line); print line }
  /openssl dgst/ { f = 0 }
' "$SCRIPT" >"$snippet"
grep -q 'string_to_sign=' "$snippet" || { echo "FAIL: could not extract signing snippet"; rm -f "$snippet"; exit 1; }

result="$(bash -c '
  set -eu
  content_type="'"$content_type"'"
  date_value="'"$date_value"'"
  resource="'"$resource"'"
  S3_SECRET_ACCESS_KEY="'"$secret"'"
  . "'"$snippet"'"
  printf "%s\n" "$(printf "%s" "$string_to_sign" | wc -l | tr -d " ")"
  printf "%s\n" "$signature"
')"
rm -f "$snippet"

nl_count="$(printf '%s\n' "$result" | sed -n 1p)"
got_sig="$(printf '%s\n' "$result" | sed -n 2p)"

# The canonical AWS SigV2 string-to-sign (PUT\n\n<ct>\n<date>\n<resource>) has
# exactly 4 real newline separators. The buggy literal-\n form has 0.
[ "${nl_count:-0}" -ge 4 ] || {
  echo "FAIL: string_to_sign has ${nl_count:-0} real newlines (expected >=4) — signed over literal \\n (BUG-004)"
  exit 1
}

# Reference signature, computed independently with REAL newlines (printf format
# string interprets \n). The shipped code must produce exactly this.
expected="$(printf 'PUT\n\n%s\n%s\n%s' "$content_type" "$date_value" "$resource" \
  | openssl dgst -sha1 -hmac "$secret" -binary | base64)"
[ "$got_sig" = "$expected" ] || {
  echo "FAIL: signature mismatch — got '$got_sig', expected '$expected' (BUG-004)"
  exit 1
}

# Sanity: the broken literal-\n signature MUST differ, proving the test detects
# the regression rather than passing trivially.
broken="$(printf '%s' "PUT\\n\\n${content_type}\\n${date_value}\\n${resource}" \
  | openssl dgst -sha1 -hmac "$secret" -binary | base64)"
[ "$got_sig" != "$broken" ] || {
  echo "FAIL: signature equals the broken literal-\\n form (BUG-004 not fixed)"
  exit 1
}

# --- structural: the buggy literal-\n string_to_sign must be gone -------------
if grep -qE 'string_to_sign="PUT\\n' "$SCRIPT"; then
  echo "FAIL: backup-entrypoint.sh still builds string_to_sign with literal \\n (BUG-004)"
  exit 1
fi

echo "PASS: backup S3 SigV2 signature over real newlines (BUG-004)"

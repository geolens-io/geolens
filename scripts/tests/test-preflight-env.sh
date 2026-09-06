#!/bin/sh
# Regression test for scripts/preflight-env.sh (fix(#1882), fix(#1886)).
#
# `make dev` runs preflight before any Compose build, so a false failure here
# blocks the stack on a well-formed .env. The encryption-key shape check added
# in #1871 read .env with a local parser that returned a trailing `# comment`
# as part of the value, which rejected two forms Compose accepts:
#
#   SECRET_ENCRYPTION_KEY=<key> # rotation key
#   SECRET_ENCRYPTION_KEY="<key>" # rotation key
#
# Both are pinned against real `docker compose` by
# test-env-file-compose-oracle.sh and against get_env_value's own dequoting by
# test-restore-env-sourcing-safety.sh. preflight now reads through that same
# get_env_value, and these cases keep it there.
#
# Pure shell against a throwaway repo tree. No stack, no DB, no network.
set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"       # scripts/

PASS=0
FAIL=0
ok()  { PASS=$((PASS + 1)); printf 'ok %d - %s\n' "$((PASS + FAIL))" "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'not ok %d - %s\n' "$((PASS + FAIL))" "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

FAKE="$WORK/repo"
mkdir -p "$FAKE/scripts/lib"
cp "$REPO_ROOT/preflight-env.sh" "$FAKE/scripts/preflight-env.sh"
cp "$REPO_ROOT/lib/common.sh" "$FAKE/scripts/lib/common.sh"

# The key the docs tell an operator to generate. Falls back to a shape-only
# fixture (32 zero bytes) on a host without openssl; neither is a credential.
if command -v openssl >/dev/null 2>&1; then
    VALID_KEY="$(openssl rand -base64 32 | tr -d '\n' | tr '+/' '-_')"
else
    VALID_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
fi

# preflight only checks that the required trio is non-empty, so these carry no
# key or password shape. The hex value below is the mistake the check exists to
# catch, generated rather than written out so no high-entropy literal lands in
# the repo.
NONEMPTY="present-and-not-a-secret"
if command -v openssl >/dev/null 2>&1; then
    HEX_VALUE="$(openssl rand -hex 32)"
else
    HEX_VALUE="0000000000000000000000000000000000000000000000000000000000000000"
fi

REQUIRED_LINES="JWT_SECRET_KEY=$NONEMPTY
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=$NONEMPTY"

# Writes .env with the required trio plus any extra lines, runs preflight,
# and leaves the exit code in $STATUS and the combined output in $WORK/out.txt.
run_preflight() {
    printf '%s\n' "$REQUIRED_LINES" > "$FAKE/.env"
    if [ $# -gt 0 ]; then
        printf '%s\n' "$1" >> "$FAKE/.env"
    fi
    bash "$FAKE/scripts/preflight-env.sh" > "$WORK/out.txt" 2>&1
    STATUS=$?
}

# Same, with NAME=VALUE exported into preflight's environment, the way an
# operator's shell hands it to `make dev` and then to Compose.
run_preflight_env() {
    printf '%s\n' "$REQUIRED_LINES" > "$FAKE/.env"
    if [ $# -gt 2 ]; then
        printf '%s\n' "$3" >> "$FAKE/.env"
    fi
    env "$1=$2" bash "$FAKE/scripts/preflight-env.sh" > "$WORK/out.txt" 2>&1
    STATUS=$?
}

# ============================================================================
# CASE 1 — the two annotated forms the local parser rejected.
# ============================================================================
run_preflight "SECRET_ENCRYPTION_KEY=$VALID_KEY # rotation key"
if [ "$STATUS" -eq 0 ]; then
    ok "an unquoted key with a trailing comment passes"
else
    bad "an unquoted key with a trailing comment was rejected: $(cat "$WORK/out.txt")"
fi

run_preflight "SECRET_ENCRYPTION_KEY=\"$VALID_KEY\" # rotation key"
if [ "$STATUS" -eq 0 ]; then
    ok "a quoted key with a trailing comment passes"
else
    bad "a quoted key with a trailing comment was rejected: $(cat "$WORK/out.txt")"
fi

run_preflight "SECRET_ENCRYPTION_KEY_PREVIOUS=$VALID_KEY # retiring"
if [ "$STATUS" -eq 0 ]; then
    ok "the previous key accepts the same annotated form"
else
    bad "an annotated previous key was rejected: $(cat "$WORK/out.txt")"
fi

# ============================================================================
# CASE 2 — the plain forms, and no key at all.
# ============================================================================
run_preflight "SECRET_ENCRYPTION_KEY=$VALID_KEY"
if [ "$STATUS" -eq 0 ]; then
    ok "a bare key passes"
else
    bad "a bare key was rejected: $(cat "$WORK/out.txt")"
fi

run_preflight "SECRET_ENCRYPTION_KEY=\"$VALID_KEY\""
if [ "$STATUS" -eq 0 ]; then
    ok "a quoted key passes"
else
    bad "a quoted key was rejected: $(cat "$WORK/out.txt")"
fi

run_preflight
if [ "$STATUS" -eq 0 ]; then
    ok "no encryption key at all passes (the setting is optional)"
else
    bad "an .env without the key was rejected: $(cat "$WORK/out.txt")"
fi

run_preflight "SECRET_ENCRYPTION_KEY="
if [ "$STATUS" -eq 0 ]; then
    ok "an empty key passes (the app reads it as unset)"
else
    bad "an empty key was rejected: $(cat "$WORK/out.txt")"
fi

# ============================================================================
# CASE 3 — a malformed key still fails, naming the variable. Without this the
# whole check could be deleted and every case above would still pass.
# ============================================================================
run_preflight "SECRET_ENCRYPTION_KEY=$HEX_VALUE"
if [ "$STATUS" -ne 0 ] && grep -q "SECRET_ENCRYPTION_KEY" "$WORK/out.txt"; then
    ok "a hex value is refused and the message names the variable"
else
    bad "a hex value was accepted (exit $STATUS)"
fi

run_preflight "SECRET_ENCRYPTION_KEY_PREVIOUS=not-a-key"
if [ "$STATUS" -ne 0 ] && grep -q "SECRET_ENCRYPTION_KEY_PREVIOUS" "$WORK/out.txt"; then
    ok "a malformed previous key is refused"
else
    bad "a malformed previous key was accepted (exit $STATUS)"
fi

run_preflight "SECRET_ENCRYPTION_KEY=$VALID_KEY # rotation key # second hash"
if [ "$STATUS" -eq 0 ]; then
    ok "a comment containing a second hash is still a comment"
else
    bad "a two-hash comment was rejected: $(cat "$WORK/out.txt")"
fi

# ============================================================================
# CASE 4 — the pre-existing required-var check, through the shared parser.
# ============================================================================
REQUIRED_LINES="JWT_SECRET_KEY=$NONEMPTY # signing key
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=$NONEMPTY"
run_preflight
if [ "$STATUS" -eq 0 ]; then
    ok "an annotated required value counts as present"
else
    bad "an annotated required value read as missing: $(cat "$WORK/out.txt")"
fi

REQUIRED_LINES="JWT_SECRET_KEY=
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=$NONEMPTY"
run_preflight
if [ "$STATUS" -ne 0 ] && grep -q "JWT_SECRET_KEY" "$WORK/out.txt"; then
    ok "an empty required value still fails, naming the variable"
else
    bad "an empty required value was accepted (exit $STATUS)"
fi

REQUIRED_LINES="JWT_SECRET_KEY=$NONEMPTY
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=$NONEMPTY"

# ============================================================================
# CASE 5 — no .env at all.
# ============================================================================
rm -f "$FAKE/.env"
bash "$FAKE/scripts/preflight-env.sh" > "$WORK/out.txt" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ] && grep -q "not found" "$WORK/out.txt"; then
    ok "a missing .env fails with the bootstrap message"
else
    bad "a missing .env did not fail as expected (exit $STATUS)"
fi

# ============================================================================
# CASE 6 (fix(#1886)): an exported name overrides its .env line for Compose.
# ============================================================================
run_preflight_env SECRET_ENCRYPTION_KEY "$HEX_VALUE" "SECRET_ENCRYPTION_KEY=$VALID_KEY"
if [ "$STATUS" -ne 0 ] && grep -q "SECRET_ENCRYPTION_KEY" "$WORK/out.txt" && grep -q "environment" "$WORK/out.txt"; then
    ok "a malformed exported key is refused over a valid .env line, naming the environment as the source"
else
    bad "a malformed exported key was masked by a valid .env line (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight_env SECRET_ENCRYPTION_KEY "$VALID_KEY" "SECRET_ENCRYPTION_KEY=$HEX_VALUE"
if [ "$STATUS" -eq 0 ]; then
    ok "a valid exported key passes over a malformed .env line"
else
    bad "a valid exported key was rejected because of the .env line: $(cat "$WORK/out.txt")"
fi

run_preflight_env SECRET_ENCRYPTION_KEY_PREVIOUS not-a-key "SECRET_ENCRYPTION_KEY_PREVIOUS=$VALID_KEY"
if [ "$STATUS" -ne 0 ] && grep -q "SECRET_ENCRYPTION_KEY_PREVIOUS" "$WORK/out.txt"; then
    ok "the previous key is checked from the environment too"
else
    bad "a malformed exported previous key was accepted over a valid .env line (exit $STATUS)"
fi

run_preflight_env SECRET_ENCRYPTION_KEY "$HEX_VALUE"
if [ "$STATUS" -ne 0 ] && grep -q "SECRET_ENCRYPTION_KEY" "$WORK/out.txt"; then
    ok "a malformed exported key is refused when .env has no line for it"
else
    bad "a malformed exported key was accepted when .env had no line for it (exit $STATUS)"
fi

# Compose passes the key as "${SECRET_ENCRYPTION_KEY:-}", so an exported empty
# value reaches the app as unset even when .env holds a line.
run_preflight_env SECRET_ENCRYPTION_KEY "" "SECRET_ENCRYPTION_KEY=$HEX_VALUE"
if [ "$STATUS" -eq 0 ]; then
    ok "an exported empty key passes over a malformed .env line (Compose sends the empty value)"
else
    bad "an exported empty key did not mask the .env line: $(cat "$WORK/out.txt")"
fi

# The required trio reaches Compose as a plain ${VAR}, so an exported empty
# value is what the container gets.
run_preflight_env JWT_SECRET_KEY ""
if [ "$STATUS" -ne 0 ] && grep -q "JWT_SECRET_KEY" "$WORK/out.txt" && grep -q "environment" "$WORK/out.txt"; then
    ok "an exported empty JWT_SECRET_KEY is refused over a non-empty .env line, naming the environment"
else
    bad "an exported empty JWT_SECRET_KEY was masked by the .env line (exit $STATUS): $(cat "$WORK/out.txt")"
fi

REQUIRED_LINES="JWT_SECRET_KEY=
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=$NONEMPTY"
run_preflight_env JWT_SECRET_KEY "$NONEMPTY"
if [ "$STATUS" -eq 0 ]; then
    ok "an exported JWT_SECRET_KEY satisfies the check over an empty .env line"
else
    bad "an exported JWT_SECRET_KEY was ignored over an empty .env line: $(cat "$WORK/out.txt")"
fi
REQUIRED_LINES="JWT_SECRET_KEY=$NONEMPTY
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=$NONEMPTY"

# ============================================================================
# CASE 7 (fix(#1886)): a line Compose refuses to load is refused, exported or not.
# ============================================================================
run_preflight_env SECRET_ENCRYPTION_KEY "$VALID_KEY" 'SECRET_ENCRYPTION_KEY=${NO_SUCH_VAR:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (SECRET_ENCRYPTION_KEY)" "$WORK/out.txt"; then
    ok "a valid exported key over a line Compose refuses is refused, naming the .env line"
else
    bad "a valid exported key masked a line Compose refuses (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'SECRET_ENCRYPTION_KEY=${NO_SUCH_VAR:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (SECRET_ENCRYPTION_KEY)" "$WORK/out.txt"; then
    ok "the same line is refused with nothing exported"
else
    bad "a line Compose refuses passed with nothing exported (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight_env SECRET_ENCRYPTION_KEY "$VALID_KEY" 'SECRET_ENCRYPTION_KEY="unterminated'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (SECRET_ENCRYPTION_KEY)" "$WORK/out.txt"; then
    ok "an unterminated quote is refused under a valid exported key too"
else
    bad "a valid exported key masked an unterminated quote (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight_env SECRET_ENCRYPTION_KEY "$VALID_KEY" "SECRET_ENCRYPTION_KEY"
if [ "$STATUS" -eq 0 ]; then
    ok "a bare KEY line inherits the exported key and is not refused"
else
    bad "a bare KEY line was refused under an exported key: $(cat "$WORK/out.txt")"
fi

run_preflight "SECRET_ENCRYPTION_KEY"
if [ "$STATUS" -eq 0 ]; then
    ok "a bare KEY line with nothing exported reads as unset and passes"
else
    bad "a bare KEY line with nothing exported was refused: $(cat "$WORK/out.txt")"
fi

# ============================================================================
# CASE 8 (fix(#1899)): the whole file is checked as Compose loads it, by line.
# ============================================================================
run_preflight 'UNRELATED=${MISSING:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (UNRELATED)" "$WORK/out.txt"; then
    ok "an unrelated line Compose refuses is refused, naming line and key"
else
    bad "an unrelated line Compose refuses passed (exit $STATUS): $(cat "$WORK/out.txt")"
fi
if ! grep -q "boom" "$WORK/out.txt" && ! grep -q "MISSING" "$WORK/out.txt"; then
    ok "the refusal never prints the line's value"
else
    bad "the refusal printed the line's value: $(cat "$WORK/out.txt")"
fi

DUPLICATE="$(printf 'SECRET_ENCRYPTION_KEY=${MISSING:?boom}\nSECRET_ENCRYPTION_KEY=%s' "$VALID_KEY")"
run_preflight "$DUPLICATE"
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (SECRET_ENCRYPTION_KEY)" "$WORK/out.txt"; then
    ok "an earlier invalid duplicate of a checked key is refused although the last definition is valid"
else
    bad "an earlier invalid duplicate was masked by the last definition (exit $STATUS): $(cat "$WORK/out.txt")"
fi

MIXED_VALID="$(printf '# comment\n\nexport EXPORTED=1\nQUOTED="with # hash" # note\nSINGLE='"'"'lit $x'"'"'\nBARE\nSPACED = value\nREF=${JWT_SECRET_KEY}\nODD-KEY=x\n1ODD=x\nDOTTED.KEY=x\nCOLON:sep value\nTAB\t=x\nDOLLAR=$5\nJUNK="a"b\n=x\nA\tB="d\ne f\n"\nMULTI="a\nb c\n"')"
run_preflight "$MIXED_VALID"
if [ "$STATUS" -eq 0 ]; then
    ok "a file of lines Compose loads still passes (comments, export, quotes, bare, odd keys, an empty key, a tab in a key, refs, multiline)"
else
    bad "a valid file was refused by the whole-file check: $(cat "$WORK/out.txt")"
fi

run_preflight 'FOO # comment'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (FOO)" "$WORK/out.txt"; then
    ok "a bare key followed by a comment is refused like Compose does"
else
    bad "a bare key followed by a comment passed (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'garbage line'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (garbage)" "$WORK/out.txt"; then
    ok "a line with a space and no = is refused"
else
    bad "a line with a space and no = passed (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'FOO#BAR=x'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (FOO)" "$WORK/out.txt"; then
    ok "a key holding a character Compose rejects is refused"
else
    bad "a key holding # passed (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'FOO="unterminated'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (FOO)" "$WORK/out.txt"; then
    ok "an unterminated quote on an unrelated key is refused, naming its opening line"
else
    bad "an unterminated quote on an unrelated key passed (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'FOO=${X'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (FOO)" "$WORK/out.txt"; then
    ok "an unclosed \${ on an unrelated key is refused"
else
    bad "an unclosed \${ on an unrelated key passed (exit $STATUS): $(cat "$WORK/out.txt")"
fi

CONTINUATION="$(printf 'FOO="a\nb c\n"\nBAR # after')"
run_preflight "$CONTINUATION"
if [ "$STATUS" -ne 0 ] && grep -q "line 7 (BAR)" "$WORK/out.txt"; then
    ok "a spaced continuation line of a multiline value is exempt and the refusal names the real line after it"
else
    bad "a multiline value's continuation was misjudged (exit $STATUS): $(cat "$WORK/out.txt")"
fi

# fix(#1899 codex r1): a key outside the shell-identifier charset is a record
# too, so its value is interpolated where Compose interpolates it.
run_preflight 'ODD-KEY=${MISSING:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (ODD-KEY)" "$WORK/out.txt"; then
    ok "a hyphenated key with a value Compose refuses is refused"
else
    bad "a hyphenated key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'DOTTED.KEY=${X'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (DOTTED.KEY)" "$WORK/out.txt"; then
    ok "a dotted key with an unclosed \${ is refused"
else
    bad "a dotted key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight 'COLON: ${MISSING:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (COLON)" "$WORK/out.txt"; then
    ok "a colon-terminated key with a value Compose refuses is refused"
else
    bad "a colon-terminated key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight '1ODD=${MISSING:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (1ODD)" "$WORK/out.txt"; then
    ok "a digit-leading key with a value Compose refuses is refused"
else
    bad "a digit-leading key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

# fix(#1909): an empty key and a key holding a tab are records too.
run_preflight '=${MISSING:?boom}'
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (?)" "$WORK/out.txt"; then
    ok "an empty key with a value Compose refuses is refused"
else
    bad "an empty key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight "$(printf 'A\tB=${MISSING:?boom}')"
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (A)" "$WORK/out.txt"; then
    ok "a key holding a tab with a value Compose refuses is refused, named up to the tab"
else
    bad "a tab-holding key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight "$(printf 'A\tB =${MISSING:?boom}')"
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (A)" "$WORK/out.txt"; then
    ok "a separator space after a tab-holding key does not hide its value"
else
    bad "a tab-holding key with a separator space was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

run_preflight "$(printf 'export\t=${MISSING:?boom}')"
if [ "$STATUS" -ne 0 ] && grep -q "line 4 (?)" "$WORK/out.txt"; then
    ok "an export prefix before an empty key still leaves the key empty, as Compose reads it"
else
    bad "an export-prefixed empty key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

printf '\357\273\277=${MISSING:?boom}\n' > "$FAKE/.env"
printf '%s\n' "$REQUIRED_LINES" >> "$FAKE/.env"
bash "$FAKE/scripts/preflight-env.sh" > "$WORK/out.txt" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ] && grep -q "line 1 (?)" "$WORK/out.txt"; then
    ok "a BOM before an empty key on the first line does not hide it"
else
    bad "a BOM-prefixed empty key's value was never interpolated (exit $STATUS): $(cat "$WORK/out.txt")"
fi

: > "$FAKE/.env"
bash "$FAKE/scripts/preflight-env.sh" > "$WORK/out.txt" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ] && grep -q "JWT_SECRET_KEY" "$WORK/out.txt" && ! grep -q "cannot be loaded" "$WORK/out.txt" && ! grep -q "No such file" "$WORK/out.txt"; then
    ok "an empty .env loads and fails only on the required vars, with no stray error"
else
    bad "an empty .env was misjudged (exit $STATUS): $(cat "$WORK/out.txt")"
fi

printf '%s\n' "$REQUIRED_LINES" > "$FAKE/.env"
printf 'BRACKET[0]=${MISSING:?boom}\n' >> "$FAKE/.env"
touch "$WORK/BRACKET0"
( cd "$WORK" && bash "$FAKE/scripts/preflight-env.sh" > "$WORK/out.txt" 2>&1 )
STATUS=$?
if [ "$STATUS" -ne 0 ] && grep -qF "line 4 (BRACKET[0])" "$WORK/out.txt"; then
    ok "a bracketed key is refused by its own name even beside a file its brackets would glob to"
else
    bad "a bracketed key was mishandled (exit $STATUS): $(cat "$WORK/out.txt")"
fi

ODD_MULTI="$(printf 'ODD-KEY="a\nb c\n"')"
run_preflight "$ODD_MULTI"
if [ "$STATUS" -eq 0 ]; then
    ok "a multiline value under a hyphenated key keeps its continuation lines exempt"
else
    bad "a multiline value under a hyphenated key was refused: $(cat "$WORK/out.txt")"
fi

echo "1..$((PASS + FAIL))"
echo "# ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]

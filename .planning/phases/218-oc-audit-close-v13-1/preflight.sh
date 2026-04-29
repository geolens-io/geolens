#!/usr/bin/env bash
# Phase 218 Wave 0 pre-flight. Asserts post-217 disk state before /oc-audit runs.
# Run from repo root (the script chdirs there itself).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

ERRORS=0
pass() { echo "  OK: $*"; }
fail() { echo "  FAIL: $*" >&2; ERRORS=$((ERRORS + 1)); }

echo "=== Working tree ==="
if [ -z "$(git status --porcelain | grep -v '^??' || true)" ]; then
    pass "working tree clean (ignoring untracked)"
else
    fail "uncommitted tracked changes present"
fi

echo "=== Phase 217 evidence (post-merge state) ==="
[ -f backend/app/modules/audit/router.py ] && pass "audit/router.py exists" || fail "audit/router.py missing"
grep -q 'require_enterprise' backend/app/modules/audit/router.py && pass "audit-export gate present" || fail "audit-export gate missing"
[ -f backend/app/modules/catalog/authorization.py ] && pass "catalog/authorization.py exists" || fail "catalog/authorization.py missing"
[ ! -f backend/app/modules/auth/visibility.py ] && pass "auth/visibility.py removed" || fail "auth/visibility.py still present"
[ -f backend/openapi.json ] && pass "backend/openapi.json present" || fail "backend/openapi.json missing"
[ -d cli ] && pass "cli/ directory exists" || fail "cli/ directory missing"
[ -d sdks/python/geolens_sdk ] && pass "python sdk directory exists" || fail "python sdk directory missing"

echo "=== Enterprise overlay (sibling repo) ==="
if [ -d "$HOME/Code/geolens-enterprise/geolens_enterprise/auth/saml" ]; then
    pass "SAML overlay present at ~/Code/geolens-enterprise/geolens_enterprise/auth/saml"
else
    fail "SAML overlay missing — expected at ~/Code/geolens-enterprise/geolens_enterprise/auth/saml"
fi

echo "=== SAML logic absent from core (narrow regex; Pitfall 5) ==="
# Look for SAML implementation (top-level class/def names containing 'saml'),
# not enum strings, docstrings, or column scaffolding. The regex anchors at the
# `class`/`def` keyword and matches identifiers that start with or contain 'saml'.
# Phase 217 documented carve-out: oauth/{schemas,models,service}.py and
# settings/router.py contain `deferred_group="saml"` columns and docstring
# references — these are NOT SAML logic and the anchored regex correctly skips
# them. Exception (also carved out): the `def _safe_read_deferred_saml_fields`
# helper in oauth/schemas.py which exists only to make the deferred-group columns
# safe to read on community DBs without SAML columns. We allowlist this single
# helper-name pattern explicitly (it has no SAML business logic — it's a
# defensive read-handler for the carve-out scaffolding).
RAW=$(rg -i '^\s*(class|def)\s+\w*saml' backend/app/ --no-messages || true)
# Strip allowlisted carve-out helper, then count remaining lines
FILTERED=$(printf '%s' "$RAW" | grep -v '_safe_read_deferred_saml_fields' || true)
if [ -z "$FILTERED" ]; then
    HITS=0
else
    HITS=$(printf '%s\n' "$FILTERED" | wc -l | tr -d ' ')
fi
if [ "$HITS" -eq 0 ]; then
    pass "no SAML logic in backend/app/ (0 hits for anchored class/def saml regex; deferred-group scaffolding carved out)"
else
    fail "$HITS SAML logic hit(s) in backend/app/"
fi

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "$ERRORS pre-flight check(s) failed." >&2
    exit 1
fi
echo "ALL PRE-FLIGHT CHECKS PASS"

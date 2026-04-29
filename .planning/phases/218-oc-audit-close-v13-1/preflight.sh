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
# Look for SAML implementation, not enum strings or column scaffolding (4 false-positive files
# carved out by Phase 217: oauth/schemas.py, oauth/models.py, oauth/service.py, settings/router.py)
HITS=$(rg -i 'class.*Saml|def.*saml' backend/app/ --no-messages | wc -l | tr -d ' ' || echo 0)
if [ "$HITS" -eq 0 ]; then
    pass "no SAML logic in backend/app/ (0 hits for class.*Saml|def.*saml)"
else
    fail "$HITS SAML logic hit(s) in backend/app/"
fi

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "$ERRORS pre-flight check(s) failed." >&2
    exit 1
fi
echo "ALL PRE-FLIGHT CHECKS PASS"

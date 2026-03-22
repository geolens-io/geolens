#!/usr/bin/env bash
# validate-firstrun.sh
#
# Run on a target Ubuntu 24.04 VM after the cloud-init first-run script
# has executed. Verifies the entire first-run system works correctly.
#
# Usage: sudo bash validate-firstrun.sh

set -euo pipefail

PASSED=0
FAILED=0
WARNED=0
TOTAL=12

pass() { echo "PASS"; PASSED=$((PASSED + 1)); }
fail() { echo "FAIL${1:+ ($1)}"; FAILED=$((FAILED + 1)); }
warn() { echo "WARN${1:+ ($1)}"; WARNED=$((WARNED + 1)); }

echo "=== GeoLens First-Run Validation ==="
echo ""

# ---------- 1. .env exists ----------
echo -n "1.  .env exists: "
if [ -f /opt/geolens/.env ]; then
    pass
else
    fail "not found"
fi

# ---------- 2. Passwords are random (not hardcoded) ----------
echo -n "2.  Passwords are random: "
PG_PASS=$(grep POSTGRES_PASSWORD /opt/geolens/.env 2>/dev/null | cut -d= -f2)
if [ -n "${PG_PASS}" ] && [ "${PG_PASS}" != "admin" ] && [ "${PG_PASS}" != "password" ]; then
    pass
else
    fail "POSTGRES_PASSWORD is empty or hardcoded"
fi

# ---------- 3. JWT secret is hex format ----------
echo -n "3.  JWT secret is 64-char hex: "
JWT=$(grep JWT_SECRET_KEY /opt/geolens/.env 2>/dev/null | cut -d= -f2)
if echo "${JWT}" | grep -qE '^[0-9a-f]{64}$'; then
    pass
else
    fail "got: ${JWT:-empty}"
fi

# ---------- 4. .env has chmod 600 ----------
echo -n "4.  .env is chmod 600: "
PERMS=$(stat -c %a /opt/geolens/.env 2>/dev/null)
if [ "${PERMS}" = "600" ]; then
    pass
else
    fail "${PERMS:-unknown}"
fi

# ---------- 5. PUBLIC_API_URL has /api suffix ----------
echo -n "5.  PUBLIC_API_URL ends with /api: "
API_URL=$(grep PUBLIC_API_URL /opt/geolens/.env 2>/dev/null | cut -d= -f2-)
if echo "${API_URL}" | grep -qE '/api$'; then
    pass
else
    fail "${API_URL:-empty}"
fi

# ---------- 6. PUBLIC_APP_URL is not localhost ----------
echo -n "6.  PUBLIC_APP_URL has public IP: "
APP_URL=$(grep PUBLIC_APP_URL /opt/geolens/.env 2>/dev/null | cut -d= -f2-)
if echo "${APP_URL}" | grep -qE 'localhost|127\.0\.0\.1'; then
    warn "contains localhost -- expected on non-cloud VMs"
else
    pass
fi

# ---------- 7. Credential log exists with chmod 600 ----------
echo -n "7.  geolens-init.log exists (chmod 600): "
if [ -f /var/log/geolens-init.log ]; then
    LOG_PERMS=$(stat -c %a /var/log/geolens-init.log 2>/dev/null)
    if [ "${LOG_PERMS}" = "600" ]; then
        pass
    else
        fail "permissions are ${LOG_PERMS}, expected 600"
    fi
else
    fail "not found"
fi

# ---------- 8. Credential log contains admin password ----------
echo -n "8.  Credential log has admin password: "
if grep -q "Password:" /var/log/geolens-init.log 2>/dev/null; then
    pass
else
    fail "no Password: line found"
fi

# ---------- 9. All Docker services healthy ----------
echo -n "9.  All Docker services healthy: "
cd /opt/geolens
UNHEALTHY=$(docker compose -f docker-compose.prod.yml ps --format json 2>/dev/null | \
    python3 -c "
import sys, json
for line in sys.stdin:
    svc = json.loads(line)
    health = svc.get('Health', '')
    if health and 'healthy' not in health:
        print(svc.get('Name', 'unknown'))
" 2>/dev/null || true)
if [ -z "${UNHEALTHY}" ]; then
    pass
else
    fail "unhealthy: ${UNHEALTHY}"
fi

# ---------- 10. geolens.service is enabled ----------
echo -n "10. geolens.service is enabled: "
if systemctl is-enabled geolens.service >/dev/null 2>&1; then
    pass
else
    fail "not enabled"
fi

# ---------- 11. No cloud-init.target dependency ----------
echo -n "11. geolens.service has no cloud-init.target: "
if grep -q "cloud-init.target" /etc/systemd/system/geolens.service 2>/dev/null; then
    fail "cloud-init.target dependency found"
else
    pass
fi

# ---------- 12. cloud-init-output.log is restricted ----------
echo -n "12. cloud-init-output.log is chmod 600: "
if [ -f /var/log/cloud-init-output.log ]; then
    CI_PERMS=$(stat -c %a /var/log/cloud-init-output.log 2>/dev/null)
    if [ "${CI_PERMS}" = "600" ]; then
        pass
    else
        fail "permissions are ${CI_PERMS}, expected 600"
    fi
else
    fail "not found"
fi

# ---------- Summary ----------
echo ""
echo "=============================================="
echo " Results: ${PASSED}/${TOTAL} passed, ${FAILED} failed, ${WARNED} warnings"
echo "=============================================="
echo ""
echo "Next steps -- reboot the VM and verify:"
echo "  1. Services restart automatically:"
echo "     systemctl status geolens.service"
echo "  2. .env is NOT regenerated (compare POSTGRES_PASSWORD before/after reboot):"
echo "     grep POSTGRES_PASSWORD /opt/geolens/.env"
echo "  3. No new geolens-init.log entries (timestamp unchanged):"
echo "     cat /var/log/geolens-init.log"
echo ""

# Exit with failure if any checks failed
if [ "${FAILED}" -gt 0 ]; then
    exit 1
fi

#!/usr/bin/env bash
# /var/lib/cloud/scripts/per-instance/01-geolens-init.sh
#
# Cloud-init per-instance first-run script for GeoLens.
# Runs exactly once on first boot. Generates credentials,
# detects public IP, starts Docker Compose, logs access info.
#
# Target location on VM: /var/lib/cloud/scripts/per-instance/01-geolens-init.sh
# (Packer copies this file during image build)

set -euo pipefail

# ---------- Constants ----------
APP_DIR="/opt/geolens"
ENV_FILE="${APP_DIR}/.env"
LOG_FILE="/var/log/geolens-init.log"

# ---------- Guard clause ----------
# Prevent credential overwrite on partial re-runs or cloned instances
if [ -f "${ENV_FILE}" ]; then
    echo "GeoLens: .env already exists, skipping initialization"
    exit 0
fi

# ---------- Configure swap ----------
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "GeoLens: 2GB swap configured"
fi

# ---------- Generate credentials ----------
POSTGRES_PASSWORD=$(openssl rand -base64 24)
JWT_SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASSWORD=$(openssl rand -base64 18)

# ---------- Detect public IP ----------
PUBLIC_IP=""

# Try AWS IMDSv2 first (PUT to get session token, then GET public IP)
TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 300" \
    --connect-timeout 2 --max-time 3 || true)

if [ -n "${TOKEN}" ]; then
    PUBLIC_IP=$(curl -sf \
        -H "X-aws-ec2-metadata-token: ${TOKEN}" \
        "http://169.254.169.254/latest/meta-data/public-ipv4" \
        --connect-timeout 2 --max-time 3 || true)
fi

# Fallback: DigitalOcean metadata
if [ -z "${PUBLIC_IP}" ]; then
    PUBLIC_IP=$(curl -sf \
        "http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address" \
        --connect-timeout 2 --max-time 3 || true)
fi

# Final fallback
if [ -z "${PUBLIC_IP}" ]; then
    PUBLIC_IP="localhost"
    echo "WARNING: Could not detect public IP via IMDS or DO metadata. Using localhost."
fi

# ---------- Write .env ----------
# Source pinned image versions if available (written by Packer build)
if [ -f "${APP_DIR}/.env.versions" ]; then
    # shellcheck source=/dev/null
    . "${APP_DIR}/.env.versions"
fi

cat > "${ENV_FILE}" <<EOF
POSTGRES_DB=geolens
POSTGRES_USER=geolens
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
JWT_SECRET_KEY=${JWT_SECRET_KEY}
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=${ADMIN_PASSWORD}
PUBLIC_APP_URL=http://${PUBLIC_IP}
PUBLIC_API_URL=http://${PUBLIC_IP}/api
LOG_JSON=true
LOG_LEVEL=INFO
GEOLENS_VERSION=${GEOLENS_VERSION:-latest}
TITILER_VERSION=${TITILER_VERSION:-latest}
EOF
chmod 600 "${ENV_FILE}"

# ---------- Pull images (conditional) and start ----------
cd "${APP_DIR}"

# Only pull if images are not already cached in the AMI
CACHED_IMAGES=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -c 'geolens\|titiler' || true)
if [ "${CACHED_IMAGES}" -lt 3 ]; then
    echo "GeoLens: Pulling Docker images (not cached in AMI)..."
    docker compose -f docker-compose.prod.yml pull
else
    echo "GeoLens: Docker images already cached in AMI, skipping pull"
fi

docker compose -f docker-compose.prod.yml up -d --wait --wait-timeout 120

# ---------- Health check ----------
sleep 5
if curl -sf http://localhost/api/health > /dev/null 2>&1; then
    echo "GeoLens health check: PASS"
else
    echo "WARNING: GeoLens health check failed -- stack may still be starting"
fi

# ---------- AWS Marketplace metering (if product code is set) ----------
# RegisterUsage confirms this instance was launched via a valid Marketplace subscription.
# Requires IAM role with aws-marketplace:RegisterUsage permission.
if [ -n "${AWS_MARKETPLACE_PRODUCT_CODE:-}" ]; then
    REGION=""
    if [ -n "${TOKEN}" ]; then
        REGION=$(curl -sf -H "X-aws-ec2-metadata-token: ${TOKEN}" \
            "http://169.254.169.254/latest/meta-data/placement/region" \
            --connect-timeout 2 --max-time 3 || true)
    fi
    if [ -n "${REGION}" ]; then
        aws marketplace-metering register-usage \
            --product-code "${AWS_MARKETPLACE_PRODUCT_CODE}" \
            --public-key-version 1 \
            --region "${REGION}" \
            2>&1 || echo "WARN: Marketplace RegisterUsage failed (non-fatal for BYOL)"
    else
        echo "WARN: Could not detect AWS region for Marketplace metering"
    fi
fi

# ---------- Write credential log ----------
cat > "${LOG_FILE}" <<EOF
====================================================
GeoLens First-Run Initialization
Date: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
====================================================

URL:      http://${PUBLIC_IP}
Username: admin
Password: ${ADMIN_PASSWORD}

====================================================
EOF
chmod 600 "${LOG_FILE}"

# ---------- Secure cloud-init output log ----------
# Defense-in-depth: restrict cloud-init-output.log which captures script stdout
chmod 600 /var/log/cloud-init-output.log 2>/dev/null || true

# ---------- Print summary to stdout ----------
# NOTE: Do NOT echo the password here. cloud-init-output.log may be
# readable during boot. Direct users to the dedicated credential log.
echo ""
echo "=============================================="
echo " GeoLens is ready!"
echo " URL:      http://${PUBLIC_IP}"
echo " Username: admin"
echo " Credentials: sudo cat ${LOG_FILE}"
echo "=============================================="
echo ""

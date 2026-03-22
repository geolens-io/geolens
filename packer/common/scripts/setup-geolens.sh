#!/usr/bin/env bash
set -euo pipefail

# Create application directory structure
sudo mkdir -p /opt/geolens/scripts /opt/geolens/deploy /opt/geolens/nginx

# Copy application files from /tmp (uploaded by file provisioners)
sudo cp /tmp/docker-compose.prod.yml /opt/geolens/
sudo cp /tmp/init-db.sh /opt/geolens/scripts/
sudo cp /tmp/backup-entrypoint.sh /opt/geolens/scripts/
sudo cp /tmp/backup.sh /opt/geolens/scripts/
sudo cp /tmp/backup-s3-upload.py /opt/geolens/scripts/
sudo cp /tmp/backup-s3-retention.py /opt/geolens/scripts/
sudo cp /tmp/validate-firstrun.sh /opt/geolens/deploy/
sudo cp /tmp/tls.conf.template /opt/geolens/nginx/
sudo cp /tmp/USAGE.md /opt/geolens/

# Write VERSION file from Packer build variable
echo "${APP_VERSION:-unknown}" | sudo tee /opt/geolens/VERSION > /dev/null

# Write pinned image versions to .env.versions (sourced by cloud-init)
cat <<EOF | sudo tee /opt/geolens/.env.versions > /dev/null
GEOLENS_VERSION=${GEOLENS_VERSION:-latest}
TITILER_VERSION=${TITILER_VERSION:-latest}
EOF

# Install cloud-init per-instance script
sudo mkdir -p /var/lib/cloud/scripts/per-instance
sudo cp /tmp/01-geolens-init.sh /var/lib/cloud/scripts/per-instance/
sudo chmod 755 /var/lib/cloud/scripts/per-instance/01-geolens-init.sh

# Install systemd service
sudo cp /tmp/geolens.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable geolens.service

# Install MOTD banner
sudo cp /tmp/99-geolens /etc/update-motd.d/99-geolens
sudo chmod 755 /etc/update-motd.d/99-geolens

# Configure unattended-upgrades for automatic security updates
sudo apt-get update
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

# Configure Docker log rotation via logrotate (defense-in-depth alongside json-file driver limits)
cat <<'LOGROTATE' | sudo tee /etc/logrotate.d/docker-containers > /dev/null
/var/lib/docker/containers/*/*.log {
    rotate 7
    daily
    compress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

# Pre-pull Docker images to speed up first boot
# The cloud-init script does docker compose pull anyway, but caching in the AMI
# eliminates the ~2-5 min GHCR download on first boot
# Allow failure: GHCR images may not be published yet (cloud-init pulls at boot)
cd /opt/geolens
sudo env GEOLENS_VERSION="${GEOLENS_VERSION:-latest}" TITILER_VERSION="${TITILER_VERSION:-latest}" \
    docker compose -f docker-compose.prod.yml pull \
    || echo "WARN: docker compose pull failed (some images may not be published yet); cloud-init will pull at first boot"

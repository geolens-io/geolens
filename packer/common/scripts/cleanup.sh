#!/usr/bin/env bash
set -euo pipefail

# Remove SSH host keys (regenerated on first boot by cloud-init)
sudo rm -f /etc/ssh/ssh_host_*

# Remove all authorized_keys files (defense-in-depth with ssh_clear_authorized_keys)
sudo find /home -name authorized_keys -delete
sudo rm -f /root/.ssh/authorized_keys

# Clear bash history for all users
sudo find /home -name .bash_history -delete
sudo rm -f /root/.bash_history
history -c || true

# Update all packages to latest (Marketplace scanner checks for pending security updates)
sudo apt-get update
sudo apt-get upgrade -y

# Clean apt cache
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*

# Remove temporary files
sudo rm -rf /tmp/* /var/tmp/*

# Clean cloud-init state so it re-runs on first boot of the AMI
sudo cloud-init clean --logs

# Remove machine ID (regenerated on first boot)
sudo truncate -s 0 /etc/machine-id

# Sync filesystem
sync

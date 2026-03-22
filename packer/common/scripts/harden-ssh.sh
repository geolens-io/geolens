#!/usr/bin/env bash
set -euo pipefail

# Disable password authentication in main sshd_config
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config

# Create drop-in config that takes precedence over any cloud-init overrides
# Ubuntu 24.04 uses /etc/ssh/sshd_config.d/*.conf -- 99- prefix ensures it loads last
echo "PasswordAuthentication no" | sudo tee /etc/ssh/sshd_config.d/99-marketplace.conf

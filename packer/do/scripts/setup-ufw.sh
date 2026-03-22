#!/usr/bin/env bash
set -euo pipefail

# Enable ufw with default deny incoming, allow outgoing
ufw default deny incoming
ufw default allow outgoing

# Allow SSH, HTTP, HTTPS
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

# Enable non-interactively
ufw --force enable

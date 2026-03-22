#!/usr/bin/env bash
set -euo pipefail

# Download DO marketplace validation script
curl -fsSL https://raw.githubusercontent.com/digitalocean/marketplace-partners/master/scripts/99-img-check.sh -o /tmp/img_check.sh
chmod +x /tmp/img_check.sh

# Run validation (informational -- don't fail the build on warnings)
bash /tmp/img_check.sh || echo "WARN: img_check.sh reported issues (review output above)"

# Clean up
rm -f /tmp/img_check.sh

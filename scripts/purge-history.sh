#!/usr/bin/env bash
# purge-history.sh — Rewrite git history for public open-source release
#
# DESTRUCTIVE: This permanently rewrites ALL git history to remove internal
# artifacts (.planning/, .claude/, internal docs, etc.) from every commit.
# All collaborators must re-clone after this runs and you force-push.
#
# A mirror backup is created before any changes are made.

set -euo pipefail

echo "============================================================"
echo "  GeoLens — Public Release History Rewrite"
echo "============================================================"
echo ""
echo "WARNING: This script is DESTRUCTIVE. It will:"
echo "  - Rewrite the entire git history of this repository"
echo "  - Delete all tags (fresh start for public release)"
echo "  - Remove internal artifacts from every historical commit"
echo ""
echo "A mirror backup will be created before any changes."
echo "This cannot be undone without restoring from the backup."
echo ""
read -p "Type YES to continue: " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
  echo "Aborted."
  exit 1
fi

echo ""

# Check git-filter-repo is installed
if ! command -v git-filter-repo &>/dev/null; then
  echo "ERROR: git-filter-repo is not installed."
  echo ""
  echo "Install it with:"
  echo "  brew install git-filter-repo"
  echo ""
  echo "Then re-run this script."
  exit 1
fi

echo "git-filter-repo found: $(command -v git-filter-repo)"
echo ""

# Create mirror backup before anything destructive
BACKUP_DIR="../geolens-backup-$(date +%Y%m%d)"
echo "Creating mirror backup at: $BACKUP_DIR"
git clone --mirror . "$BACKUP_DIR"
echo "Backup created."
echo ""

# Delete all tags — starting fresh for public release (user decision).
# Internal milestone tags (v1.0-v14.0) are not relevant to public consumers.
echo "Deleting all local tags..."
git tag -l | xargs -r git tag -d
echo "All tags deleted."
echo ""

# Rewrite history — remove all internal artifact paths from every commit
echo "Rewriting history with git-filter-repo..."
git filter-repo --force \
  --invert-paths \
  --path .planning/ \
  --path plans/ \
  --path prd.md \
  --path todo.md \
  --path smoke-check.md \
  --path artifacts/ \
  --path .agents/ \
  --path .codex/ \
  --path .claude/ \
  --path docs-internal/ \
  --path docs/audits/ \
  --path docs/GTM/ \
  --path docs/decisions/ \
  --path "docs/dep-audit-2026-03-31.md" \
  --path "docs/sec-audit-full-2026-03-30.md" \
  --path "docs/handoff-landing-page-oss-identity-20260403.md" \
  --path "docs/ux-plan-landing-page-20260403.md" \
  --path "docs/ux-review-map-builder-retroactive-2026-03-31.md" \
  --path "docs/api-contract-full-2026-03-30.md" \
  --path "docs/cloud-readiness-assessment.md" \
  --path "docs/connection-budget.md"

echo "History rewrite complete."
echo ""

# Re-add origin remote (git-filter-repo removes it as a safety measure)
git remote add origin https://github.com/geolens-io/geolens.git
echo "Remote 'origin' re-added."
echo ""

echo "============================================================"
echo "History rewrite complete. All tags deleted."
echo "Backup at: $BACKUP_DIR"
echo ""
echo "Next steps (run manually):"
echo "  git push origin --force --all"
echo ""
echo "After force-push, all collaborators must re-clone."
echo "============================================================"

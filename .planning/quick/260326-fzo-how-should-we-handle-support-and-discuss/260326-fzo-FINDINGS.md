# Support & Discussions Strategy for GeoLens Public Release

**Date:** 2026-03-26
**Scope:** Community support channels, enterprise support boundary, GitHub repo configuration, in-app help UX

---

## Overview

GeoLens uses **GitHub as the single community platform**: Discussions for questions/ideas/announcements, Issues for bugs/feature requests. No separate Discord or forum — keeping everything in one searchable, indexed location reduces maintenance and makes community knowledge discoverable.

---

## Channel Routing

| User Need | Channel | Template/Category |
|-----------|---------|-------------------|
| Question / How-to | GitHub Discussions | Q&A category |
| Bug report | GitHub Issues | Bug Report template |
| Feature request | GitHub Issues | Feature Request template |
| Feature idea / discussion | GitHub Discussions | Ideas category |
| Announcement | GitHub Discussions | Announcements (maintainer-only) |
| Show & Tell | GitHub Discussions | Show & Tell category |
| Security vulnerability | Email | security@geolens.io |
| Enterprise support | Private | enterprise@geolens.io |

The issue template chooser now **disables blank issues** and redirects questions to Discussions Q&A and ideas to Discussions Ideas. This forces routing through structured templates and reduces low-quality submissions.

---

## Support Tiers

### Community (Free)
- **Channels:** GitHub Discussions + Issues
- **Response:** Best-effort, community-driven
- **SLA:** None
- **Scope:** How-to questions, bug reports, feature requests, general discussion

### Enterprise (Paid)
- **Channels:** Private Slack or email
- **Response:** Guaranteed response times per SLA
- **Scope:** Priority bug fixes, upgrade assistance, security patching guidance, deployment support
- **Contact:** enterprise@geolens.io

The boundary between community and enterprise is clearly documented in `SUPPORT.md` at the repo root.

---

## Discussion Categories

These must be created manually in GitHub repo Settings > Discussions after enabling the feature.

| Category | Format | Purpose |
|----------|--------|---------|
| Announcements | Announcement | Maintainer-only posts for releases, breaking changes |
| Q&A | Question | Community help — structured with accepted answers |
| Ideas | Open-ended | Feature ideas and enhancement discussions |
| Show & Tell | Open-ended | Community projects, integrations, demos |
| General | Open-ended | Everything else |

Discussion form templates (`q-a.yml`, `ideas.yml`) provide structured inputs for the Q&A and Ideas categories.

---

## Repo Configuration Delivered

| File | Status | Purpose |
|------|--------|---------|
| `SUPPORT.md` | Created | Routes users to correct support channels |
| `CODE_OF_CONDUCT.md` | Created | Contributor Covenant v2.1 |
| `.github/ISSUE_TEMPLATE/config.yml` | Updated | Disables blank issues, redirects to Discussions |
| `.github/DISCUSSION_TEMPLATE/q-a.yml` | Created | Structured Q&A form template |
| `.github/DISCUSSION_TEMPLATE/ideas.yml` | Created | Structured Ideas form template |
| `AppLayout.tsx` | Updated | Footer "Community" link to Discussions |
| `common.json` (4 locales) | Updated | i18n translations for footer link |

---

## Post-Deployment Checklist

Manual steps required after pushing to the public repo:

- [ ] **Enable Discussions** in GitHub repo Settings > General > Features
- [ ] **Create discussion categories:**
  - Announcements (announcement format)
  - Q&A (question format)
  - Ideas (open-ended format)
  - Show & Tell (open-ended format)
  - General (open-ended format)
- [ ] **Pin a welcome post** in Announcements introducing the project and community
- [ ] **Pin a "How to get help" post** in General linking to SUPPORT.md
- [ ] **Verify SUPPORT.md** renders on the repo's Community tab
- [ ] **Verify CODE_OF_CONDUCT.md** renders on the repo's Community tab
- [ ] **Test issue template chooser** — creating a new issue should show Bug Report, Feature Request, Ask a Question (-> Discussions), Share an Idea (-> Discussions)

---

## Future Considerations

1. **GitHub Actions bot for stale discussions** — auto-close inactive Q&A threads after 30 days with a "still need help?" prompt
2. **Saved searches / auto-labels** — triage labels for common topics (ingestion, tiles, auth, AI)
3. **Community health metrics** — track response times, resolution rates, active contributors
4. **Discord consideration** — if community grows beyond GitHub's capacity, consider Discord for real-time chat while keeping Discussions for archival Q&A

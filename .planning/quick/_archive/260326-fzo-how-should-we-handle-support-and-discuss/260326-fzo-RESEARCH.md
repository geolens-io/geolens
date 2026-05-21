# Quick Task 260326-fzo: Support & Discussions Strategy - Research

**Researched:** 2026-03-26
**Domain:** Community support infrastructure, GitHub configuration, open-core support tiers
**Confidence:** HIGH

## Summary

GeoLens already has solid GitHub infrastructure in place: CONTRIBUTING.md, bug report and feature request issue templates (YAML forms), a PR template, and a config.yml that links to GitHub Discussions. What is missing: SUPPORT.md, CODE_OF_CONDUCT.md, actual Discussion categories configuration, and an in-app help link.

The footer in `AppLayout.tsx` is a single "Powered by GeoLens" link to the GitHub repo. This is the natural place to add a help/community link -- either alongside the existing link or as a small separator-delimited addition.

**Primary recommendation:** Enable GitHub Discussions with 5 categories, add SUPPORT.md and CODE_OF_CONDUCT.md, and extend the footer with a "Community" or "Help" link pointing to Discussions.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- GitHub Discussions only -- no Discord or separate forum
- Community support: GitHub Discussions + Issues (free, best-effort)
- Enterprise support: private Slack/email with SLA (paid, separate from public channels)
- Deliverables: strategy doc (FINDINGS.md), repo config (templates, SUPPORT.md, CONTRIBUTING.md), in-app help link
- Help link: lightweight, points to GitHub Discussions, not a full help page

### Claude's Discretion
- Discussion category naming and structure
- Issue template content and categories
- Exact placement of help link in UI (footer vs sidebar vs header)

### Deferred Ideas (OUT OF SCOPE)
- None specified

</user_constraints>

## What Already Exists

| File | Status | Notes |
|------|--------|-------|
| `.github/CONTRIBUTING.md` | EXISTS | Complete -- dev setup, code style, PR guidance, security contact |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | EXISTS | Well-structured YAML form with area dropdown, version, deployment method |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | EXISTS | YAML form with problem/solution/alternatives/area fields |
| `.github/ISSUE_TEMPLATE/config.yml` | EXISTS | Links to Discussions, blank issues enabled |
| `.github/PULL_REQUEST_TEMPLATE.md` | EXISTS | Checklist format with area, testing, i18n |
| `SUPPORT.md` | MISSING | Needs creation |
| `CODE_OF_CONDUCT.md` | MISSING | Needs creation |
| `.github/DISCUSSION_TEMPLATE/` | MISSING | Optional -- forms for structured discussion posts |
| GitHub Discussions | NOT ENABLED | config.yml references it but Discussions must be enabled in repo settings |

## Recommended Discussion Categories

Based on GitHub's category format types and patterns from successful open-source geospatial projects (MapLibre, GeoServer, QGIS forums):

| Category | Format | Emoji | Purpose |
|----------|--------|-------|---------|
| Announcements | Announcement | megaphone | Releases, breaking changes, roadmap updates (maintainer-only posting) |
| Q&A | Question/Answer | question | "How do I..." questions -- markable as answered |
| Ideas | Open-ended | bulb | Feature ideas and enhancement discussion before they become issues |
| Show & Tell | Open-ended | star | Share deployments, workflows, integrations -- builds community |
| General | Open-ended | speech_balloon | Everything else -- deployment help, architecture questions, OGC/STAC discussion |

**Why these 5:** Q&A with answer-marking reduces repeat questions. Announcements keeps release noise separate. Ideas channels feature requests before they become formal issues. Show & Tell encourages adoption stories (marketing gold). General catches the rest without creating too many categories early on.

**What to skip for now:** "Bug Reports" category (already handled by issue templates), "Development" (use PRs/issues), "Polls" (premature).

## SUPPORT.md Content Pattern

Standard open-source SUPPORT.md should include:
1. Where to get help (Discussions Q&A for questions, Issues for bugs)
2. What NOT to use issues for (general questions -- redirect to Discussions)
3. Enterprise support path (contact email/page for SLA-backed support)
4. Security vulnerability reporting (email, not public issues -- already in CONTRIBUTING.md)

## CODE_OF_CONDUCT.md

Use the Contributor Covenant v2.1 -- industry standard, GitHub has a built-in generator for it. Minimal effort, signals professionalism.

## Enterprise Support Boundary

From `docs/GTM/free-vs-enterprise.md`, the enterprise support tier includes:
- Priority support
- SLA guarantees
- Upgrade assistance
- Security patching guidance

SUPPORT.md should clearly delineate: "Community support is best-effort via GitHub Discussions and Issues. For guaranteed response times and private support channels, see [Enterprise page/contact]."

## In-App Help Link

### Current Footer Structure

`frontend/src/components/layout/AppLayout.tsx` lines 18-29:

```tsx
{!isMapBuilder && !isDatasetDetail && (
  <footer className="py-2 text-center text-xs text-muted-foreground">
    <a href={GEOLENS_GITHUB_URL} target="_blank" rel="noopener noreferrer"
       className="hover:text-foreground transition-colors">
      {t('footer.poweredBy')}
    </a>
  </footer>
)}
```

The footer is hidden on map builder and dataset detail pages (those have their own layouts).

### Recommendation: Extend the footer

Add a second link separated by a dot/pipe:

```
Powered by GeoLens  ·  Community
```

Where "Community" links to `https://github.com/geolens-io/geolens/discussions`.

**Why footer over sidebar/header:**
- Footer already exists with the right styling
- Sidebar is admin-only (AdminSidebar) -- not visible to all users
- Header (Navbar) is already dense with navigation
- Footer placement is unobtrusive and conventional for open-source apps

**i18n keys needed:** `footer.community` in all 4 locales (en, fr, es, de).

## Issue Template Gaps

The existing templates are solid. One addition to consider:

**Add a "Question" issue template redirect** -- currently `config.yml` links to Discussions, but adding an explicit "Ask a Question" option in the template chooser with `url:` pointing to Discussions Q&A category would reduce misplaced questions in Issues.

Updated `config.yml`:
```yaml
blank_issues_enabled: false  # Changed: force template usage
contact_links:
  - name: Ask a Question
    url: https://github.com/geolens-io/geolens/discussions/categories/q-a
    about: Get help from the community (not for bug reports)
  - name: Share an Idea
    url: https://github.com/geolens-io/geolens/discussions/categories/ideas
    about: Suggest features or discuss enhancements before opening an issue
```

**Note:** Disabling blank issues forces users through templates or Discussion links, reducing low-quality issue submissions.

## Common Pitfalls

### Pitfall 1: Discussions enabled but empty
**What goes wrong:** Users arrive at an empty Discussions page and leave.
**How to avoid:** Seed 2-3 starter posts: a welcome/intro in Announcements, a pinned "How to get help" in General, and one example Q&A.

### Pitfall 2: No triage between Issues and Discussions
**What goes wrong:** Questions pile up in Issues, bugs get posted in Discussions.
**How to avoid:** SUPPORT.md + issue template config.yml make the routing clear. Regularly convert misplaced discussions to issues (GitHub has a built-in "Convert to issue" button).

### Pitfall 3: Enterprise support path unclear
**What goes wrong:** Enterprise prospects post in public Discussions expecting SLA support.
**How to avoid:** SUPPORT.md explicitly states community = best-effort, enterprise = contact sales/email.

## Sources

### Primary (HIGH confidence)
- Repo audit: `.github/` directory, `AppLayout.tsx`, i18n files -- direct file reads
- `docs/GTM/free-vs-enterprise.md` -- enterprise tier definition
- `docs/GTM/repo-split.md` -- open-core architecture boundary

### Secondary (MEDIUM confidence)
- [GitHub Discussions documentation](https://docs.github.com/en/discussions) -- category formats, forms, management
- [Managing categories for discussions](https://docs.github.com/en/discussions/managing-discussions-for-your-community/managing-categories-for-discussions) -- up to 25 categories, sections, formats

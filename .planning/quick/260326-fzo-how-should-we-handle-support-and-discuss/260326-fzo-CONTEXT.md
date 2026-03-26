# Quick Task 260326-fzo: Support & Discussions Strategy - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Task Boundary

Define the support and community engagement strategy for GeoLens public release. Produce a strategy doc, configure GitHub repo with issue templates/discussion categories/SUPPORT.md/CONTRIBUTING.md, and add a help link in the app UI.

</domain>

<decisions>
## Implementation Decisions

### Channel Strategy
- GitHub Discussions only — single location, integrated with issues/PRs, searchable, low maintenance
- No Discord or separate forum

### Support Tiers
- Community support: GitHub Discussions + Issues (free, best-effort)
- Enterprise support: private Slack/email with SLA (paid, separate from public channels)
- Clear boundary between community and enterprise support paths

### Deliverable Scope
- Strategy/recommendations doc (FINDINGS.md)
- Actual repo config: issue templates, discussion categories, SUPPORT.md, CONTRIBUTING.md
- In-app help link pointing to GitHub Discussions

### In-App UX
- Add a help/support link in the app footer or sidebar
- Points to GitHub Discussions
- Lightweight — not a full help page

### Claude's Discretion
- Discussion category naming and structure
- Issue template content and categories
- Exact placement of help link in UI (footer vs sidebar vs header)

</decisions>

<specifics>
## Specific Ideas

- Consider standard open-source patterns: SUPPORT.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md
- Issue templates: bug report, feature request, question
- Discussion categories: General, Q&A, Ideas, Show & Tell
- Help link should feel natural, not intrusive

</specifics>

<canonical_refs>
## Canonical References

- docs/GTM/repo-split.md — enterprise vs community boundary
- docs/FEATURES.md — existing project documentation

</canonical_refs>

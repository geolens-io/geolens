# Quick Task 260330: Search Card Layout + Style Review - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Task Boundary

Review the current state of the search result cards in the live local GeoLens app and answer:

- How strong is the current card layout and styling?
- What should change to make each card feel simpler, more elegant, and more intuitive?
- Which problems are real UI bugs versus styling/taste issues?

Primary scope:
- Dataset cards on desktop and tablet
- Collection-card behavior when surfaced in search
- Card preview, text hierarchy, metadata hierarchy, and visual density

Out of scope:
- Mobile-first redesign
- Broader search-shell redesign except where it directly distorts card perception
- Product-code changes in this pass
</domain>

<decisions>
## Implementation Decisions

### Evidence First
- Start with live Playwright inspection on the running local stack at `http://localhost:8080`.
- Confirm major findings in source before writing recommendations.

### Design Intent
- Favor simple, calm, legible cards over “feature-dense” cards.
- Desktop and tablet are the decision-making breakpoints.
- Optimize for fast scanning: title, source, summary, facts, tags, timestamp.

### Historical Context
- The cards were already reworked today in quick tasks `260329-ga7` and `260329-kq7`.
- This pass should assess the current live state, not re-justify those earlier changes.

### Deliverable Shape
- Docs-only quick task: context, research, review, summary, verification.
- No product implementation in this pass.
</decisions>

<specifics>
## Specific Inspection Targets

- Default desktop result stack at `1440px`
- Tablet result stack at `900px`
- Long-source dataset card (`Riparian Integrity Score`)
- Collection search case (`Natural Earth Cultural`)
- Quicklook failure behavior for cards with missing previews

Questions to settle:
- Does the current 120px preview help or hurt clarity?
- Are source, description, facts, tags, and footer clearly ordered by importance?
- Do collection cards still feel intentional when the dataset-specific bands are absent?
- Are there contradictory search states that make the cards feel broken?
</specifics>

<canonical_refs>
## Canonical References

- `frontend/src/components/search/SearchResultCard.tsx`
- `frontend/src/pages/SearchPage.tsx`
- `frontend/src/hooks/use-quicklook.ts`
- `.planning/quick/260329-ga7-search-results-card-ui-ux-restructure-st/260329-ga7-PLAN.md`
- `.planning/quick/260329-kq7-enhance-dataset-cards-with-quick-actions/260329-kq7-SUMMARY.md`
</canonical_refs>

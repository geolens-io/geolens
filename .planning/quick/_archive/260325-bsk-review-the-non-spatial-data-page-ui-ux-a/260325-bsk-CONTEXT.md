# Quick Task 260325-bsk: Non-spatial data page UI/UX review - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Task Boundary

Review the non-spatial data page UI/UX and general functionality. Identify gaps, issues, or concerns. Check alignment with other data detail pages. Find easy win enhancements. Use Playwright MCP to evaluate http://localhost:8080/datasets/97fafb8a-8eaa-4a70-a46b-3193bca792fd#data as reference.

</domain>

<decisions>
## Implementation Decisions

### Visual Consistency Scope
- General feel match: same design language, spacing, typography — but non-spatial pages can differ where spatial features don't apply. Not pixel-perfect.

### Fix vs Report
- Fix easy wins (styling, spacing, small UX improvements) and document larger items as recommendations in a review report.

### Data Type Coverage
- Focus review on the specific dataset at the provided URL as representative example. No need to test multiple dataset types.

### Claude's Discretion
- None — all areas discussed.

</decisions>

<specifics>
## Specific Ideas

- Use Playwright MCP server to capture and evaluate the page at http://localhost:8080/datasets/97fafb8a-8eaa-4a70-a46b-3193bca792fd#data
- Compare with spatial dataset detail pages for consistency
- Look for missing states, accessibility issues, responsiveness gaps

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above

</canonical_refs>

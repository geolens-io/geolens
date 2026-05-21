# Quick Task 260425-lbc: Map Overlay Element Positioning Review - Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Task Boundary

In the map builder, review the map overlay elements and make sure they are all positioned well as not to conflict with one another. For example, the filter pills conflict with measure widget.

</domain>

<decisions>
## Implementation Decisions

### Audit Scope
- Review ALL map overlay elements (filter pills, measure widget, zoom controls, scale bar, attribution, legend, etc.) and fix all positioning conflicts — not just the reported filter pills vs measure widget issue.

### Fix Approach
- Use CSS positioning fixes (adjust margins, padding, absolute positions) for targeted conflict resolution. No structural layout system refactor — keep changes minimal and focused.

### Responsive / Mobile
- Mobile is low/not a priority. Focus on desktop viewport sizes. Don't invest effort in responsive breakpoints for overlay positioning.

### Claude's Discretion
- Specific z-index ordering when overlays must stack
- Exact pixel offsets and spacing values between elements

</decisions>

<specifics>
## Specific Ideas

- Filter pills conflict with measure widget — this is the known trigger for the audit
- All interactive overlays, widgets, and map chrome should be checked

</specifics>

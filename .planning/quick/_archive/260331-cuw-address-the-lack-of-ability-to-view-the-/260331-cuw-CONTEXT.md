# Quick Task 260331-cuw: Full Table View on Dataset Details Page - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Task Boundary

Address the lack of ability to view the entire table on the dataset details page (vector). **Primary issue: cannot scroll horizontally to see all columns.** The table is constrained within Card > CardContent and the `overflow-auto` container may not be working correctly for wide tables. Secondary: add an expand/full-view mechanism and improve overall data tab UX.

</domain>

<decisions>
## Implementation Decisions

### Expand Mechanism
- Expand button on the data tab that collapses the map and expands the table to fill the page
- Map can be toggled back (collapse/expand toggle)

### Table Height
- Expanded table fills available viewport height with internal scroll
- Pagination footer stays pinned at bottom

### Column Visibility
- Claude's discretion — choose best UX approach based on expert opinion

### General UI/UX Audit
- Table polish: row striping, hover states, better column headers, cell alignment, truncation handling
- Interaction gaps: missing features like sort, export, row click-to-detail, keyboard navigation
- Visual density: compact/comfortable row heights, font sizing, spacing between elements

</decisions>

<specifics>
## Specific Ideas

- Example dataset: http://localhost:8080/datasets/98240e38-136c-419e-9777-c5fbaf70a55d#data (Wildlife Corridor, 203 features, single objectid column)
- Current table is limited to tab panel area below a ~60% height map
- Pagination exists (25/50/100 rows per page) but no way to see full table
- Use Playwright MCP server for visual verification

</specifics>

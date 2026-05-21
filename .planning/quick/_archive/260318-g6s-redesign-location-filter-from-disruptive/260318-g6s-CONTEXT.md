# Quick Task 260318-g6s: Redesign location filter from disruptive popover to compact expandable panel - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Task Boundary

Redesign the location/spatial filter from a large disruptive popover overlay into a right-side panel that doesn't block search results. The current popover sits on top of results, feels like a modal but behaves like a dropdown — awkward in-between behavior that blocks scanning.

</domain>

<decisions>
## Implementation Decisions

### Panel Layout
- **Right-side panel** (~360-420px wide) that slides in from the right
- Results stay visible on the left while panel is open
- Desktop: right-side panel; Mobile/tablet: full-screen spatial filter view
- Panel contents: title ("Search area"), mini map, draw bbox/polygon tools, clear area, optional Intersects/Within mode toggle, Apply button

### Draw Interaction
- **Both rectangle + polygon**, with rectangle as the default mode
- Rectangle: click-drag to draw a bounding box (fast, covers 90% of use cases)
- Polygon: click to add vertices, double-click to finish (for irregular areas)
- UI: `Rectangle | Polygon` toggle, default to Rectangle
- Contextual instructions per mode
- Do NOT make polygon the first thing users see — rectangle is primary

### Filter Persistence
- **Collapse after filter is applied** — panel closes on Apply
- Active filter chip appears (e.g., "Area selected" or "Within selected area")
- Clicking chip reopens panel with geometry preserved
- Chip has `x` to remove spatial filter
- Panel stays open during active drawing/editing — only collapses after Apply
- Flow: open → draw/edit → apply → collapse

</decisions>

<specifics>
## Specific Ideas

- Width around 360-420px for the right-side panel
- Filter chip text options: "Area selected", "Within selected area", "Within map area"
- Future-friendly: later may add "Use current map extent", "Upload/select geometry", "Pick from saved area"
- On smaller screens, right panel becomes full-screen drawer/modal

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above

</canonical_refs>

# Quick Task 260318-gnv: Spatial filter panel completeness - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Task Boundary

Complete the spatial filter panel UX: full state machine (empty→drawing→drawn→applied), proper footer (Clear/Cancel/Apply), area summary, rectangle/polygon mode icons, active chip in main UI, Intersects/Within predicate toggle, "Use current map extent" quick-set, and hero compression when in active search mode.

</domain>

<decisions>
## Implementation Decisions

### Spatial Predicate Toggle
- Add Intersects (default) / Within toggle below the map in the panel
- Small segmented control or radio group
- Note: backend currently only supports bbox with ST_Intersects — the Within option should use ST_Within when applied (or ST_Contains depending on semantics). If backend doesn't support it yet, add it.

### Use Current Map Extent
- Add a "Use current map extent" button that captures the current map viewport bbox
- Low effort, high utility — placed below or near the map

### Hero Compression
- Include in this task — compress hero to compact sticky search bar when in active search mode
- Triggers: query exists, non-default type selected, any filters active, spatial panel open
- Completes the landing → working-surface layout transition

### Panel State Machine (from prior feedback)
- States: empty → drawing → drawn → applied → editing
- Below-map area: selected area summary, clear area action, predicate toggle
- Footer: Clear area / Apply (or Clear / Cancel / Apply)
- Text updates after drawing: "1 area selected" or bbox coordinates
- Mode toggle: add rectangle + polygon icons for scannability

### Active Chip in Main UI
- After apply: show "Area selected" chip in filter bar
- Click chip reopens panel with geometry preserved
- Chip has x to clear spatial filter

</decisions>

<specifics>
## Specific Ideas

- Footer pattern: "Clear area" left-aligned, "Apply" right-aligned (or grouped)
- Area summary: show bbox coordinates or "1 polygon selected" depending on draw mode
- Mode icons: simple rectangle outline icon, polygon outline icon next to text labels
- Hero compact mode: single-row sticky bar with search input + filter controls inline

</specifics>

# Quick Task 260329-rr9: Programmatic widget placement (floating w/anchor or sidebar) - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Task Boundary

Add a programmatic placement option to the widget registration API so widgets can declare whether they render as floating (anchored to a map corner) or in a sidebar panel.

</domain>

<decisions>
## Implementation Decisions

### Placement API Design
- Replace the flat `slot: WidgetSlot` field with a structured `placement` object
- `placement: { mode: 'floating', anchor: WidgetSlot }` for map-corner widgets
- `placement: { mode: 'sidebar', side: 'left' | 'right' }` for sidebar widgets
- Backward-compatible: existing slot-based registrations should still work or be migrated

### Sidebar Behavior
- Sidebar widgets render in a dedicated slide-over panel that overlays the map
- Panel appears on the specified side (left or right)
- Multiple sidebar widgets stack vertically inside the panel
- Panel auto-collapses when all sidebar widgets within it are closed
- Does NOT resize the map — overlay only

### Runtime Switching
- Placement is fixed at registration time by the developer
- Users can toggle widget visibility (on/off) but cannot change placement
- No drag/move or pin-to-sidebar UI needed

</decisions>

<specifics>
## Specific Ideas

- WidgetHost groups widgets by mode first (floating vs sidebar), then by anchor/side
- Sidebar panel component should be a new component (e.g., WidgetSidebar) rendered alongside WidgetHost
- Panel should have smooth open/close animation (slide in/out)
- WidgetPanel wrapper should work in both floating and sidebar contexts

</specifics>

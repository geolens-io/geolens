# Quick Task 260324-o6s: Fix Zoom to Layer in map creator and make sidebar expandable from default size - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Task Boundary

Fix Zoom to Layer in map creator and make sidebar expandable from default size

</domain>

<decisions>
## Implementation Decisions

### Zoom Behavior
- Skip silently when no features/bounds are available — do not show a toast or warning

### Sidebar Resize UX
- Vertical drag handle on the right edge of the sidebar — standard resizable panel pattern

### Sidebar Default Width
- Keep the current default width unchanged — just make it resizable from that starting point

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

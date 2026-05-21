# Quick Task 260320-bbv: Revisit collections filter UX on search page — Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Task Boundary

Revisit how collections are presented as a search option in the search page. Move from button group toggle (where collections is an exclusive record type alongside Vector/Raster/VRT) to a cross-cutting select dropdown filter.

</domain>

<decisions>
## Implementation Decisions

### Filtering Semantics
- Collections become a **cross-cutting filter** (like keywords), not an exclusive record type
- Selecting a collection filters datasets that belong to it, combinable with Vector/Raster/VRT toggles
- Remove "Collections" from the ToggleGroup button group entirely

### Collection Discovery
- Existing dedicated /collections page is sufficient for browsing collections
- No new discovery UI needed — collections are linked from dataset detail pages and the collections page

### Multi-select Behavior
- **Single-select** dropdown — one collection at a time
- Simpler UX, plain select dropdown (not popover with checkboxes like keywords)

### Claude's Discretion
- None — all areas discussed

</decisions>

<specifics>
## Specific Ideas

- Use a standard select dropdown component (not popover/checkbox pattern used by keywords)
- Collection select should show collection name + dataset count
- When a collection is selected, search results show only datasets belonging to that collection
- Collection filter should be clearable

</specifics>

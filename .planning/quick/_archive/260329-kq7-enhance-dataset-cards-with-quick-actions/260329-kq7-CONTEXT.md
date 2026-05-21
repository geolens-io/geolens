# Quick Task 260329-kq7: Enhance Dataset Cards - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Task Boundary

Improve SearchResultCard legibility and visual hierarchy. Focus on helping users quickly understand each dataset — no quick action buttons.

</domain>

<decisions>
## Implementation Decisions

### Quick Actions
- **No quick actions.** User wants the card focused purely on dataset comprehension, not workflow shortcuts. No Download, Preview, Copy, or Favorite buttons.

### Description
- **Claude's Discretion.** Show `properties.description` when available (1-2 lines, truncated). If empty, generate a concise auto-description from metadata (e.g. "MultiPolygon dataset with 258 features in EPSG:4326"). Goal: every card has some descriptive text below the title.

### Metadata vs Tags Styling
- **Icon + plain text for specs.** Drop the pill/chip background for technical metadata (geometry type, feature count, CRS, band count, GSD). Use small inline icons with plain text instead. Reserve the pill/chip style exclusively for keyword tags. This creates a clear visual hierarchy: specs are informational context, tags are searchable categories.

### Layout & Whitespace
- **Larger thumbnail + description.** Increase thumbnail from 80px to ~120px. Add 1-2 line description beside the thumbnail. Tighten vertical spacing between bands to compensate for the added description line.

</decisions>

<specifics>
## Specific Ideas

- Specs row: use lucide icons — e.g. `Hexagon` or `Shapes` for geometry type, `Globe` for CRS, `Hash`/`Layers` for feature/band count, `Ruler` for GSD
- Description should appear between title/source and the specs row
- Thumbnail increase should maintain aspect ratio (square, ~120x120)
- Collections already show description — extend same pattern to datasets
- Source organization line already exists — keep it, description goes below it

</specifics>

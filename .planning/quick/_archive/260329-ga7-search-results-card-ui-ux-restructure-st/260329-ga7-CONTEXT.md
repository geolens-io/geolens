# Quick Task 260329-ga7: Search Results Card UI/UX Restructure - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Task Boundary

Restructure SearchResultCard to use a 4-band layout (header / facts / tags / footer) with stronger visual hierarchy, segmented metadata rows, reduced preview dominance, and deliberate whitespace allocation.

</domain>

<decisions>
## Implementation Decisions

### Preview Sizing
- Shrink from current 140h × 224w (14rem) to 80×80px square
- Aligned top-right within the header zone
- Recovers ~60% of current preview space for content hierarchy
- Keep existing preview types (quicklook, bbox map, fallback icons) — just resize

### Facts vs Tags Visual Split
- Whitespace-only separation: same chip style for both rows
- gap-3 (12px) between the facts row and tags row
- Position alone signals meaning — no different chip variants or section labels

### Footer Content
- Left-aligned: updated time ("Updated 1 hour ago")
- Right-aligned: visibility badge (Public / Internal / Draft)
- No match reason — keep it clean
- Record status badges (Draft, Internal, etc.) move from top badges area to footer visibility position

### Whitespace / Spacing Philosophy
- Consistent gap-3 (12px) between all 4 bands
- No weighted gaps — predictable rhythm throughout
- Keep existing content padding (p-4 sm:p-5)
- The structure itself creates hierarchy, not variable spacing

### Claude's Discretion
- Exact grid template adjustments for the shrunk preview
- Mobile responsive behavior (preview already hidden on mobile — maintain that)
- How to handle collections (no preview, different metadata) within the 4-band model
- Whether to increase max visible tags from 2 to 3 given recovered space

</decisions>

<specifics>
## Specific Ideas

- 4-band structure: header → facts → tags → footer
- Header block: type badge + title + source/collection + preview (80×80 top-right)
- Facts row: geometry, feature count, CRS, band count, GSD, VRT type (record-type dependent)
- Tags row: keywords with overflow indicator
- Footer: update time (left) + visibility (right)
- Card overall should feel "under-structured → well-structured" not "spacious → compressed"

</specifics>

<canonical_refs>
## Canonical References

- Current component: `frontend/src/components/search/SearchResultCard.tsx` (~302 lines)
- Badge component: `frontend/src/components/search/RecordTypeBadge.tsx`
- Status colors: `frontend/src/lib/status-colors.ts`
- Data type: `OGCRecordResponse` in `frontend/src/types/api.ts`

</canonical_refs>

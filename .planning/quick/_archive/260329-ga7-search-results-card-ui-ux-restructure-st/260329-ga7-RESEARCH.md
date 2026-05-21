# Quick Task 260329-ga7: Search Results Card UI/UX Restructure - Research

**Researched:** 2026-03-29
**Domain:** Frontend UI — SearchResultCard component restructure
**Confidence:** HIGH

## Summary

The SearchResultCard component (302 lines) currently uses a 2-column grid layout: left content column with a flex-col gap-3 stack, right preview column (14rem / 224px wide, 140px tall). The restructure moves to a 4-band layout (header / facts / tags / footer) with an 80x80 inline preview instead of a full side column.

**Primary recommendation:** Restructure the inner content div from its current 5-section flex-col into 4 explicit bands, move the preview inline into the header band, and relocate status badges from header to footer.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Preview: shrink from 140h x 224w to 80x80px square, top-right in header zone
- Facts vs Tags: whitespace-only separation (gap-3), same chip style, no section labels
- Footer: left = updated time, right = visibility badge (Public/Internal/Draft); no match reason
- Spacing: consistent gap-3 (12px) between all 4 bands; keep existing p-4 sm:p-5 padding
- Record status badges move from top badges area to footer visibility position

### Claude's Discretion
- Exact grid template for shrunk preview
- Mobile responsive behavior (preview already hidden on mobile — maintain)
- Collection handling within the 4-band model
- Whether to increase max visible tags from 2 to 3
</user_constraints>

## Current Layout Analysis

### Existing Structure (SearchResultCard.tsx)
```
Card
  div.flex-col.md:grid.md:grid-cols-[minmax(0,1fr)_14rem]
    div.p-4.sm:p-5                          ← Content column
      div.flex-col.gap-3                    ← Inner stack
        1. Badges row (status + type + dataset count)
        2. Title block (title + source org / description)
        3. Specs row (geometry, count, CRS as chips)
        4. Keywords row (max 2 + overflow)
        5. Provenance row (updated by + time)
    div.hidden.md:flex (border-l, bg-muted/15, p-4)  ← Preview column
      quicklook | bbox SVG | loader | error | folder icon
```

### Target 4-Band Structure
```
Card
  div.p-4.sm:p-5
    Band 1 — HEADER: [type badge + title + source org] + [80x80 preview top-right]
    Band 2 — FACTS: geometry, feature count, CRS, band count, GSD, VRT type (chips)
    Band 3 — TAGS: keywords with overflow
    Band 4 — FOOTER: updated time (left) | visibility badge (right)
```

## Section-by-Section Mapping

### Band 1: Header
- **Type badge:** Currently in badges row (line 172). Keep `<RecordTypeBadge>` as-is.
- **Title:** Currently `text-lg font-semibold` block (line 183). No change needed.
- **Source org:** Currently below title (line 187-195). Keep as subtitle.
- **Preview:** Move from separate right column into header. Use CSS grid `grid-cols-[1fr_80px]` with preview in second column. On mobile (`md:` breakpoint), hide preview — already the pattern.
- **Collection special case:** Shows FolderOpen icon in preview area; in 4-band model, can show 80x80 icon area or skip preview entirely.

### Band 2: Facts (specs row)
- **Already exists** as `dataset-card-specs` div (line 204-215). Currently uses `buildCardSpecs()` to produce chip array.
- **No structural change needed** — just ensure gap-3 separation from Band 1 above and Band 3 below.
- Collections skip this band (`cardSpecs` is empty for collections).

### Band 3: Tags
- **Already exists** (lines 217-229). Currently shows max 2 keywords + "+N more".
- Consider increasing to 3 given recovered space (Claude's discretion).
- Same chip styling as facts — context decision says "same chip style for both rows."
- Currently tags use `Badge variant="outline"` while specs use custom `span` with similar styling. **Needs harmonization** — both should use the same chip style.

### Band 4: Footer
- **Left side — updated time:** Currently in provenance row (lines 238-262). Simplify to just "Updated {relative time}" — drop "Updated by {identity}" detail per decision ("Updated 1 hour ago").
- **Right side — visibility badge:** `record_status` maps to visibility display (Draft, Internal, etc.). The `record_status` field IS available on `OGCRecordProperties` (line 282 of api.ts). Values: `draft`, `ready`, `internal`, `archived`, `deprecated`, `published` (published = no badge shown).

### Critical Data Model Finding: Visibility vs Record Status
The CONTEXT.md says footer-right shows "Public / Internal / Draft". The `OGCRecordProperties` type has `record_status` (draft/ready/internal/archived/deprecated/published) but does NOT have a `visibility` field (that lives only on the dataset detail type). The status badges currently handle `draft`, `ready`, `internal` — these map directly to the footer visibility concept. For `published` status, show nothing or "Public". This is a direct relocation of the existing status badge logic from Band 1 to Band 4.

## Preview Resize Details

### BBoxPreview (SVG)
- Currently renders with `h-[120px] w-full` in SVG and container `h-[140px]` in card.
- At 80x80, the SVG world map will still work — it uses `viewBox` with `preserveAspectRatio="xMidYMid meet"`. Just needs class change to `h-[80px] w-[80px]`.
- Adaptive viewBox zoom for small extents will still function at 80x80.

### Quicklook Images
- Currently `h-[140px] w-full object-cover`. Change to `h-[80px] w-[80px] object-cover`.
- `object-cover` on a square will crop non-square quicklooks appropriately.
- Loading spinner and error states also use `h-[140px]` — all need 80x80.

### Preview Container
- Currently a separate grid column with `border-l bg-muted/15 p-4`. In new layout, it becomes an inline element in the header band.
- New approach: `rounded-lg overflow-hidden border border-border/40` at 80px square, no background fill needed when inline.

## Collection Handling

Collections currently show:
- FolderOpen icon in preview (140px), dataset count badge, description
- No specs, no keywords, no source org

In 4-band model:
- Band 1: Collection badge + title + description (no preview, or 80x80 FolderOpen icon)
- Band 2: Skip (no specs)
- Band 3: Skip (no keywords)
- Band 4: Updated time only (collections don't have record_status in current rendering)

Recommendation: Hide preview entirely for collections (saves the 80px column). Show dataset count badge inline with type badge in header.

## Test File Impact

**File:** `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` (394 lines)

Tests that will need updates:
1. **`data-testid="dataset-card-specs"`** — Still valid, band 2 keeps this testid.
2. **`data-testid="dataset-card-source"`** — Still valid, stays in band 1.
3. **`data-testid="dataset-card-updated-attribution"`** — Footer simplification changes text from "Updated by {user}" to "Updated {time}". Tests at lines 84-88 check for "Updated by" text — these need updating.
4. **Status badge test** (line 357-363) — Draft badge moves to footer; test still works if querying by text "Draft" but location changes.
5. **Tag overflow test** — If max tags changes from 2 to 3, the "+2 more" assertion (line 273) needs adjustment.

## Chip Style Harmonization

Current inconsistency:
- **Specs chips** (Band 2): `<span>` with `rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground/90`
- **Tag chips** (Band 3): `<Badge variant="outline">` with `border-border/50 bg-background/60 text-xs font-normal text-muted-foreground/85`

Decision says "same chip style for both rows." Recommend using the specs chip style for both (plain `<span>` with consistent classes), since it's more subtle and doesn't carry Badge semantic weight.

## Pitfalls

1. **Preview at 80x80 with rounded corners** — The BBoxPreview SVG at small size may render grid lines as visual noise. Consider hiding grid lines or using a simpler world outline at this size.
2. **Footer visibility badge for "published"** — Most records are published; showing "Public" for every card adds noise. Recommend: only show badge for non-published statuses (draft/internal/ready), matching current behavior where published records show no status badge.
3. **Grid template on mobile** — Preview is hidden on mobile. The header grid should be `grid-cols-1 md:grid-cols-[1fr_80px]` to avoid empty 80px column on small screens.
4. **Collection footer** — Collections don't have `record_status` in current data. Footer should gracefully handle missing status.

## Project Constraints (from CLAUDE.md)

- Prefer simple, readable code over clever abstractions
- Follow existing project conventions
- No AI/Bot activity in commit messages

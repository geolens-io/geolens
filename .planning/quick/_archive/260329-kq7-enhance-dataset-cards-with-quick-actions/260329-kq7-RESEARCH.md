# Quick Task 260329-kq7: Enhance Dataset Cards - Research

**Researched:** 2026-03-29
**Domain:** Frontend UI (SearchResultCard component)
**Confidence:** HIGH

## Summary

All data needed for this task is already available in the frontend types and API responses. The `OGCRecordProperties` type includes `description: string | null` (line 262 of `api.ts`), so no backend changes are needed. The codebase already has a `geometryIcon()` utility in `geo-utils.ts` that maps geometry types to lucide icons, which can be reused for specs. The skeleton component mirrors the card's 4-band layout and needs dimension/structure updates to match.

**Primary recommendation:** Modify `buildCardSpecs` to return structured objects (icon + label) instead of plain strings, update the specs row rendering to use icon+text instead of pill badges, add description display, and increase thumbnail to 120px.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- No quick actions on cards (no Download, Preview, Copy, Favorite buttons)
- Icon + plain text for specs (drop pill/chip background for technical metadata)
- Reserve pill/chip style exclusively for keyword tags
- Larger thumbnail (~120px) + description beside it
- Tighten vertical spacing between bands

### Claude's Discretion
- Description display: show `properties.description` when available (1-2 lines, truncated). If empty, generate auto-description from metadata.

### Deferred Ideas (OUT OF SCOPE)
- None specified
</user_constraints>

## Key Findings

### 1. Description Field Availability

**Confidence: HIGH** -- verified in source code.

`OGCRecordProperties` at `frontend/src/types/api.ts:262` already has:
```typescript
description: string | null;
```

The card already renders description for collections (line 181-184 of `SearchResultCard.tsx`):
```tsx
{isCollection && properties.description && (
  <p className="max-w-3xl text-sm leading-6 text-muted-foreground line-clamp-2">
    {properties.description}
  </p>
)}
```

**Action:** Extend this pattern to all record types. For datasets without a description, generate an auto-description string from available metadata (geometry type, feature count, CRS, band count, etc.).

### 2. Icon Mapping for Specs

The codebase already uses `geometryIcon()` in `frontend/src/lib/geo-utils.ts` which maps geometry types to lucide icons:
- Point/MultiPoint -> `MapPin`
- LineString/MultiLineString -> `Route`
- Polygon -> `Pentagon`
- MultiPolygon -> `Hexagon`

**Recommended icon assignments for all spec types:**

| Spec | Icon | Import | Rationale |
|------|------|--------|-----------|
| Geometry type | `geometryIcon()` result | Already in `geo-utils.ts` | Reuse existing utility |
| CRS | `Globe` | lucide-react | Already used for CRS/geo context throughout codebase |
| Feature count | `Hash` | lucide-react | Numeric count indicator |
| Band count | `Layers` | lucide-react | Already used for vector datasets in RecordTypeBadge |
| GSD | `Ruler` | lucide-react | Already used in MeasurementWidget |
| Source count | `FolderOpen` | lucide-react | Or use `Combine` (already imported in RecordTypeBadge for VRT) |
| VRT type | `Combine` | lucide-react | Already used as VRT icon in RecordTypeBadge |

Note: `Globe`, `Ruler`, `Layers`, `Combine`, `MapPin`, `Route`, `Pentagon`, `Hexagon` are all already imported elsewhere in the codebase -- consistent usage.

### 3. Specs Styling Change

**Current:** Specs use pill/chip styling identical to tags:
```tsx
className="inline-flex items-center rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground/90"
```

**Target:** Plain text with small icon, no background/border:
```tsx
className="inline-flex items-center gap-1 text-xs text-muted-foreground"
```

Tags (Band 3) keep their current pill styling.

### 4. buildCardSpecs Refactor

Current `buildCardSpecs` returns `string[]`. Needs to return structured data:

```typescript
interface CardSpec {
  icon: LucideIcon;
  label: string;
}
```

The `geometryIcon()` function from `geo-utils.ts` returns `LucideIcon | null`, which fits directly. For specs without a geometry-specific icon, assign the fixed icon from the table above.

### 5. Auto-Description Generation

When `properties.description` is null/empty, build from metadata:
- Vector: `"{GeometryType} dataset with {N} features in {CRS}"`
- Raster: `"Raster dataset, {N} bands, {GSD} resolution"`
- VRT: `"{VrtType} virtual raster with {N} sources"`
- Table: `"Table with {N} rows"`

This ensures every card has descriptive text. Use a `buildAutoDescription()` helper.

### 6. Thumbnail Size Change

Current: `80px` hardcoded in 6 places (grid template column, explicit w/h on container and img/fallback elements).

Target: `120px`. Update grid from `md:grid-cols-[1fr_80px]` to `md:grid-cols-[1fr_120px]` and all `h-[80px] w-[80px]` to `h-[120px] w-[120px]`.

### 7. Skeleton Updates Required

`DatasetCardSkeleton.tsx` mirrors the card layout. Changes needed:
- Grid column: `md:grid-cols-[1fr_80px]` -> `md:grid-cols-[1fr_120px]`
- Thumbnail skeleton: `h-[80px] w-[80px]` -> `h-[120px] w-[120px]`
- Add a description skeleton line (thin bar below title/source)
- Specs row: change from rounded-full pill skeletons to shorter inline skeletons (no rounded-full, thinner)
- Consider tightening gap from `gap-3` to `gap-2` to match tighter layout

### 8. i18n Keys

The `search` namespace in `search.json` already has `card.sourceCount` (with `defaultValue` fallback in code). No missing translation keys identified -- specs use existing keys with `defaultValue` fallbacks. The auto-description strings should use translation keys for proper i18n:

New keys needed in `search.json`:
```json
{
  "card": {
    "autoDesc": {
      "vector": "{{geometryType}} dataset with {{count}} features in {{crs}}",
      "raster": "Raster dataset, {{bands}} bands, {{gsd}} resolution",
      "vrt": "{{vrtType}} virtual raster with {{count}} sources",
      "table": "Table with {{count}} rows",
      "fallback": "Geospatial dataset"
    }
  }
}
```

## Common Pitfalls

### Pitfall 1: Icon size consistency
Spec icons should be `size-3` (12px) to match the `text-xs` label text. The badge component uses `[&>svg]:size-3` but specs won't use Badge, so set icon size explicitly.

### Pitfall 2: Separator between specs
With plain text specs (no pill background), items need visual separation. Use a `dot` separator (`\u00B7`) or Tailwind `gap-x-3` with subtle spacing. A dot separator is more readable than relying on gap alone.

### Pitfall 3: Thumbnail aspect ratio on quicklook images
Increasing to 120px may reveal aspect-ratio issues with quicklook images. Keep `object-cover` on the img tag (already present).

## Sources

### Primary (HIGH confidence)
- `frontend/src/types/api.ts` -- OGCRecordProperties type definition
- `frontend/src/components/search/SearchResultCard.tsx` -- current implementation
- `frontend/src/lib/geo-utils.ts` -- existing geometryIcon() utility
- `frontend/src/i18n/locales/en/search.json` -- existing i18n keys

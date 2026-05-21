# Quick Task 260318-81u: Search Page UX Assessment - Research

**Researched:** 2026-03-18
**Domain:** Search page UI components, i18n, filter architecture
**Confidence:** HIGH (all findings from direct codebase inspection)

## Summary

The search page is composed of `SearchPage.tsx` (orchestrator), `FilterPanel.tsx` (filters + type toggles + result count), `DatasetCard.tsx` (dataset results), and `CollectionSearchCard.tsx` (collection results). All user-facing text is in `frontend/src/i18n/locales/en/search.json`. The filter bar is a single flat row on desktop with a ToggleGroup for record types, plus inline filter selects/popovers. Type-aware filter hiding already exists partially (geometry filter hides for raster/VRT types). Badge styling already uses colored variants for VRT (violet) and Raster (emerald) but lacks icons and uses "VRT" text.

**Primary recommendation:** This is a well-scoped UI-only change. Touch i18n strings, DatasetCard badge rendering, CollectionSearchCard layout, FilterPanel row structure, and SearchBar placeholder. No backend changes needed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Secondary row pattern**: Global filters in primary row, type-specific in labeled secondary row when one type selected
- **Global filters**: Type, Location, Time, Keywords, Collection, Status
- **Type-specific**: Vector (geometry type, feature count, CRS), Raster (band count, resolution, CRS), VRT (VRT type, source count, band count, CRS)
- **VRT labeling**: Context-dependent — "Virtual Raster" in primary UI, "VRT" only in dense badges
- **Result card badges**: Icon + colored badge, subtle/muted, soft tint backgrounds
- **Color mapping**: Vector=blue, Raster=green, Virtual Raster=purple, Collection=amber
- **Language fixes**: "datasets found" -> "results", pluralization fixes, "Geometry" rename, tab label pluralization, VRT -> Virtual Raster

### Claude's Discretion
- Exact lucide icon choices
- Exact color hex values (must work light + dark mode)
- Whether to add subtype metadata to cards now or defer
- Exact search placeholder wording

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Current File Map

### Core Components
| File | Role | Lines |
|------|------|-------|
| `frontend/src/pages/SearchPage.tsx` | Page orchestrator, renders hero/search/filters/results/pagination | 117 |
| `frontend/src/components/search/FilterPanel.tsx` | All filters + type toggle + result count (desktop + mobile) | 857 |
| `frontend/src/components/search/DatasetCard.tsx` | Result card for vector/raster/VRT records | 205 |
| `frontend/src/components/search/CollectionSearchCard.tsx` | Result card for collection records | 44 |
| `frontend/src/components/search/SearchBar.tsx` | Search input with typeahead | ~80 |
| `frontend/src/components/search/FilterChip.tsx` | Removable filter pill (Badge + X button) | 25 |
| `frontend/src/stores/search-store.ts` | Zustand store for all search/filter state | 102 |
| `frontend/src/hooks/use-search.ts` | TanStack Query hooks (useSearchResults, useFacets, useCatalogSummary) | 38 |
| `frontend/src/i18n/locales/en/search.json` | All search page English strings | 132 |

### Test Files
| File | Covers |
|------|--------|
| `frontend/src/components/search/__tests__/DatasetCard.test.tsx` | DatasetCard rendering |
| `frontend/src/components/search/__tests__/FilterPanel.test.tsx` | FilterPanel rendering |
| `frontend/src/components/search/__tests__/CollectionSearchCard.test.tsx` | CollectionSearchCard |
| `frontend/src/components/search/__tests__/SearchBar.test.tsx` | SearchBar |

## Language & Label Findings

### Issues Found

| Issue | Location | Current Text | Fix |
|-------|----------|-------------|-----|
| "datasets found" count | `search.json` L41-42 | `"datasetCount_one": "{{count}} dataset found"` / `"datasetCount_other": "{{count}} datasets found"` | Change to "result" / "results" |
| "No datasets found" empty | `search.json` L10 | `"title": "No datasets found"` | Change to "No results found" |
| Search placeholder | `search.json` L3 | `"Search datasets by name, description, tags..."` | More inclusive wording |
| "VRT" filter label | `search.json` L47, FilterPanel L352/619 | `"vrt": "VRT"` | Change to `"Virtual Raster"` |
| "VRT" card badge | DatasetCard L117 | `t('card.vrt', { defaultValue: 'VRT' })` | Change to "Virtual Raster" (or keep "VRT" in card — it's a dense badge context per CONTEXT.md) |
| "Collection" singular tab | FilterPanel L357 | `t('filters.collection', { defaultValue: 'Collection' })` | The i18n key is singular and used for both tab label and count display. Tab shows "Collection (3)" — should be "Collections (3)" when count > 1. Need separate key or pluralized key. |
| "Geometry" filter label | `search.json` L18 | `"geometry": "Geometry"` | Rename to "Geometry Type" or make type-aware. Under new architecture, this moves to vector-specific secondary row. |
| Band count pluralization | DatasetCard L130 | `defaultValue: '{{count}} bands'` — no `_one`/`_other` keys in search.json | Add `card.bandCount_one` and `card.bandCount_other` to search.json |
| Sheet description | FilterPanel L587 | `"Refine the dataset list without leaving the search page."` | Update to "Refine results..." |

### i18n Keys Needing Changes
```json
{
  "filters.datasetCount_one": "{{count}} result",
  "filters.datasetCount_other": "{{count}} results",
  "filters.vrt": "Virtual Raster",
  "card.vrt": "Virtual Raster",
  "card.bandCount_one": "{{count}} band",
  "card.bandCount_other": "{{count}} bands",
  "empty.title": "No results found",
  "placeholder": "Search geospatial data...",
  "filters.sheetDescription": "Refine results without leaving the search page."
}
```

Note: `"Collection"` tab label needs pluralization — either a new `filters.collection_other` key or separate `filters.collectionTab` key. The ToggleGroup currently uses `filters.collection` for both the toggle label and chip label.

## Current Filter Architecture

### Desktop Layout (single row)
```
[All (18)] [Vector (10)] [Raster (5)] [VRT (0)] [Collection (3)] | Keywords▾ | Geometry▾ | Org▾ | CRS▾ | Location▾ | Upload Date▾ | Temporal▾ | Sort▾ | Clear | Save | "18 datasets found"
```

All filters are in one `flex-wrap` row. No secondary row exists.

### Type-Aware Hiding (already partial)
- `geometry_type` filter hidden when `recordType === 'raster_dataset' || 'vrt_dataset' || 'collection'` (FilterPanel L381)
- All other filters (org, CRS, location, date, temporal) always visible regardless of type

### Mobile Layout
- Compact: result count + "Filters" button (with badge count)
- Filters open in a bottom Sheet with all controls stacked vertically
- Active filters shown as FilterChip pills below the count

### Search Store State
The store already has `record_type` as a string (single-select). No multi-select type filtering exists — the ToggleGroup is `type="single"`. This means the secondary-row logic is simpler: check `record_type` value, show corresponding filters.

### New Secondary Row Architecture

The planner should structure FilterPanel as:
1. **Primary row**: Type ToggleGroup, Keywords, Location, Upload Date, Temporal Extent, Sort, Clear, Save, Count
2. **Secondary row** (conditional): Appears below primary when exactly one non-"all" type is selected
   - Vector: Geometry Type, Feature Count range(?), CRS
   - Raster: Band Count, Resolution/GSD, CRS
   - VRT: VRT Type, Source Count, Band Count, CRS
   - Collection: (none currently — could add item count range)

Note: Organization and CRS are currently global filters. Per CONTEXT.md, CRS moves to type-specific. Organization stays global but isn't listed in CONTEXT.md global list — planner should decide (keep global or drop).

### Backend Filter Support
The search API (`/search/datasets`) currently supports: `q`, `bbox`, `keywords`, `geometry_type`, `srid`, `source_organization`, `record_type`, `datetime`, `date_from`, `date_to`, `sort_by`, `offset`, `limit`.

**Missing backend filters for type-specific secondary row:**
- `band_count` range — NOT in search API
- `resolution`/`gsd` range — NOT in search API
- `feature_count` range — NOT in search API
- `vrt_type` — NOT in search API
- `source_count` — NOT in search API

These are display-only on cards (from the OGC record properties). The planner should either: (a) defer these filters as UI-only labels on the secondary row, (b) add backend filter support, or (c) scope secondary row to only CRS + Geometry Type (which already have backend support).

## Result Card Type Badge Architecture

### Current Badge Rendering (DatasetCard)
```tsx
{isVrt ? (
  <Badge variant="secondary" className="text-xs bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
    VRT
  </Badge>
) : isRaster ? (
  <Badge variant="secondary" className="text-xs bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
    Raster
  </Badge>
) : properties.geometry_type ? (
  <Badge variant="secondary" className="text-xs">
    {getGeometryTypeLabel(t, properties.geometry_type)}
  </Badge>
) : null}
```

**Observations:**
- VRT already has violet coloring, Raster already has emerald/green
- Vector has no color — just default secondary badge showing geometry type
- No icons on any badges
- The geometry type label replaces the type badge for vectors (shows "Polygon" instead of "Vector")
- Collection cards (`CollectionSearchCard`) have a separate component with no colored type badge

### Proposed Badge Pattern
A reusable `RecordTypeBadge` component:
```tsx
// Lucide icons: Layers (vector), Grid3X3 (raster), Layers+Grid (VRT), FolderOpen (collection)
<Badge variant="secondary" className={colorClasses[recordType]}>
  <Icon className="size-3" />
  {label}
</Badge>
```

Color scheme already in use:
- **Raster**: `bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400`
- **VRT**: `bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400`
- **Vector** (new): `bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400`
- **Collection** (new): `bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400`

### Available Metadata on Search Results

| Field | Available in search results? | Type |
|-------|-----|------|
| `record_type` | Yes | string |
| `geometry_type` | Yes | string or null |
| `feature_count` | Yes | number or null |
| `band_count` | Yes (for raster/VRT) | number or null |
| `crs` | Yes | string like "EPSG:4326" or null |
| `res_x` / `res_y` | Yes (as `gsd` in STAC properties) but NOT typed in frontend `OGCRecordProperties` | number |
| `epsg` | Yes (as `proj:epsg`) but NOT typed in frontend | number |
| `vrt_type` | NO — only in detail response | - |
| `source_count` | NO — only in detail response | - |

**Implication for card metadata:** Can show geometry type, feature count, band count, CRS on cards. Cannot show VRT type or source count without backend changes or an additional API call.

## Available UI Primitives

| Component | Path | Notes |
|-----------|------|-------|
| `Badge` | `components/ui/badge.tsx` | CVA variants: default, secondary, destructive, outline, ghost, link. Supports className overrides for custom colors. |
| `FilterChip` | `components/search/FilterChip.tsx` | Badge + X button. Used for active filter pills. |
| `ToggleGroup` | `components/ui/toggle-group.tsx` | radix-ui. Used for type selector. Single or multi select. |
| Lucide icons | `lucide-react` | Project standard. Available: `Layers`, `Grid3X3`, `FolderOpen`, `Box`, `Map` etc. |

## Common Pitfalls

### Pitfall 1: ToggleGroup "Collection" pluralization
The current code uses `t('filters.collection')` for both the toggle item label and filter chip. A toggle with count "Collection (3)" reads oddly. However, since it's a filter button (not a heading), "Collection" as a category name is acceptable. The assessment called this out — planner should decide if this is worth a separate i18n key or if "Collections" always is fine.

### Pitfall 2: Secondary row on mobile
The mobile filter Sheet already stacks everything vertically. Adding a secondary row concept on mobile means either: (a) visually grouping type-specific filters under a label in the sheet, or (b) showing/hiding sections. Option (a) is simpler and matches the Sheet's existing structure.

### Pitfall 3: Type badge in CollectionSearchCard
`CollectionSearchCard` is a completely separate component from `DatasetCard`. The type badge must be added there too, or better yet, extract `RecordTypeBadge` as a shared component.

### Pitfall 4: Test breakage
Existing tests (`DatasetCard.test.tsx`, `FilterPanel.test.tsx`, `CollectionSearchCard.test.tsx`) assert on current text like "VRT", "datasets found", etc. All tests need updating alongside i18n changes.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest + React Testing Library |
| Config file | `frontend/vitest.config.ts` |
| Quick run command | `cd frontend && npx vitest run --reporter=verbose` |
| Full suite command | `cd frontend && npx vitest run` |

### Key Test Files to Update
| File | What Changes |
|------|-------------|
| `__tests__/DatasetCard.test.tsx` | Badge text ("VRT" -> "Virtual Raster"), badge icon assertions, type badge for vectors |
| `__tests__/FilterPanel.test.tsx` | "datasets found" -> "results", "VRT" -> "Virtual Raster", secondary row rendering |
| `__tests__/CollectionSearchCard.test.tsx` | Collection type badge with icon+color |
| `__tests__/SearchBar.test.tsx` | Placeholder text change |

## Sources

All findings from direct codebase inspection (HIGH confidence). No external research needed — this is a UI-only task within existing components.

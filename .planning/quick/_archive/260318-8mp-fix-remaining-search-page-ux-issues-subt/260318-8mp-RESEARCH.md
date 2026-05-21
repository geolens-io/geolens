# Quick Task: Fix Remaining Search Page UX Issues - Research

**Researched:** 2026-03-18
**Domain:** Frontend search UX (React, i18n, API integration)
**Confidence:** HIGH

## Summary

Five discrete UX issues on the search page, all traceable to specific files and lines. The most architecturally significant is the count inconsistency between tabs and results, which stems from facets counting collections separately from the Dataset table while the search endpoint only queries datasets.

## Issue 1: Subtitle Language

**File:** `frontend/src/i18n/locales/en/search.json`, line 3
**Key:** `subtitle`
**Current value:** `"Search, preview, and export datasets from the catalog"`

**Problem:** Says "datasets" but the catalog now includes collections, raster datasets, and VRTs. The subtitle should reflect the broader record types.

**Fix:** Change to something like `"Search, preview, and export geospatial data from the catalog"` or `"Discover and explore geospatial data in the catalog"`. Update all locale files (en, de, es, fr).

**Rendered at:** `frontend/src/pages/SearchPage.tsx`, line 36 (`{t('subtitle')}`)

## Issue 2: Tab Pluralization - "Collection" should be "Collections"

**File:** `frontend/src/components/search/FilterPanel.tsx`, lines 357-359 (desktop) and 637-639 (mobile)
**Key:** `filters.collection` in `en/search.json` line 53

**Current code (desktop, line 357-359):**
```tsx
<ToggleGroupItem value="collection" className="text-xs px-2.5 h-7">
  {t('filters.collection', { defaultValue: 'Collection' })} ({counts.collection})
</ToggleGroupItem>
```

**Problem:** The i18n key `filters.collection` is `"Collection"` (singular). When used as a tab label showing a count like "(2)", it should be plural: "Collections (2)".

**Fix options:**
1. Simple: Add a `filters.collections` key (plural) = `"Collections"` and use it for the tab label. The singular form is used elsewhere (e.g., filter chips) where singular is correct.
2. Alternative: Just hardcode the tab label to use plural since a tab always represents a category.

**Also update:** Mobile toggle at line 637-639 with same fix.

## Issue 3: Count Inconsistency (CRITICAL)

### Architecture

- **Tab counts** come from `/search/facets` endpoint via `useFacets()` hook (`frontend/src/hooks/use-search.ts`, line 17-29)
- **"X results" text** comes from `data.numberMatched` returned by `/search/datasets` endpoint via `useSearchResults()` hook (line 6-15)
- The facets hook **strips `record_type`** from params (line 21) so facet counts always show totals across all types

### "All" tab shows 148 but results show "146 results"

**Root cause:** The "All" tab count is computed at `FilterPanel.tsx` line 342:
```tsx
Object.values(counts).reduce((a, b) => a + b, 0)
```
This sums ALL facet counts including `counts.collection` (e.g., 2 collections). But `numberMatched` from `/search/datasets` only counts Dataset table rows (146 datasets). Collections are **appended** to results on the first page (router.py lines 209-235) but are NOT included in `numberMatched`/`total`.

So: 146 datasets + 2 collections = 148 in facets, but `numberMatched` = 146.

**Fix:** The "All" tab total should exclude collections: sum only dataset record_type counts (vector_dataset + raster_dataset + vrt_dataset). Or better: use `numberMatched` for the results count text and keep facet totals for tabs but exclude collection from the "All" sum.

### "Collection" tab shows (2) but results show "0 results"

**Root cause:** When user clicks the Collection tab, `record_type=collection` is sent to `/search/datasets`. The search service queries the **Dataset** table with `Record.record_type == 'collection'` (service.py line 645-646). But collections live in a **separate `Collection` table**, not in the Dataset table. No datasets have `record_type='collection'`, so the result is 0.

Collections are only appended as bonus results when a text query is active AND offset=0 (router.py lines 209-211). The `record_type` filter blocks this path because it filters at the dataset level before collection appending.

**Fix options:**
1. **Remove the Collection tab entirely** from the type toggle. Collection results already appear automatically when text searching. The tab is misleading because it implies a filterable type.
2. **Route collection tab to a separate API call** that queries the Collection table. This is more work and may be overkill.
3. **Add collection search to the main search path** when `record_type=collection` -- instead of querying datasets, query collections directly and return them as features with the correct `numberMatched`.

**Recommendation:** Option 1 (remove tab) is simplest and avoids user confusion. Collections already surface in search results. If the tab must stay, option 3 requires backend changes.

## Issue 4: Empty Secondary Filter Rows

**File:** `frontend/src/components/search/FilterPanel.tsx`, lines 476-582

**Current behavior:** The secondary filter row renders when `recordType && recordType !== 'collection'` (line 476). It shows:
- A label like "Raster filters" or "Virtual Raster filters"
- Geometry type dropdown: only for `vector_dataset` (line 487)
- Organization dropdown: only if `organizations.length > 0` (line 520)
- CRS dropdown: only if `srids.length > 0` (line 551)

**Problem:** When Raster or VRT is selected AND the catalog has no organizations/SRIDs populated, the row shows just the label "Raster filters" with nothing else. This is confusing empty UI.

**Why org/CRS might be empty:** These come from `useCatalogSummary()` which fetches `/collections/datasets` (search.ts line 34-36). The summaries may not include org/srid data for raster/VRT types if the catalog summary aggregation doesn't cover them.

**Fix:** Hide the secondary filter row entirely when there are no type-specific filters to show. The condition should be:
```tsx
{recordType === 'vector_dataset' && (
  <div className="secondary-row">
    {/* geometry + org + crs filters */}
  </div>
)}
{(recordType === 'raster_dataset' || recordType === 'vrt_dataset') && (organizations.length > 0 || srids.length > 0) && (
  <div className="secondary-row">
    {/* org + crs filters only */}
  </div>
)}
```

Or simpler: only show the row when at least one filter control would render inside it.

## Issue 5: "Upload Date" Label

**File:** `frontend/src/i18n/locales/en/search.json`, line 32
**Key:** `filters.dateRange`
**Current value:** `"Upload Date"`

**Used at:** `FilterPanel.tsx` line 167 (desktop popover button) and line 770 (mobile section label)

**Problem:** "Upload Date" is imprecise -- it actually filters on `created_at` which is the date the record was created/ingested. "Date Added" is already used for the sort option (`filters.dateAdded` on line 28). The filter and sort should use consistent language.

**Fix:** Change `filters.dateRange` to `"Date Added"` to match the sort option terminology. Update all locale files.

## Files to Modify

| File | Changes |
|------|---------|
| `frontend/src/i18n/locales/en/search.json` | Update `subtitle`, `filters.dateRange`; add `filters.collections` (plural) |
| `frontend/src/i18n/locales/de/search.json` | Same keys |
| `frontend/src/i18n/locales/es/search.json` | Same keys |
| `frontend/src/i18n/locales/fr/search.json` | Same keys |
| `frontend/src/components/search/FilterPanel.tsx` | Fix tab plural, fix "All" count to exclude collections, remove or fix Collection tab, hide empty secondary rows |

## Sources

- `frontend/src/pages/SearchPage.tsx` - Main page component
- `frontend/src/components/search/FilterPanel.tsx` - All filter/tab logic
- `frontend/src/i18n/locales/en/search.json` - English translations
- `frontend/src/hooks/use-search.ts` - Search and facet hooks
- `frontend/src/api/search.ts` - API client functions
- `frontend/src/stores/search-store.ts` - Search state management
- `backend/app/search/service.py` - Facet counting (lines 167-309) and search (lines 488+)
- `backend/app/search/router.py` - Search endpoint with collection appending (lines 73-271)

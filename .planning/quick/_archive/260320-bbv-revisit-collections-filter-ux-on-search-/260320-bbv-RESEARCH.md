# Quick Task 260320-bbv: Collections Filter UX - Research

**Researched:** 2026-03-20
**Domain:** Search filter panel, collection filtering
**Confidence:** HIGH

## Summary

The current search page treats "Collections" as an exclusive record type in a ToggleGroup alongside Vector/Raster/VRT. When selected, it branches to a completely separate search path (`search_collections`) that queries the `catalog.collections` table directly. The task is to remove "Collections" from the ToggleGroup and add a cross-cutting collection dropdown filter that narrows dataset results to those belonging to a specific collection.

The backend `search_datasets` function does NOT currently support a `collection_id` filter parameter. A new filter clause joining through `CollectionDataset` is needed. The frontend needs a new `collection_id` state field in the search store, a Select dropdown in the FilterPanel, and a way to fetch available collections for the dropdown options.

**Primary recommendation:** Add `collection_id` param to backend search + facets, add collection Select dropdown to FilterPanel using existing `<Select>` component pattern, remove "collection" from ToggleGroup.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Collections become a **cross-cutting filter** (like keywords), not an exclusive record type
- Selecting a collection filters datasets that belong to it, combinable with Vector/Raster/VRT toggles
- Remove "Collections" from the ToggleGroup button group entirely
- **Single-select** dropdown -- one collection at a time
- Use a standard select dropdown component (not popover/checkbox pattern used by keywords)
- Collection select should show collection name + dataset count
- When a collection is selected, search results show only datasets belonging to that collection
- Collection filter should be clearable
- Existing dedicated /collections page is sufficient for browsing collections
- No new discovery UI needed

### Claude's Discretion
- None -- all areas discussed

### Deferred Ideas
- None specified
</user_constraints>

## Current Architecture

### ToggleGroup (record_type filter)
**File:** `frontend/src/components/search/FilterPanel.tsx` (lines 347-375 desktop, 633-661 mobile)

The ToggleGroup is `type="single"` with values: `all`, `vector_dataset`, `raster_dataset`, `vrt_dataset`, `collection`. Each item shows facet counts from `facets?.record_type`. The "All" count sums all four types including `collection`.

When `record_type === "collection"`, the router (`backend/app/search/router.py:138-169`) takes a **completely separate code path** -- it calls `search_collections()` which queries the `catalog.collections` table directly and returns collection-shaped features. This means collections are NOT datasets and never go through `search_datasets()`.

### Search Store State
**File:** `frontend/src/stores/search-store.ts`

The store has a `record_type: string` field. `setFilter(key, value)` is generic. `toParams()` serializes all non-empty values to URL params. `resetFilters()` resets to `initialState`. `restoreParams()` hydrates from URL params (used by saved searches).

### Backend Search
**File:** `backend/app/search/service.py`

- `search_datasets()` (line 517): Accepts `record_type` param, filters via `Record.record_type == record_type` (line 678-679). Does NOT have a `collection_id` parameter.
- `get_facet_counts()` (line 167): Returns `record_type` counts (grouped by `Record.record_type`), then separately counts collections from the `Collection` table (lines 312-324). Also does NOT support `collection_id`.
- `search_collections()` (line 458): Standalone function querying `Collection` table with text search, returns `[{id, name, description, dataset_count, created_at}]`.

### Collection Model
**File:** `backend/app/collections/models.py`

- `Collection` table: `catalog.collections` (id, name, description, created_by, created_at, updated_at)
- `CollectionDataset` join table: `catalog.collection_datasets` (collection_id, dataset_id, added_at, added_by, sort_order)

A dataset can belong to multiple collections. The join is `CollectionDataset.dataset_id -> Dataset.id`.

### Existing Select Component
**File:** `frontend/src/components/ui/select.tsx` (shadcn/radix)

Already imported and used extensively in FilterPanel for geometry type, organization, CRS, and sort dropdowns. Pattern: `<Select value={} onValueChange={}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem>...</SelectItem></SelectContent></Select>`.

### Facets API
**File:** `frontend/src/api/search.ts` + `frontend/src/hooks/use-search.ts`

`useFacets()` calls `/search/facets` with all search params except `record_type`. Returns `{ record_type, keywords, source_organization, srid }`. Currently does NOT include collection facets.

### Collections List API
**File:** `backend/app/collections/router.py:174`

`GET /catalog/collections/` returns all collections with dataset_count. Requires auth. This endpoint could be used to populate the dropdown, but it's behind auth and heavier than needed (computes spatial extent per collection).

## Changes Required

### Backend

1. **Add `collection_id` param to `search_datasets()`** (service.py line 517):
   - New param: `collection_id: uuid_mod.UUID | None = None`
   - Filter: `stmt = stmt.where(exists(select(CollectionDataset.dataset_id).where(CollectionDataset.dataset_id == Dataset.id, CollectionDataset.collection_id == collection_id)))`

2. **Add `collection_id` param to `get_facet_counts()`** (service.py line 167):
   - Same join filter as above so facets reflect the collection constraint

3. **Add `collection_id` query param to router** (router.py `_handle_search`):
   - New param: `collection_id: uuid.UUID | None = Query(None)`
   - Pass through to `search_datasets()` and `get_facet_counts()`

4. **Add collection facet data to facets response** (or use separate endpoint):
   - Option A: Add `collections` key to facets response with `[{id, name, dataset_count}]` -- lightweight, reuses `search_collections()` logic
   - Option B: Add a new lightweight endpoint `GET /search/collection-options` that returns `[{id, name, dataset_count}]`
   - **Recommendation:** Option A -- add a `collections` key to facets response. Reuse `search_collections(session, "", user, user_roles, limit=100)` to get all collections with counts. This avoids a separate API call.

5. **Remove collection-only search branch** (router.py lines 138-169):
   - The `if record_type == "collection"` branch can be removed since collections are no longer a record_type filter value. However, consider keeping it for backward compatibility or remove it if no other consumer uses it.

### Frontend

1. **Search store** (`search-store.ts`):
   - Add `collection_id: string` to `SearchState` and `initialState` (empty string = no filter)
   - Add to `toParams()`: `if (state.collection_id) params.collection_id = state.collection_id`
   - Add to `restoreParams()`: `collection_id: params.collection_id || ''`

2. **FilterPanel** (`FilterPanel.tsx`):
   - Remove `collection` ToggleGroupItem from both desktop (line 371-374) and mobile (line 657-660)
   - Update "All" count to exclude `counts.collection` (line 357, 643)
   - Add collection Select dropdown (position: after ToggleGroup, before keywords)
   - Fetch collections for dropdown options from facets data (new `collections` key)
   - Show as FilterChip when active, Select when inactive (same pattern as organization/CRS)
   - Add `collection_id` to `hasActiveFilters` check
   - Add `collection_id` to `activeFilterCount`
   - Add FilterChip for active collection in mobile chip row

3. **Facets hook** (`use-search.ts`):
   - Also exclude `collection_id` from facet params (like `record_type`) so collection facets show counts for all collections regardless of selection. Actually -- this depends on desired behavior. If user selects a collection, they probably want facets to reflect that filter. Keep `collection_id` in facet params.

4. **API types** (`types/api.ts`):
   - Update `FacetResponse` type to include `collections?: Array<{id: string, name: string, dataset_count: number}>`

### "All" Count Fix

Currently "All" count includes `counts.collection`. After removing collections from the ToggleGroup, the "All" count should only sum `vector_dataset + raster_dataset + vrt_dataset`. The facets API still returns `collection` in `record_type` counts -- that's fine, just don't display it in the ToggleGroup.

### Secondary Filter Row

The secondary filter row (line 492-603) is hidden when `recordType === 'collection'`. After this change, that condition is irrelevant since `recordType` will never be `'collection'`. Remove the `recordType !== 'collection'` check.

## Common Pitfalls

### Pitfall 1: Facet double-request
Adding collections to facets response means every facet call also queries collections. Keep it lightweight -- just name + count, no extent computation.

### Pitfall 2: Empty collection dropdown
If no collections exist, the dropdown should not render at all (same pattern as organization/CRS filters which check `organizations.length > 0`).

### Pitfall 3: Collection filter + record_type interaction
When a collection is selected AND a record_type toggle is active (e.g., "Vector"), results should show only vector datasets in that collection. The backend must apply BOTH filters. This works naturally with the proposed implementation since they're independent WHERE clauses.

### Pitfall 4: Mobile filter sheet
The mobile sheet has its own ToggleGroup copy. Must remove "Collections" from there too and add the collection Select dropdown.

### Pitfall 5: Saved search serialization
The `toParams()`/`restoreParams()` must handle `collection_id` for saved searches to work correctly with the new filter.

## Sources

### Primary (HIGH confidence)
- `frontend/src/components/search/FilterPanel.tsx` -- current filter panel implementation
- `frontend/src/stores/search-store.ts` -- search state management
- `backend/app/search/service.py` -- search and facet service
- `backend/app/search/router.py` -- search API endpoints
- `backend/app/collections/models.py` -- Collection/CollectionDataset models

## Metadata

**Confidence breakdown:**
- Architecture: HIGH -- all code paths traced through source
- Backend changes: HIGH -- clear pattern from existing filters
- Frontend changes: HIGH -- existing Select pattern to follow

**Research date:** 2026-03-20
**Valid until:** 2026-04-20

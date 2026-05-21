---
phase: 260318-mhz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/search/router.py
  - backend/app/search/service.py
  - frontend/src/types/api.ts
  - frontend/src/hooks/use-quicklook.ts
  - frontend/src/components/search/SearchResultCard.tsx
  - frontend/src/components/search/DatasetCard.tsx
  - frontend/src/components/search/CollectionSearchCard.tsx
  - frontend/src/components/search/DatasetCardSkeleton.tsx
  - frontend/src/components/search/FilterPanel.tsx
  - frontend/src/pages/SearchPage.tsx
  - frontend/src/components/search/__tests__/SearchResultCard.test.tsx
  - frontend/src/components/search/__tests__/DatasetCard.test.tsx
  - frontend/src/components/search/__tests__/CollectionSearchCard.test.tsx
autonomous: true
requirements: [CARD-OVERHAUL]

must_haves:
  truths:
    - "All record types (vector, raster, VRT, collection) render through a single unified card component"
    - "Each type shows type-specific metadata (geometry/count for vector, bands/resolution for raster, vrt_type/source_count for VRT, dataset_count for collection)"
    - "Cards have 2-column layout: content left, preview right (hidden on mobile)"
    - "VRT cards show vrt_type (Mosaic/Band Stack) and source_count from API"
    - "Collection cards match the unified card layout instead of the minimal row format"
    - "Filter panel secondary row does not show for collection type"
    - "Type badges use correct colors: blue=vector, emerald=raster, violet=VRT, amber=collection"
  artifacts:
    - path: "frontend/src/hooks/use-quicklook.ts"
      provides: "Extracted quicklook fetch hook with blob URL lifecycle management"
      exports: ["useQuicklook"]
    - path: "frontend/src/components/search/SearchResultCard.tsx"
      provides: "Unified card component for all record types"
      exports: ["SearchResultCard"]
    - path: "frontend/src/types/api.ts"
      provides: "Updated OGCRecordProperties with dataset_count, vrt_type, source_count, gsd"
      contains: "dataset_count"
    - path: "backend/app/search/router.py"
      provides: "VRT fields (vrt_type, source_count) in search response"
      contains: "vrt_type"
  key_links:
    - from: "frontend/src/components/search/SearchResultCard.tsx"
      to: "frontend/src/hooks/use-quicklook.ts"
      via: "useQuicklook hook call"
      pattern: "useQuicklook"
    - from: "frontend/src/pages/SearchPage.tsx"
      to: "frontend/src/components/search/SearchResultCard.tsx"
      via: "rendering all feature types through SearchResultCard"
      pattern: "SearchResultCard"
    - from: "backend/app/search/router.py"
      to: "backend/app/raster/models.py"
      via: "RasterAsset.vrt_type and VrtGeneration.source_count in bulk query"
      pattern: "vrt_type"
---

<objective>
Overhaul search result cards into a unified card system where all record types (vector, raster, VRT, collection) render through one shared component with type-specific metadata slots.

Purpose: Eliminate the visual mismatch between DatasetCard and CollectionSearchCard, add VRT-specific metadata (vrt_type, source_count) from the API, and create consistent 2-column card layout across all types.

Output: Single SearchResultCard component, useQuicklook hook, backend VRT field enrichment, updated types, filter panel bug fix.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@frontend/src/components/search/DatasetCard.tsx
@frontend/src/components/search/CollectionSearchCard.tsx
@frontend/src/components/search/RecordTypeBadge.tsx
@frontend/src/components/search/DatasetCardSkeleton.tsx
@frontend/src/components/search/FilterPanel.tsx
@frontend/src/pages/SearchPage.tsx
@frontend/src/types/api.ts
@backend/app/search/router.py
@backend/app/search/service.py
@backend/app/raster/models.py

<interfaces>
<!-- Key types the executor needs -->

From frontend/src/types/api.ts:
```typescript
export interface OGCRecordProperties {
  type: string;
  title: string;
  description: string | null;
  keywords: string[] | null;
  created: string | null;
  updated: string | null;
  updated_by_display: string | null;
  never_edited: boolean;
  crs: string | null;
  geometry_type: string | null;
  feature_count: number | null;
  contact: Record<string, unknown> | null;
  license: string | null;
  source_organization: string | null;
  quality_detail?: { overall: number; /* ... */ } | null;
  record_status?: string | null;
  record_type?: string;
  band_count?: number | null;
  epsg?: number | null;
  res_x?: number | null;
  res_y?: number | null;
  width?: number | null;
  height?: number | null;
  dtype?: string | null;
  nodata?: string | null;
  // MISSING: dataset_count, vrt_type, source_count, gsd
}

export interface OGCRecordResponse {
  type: "Feature";
  id: string;
  geometry: Geometry | null;
  properties: OGCRecordProperties;
  links: OGCRecordLink[];
}
```

From backend/app/raster/models.py:
```python
class RasterAsset:
    vrt_type: str | None  # 'mosaic' or 'band_stack'
    resolution_strategy: str | None

class VrtGeneration:
    source_count: int | None
```

From backend/app/search/router.py (lines 226-252):
```python
# Bulk raster metadata query — currently selects band_count, epsg, res_x, res_y,
# width, height, dtype, nodata, band_info. Does NOT select vrt_type or resolution_strategy.
# source_count is on VrtGeneration, not RasterAsset.
```

Collection feature shape from backend (lines 267-289):
```python
{
    "type": "Feature",
    "id": coll["id"],
    "geometry": None,
    "properties": {
        "type": "collection",
        "title": coll["name"],
        "description": coll["description"],
        "record_type": "collection",
        "dataset_count": coll["dataset_count"],
        "created": coll["created_at"],
    },
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend VRT fields + TypeScript type updates</name>
  <files>
    backend/app/search/router.py
    backend/app/search/service.py
    frontend/src/types/api.ts
  </files>
  <action>
**Backend — Add vrt_type and source_count to search response:**

1. In `backend/app/search/router.py` lines 226-252 (bulk raster metadata query), add `RasterAsset.vrt_type` and `RasterAsset.resolution_strategy` to the select columns. In the dict builder (line 242), add:
   - `"vrt_type": row.vrt_type`
   - `"resolution_strategy": row.resolution_strategy`

2. For `source_count`: after the raster_meta bulk query, add a second bulk query for VRT datasets only. Query `VrtGeneration` table for the current generation's `source_count` for each VRT dataset_id. Use `RasterAsset.current_generation_id` to join. Merge `source_count` into the `raster_meta` dict for VRT records. Pattern:
   ```python
   vrt_ids = [did for did in raster_ids if ...]  # filter to VRT only
   # Actually simpler: just query VrtGeneration where dataset_id matches and use RasterAsset.current_generation_id
   ```
   Simplest approach: after building raster_meta, for VRT datasets, do a second query:
   ```python
   from app.raster.models import VrtGeneration
   vrt_dataset_ids = [did for did in raster_ids if raster_meta.get(str(did), {}).get("vrt_type") is not None]
   if vrt_dataset_ids:
       vg_stmt = select(
           RasterAsset.dataset_id,
           VrtGeneration.source_count,
       ).join(VrtGeneration, VrtGeneration.id == RasterAsset.current_generation_id
       ).where(RasterAsset.dataset_id.in_(vrt_dataset_ids))
       vg_result = await db.execute(vg_stmt)
       for row in vg_result.all():
           if str(row.dataset_id) in raster_meta:
               raster_meta[str(row.dataset_id)]["source_count"] = row.source_count
   ```

3. In `backend/app/search/service.py` `dataset_to_ogc_record` function (around line 1117), after the existing raster_meta enrichment block, add for VRT records:
   ```python
   if raster_meta.get("vrt_type"):
       ogc_record["properties"]["vrt_type"] = raster_meta["vrt_type"]
   if raster_meta.get("source_count") is not None:
       ogc_record["properties"]["source_count"] = raster_meta["source_count"]
   ```

4. Also apply the same vrt_type/source_count enrichment to the single-item endpoint (around line 1033-1070 in router.py) — add `RasterAsset.vrt_type`, `RasterAsset.resolution_strategy` to the select, and a VrtGeneration subquery for source_count.

**Frontend — Update OGCRecordProperties type:**

5. In `frontend/src/types/api.ts`, add to `OGCRecordProperties`:
   - `dataset_count?: number;` (for collections — already sent by backend)
   - `vrt_type?: string | null;` (for VRT — 'mosaic' | 'band_stack')
   - `source_count?: number | null;` (for VRT)
   - `gsd?: number | null;` (for raster/VRT — already sent by backend via `gsd` key)
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T api python -c "from app.search.service import dataset_to_ogc_record; print('OK')" && cd frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - OGCRecordProperties includes dataset_count, vrt_type, source_count, gsd fields
    - Backend search response includes vrt_type and source_count for VRT records
    - TypeScript compiles without errors
  </done>
</task>

<task type="auto">
  <name>Task 2: Unified SearchResultCard component + useQuicklook hook</name>
  <files>
    frontend/src/hooks/use-quicklook.ts
    frontend/src/components/search/SearchResultCard.tsx
    frontend/src/components/search/DatasetCardSkeleton.tsx
    frontend/src/components/search/FilterPanel.tsx
    frontend/src/pages/SearchPage.tsx
    frontend/src/components/search/__tests__/SearchResultCard.test.tsx
    frontend/src/components/search/__tests__/DatasetCard.test.tsx
    frontend/src/components/search/__tests__/CollectionSearchCard.test.tsx
  </files>
  <action>
**1. Extract useQuicklook hook** (`frontend/src/hooks/use-quicklook.ts`):
- Move the quicklook fetch logic from DatasetCard (lines 28-62) into a reusable hook: `useQuicklook(datasetId: string | null)` returning `{ src: string | null, isLoading: boolean, isError: boolean }`.
- When `datasetId` is null (e.g., collections), return `{ src: null, isLoading: false, isError: false }` immediately.
- Preserve blob URL cleanup on unmount/re-key. Use the same auth header pattern (`useAuthStore.getState().token`).

**2. Create SearchResultCard** (`frontend/src/components/search/SearchResultCard.tsx`):
- Single component accepting `{ feature: OGCRecordResponse }`.
- Determine `recordType` from `feature.properties.record_type` (default to `'vector_dataset'`).
- Determine link path: collections go to `/collections/{id}`, datasets go to `/datasets/{id}`.

**Layout (2-column, matches existing DatasetCard structure):**
```
<Link to={linkPath} className="group block">
  <Card className="flex flex-col sm:flex-row gap-0 py-0 overflow-hidden cursor-pointer group-hover:shadow-md group-hover:border-primary/20 group-hover:bg-accent/50 transition-...">
    {/* Left: Content */}
    <div className="flex-1 p-3 min-w-0">
      {/* Row 1: Title (line-clamp-2 sm:line-clamp-1, text-lg font-semibold, group-hover:text-primary) */}
      {/* Row 2: Identity — RecordTypeBadge + type-specific inline metadata */}
      {/* Row 3: Tags (max 2 + overflow, only if keywords exist) */}
      {/* Row 4: Footer — provenance or collection-specific footer */}
    </div>
    {/* Right: Preview (hidden sm:block sm:w-40, only for non-collection types) */}
  </Card>
</Link>
```

**Row 2 — Type-specific metadata (plain text with dot separators):**
- **Vector**: `RecordTypeBadge` + geometry_type + feature_count + CRS + source_organization + QualityBadge
- **Raster**: `RecordTypeBadge` + band_count bands + gsd resolution (format as "Xm" if < 1000, else "X.Xkm") + CRS + source_organization + QualityBadge
- **VRT**: `RecordTypeBadge` + vrt_type label ("Mosaic" or "Band Stack", capitalize first letter) + source_count sources + band_count bands + CRS + QualityBadge
- **Collection**: `RecordTypeBadge` + dataset_count datasets badge (secondary variant)

Use the exact same `<span className="text-xs text-muted-foreground flex items-center gap-1">` pattern with `<span aria-hidden>·</span>` separators between items, matching the existing DatasetCard style.

**Row 3 — Tags**: Same as current DatasetCard (filter out 'synthetic'/'perf-seed', show max 2, "+N more" overflow). Skip entirely for collections (they have no keywords).

**Row 4 — Footer**:
- For datasets: Same provenance attribution as current DatasetCard (updatedBy + time, with all fallbacks).
- For collections: Show description (line-clamp-2) if available, otherwise show created date.

**Preview column (right side)**:
- For datasets (vector/raster/VRT): Use `useQuicklook(feature.id)` with same three-state rendering (loading spinner, image, error fallback with ImageOff, BBoxPreview as final fallback).
- For collections: Show a styled folder icon placeholder (FolderOpen from lucide, centered in muted background, matching the preview column dimensions).

**Status badges**: Keep the same status badge rendering (draft/ready/internal/archived/deprecated) and synthetic badge before RecordTypeBadge, only for non-collection types.

**3. Update DatasetCardSkeleton**: No structural changes needed — the skeleton already matches the unified layout.

**4. Fix FilterPanel bug** (`frontend/src/components/search/FilterPanel.tsx`):
- Line 493: The secondary filter row condition `recordType && (recordType === 'vector_dataset' || organizations.length > 0 || srids.length > 0)` shows for collections too. Fix: add `recordType !== 'collection'` to the condition:
  ```tsx
  {recordType && recordType !== 'collection' && (
    recordType === 'vector_dataset' || organizations.length > 0 || srids.length > 0
  ) && (
  ```
- Also fix the label fallthrough at line 498-502: add collection case (though it should never render now).

**5. Update SearchPage** (`frontend/src/pages/SearchPage.tsx`):
- Replace the conditional `CollectionSearchCard` / `DatasetCard` rendering with a single:
  ```tsx
  <SearchResultCard key={feature.id} feature={feature} />
  ```
- Remove imports of `CollectionSearchCard` and `DatasetCard`.
- Import `SearchResultCard` instead.

**6. Update tests**:
- Create `frontend/src/components/search/__tests__/SearchResultCard.test.tsx` with tests covering:
  - Vector card renders title, link to `/datasets/{id}`, geometry type, feature count, CRS
  - Raster card renders band count, RecordTypeBadge with "Raster"
  - VRT card renders vrt_type label, source_count, band count
  - Collection card renders title, link to `/collections/{id}`, dataset count badge
  - Tags display (max 2 + overflow)
  - Status badge for non-published records
- Update existing `DatasetCard.test.tsx` to import `SearchResultCard` instead of `DatasetCard` (or delete and consolidate into the new test file).
- Update `CollectionSearchCard.test.tsx` similarly.

**Do NOT delete** `DatasetCard.tsx` and `CollectionSearchCard.tsx` — leave them in place (they might be imported elsewhere). Just make sure SearchPage no longer uses them.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run --reporter=verbose src/components/search/__tests__/SearchResultCard.test.tsx 2>&1 | tail -30</automated>
  </verify>
  <done>
    - SearchResultCard renders all four record types through one component
    - useQuicklook hook extracted and working for dataset types, returns null for collections
    - Collection cards now use the same 2-column card layout as datasets with folder icon preview
    - VRT cards show vrt_type ("Mosaic"/"Band Stack") and source_count
    - Raster cards show gsd resolution
    - Filter panel secondary row no longer shows for collection type filter
    - SearchPage renders all results via SearchResultCard
    - All tests pass
  </done>
</task>

</tasks>

<verification>
1. `cd frontend && npx tsc --noEmit` — TypeScript compiles cleanly
2. `cd frontend && npx vitest run --reporter=verbose src/components/search/__tests__/` — all search card tests pass
3. Visual: load http://localhost:8080, search for records — all types render in unified card layout
4. Visual: filter to Collections — secondary filter row does not appear
5. Visual: VRT records show "Mosaic" or "Band Stack" label with source count
</verification>

<success_criteria>
- Single SearchResultCard component handles vector, raster, VRT, and collection records
- 2-column layout (content + preview) consistent across all types
- VRT-specific fields (vrt_type, source_count) flow from backend through to card display
- Collection cards upgraded from minimal row to full card with folder icon preview
- Filter panel bug fixed (no "Virtual Raster filters" label when collection type selected)
- All existing search card tests updated and passing
- No TypeScript errors
</success_criteria>

<output>
After completion, create `.planning/quick/260318-mhz-search-result-cards-overhaul-unified-car/260318-mhz-01-SUMMARY.md`
</output>

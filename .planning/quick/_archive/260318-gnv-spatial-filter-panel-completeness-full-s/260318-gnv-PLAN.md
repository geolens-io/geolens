---
phase: 260318-gnv
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/search/service.py
  - backend/app/search/router.py
  - frontend/src/stores/search-store.ts
  - frontend/src/components/search/SpatialFilterPanel.tsx
  - frontend/src/components/search/FilterPanel.tsx
  - frontend/src/pages/SearchPage.tsx
autonomous: true
requirements: [STATE-01, PRED-01, HERO-01, EXTENT-01, BACKEND-01]

must_haves:
  truths:
    - "Drawing a rectangle or polygon shows area summary text below the map"
    - "Intersects/Within toggle changes the spatial predicate sent to backend"
    - "'Use current map extent' captures panel map viewport as a bbox rectangle"
    - "Apply closes panel and shows 'Area selected' chip in filter bar"
    - "Hero compresses when spatial panel is open (even before applying)"
    - "Backend filters with ST_Within when spatial_predicate=within"
    - "Mode toggle shows rectangle and polygon icons alongside text"
  artifacts:
    - path: "frontend/src/components/search/SpatialFilterPanel.tsx"
      provides: "Complete spatial filter panel with state machine, predicate toggle, map extent button, mode icons, area summary"
    - path: "frontend/src/stores/search-store.ts"
      provides: "spatial_predicate and spatialPanelOpen fields"
    - path: "backend/app/search/service.py"
      provides: "ST_Within support via spatial_predicate parameter"
    - path: "backend/app/search/router.py"
      provides: "spatial_predicate query parameter on search endpoints"
  key_links:
    - from: "frontend/src/stores/search-store.ts"
      to: "backend/app/search/router.py"
      via: "spatial_predicate query param in toParams()"
      pattern: "spatial_predicate"
    - from: "frontend/src/components/search/SpatialFilterPanel.tsx"
      to: "frontend/src/stores/search-store.ts"
      via: "onApply passes predicate, store serializes to URL"
      pattern: "spatial_predicate"
    - from: "frontend/src/pages/SearchPage.tsx"
      to: "frontend/src/stores/search-store.ts"
      via: "spatialPanelOpen triggers hero collapse"
      pattern: "spatialPanelOpen"
---

<objective>
Complete the spatial filter panel UX with full state machine, area summary, mode icons, Intersects/Within predicate toggle, "Use current map extent" button, active chip behavior, and hero compression when spatial panel is open.

Purpose: The spatial filter panel (from 260318-g6s) has basic draw+apply but lacks polish -- no area feedback, no predicate choice, no quick-set from viewport, and hero doesn't compress when the panel is open. This task finishes the UX.
Output: Fully functional spatial filter panel with backend ST_Within support.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/search/SpatialFilterPanel.tsx
@frontend/src/components/search/FilterPanel.tsx
@frontend/src/stores/search-store.ts
@frontend/src/pages/SearchPage.tsx
@backend/app/search/service.py
@backend/app/search/router.py
@frontend/src/hooks/use-search.ts

<interfaces>
<!-- From search-store.ts: -->
```typescript
interface SearchState {
  q: string;
  bbox: string;
  keywords: string[];
  geometry_type: string;
  // ... other fields
  setFilter: (key: string, value: string | string[] | boolean) => void;
  toParams: () => Record<string, string>;
  restoreParams: (params: Record<string, string>) => void;
}
```

<!-- From SpatialFilterPanel.tsx: -->
```typescript
interface SpatialFilterPanelProps {
  open: boolean;
  onClose: () => void;
  onApply: (bbox: string) => void;
  initialBbox?: string;
}
```

<!-- From FilterPanel.tsx (line 872-884): -->
```tsx
<LazySpatialFilterPanel
  open={spatialPanelOpen}
  onClose={() => setSpatialPanelOpen(false)}
  onApply={(bboxValue) => {
    useSearchStore.getState().setFilter('bbox', bboxValue);
    setSpatialPanelOpen(false);
  }}
  initialBbox={bbox}
/>
```

<!-- Backend search_datasets signature (service.py line 510): -->
```python
async def search_datasets(session, user, user_roles, *, q=None, bbox=None, keywords=None, geometry_type=None, srid=None, source_organization=None, record_type=None, date_from=None, date_to=None, vintage_start=None, vintage_end=None, sort_by="relevance", skip=0, limit=10, cql2_filter=None, cql2_filter_lang="cql2-text", datetime_param=None, exclude_synthetic=True)
```

<!-- Backend get_facet_counts signature (service.py line 167): -->
```python
async def get_facet_counts(session, user, user_roles, *, q=None, bbox=None, keywords=None, geometry_type=None, srid=None, source_organization=None, datetime_param=None, exclude_synthetic=True)
```

<!-- ST_Intersects locations in service.py: lines 258, 382, 645 -->

<!-- _handle_search in router.py (line 73) passes bbox to search_datasets -->

<!-- Router endpoints with bbox: /search/datasets (line 432), /search/facets (line 376), /collections/datasets/items (line 855) -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend ST_Within support + spatial_predicate parameter</name>
  <files>backend/app/search/service.py, backend/app/search/router.py</files>
  <action>
  1. In `search_datasets()` (service.py line 510): Add `spatial_predicate: str = "intersects"` keyword parameter. At the 3 ST_Intersects locations (lines ~258, ~382, ~645), replace the hardcoded `func.ST_Intersects(...)` with a conditional:
     ```python
     envelope = func.ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)
     spatial_fn = func.ST_Within if spatial_predicate == "within" else func.ST_Intersects
     stmt = stmt.where(spatial_fn(Record.spatial_extent, envelope))
     ```
     Extract the envelope construction to avoid repetition at each location.

  2. In `get_facet_counts()` (service.py line 167): Add `spatial_predicate: str = "intersects"` parameter. Apply the same conditional at the bbox filter in that function (line ~382).

  3. In `_handle_search()` (router.py line 73): Add `spatial_predicate: str = "intersects"` parameter. Pass it through to `search_datasets()` call (line ~159).

  4. In `search_datasets_endpoint()` (router.py line 432): Add `spatial_predicate: str = Query("intersects", description="Spatial predicate: intersects or within")` parameter. Pass to `_handle_search()`.

  5. In `search_facets_endpoint()` (router.py line 376): Add same `spatial_predicate` query parameter. Pass to `get_facet_counts()`.

  6. In `collection_items()` (router.py line 855): Add same `spatial_predicate` query parameter. Pass to `_handle_search()`.

  Do NOT add spatial_predicate to collection search (it has no spatial column).
  </action>
  <verify>cd /Users/ishiland/Code/geolens/backend && python -c "from app.search.service import search_datasets, get_facet_counts; print('imports ok')" && grep -c "spatial_predicate" app/search/service.py app/search/router.py</verify>
  <done>All 3 ST_Intersects locations conditionally use ST_Within when spatial_predicate="within". The parameter is exposed on /search/datasets, /search/facets, and /collections/datasets/items endpoints.</done>
</task>

<task type="auto">
  <name>Task 2: Frontend store, panel UX, and hero compression</name>
  <files>frontend/src/stores/search-store.ts, frontend/src/components/search/SpatialFilterPanel.tsx, frontend/src/components/search/FilterPanel.tsx, frontend/src/pages/SearchPage.tsx</files>
  <action>
  **search-store.ts:**
  1. Add `spatial_predicate: string` to SearchState interface (default: 'intersects').
  2. Add `spatialPanelOpen: boolean` to SearchState (default: false) -- UI-only field, NOT serialized to URL params.
  3. Add `setSpatialPanelOpen: (open: boolean) => void` action.
  4. In `toParams()`: serialize `spatial_predicate` only when not 'intersects' (same pattern as sort_by).
  5. In `restoreParams()`: restore `spatial_predicate` from params (default 'intersects').
  6. In `resetFilters()`: reset `spatial_predicate` to 'intersects' and `spatialPanelOpen` to false.

  **SpatialFilterPanel.tsx -- extend with all panel UX features:**

  1. **Mode icons:** Import `Square` and `Pentagon` from lucide-react. Add to ToggleGroupItems:
     ```tsx
     <ToggleGroupItem value="rectangle" className="flex-1 text-xs">
       <Square className="mr-1 size-3" />
       Rectangle
     </ToggleGroupItem>
     <ToggleGroupItem value="polygon" className="flex-1 text-xs">
       <Pentagon className="mr-1 size-3" />
       Polygon
     </ToggleGroupItem>
     ```

  2. **Predicate toggle:** Add `predicate` state (default from store's `spatial_predicate`). Render a ToggleGroup below the map, above instruction text:
     ```tsx
     <div className="mt-2 flex items-center gap-2">
       <span className="text-xs text-muted-foreground">Mode:</span>
       <ToggleGroup type="single" value={predicate} onValueChange={(v) => v && setPredicate(v as 'intersects' | 'within')} className="h-7">
         <ToggleGroupItem value="intersects" className="text-xs px-2 h-7">Intersects</ToggleGroupItem>
         <ToggleGroupItem value="within" className="text-xs px-2 h-7">Within</ToggleGroupItem>
       </ToggleGroup>
     </div>
     ```

  3. **"Use current map extent" button:** Below the predicate toggle, add:
     ```tsx
     <Button variant="outline" size="sm" className="mt-2 w-full text-xs" onClick={() => {
       const map = mapRef.current;
       if (!map) return;
       const bounds = map.getBounds();
       const bboxStr = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
       // Clear existing drawn feature
       const td = drawRef.current;
       if (td && drawnFeatureIdRef.current != null) {
         try { td.removeFeatures([drawnFeatureIdRef.current]); } catch {}
       }
       // Add rectangle feature from bounds
       if (td) {
         const poly = bboxToPolygon(bboxStr);
         const ids = td.addFeatures([poly]);
         if (ids.length > 0) drawnFeatureIdRef.current = ids[0];
       }
       setPendingBbox(bboxStr);
     }}>
       Use current map extent
     </Button>
     ```

  4. **Area summary:** Replace the static instruction text with state-aware content. Derive panel state from `pendingBbox`:
     - When `pendingBbox` is empty: show draw instruction (current behavior)
     - When `pendingBbox` is set: show area summary. For rectangle, show rounded bbox coords; for polygon, show "1 polygon selected". Use `text-xs text-muted-foreground`.
     ```tsx
     {pendingBbox ? (
       <p className="mt-2 text-xs text-muted-foreground">
         {drawMode === 'rectangle'
           ? `Bbox: ${pendingBbox.split(',').map(n => Number(n).toFixed(2)).join(', ')}`
           : '1 polygon selected'}
       </p>
     ) : (
       <p className="mt-2 text-xs text-muted-foreground">{/* existing instruction */}</p>
     )}
     ```

  5. **Update props:** Change `onApply` signature to `onApply: (bbox: string, predicate: string) => void`. Also accept `initialPredicate?: string` prop to restore predicate when reopening. Update `handleApply` to pass predicate.

  6. **Clear resets predicate:** In `handleClear`, reset predicate to 'intersects'.

  **FilterPanel.tsx:**
  1. Replace local `spatialPanelOpen` useState with store's `spatialPanelOpen` and `setSpatialPanelOpen`:
     ```tsx
     const spatialPanelOpen = useSearchStore((s) => s.spatialPanelOpen);
     const setSpatialPanelOpen = useSearchStore((s) => s.setSpatialPanelOpen);
     ```
  2. Update `onApply` callback to also set `spatial_predicate` in store:
     ```tsx
     onApply={(bboxValue, predicate) => {
       const store = useSearchStore.getState();
       store.setFilter('bbox', bboxValue);
       store.setFilter('spatial_predicate', predicate);
       setSpatialPanelOpen(false);
     }}
     ```
  3. Pass `initialPredicate={useSearchStore.getState().spatial_predicate}` to `LazySpatialFilterPanel`.
  4. When chip X clears bbox, also reset `spatial_predicate`:
     ```tsx
     onRemove={() => {
       const store = useSearchStore.getState();
       store.setFilter('bbox', '');
       store.setFilter('spatial_predicate', 'intersects');
     }}
     ```

  **SearchPage.tsx:**
  1. Subscribe to `spatialPanelOpen` from store:
     ```tsx
     const spatialPanelOpen = useSearchStore((s) => s.spatialPanelOpen);
     ```
  2. Add `spatialPanelOpen` to `isLanding` check:
     ```tsx
     const isLanding = !q && !recordType && keywords.length === 0 && !geometryType && !bbox && !spatialPanelOpen;
     ```
  </action>
  <verify>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</verify>
  <done>
  - Mode toggle shows Square/Pentagon icons next to text
  - Intersects/Within toggle appears below map, defaults to Intersects
  - "Use current map extent" captures panel map viewport as drawn rectangle with visual feedback
  - Area summary shows bbox coords or "1 polygon selected" after drawing
  - Apply sends predicate to store, store serializes spatial_predicate to API params
  - Clear area resets predicate to intersects
  - Chip X in filter bar clears both bbox and predicate
  - Hero compresses when spatialPanelOpen is true (even without applied bbox)
  </done>
</task>

</tasks>

<verification>
1. `cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit` -- no type errors
2. `cd /Users/ishiland/Code/geolens/backend && python -c "from app.search.router import search_router; print('router ok')"` -- imports succeed
3. `grep -c "spatial_predicate" frontend/src/stores/search-store.ts` -- at least 5 occurrences
4. `grep -c "ST_Within" backend/app/search/service.py` -- at least 3 occurrences
5. `grep "spatialPanelOpen" frontend/src/pages/SearchPage.tsx` -- appears in isLanding check
</verification>

<success_criteria>
- Backend accepts spatial_predicate=within and filters with ST_Within
- Panel shows mode icons (Square/Pentagon) on draw mode toggle
- Intersects/Within predicate toggle below map, defaults to Intersects
- "Use current map extent" button captures viewport and shows drawn rectangle
- Area summary text replaces instructions after drawing
- Hero compresses when spatial panel opens
- Chip X clears both bbox and predicate
- All TypeScript compiles, backend imports succeed
</success_criteria>

<output>
After completion, create `.planning/quick/260318-gnv-spatial-filter-panel-completeness-full-s/260318-gnv-SUMMARY.md`
</output>

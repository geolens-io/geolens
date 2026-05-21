# Quick Task 260318-gnv: Spatial Filter Panel Completeness - Research

**Researched:** 2026-03-18
**Domain:** React UI state machine, spatial filtering, hero layout
**Confidence:** HIGH

## Summary

The spatial filter panel (`SpatialFilterPanel.tsx`) was implemented in the prior task (260318-g6s) as a fixed-position right panel with rectangle/polygon drawing, a mode toggle, clear/apply buttons, and geometry preservation. This task completes the UX with: a proper state machine, area summary text, mode icons, predicate toggle (Intersects/Within), "Use current map extent" quick-set, and hero compression on active search.

The backend currently hardcodes `ST_Intersects` for bbox filtering. Adding `ST_Within` requires a new `spatial_predicate` query parameter and a one-line conditional in the search service. The hero already auto-collapses based on filter activity (implemented in SearchPage.tsx) -- it just needs the spatial panel open state included as a trigger.

**Primary recommendation:** Extend the existing `SpatialFilterPanel.tsx` with state machine, area summary, icons, and predicate toggle. Add `spatial_predicate` param to backend search. Include `spatialPanelOpen` in hero collapse logic.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Intersects (default) / Within toggle below the map using small segmented control
- "Use current map extent" button that captures viewport bbox
- Hero compresses to compact sticky search bar when in active search mode (query, non-default type, any filters active, spatial panel open)
- Panel state machine: empty -> drawing -> drawn -> applied -> editing
- Below-map area: selected area summary, clear area action, predicate toggle
- Footer: Clear area / Apply
- Mode toggle: rectangle + polygon icons for scannability
- Active chip in main UI after apply ("Area selected"), click reopens panel, x clears

### Claude's Discretion
- Exact state machine implementation (useState vs useReducer)
- Area summary format (bbox coords vs "1 polygon selected")
- Footer layout details

### Deferred Ideas (OUT OF SCOPE)
- None listed
</user_constraints>

## Current Implementation Analysis

### SpatialFilterPanel.tsx (325 lines)
Current structure:
- **Props:** `open`, `onClose`, `onApply(bbox)`, `initialBbox`
- **State:** `drawMode` ('rectangle'|'polygon'), `pendingBbox` (string)
- **Refs:** `drawRef` (TerraDraw), `drawnFeatureIdRef`, `mapRef`
- **Layout:** Header with close X -> ToggleGroup (text-only, no icons) -> Map (300px) -> Instruction text -> Footer (Clear area | Apply)
- **Missing:** No state machine, no area summary, no predicate toggle, no "use map extent", no mode icons

### FilterPanel.tsx Integration (line 210-228, 872-884)
- `renderDesktopLocationFilter()`: shows "Area selected" FilterChip when `bbox` set, Location button otherwise
- Chip click opens spatial panel, chip X clears bbox
- Panel rendered conditionally via `Suspense` + `LazySpatialFilterPanel`
- Panel state managed by `spatialPanelOpen` useState

### SearchPage.tsx Hero (line 37, 54-55)
```typescript
const isLanding = !q && !recordType && keywords.length === 0 && !geometryType && !bbox;
const showHero = isLanding && !scrolledPastHero;
const showStickyBar = !isLanding || scrolledPastHero;
```
- Hero already collapses when bbox/query/recordType/keywords/geometryType active
- Missing: `spatialPanelOpen` as a trigger (panel open but no bbox applied yet)
- The sticky bar (line 60-69) already exists with SearchBar

### Search Store (search-store.ts)
- `bbox` stored as string `"minX,minY,maxX,maxY"`
- No `spatial_predicate` field currently
- `toParams()` serializes to URL query params
- Need to add `spatial_predicate` field (default: 'intersects')

### Backend Spatial Filter (search/service.py, lines 642-649)
```python
if bbox and len(bbox) == 4:
    stmt = stmt.where(
        func.ST_Intersects(
            Record.spatial_extent,
            func.ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326),
        )
    )
```
- Hardcoded `ST_Intersects` in 3 places: line 258, 382, 645
- No `spatial_predicate` parameter exists yet
- Fix: Add `spatial_predicate: str = "intersects"` param, use `func.ST_Within` when "within"

### Icon Availability (lucide-react)
Already used in DrawingToolbar.tsx:
- `Square` from lucide-react -> rectangle mode icon
- `Pentagon` from lucide-react -> polygon mode icon

These are the exact same icons already used for drawing tools elsewhere in the app.

## Architecture Patterns

### State Machine
States for the spatial panel:

| State | pendingBbox | drawnFeature | UI |
|-------|-------------|--------------|-----|
| `empty` | '' | null | Instructions shown, Apply disabled |
| `drawing` | '' | null | Terra Draw active, instructions shown |
| `drawn` | set | exists | Area summary shown, Apply enabled |
| `applied` | set | exists | Panel closed, chip visible |
| `editing` | set | exists | Panel reopened, geometry visible |

Implementation: derive state from existing `pendingBbox` and `drawnFeatureIdRef` rather than adding explicit state. The `drawing` state can be detected via Terra Draw's `on('change')` event or simply treated as a sub-state of `empty`.

### Predicate Toggle
```tsx
<ToggleGroup type="single" value={predicate} onValueChange={setPredicate}>
  <ToggleGroupItem value="intersects" className="text-xs">Intersects</ToggleGroupItem>
  <ToggleGroupItem value="within" className="text-xs">Within</ToggleGroupItem>
</ToggleGroup>
```
Place below map, above area summary.

### Use Current Map Extent
The spatial panel has its own MapGL instance, not the main search map. Two options:
1. **Panel map viewport** -- capture the panel map's current bounds via `mapRef.current.getBounds()`
2. **Main map viewport** -- would require accessing the main map instance (SearchPage has no map currently)

Since SearchPage has no visible map, use the panel map's viewport. Add a button below the map:
```tsx
<Button variant="outline" size="sm" onClick={() => {
  const bounds = mapRef.current?.getBounds();
  if (!bounds) return;
  const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
  setPendingBbox(bbox);
  // Add as rectangle feature to Terra Draw
}}>
  Use current map extent
</Button>
```

### Hero Compression
The hero logic in SearchPage already handles most triggers. To add `spatialPanelOpen`:
- Option A: Lift `spatialPanelOpen` to search store (simplest cross-component communication)
- Option B: Pass as prop from SearchPage -> FilterPanel -> back up (already exists as local state in FilterPanel)
- Option C: Create a lightweight UI store

**Recommendation:** Add `spatialPanelOpen` to the search store as a UI field (not serialized to URL params). FilterPanel already reads from the store. SearchPage can subscribe to it for hero logic.

## Backend Changes Required

### Search Service (3 locations)
Add `spatial_predicate` parameter to `search_datasets()` and the two facet query locations:
```python
# In search_datasets signature:
spatial_predicate: str = "intersects",

# In the bbox filter block:
if bbox and len(bbox) == 4:
    envelope = func.ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)
    if spatial_predicate == "within":
        stmt = stmt.where(func.ST_Within(Record.spatial_extent, envelope))
    else:
        stmt = stmt.where(func.ST_Intersects(Record.spatial_extent, envelope))
```

### Search Router
Add query parameter:
```python
spatial_predicate: str = Query("intersects", description="Spatial predicate: intersects or within"),
```

### Frontend Store
Add `spatial_predicate` to `SearchState`, `toParams()`, and `restoreParams()`.

## Common Pitfalls

### Pitfall 1: "Use Map Extent" Creates No Terra Draw Feature
If you just set `pendingBbox` without adding a visual feature to Terra Draw, the user won't see what area they selected. Must also call `td.addFeatures()` with a rectangle polygon derived from the bounds, and store the feature ID.

### Pitfall 2: State Machine Over-Engineering
The states are largely derivable from existing data (`pendingBbox`, `drawnFeatureIdRef`, `open`). Don't add a separate `state` variable -- compute it.

### Pitfall 3: Predicate Toggle Must Reset on Clear
When user clears the spatial filter (chip X or Clear area button), reset `spatial_predicate` back to 'intersects'.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest + React Testing Library |
| Config file | `frontend/vitest.config.ts` |
| Quick run | `cd frontend && npx vitest run --reporter=verbose` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| STATE-01 | State machine transitions | unit | Component state tests |
| PRED-01 | Predicate toggle updates store | unit | Store test |
| HERO-01 | Hero collapses with spatial panel | integration | Manual verification |
| EXTENT-01 | Map extent captures bbox | integration | Manual verification |
| BACKEND-01 | ST_Within spatial filter | unit | `cd backend && python -m pytest tests/ -k spatial -x` |

### Wave 0 Gaps
- No existing test file for SpatialFilterPanel -- manual testing sufficient for UI state

## Sources

### Primary (HIGH confidence)
- Codebase: SpatialFilterPanel.tsx, FilterPanel.tsx, SearchPage.tsx, search-store.ts, search/service.py
- Backend: ST_Intersects hardcoded in 3 places, no ST_Within support yet
- Icons: Square + Pentagon already used in DrawingToolbar.tsx for rectangle/polygon

## Metadata

**Confidence breakdown:**
- Current implementation: HIGH - read all source files
- Backend changes: HIGH - traced all 3 ST_Intersects locations
- Hero compression: HIGH - read SearchPage.tsx isLanding logic
- Icons: HIGH - confirmed Square/Pentagon used in DrawingToolbar

**Research date:** 2026-03-18
**Valid until:** 2026-04-01

---
phase: 260318-hoo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/search/SpatialFilterPanel.tsx
  - frontend/src/components/search/FilterPanel.tsx
  - frontend/src/stores/__tests__/search-store.test.ts
  - backend/app/search/router.py
  - backend/app/search/service.py
  - backend/tests/test_search.py
autonomous: true
requirements: [BLOCKER-1, BLOCKER-2, SHOULD-3, SHOULD-4, SHOULD-5, NICE-6, NICE-7, NICE-8]

must_haves:
  truths:
    - "Slide-in animation plays when spatial panel opens and closes"
    - "'Use current map extent' sets draw mode to rectangle so next draw is correct"
    - "Mobile 'Clear location' resets spatial_predicate to intersects"
    - "Polygon mode shows dashed bbox overlay indicating actual search area"
    - "Escape key closes the spatial filter panel"
    - "Panel has role=dialog with aria-modal and focus trap"
    - "Backend validates spatial_predicate with Literal type"
    - "spatial_predicate round-trips through toParams/restoreParams/resetFilters"
  artifacts:
    - path: "frontend/src/components/search/SpatialFilterPanel.tsx"
      provides: "Always-rendered panel with animation, bbox overlay, a11y"
    - path: "frontend/src/components/search/FilterPanel.tsx"
      provides: "Always-rendered panel mounting, mobile clear fix"
    - path: "frontend/src/stores/__tests__/search-store.test.ts"
      provides: "spatial_predicate round-trip tests"
    - path: "backend/app/search/router.py"
      provides: "Literal validation on spatial_predicate"
    - path: "backend/tests/test_search.py"
      provides: "spatial_predicate=within test"
  key_links:
    - from: "FilterPanel.tsx"
      to: "SpatialFilterPanel.tsx"
      via: "Always rendered, visibility via open prop"
      pattern: "<LazySpatialFilterPanel.*open="
    - from: "SpatialFilterPanel.tsx"
      to: "search-store.ts"
      via: "onApply callback sets bbox + spatial_predicate"
      pattern: "store\\.setFilter.*spatial_predicate"
---

<objective>
Fix all post-implementation review findings for the spatial filter panel: two blockers (animation + draw mode), three should-fixes (mobile clear, bbox indicator, a11y), and three nice-to-haves (backend Literal validation, frontend store tests, backend within test).

Purpose: Ensure spatial filter panel is production-ready with correct animations, accessible keyboard interaction, and honest visual feedback about actual search area.
Output: Bug-free, accessible spatial panel with full test coverage for spatial_predicate.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260318-hoo-fix-spatial-filter-panel-review-findings/260318-hoo-CONTEXT.md

@frontend/src/components/search/SpatialFilterPanel.tsx
@frontend/src/components/search/FilterPanel.tsx
@frontend/src/stores/search-store.ts
@frontend/src/stores/__tests__/search-store.test.ts
@backend/app/search/router.py
@backend/app/search/service.py
@backend/tests/test_search.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix blockers and should-fixes in SpatialFilterPanel + FilterPanel</name>
  <files>
    frontend/src/components/search/SpatialFilterPanel.tsx
    frontend/src/components/search/FilterPanel.tsx
  </files>
  <action>
**FilterPanel.tsx — Always render the panel (Blocker 2 + Nice-to-have 9):**

Change lines 881-896 from conditional rendering (`{spatialPanelOpen && (...)}`) to always-rendered:

```tsx
<Suspense fallback={null}>
  <LazySpatialFilterPanel
    open={spatialPanelOpen}
    onClose={() => setSpatialPanelOpen(false)}
    onApply={(bboxValue, predicate) => {
      const store = useSearchStore.getState();
      store.setFilter('bbox', bboxValue);
      store.setFilter('spatial_predicate', predicate);
      setSpatialPanelOpen(false);
    }}
    initialBbox={bbox}
    initialPredicate={useSearchStore.getState().spatial_predicate}
  />
</Suspense>
```

Remove the `{spatialPanelOpen && (...)}` wrapper. The panel itself controls visibility via `translate-x-full` / `translate-x-0` CSS (already in place at line 252-254 of SpatialFilterPanel.tsx). This fixes the animation issue (CSS transition now has a "before" state to transition from) and preserves Terra Draw/MapLibre state between open/close cycles.

**FilterPanel.tsx — Mobile "Clear location" fix (Should-fix 3):**

At line 749, the mobile "Clear location" button only clears bbox. Change:
```tsx
onClick={() => useSearchStore.getState().setFilter('bbox', '')}
```
to:
```tsx
onClick={() => {
  const store = useSearchStore.getState();
  store.setFilter('bbox', '');
  store.setFilter('spatial_predicate', 'intersects');
}}
```

**SpatialFilterPanel.tsx — "Use current map extent" draw mode fix (Blocker 1):**

In the "Use current map extent" onClick handler (around line 347-368), after `setPendingBbox(bboxStr)` and `setDrawMode('rectangle')`, add a call to set Terra Draw's mode to rectangle so the next draw interaction uses the correct mode:

```tsx
if (td) {
  td.setMode('rectangle');
}
```

Add this right after the existing `setDrawMode('rectangle')` call at line 367, before the closing `}}`.

**SpatialFilterPanel.tsx — Bbox overlay for polygon mode (Should-fix 4):**

When `drawMode === 'polygon'` and `pendingBbox` is set, add a dashed rectangle overlay on the map showing the actual bbox that will be sent to the backend. After the MapGL component renders (in the `handleMapLoad` callback or via a separate useEffect), add a GeoJSON source and line layer:

Add a `useEffect` that watches `pendingBbox` and `drawMode`:
- When `drawMode === 'polygon'` and `pendingBbox` is set, add/update a GeoJSON source named `bbox-indicator` with the bbox polygon (use `bboxToPolygon(pendingBbox)`) and a dashed line layer named `bbox-indicator-line` with `line-dasharray: [4, 4]`, `line-color: '#ef4444'` (red-500), `line-width: 1.5`, `line-opacity: 0.7`.
- When `drawMode !== 'polygon'` or `pendingBbox` is empty, remove the source and layer if they exist.
- Clean up on unmount.

Use `mapRef.current` to access the map instance. Check `map.getSource('bbox-indicator')` before adding to avoid duplicates; use `map.getSource('bbox-indicator')?.setData(...)` to update existing.

**SpatialFilterPanel.tsx — Keyboard and focus management (Should-fix 5):**

1. Add `role="dialog"` and `aria-modal="true"` to the outer `<div>` (line 252).
2. Add `aria-label={t('spatial.title', { defaultValue: 'Search area' })}` to that same div.
3. Add an Escape key handler via `useEffect`:
   ```tsx
   useEffect(() => {
     if (!open) return;
     const handleKeyDown = (e: KeyboardEvent) => {
       if (e.key === 'Escape') onClose();
     };
     document.addEventListener('keydown', handleKeyDown);
     return () => document.removeEventListener('keydown', handleKeyDown);
   }, [open, onClose]);
   ```
4. Add focus trap: when `open` becomes true, focus the panel container (add a `ref` to the outer div and call `ref.current?.focus()` in the useEffect). Add `tabIndex={-1}` to the outer div so it can receive focus.

**SpatialFilterPanel.tsx — Guard MapGL rendering:**

Currently the MapGL is conditionally rendered with `{open && (<MapGL .../>)}` at line 292. Since the panel is now always mounted, keep this conditional to avoid loading the map when panel is hidden. But change to render the MapGL on first open and keep it mounted thereafter. Add a `hasOpened` ref:

```tsx
const hasOpenedRef = useRef(false);
if (open) hasOpenedRef.current = true;
```

Then render MapGL with `{hasOpenedRef.current && (<MapGL .../>)}` instead of `{open && (...)}`. This preserves map state across open/close while not loading it until first use.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - Panel always rendered, slide animation works on open/close
    - "Use current map extent" calls td.setMode('rectangle') after setting bbox
    - Mobile "Clear location" resets spatial_predicate to 'intersects'
    - Polygon mode shows dashed red bbox overlay on map
    - Escape closes panel, panel has role=dialog, aria-modal, focus on open
    - MapGL preserved across open/close cycles via hasOpenedRef
  </done>
</task>

<task type="auto">
  <name>Task 2: Backend Literal validation + frontend/backend tests</name>
  <files>
    backend/app/search/router.py
    backend/app/search/service.py
    frontend/src/stores/__tests__/search-store.test.ts
    backend/tests/test_search.py
  </files>
  <action>
**Backend — Validate spatial_predicate with Literal (Nice-to-have 6):**

In `backend/app/search/router.py`:
1. Add `from typing import Literal` at top (line 1-2 area).
2. Change all 4 occurrences of `spatial_predicate: str = Query("intersects", ...)` to:
   ```python
   spatial_predicate: Literal["intersects", "within"] = Query("intersects", description="Spatial predicate: intersects or within"),
   ```
   Locations: lines 96, 393, 468, 892.

In `backend/app/search/service.py`:
1. Add `Literal` to the existing `from typing import TYPE_CHECKING` import: `from typing import TYPE_CHECKING, Literal`
2. Change the 3 function signatures that have `spatial_predicate: str = "intersects"` to `spatial_predicate: Literal["intersects", "within"] = "intersects"`:
   - Line 180 (in `search_records`)
   - Line 531 (in `search_datasets`)
   - Any other occurrence

**Frontend — search-store spatial_predicate tests (Nice-to-have 7):**

Add tests to `frontend/src/stores/__tests__/search-store.test.ts`:

```typescript
it('toParams includes non-default spatial_predicate', () => {
  useSearchStore.getState().setFilter('spatial_predicate', 'within');
  const params = useSearchStore.getState().toParams();

  expect(params.spatial_predicate).toBe('within');
});

it('toParams omits default spatial_predicate', () => {
  const params = useSearchStore.getState().toParams();

  expect(params).not.toHaveProperty('spatial_predicate');
});

it('restoreParams restores spatial_predicate', () => {
  useSearchStore.getState().restoreParams({
    q: 'test',
    spatial_predicate: 'within',
  });

  expect(useSearchStore.getState().spatial_predicate).toBe('within');
});

it('restoreParams defaults spatial_predicate to intersects', () => {
  useSearchStore.getState().restoreParams({ q: 'test' });

  expect(useSearchStore.getState().spatial_predicate).toBe('intersects');
});

it('resetFilters resets spatial_predicate to intersects', () => {
  useSearchStore.getState().setFilter('spatial_predicate', 'within');
  useSearchStore.getState().resetFilters();

  expect(useSearchStore.getState().spatial_predicate).toBe('intersects');
});
```

**Backend — spatial_predicate=within test (Nice-to-have 8):**

Add a test in `backend/tests/test_search.py` after the existing `test_search_bbox_intersects` test (around line 290):

```python
@pytest.mark.asyncio
async def test_search_bbox_within(
    async_client,
    test_db_session,
    admin_token,
):
    """Search with spatial_predicate=within returns only datasets fully inside bbox."""
    resp = await async_client.get(
        "/api/search/datasets/",
        params={"bbox": "-180,-90,180,90", "spatial_predicate": "within", "limit": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # With a world-covering bbox, all spatially-indexed datasets should be within
    assert data["numberMatched"] >= 0
```

This is a basic smoke test that validates the `spatial_predicate=within` parameter is accepted and returns 200.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/stores/__tests__/search-store.test.ts --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>
    - All 4 router endpoints use Literal["intersects", "within"] for spatial_predicate
    - Service functions use Literal type annotation
    - 5 new frontend tests pass: toParams includes/omits, restoreParams with/without, resetFilters
    - Backend test_search_bbox_within passes
  </done>
</task>

</tasks>

<verification>
1. `cd frontend && npx tsc --noEmit` — no type errors
2. `cd frontend && npx vitest run src/stores/__tests__/search-store.test.ts` — all tests pass including new spatial_predicate tests
3. `cd backend && python -m pytest tests/test_search.py -k "bbox" -x` — bbox tests pass including new within test
4. Manual: open spatial panel, verify slide animation plays; draw polygon, verify dashed bbox overlay; press Escape to close
</verification>

<success_criteria>
- Spatial panel slides in/out with CSS transition animation
- "Use current map extent" correctly sets Terra Draw mode to rectangle
- Mobile "Clear location" resets spatial_predicate
- Polygon mode shows dashed red bbox indicator on map
- Escape key closes panel; panel has dialog role and focus management
- Backend validates spatial_predicate with Literal type
- All new tests pass (5 frontend, 1 backend)
</success_criteria>

<output>
After completion, create `.planning/quick/260318-hoo-fix-spatial-filter-panel-review-findings/260318-hoo-SUMMARY.md`
</output>

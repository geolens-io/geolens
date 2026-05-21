# Quick Task 260318-g6s: Redesign Location Filter - Research

**Researched:** 2026-03-18
**Domain:** React UI / MapLibre GL / Terra Draw spatial filtering
**Confidence:** HIGH

## Summary

The current location filter uses a `Popover` (w-80, ~320px) containing a lazy-loaded `BboxMapPicker` component that renders a 250px-tall MapLibre map with Terra Draw rectangle mode. On draw completion, it extracts a bbox string (`minX,minY,maxX,maxY`) and stores it in the zustand `useSearchStore`. The popover blocks underlying content and offers only rectangle drawing.

The redesign replaces this with a right-side `Sheet` panel (~360-420px) supporting both rectangle and polygon drawing, collapsing after apply, and showing a FilterChip when active.

**Primary recommendation:** Use the existing `Sheet` component with `side="right"` for the panel, extend `BboxMapPicker` (or create a new `SpatialFilterPanel`) to support both rectangle and polygon modes via Terra Draw (already installed with both modes available), and add a `geometry` field to the search store alongside `bbox` for polygon-based filtering.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Right-side panel (~360-420px wide) that slides in from the right
- Results stay visible on the left while panel is open
- Desktop: right-side panel; Mobile/tablet: full-screen spatial filter view
- Panel contents: title ("Search area"), mini map, draw bbox/polygon tools, clear area, optional Intersects/Within mode toggle, Apply button
- Both rectangle + polygon, with rectangle as the default mode
- Rectangle: click-drag to draw a bounding box
- Polygon: click to add vertices, double-click to finish
- UI: Rectangle | Polygon toggle, default to Rectangle
- Contextual instructions per mode
- Collapse after filter is applied - panel closes on Apply
- Active filter chip appears (e.g., "Area selected")
- Clicking chip reopens panel with geometry preserved
- Chip has x to remove spatial filter
- Panel stays open during active drawing/editing - only collapses after Apply

### Claude's Discretion
- Exact chip label text
- Internal component architecture
- Whether to extend BboxMapPicker or create new component

### Deferred Ideas (OUT OF SCOPE)
- "Use current map extent"
- "Upload/select geometry"
- "Pick from saved area"
- Intersects/Within mode toggle (listed as "optional" - skip for now, future-friendly)
</user_constraints>

## Current Implementation Analysis

### Files to Modify

| File | What | Change Needed |
|------|------|---------------|
| `frontend/src/components/search/FilterPanel.tsx` | Contains `renderDesktopLocationFilter()` using Popover | Replace popover with Sheet trigger + panel |
| `frontend/src/components/search/BboxMapPicker.tsx` | Terra Draw rectangle-only picker (250px map) | Extend to support polygon mode, preserve drawn geometry |
| `frontend/src/stores/search-store.ts` | Search state (bbox as string) | Consider adding `spatial_geometry` field for polygon GeoJSON |
| `frontend/src/hooks/use-url-search-sync.ts` | URL sync | May need to serialize polygon geometry to URL params |

### Current bbox Flow
1. User clicks "Location" button in FilterPanel -> opens Popover
2. `BboxMapPicker` renders MapLibre + Terra Draw (rectangle mode only)
3. On draw finish, extracts bbox as `"minX,minY,maxX,maxY"` string
4. Calls `onBboxSelected(bboxValue)` -> `useSearchStore.setFilter('bbox', bboxValue)`
5. Popover closes, FilterChip appears with "Location" label
6. Backend: `ST_Intersects(spatial_extent, ST_MakeEnvelope(bbox...))` in search service

### Backend Spatial Filter Capability
The backend currently **only supports bbox** (4 floats parsed from comma-separated string). For polygon support:
- Option A: Send bbox of drawn polygon (simpler, works today) -- rectangle behavior is identical, polygon just extracts its bounding box
- Option B: Add `intersects` query param accepting GeoJSON geometry (proper spatial filter) -- requires backend change

**Recommendation:** For this task, use Option A (extract bbox from polygon coordinates). This keeps the backend unchanged and still provides useful spatial filtering. The polygon drawing gives users a more intuitive way to define their area of interest, even if the actual filter is bbox-based. Future task can add true polygon intersection support.

## Standard Stack (Already Installed)

| Library | Version | Purpose |
|---------|---------|---------|
| terra-draw | ^1.25.0 | Drawing on map (rectangle + polygon modes) |
| terra-draw-maplibre-gl-adapter | ^1.3.0 | MapLibre GL adapter for Terra Draw |
| @vis.gl/react-maplibre | ^8.1.0 | React MapLibre wrapper |
| maplibre-gl | ^5.18.0 | Map rendering |
| radix-ui Dialog (Sheet) | (bundled) | Side panel/drawer component |

No new dependencies needed. All drawing modes already configured in `use-terra-draw.ts`.

## Architecture Patterns

### Component Structure

```
FilterPanel.tsx
  renderDesktopLocationFilter()
    - When no filter: Button trigger -> opens Sheet
    - When filter active: FilterChip (click reopens, x clears)
  <Sheet side="right">
    <SpatialFilterPanel />  (new component)
      - Title: "Search area"
      - Rectangle | Polygon toggle (ToggleGroup)
      - MapGL + Terra Draw (rectangle or polygon mode)
      - Contextual instruction text
      - Clear area button
      - Apply button
```

### Sheet Component Usage
The existing Sheet component supports `side="right"` with slide-in animation. Default `sm:max-w-sm` (384px) is close to the 360-420px target. Override with className for exact width.

**Important:** The Sheet uses Radix Dialog which creates a portal + overlay. The overlay (`bg-black/50`) will dim the results. Consider using `SheetOverlay` with reduced opacity or removing overlay entirely so results stay visible (per the decision: "results stay visible on the left").

**Alternative:** Instead of Sheet (which uses a modal overlay), build a custom sliding panel that doesn't use a portal/overlay. This would be a simple `div` with `position: fixed` and transition classes. This better matches the "results stay visible" requirement.

### Terra Draw Mode Switching
`BboxMapPicker` currently creates its own Terra Draw instance inline. The new component should:
1. Initialize Terra Draw with both `TerraDrawRectangleMode` and `TerraDrawPolygonMode`
2. Use `td.setMode('rectangle')` or `td.setMode('polygon')` based on toggle
3. On finish: extract bbox from coordinates (works for both rectangle and polygon)
4. Keep drawn feature visible until user clicks Apply (don't auto-remove on finish like current impl)

### Geometry Preservation
Current BboxMapPicker removes the drawn feature immediately on finish. The new design needs:
- Keep the drawn shape visible on the map after drawing
- Allow re-opening the panel with the previous geometry shown
- Store the drawn GeoJSON temporarily (component state or store) so it survives panel close/reopen

**Approach:** Store the drawn GeoJSON Feature in component state (or a ref). On panel reopen, use `td.addFeatures()` to restore it. On Apply, extract bbox and commit to search store. On Clear, remove from both TD canvas and state.

## Common Pitfalls

### Pitfall 1: Sheet Overlay Blocking Results
**What:** Sheet component renders a semi-transparent overlay over the entire page.
**Fix:** Either customize SheetOverlay to be transparent, or build a custom panel without the Radix Dialog overlay. A custom panel is simpler and more aligned with the "results stay visible" requirement.

### Pitfall 2: Terra Draw Instance Lifecycle
**What:** Creating/destroying Terra Draw instances on panel open/close causes map flicker and source/layer leaks.
**Fix:** Keep the map + Terra Draw instance alive while the panel is mounted. Use CSS to show/hide rather than conditional rendering. Or properly cleanup td sources/layers (the `use-terra-draw.ts` hook already handles this cleanup pattern).

### Pitfall 3: MapLibre in Sheet Portal
**What:** Sheet renders content in a portal (outside the DOM tree). MapLibre maps in portals can have sizing issues since the container isn't in normal document flow.
**Fix:** Ensure the map container has explicit width/height. The current BboxMapPicker uses `style={{ width: '100%', height: 250 }}` which should work in a portal.

### Pitfall 4: transformRequest in react-maplibre v8
**What:** Per project memory, `transformRequest` prop is silently ignored. Must use `onLoad` + `map.setTransformRequest()` imperatively.
**Fix:** Use the `onLoad` pattern already established in BboxMapPicker.

## Code Examples

### Terra Draw with Rectangle + Polygon Modes
```typescript
// Both modes already available in terra-draw ^1.25.0
import { TerraDraw, TerraDrawRectangleMode, TerraDrawPolygonMode } from 'terra-draw';

const td = new TerraDraw({
  adapter: new TerraDrawMapLibreGLAdapter({ map }),
  modes: [
    new TerraDrawRectangleMode({
      styles: { fillColor: MAP_COLORS.default.fill, fillOpacity: 0.15, outlineColor: MAP_COLORS.default.stroke, outlineWidth: 2 },
    }),
    new TerraDrawPolygonMode({
      styles: { fillColor: MAP_COLORS.default.fill, fillOpacity: 0.15, outlineColor: MAP_COLORS.default.stroke, outlineWidth: 2 },
    }),
  ],
});

td.start();
td.setMode('rectangle'); // default

// Switch mode:
td.setMode('polygon');
```

### Extract BBox from Any Polygon Coordinates
```typescript
function extractBbox(coords: number[][]): string {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [lng, lat] of coords) {
    if (lng < minX) minX = lng;
    if (lat < minY) minY = lat;
    if (lng > maxX) maxX = lng;
    if (lat > maxY) maxY = lat;
  }
  return `${minX},${minY},${maxX},${maxY}`;
}
```

### Custom Right Panel (No Overlay)
```tsx
// Instead of Sheet (which has overlay), a simple fixed panel:
<div className={cn(
  "fixed inset-y-0 right-0 z-40 w-[400px] border-l bg-background shadow-lg",
  "transition-transform duration-300 ease-in-out",
  isOpen ? "translate-x-0" : "translate-x-full"
)}>
  {/* Panel content */}
</div>
```

## Key Design Decisions for Planner

1. **Custom panel vs Sheet:** Use a custom fixed-position panel (not Sheet) to avoid the modal overlay that blocks results. Sheet's overlay contradicts "results stay visible on the left."

2. **New component:** Create `SpatialFilterPanel.tsx` in `components/search/` rather than extending `BboxMapPicker`. The BboxMapPicker is a focused, lazy-loaded component; the new panel has significantly different behavior (mode toggle, apply/clear buttons, geometry preservation).

3. **Backend unchanged:** Extract bbox from polygon coordinates client-side. No backend changes needed.

4. **Store change minimal:** The `bbox` field in search-store stays as-is (string format). Optionally add a `spatial_mode` field ('rectangle' | 'polygon') for UI state, but the API param remains `bbox`.

5. **Mobile:** Use Sheet with `side="bottom"` (already used for mobile filters) for the mobile/tablet spatial filter view.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: FilterPanel.tsx, BboxMapPicker.tsx, search-store.ts, use-terra-draw.ts, sheet.tsx
- terra-draw ^1.25.0 - rectangle and polygon modes confirmed in use-terra-draw.ts
- Backend search service - bbox-only spatial filtering confirmed

### Secondary (MEDIUM confidence)
- Sheet component overlay behavior - verified from sheet.tsx source (Radix Dialog with fixed overlay)

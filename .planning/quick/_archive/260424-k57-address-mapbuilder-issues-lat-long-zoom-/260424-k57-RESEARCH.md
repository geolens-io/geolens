# Quick Task 260424-k57: Map Builder UI Fixes - Research

**Researched:** 2026-04-24
**Domain:** MapLibre GL, React widget system, MapBuilder layout
**Confidence:** HIGH

## Summary

Four targeted map builder fixes. The measurement widget has a clear root cause: **dual click handlers** fighting each other. The remaining three issues are straightforward CSS/config changes.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Coordinate pill moves to **top-right corner** (from bottom-right)
- Blank basemap added as **first item in basemap picker grid** with blank/transparent thumbnail
- Blank basemap renders as **fully transparent background** (no tiles, no fill)

### Claude's Discretion
- Legend positioning: reduce bottom offset while respecting ScaleControl
- Measurement widget: investigate root cause and fix
</user_constraints>

## Issue 1: Measurement Widget Broken (CRITICAL)

**Root cause: Click handler conflict between BuilderMap and MeasurementWidget**

Both components register `map.on('click', ...)` handlers on the same MapLibre map instance:

1. **BuilderMap.tsx:288** registers a click handler for feature popups (queryRenderedFeatures). This handler runs on every click, queries features, and opens/closes popups.
2. **MeasurementWidget.tsx:173** registers a click handler for adding measurement points.

When measurement is active, both handlers fire on every click. The BuilderMap handler calls `setPopupInfo(null)` when no features are hit (line 266), which may trigger re-renders. More critically, the BuilderMap mousemove handler (line 284) overrides the cursor to `''` or `'pointer'`, fighting the MeasurementWidget's `crosshair` cursor (line 110).

**However, the real breaking issue is more fundamental:** The MeasurementWidget `useEffect` on line 69 has `[map]` as its dependency. The `ctx.mapInstance` is passed from `widgetCtx` in MapBuilderPage.tsx (line 203-206), which is memoized on `mapInstance` state. The `mapInstance` is set via `handleMapRef` callback. If `mapInstance` is `null` when the widget mounts (the widget can be toggled before the map loads or during basemap style changes), the effect runs with `map = null`, returns early, and **never re-runs** when the map becomes available, because the widget receives `ctx.mapInstance` which may be stale in the closure.

**Additional issue:** When the widget unmounts and remounts (toggled off/on), the GeoJSON source `_measure-src` may already exist on the map from a previous activation if teardown failed silently (line 182 catches all errors). The `if (!map.getSource(MEASURE_SOURCE))` guard prevents re-adding, but the source may have stale data.

**Fix approach:**
1. BuilderMap must **skip its click handler** when measurement widget is active. Pass measurement-active state down or check a shared store.
2. BuilderMap mousemove must also yield cursor control when measurement is active.
3. Alternatively, have the MeasurementWidget call `e.originalEvent.stopPropagation()` -- but MapLibre click events don't support that. The idiomatic approach is to have BuilderMap check the widget store.

**Recommended fix:**
- In BuilderMap.tsx, import `useWidgetStore` and check `activeWidgets.has('measurement')` in the click and mousemove handlers. If measurement is active, skip feature querying and cursor changes.
- This requires a ref to track the active state (to avoid re-registering handlers on every toggle).

[VERIFIED: codebase grep -- BuilderMap.tsx lines 236-296, MeasurementWidget.tsx lines 69-186]

## Issue 2: Coordinate Pill Overlap

**Current state:** `MapCoordReadout` is positioned `absolute bottom-1.5 right-1.5 z-10` inside BuilderMap's container (BuilderMap.tsx:459). MapLibre's default attribution control sits at bottom-right. Both overlap.

**Target:** Move to top-right. The MapToolbar is centered at `top-3 left-1/2 -translate-x-1/2` (MapToolbar.tsx:44), so it does not occupy top-right. NavigationControl is at `bottom-right` (BuilderMap.tsx:447). No other controls exist at top-right inside the BuilderMap container.

The WidgetHost positions `top-right` widgets at `top-12 right-3` (WidgetHost.tsx:16). The coord readout is rendered inside BuilderMap.tsx, while WidgetHost is rendered outside in MapBuilderPage.tsx -- they are in separate DOM containers so no conflict.

**Fix:** Change `bottom-1.5 right-1.5` to `top-2 right-2` in MapCoordReadout.tsx:73. Apply the same change in ViewerMap.tsx (line 517 renders the same component).

[VERIFIED: codebase grep]

## Issue 3: Legend Positioning

**Current state:** Legend anchors at `bottom-left` position: `bottom-20 left-4 z-10` (WidgetHost.tsx:17). That's 80px (5rem) from bottom. ScaleControl is at `bottom-left` (BuilderMap.tsx:448). The default MapLibre ScaleControl is roughly 20-24px tall and sits at the very bottom-left corner.

**Recommendation:** Reduce from `bottom-20` to `bottom-10` (40px from bottom). This clears the ScaleControl (~24px) with comfortable margin while being much tighter to the corner. The attribution control is at bottom-right so it does not conflict.

[VERIFIED: codebase grep]

## Issue 4: Blank Basemap

**Current state:** `toMaplibreStyle()` in basemap-utils.ts handles two patterns:
- JSON style URLs (ending `.json` or containing `/styles/`) -- returned as string
- XYZ raster tile URLs -- wrapped in a `StyleSpecification` object with a raster source

**Blank basemap approach:** A valid MapLibre GL style with no sources and no layers:

```typescript
{
  version: 8,
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': 'rgba(0,0,0,0)' }
    }
  ],
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
}
```

The `background` layer with transparent color is needed because MapLibre renders a black canvas if there are zero layers. The glyphs URL is needed for any text labels on data layers. [ASSUMED -- MapLibre behavior with empty layers array]

**Implementation plan:**
1. Add a sentinel ID (e.g., `'blank'`) and handle it in `toMaplibreStyle()` -- return the transparent style inline.
2. In `BasemapPicker.tsx`, prepend a synthetic blank entry to the `enabled` array. It does not come from the backend basemaps list.
3. Create an inline SVG data URI for the blank thumbnail (similar to existing `FALLBACK_THUMBNAIL` pattern).
4. Add `basemapThumbnail` handling for the `'blank'` ID.

**Basemap style changes and layer re-sync:** When switching to/from blank, the `useEffect` at BuilderMap.tsx:193 detects URL change via `prevBasemapUrlRef` and runs `syncLayersToMap` on `style.load`. Since the blank basemap is an inline StyleSpecification (not a URL string), it loads synchronously -- the `map.isStyleLoaded()` fallback at line 214 handles this correctly.

[VERIFIED: codebase -- toMaplibreStyle signature and BuilderMap style-change effect]

## Common Pitfalls

### Pitfall 1: Measurement cleanup on style change
**What goes wrong:** Basemap switch triggers `style.load`, which destroys all sources/layers including measurement overlays.
**How to avoid:** The MeasurementWidget cleanup in the `useEffect` return already handles this. After basemap switch, if measurement is still active, the effect re-runs (map ref doesn't change). However, points state is preserved in React state, so the overlay should rebuild. Verify this works after fix.

### Pitfall 2: Blank basemap breaks label toggle
**What goes wrong:** `reorderBasemapLabels()` expects basemap-owned label layers. A blank basemap has none.
**How to avoid:** The function should already handle zero label layers gracefully (no-op). Verify.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MapLibre renders black canvas with empty layers array | Issue 4 | Low -- just needs a background layer added |
| A2 | `bottom-10` (40px) clears ScaleControl | Issue 3 | Low -- easy to adjust if too tight |

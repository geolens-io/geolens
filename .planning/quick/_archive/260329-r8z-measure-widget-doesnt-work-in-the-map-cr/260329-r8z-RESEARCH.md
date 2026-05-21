# Quick Task: Measure Widget Doesn't Work in Map Creator - Research

**Researched:** 2026-03-29
**Domain:** MapBuilderPage widget context / maplibre-gl instance lifecycle
**Confidence:** HIGH

## Summary

The measure widget receives `mapInstance: null` because the map reference is passed via a React ref (`mapInstanceRef.current`) that is read during render. Since ref mutations don't trigger re-renders, the WidgetHost ctx object captures `null` at initial render and only gets updated if some unrelated state change causes MapBuilderPage to re-render after the map loads.

**Root cause:** `MapBuilderPage.tsx` line 436 passes `mapInstanceRef.current` directly in JSX. The `handleMapRef` callback (in `use-builder-layers.ts` line 91-93) sets the ref but never triggers a state update.

## Bug Analysis

### The Problem

In `frontend/src/pages/MapBuilderPage.tsx:436`:
```tsx
<WidgetHost ctx={{ mapInstance: mapInstanceRef.current, layers: layers.localLayers, mapId: id! }} />
```

`mapInstanceRef` is a `useRef<MaplibreMap | null>(null)` (line 68). When the BuilderMap mounts and calls `onMapRef`, the callback in `use-builder-layers.ts` does:
```ts
const handleMapRef = useCallback((map: MaplibreMap | null) => {
  (mapInstanceRef as React.MutableRefObject<MaplibreMap | null>).current = map;
}, [mapInstanceRef]);
```

This updates the ref but does NOT call any state setter, so no re-render is triggered. The `WidgetHost` continues receiving `null` until something else (like a layer state change) causes a re-render.

### Why It Sometimes Appears to Work

If layer data from the API arrives after the map loads, the `setLocalLayers()` call triggers a re-render that picks up the now-populated `mapInstanceRef.current`. But this is a race condition -- if the map loads slowly or layers load fast, the widget gets `null`.

### Impact on MeasurementWidget

In `MeasurementWidget.tsx:63`:
```ts
const map = ctx.mapInstance;
```

When `map` is `null`, the `useEffect` on line 66 short-circuits (`if (!map) return`), so:
- No source/layer is added to the map
- No click handler is registered
- The cursor never changes to crosshair
- Clicking the map does nothing

## Fix

**Option A (recommended): Add a state variable for the map instance.**

In `MapBuilderPage.tsx`, add a state that gets set alongside the ref:

```tsx
const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);

const handleMapRef = useCallback((map: MaplibreMap | null) => {
  layers.handleMapRef(map);
  setMapInstance(map);
  if (map) save.maybeAutoCaptureThumbnail(map);
}, [layers, save]);

// Then in JSX:
<WidgetHost ctx={{ mapInstance, layers: layers.localLayers, mapId: id! }} />
```

This ensures a re-render happens when the map instance becomes available, so widgets always get the current map.

**Option B: Force re-render from handleMapRef in the hook.**

Add a dummy state counter in `use-builder-layers.ts` that increments when the map ref is set. Less clean but contained in the hook.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/pages/MapBuilderPage.tsx` | Add `mapInstance` state, update `handleMapRef`, pass state to WidgetHost |

## Common Pitfalls

### Pitfall 1: Breaking Other Consumers of mapInstanceRef
The ref is used extensively in `use-builder-layers.ts` for imperative map operations (zoom, style sync, ephemeral layers). The fix should keep the ref AND add state -- don't replace the ref.

### Pitfall 2: Double Effect Runs
Adding a state variable that changes will cause MeasurementWidget's `useEffect([map])` to run. This is correct behavior -- the cleanup function properly removes layers/handlers before re-adding them.

### Pitfall 3: Stale Map on Style Change
When basemap changes, maplibre may create a new style context. The ref stays the same object, but sources/layers get cleared. The MeasurementWidget already handles this correctly since its `useEffect` cleanup removes its layers and the next click re-adds them.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `MapBuilderPage.tsx`, `use-builder-layers.ts`, `MeasurementWidget.tsx`, `WidgetHost.tsx`
- React documentation: refs don't trigger re-renders (fundamental React behavior)

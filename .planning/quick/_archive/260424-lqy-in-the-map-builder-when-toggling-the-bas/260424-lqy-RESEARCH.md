# Quick Task: Basemap Selector Race Condition + UX Polish - Research

**Researched:** 2026-04-24
**Domain:** MapLibre GL style switching, React effect lifecycle
**Confidence:** HIGH

## Summary

The layer-loss bug on rapid basemap toggling is caused by a race condition in the `style.load` listener pattern at `BuilderMap.tsx:205-234`. The effect uses `map.once('style.load', ...)` and re-registers it each time `basemapEntry?.url` changes. When the user switches basemaps 4 times in quick succession, each URL change triggers the effect cleanup (which calls `map.off` on the previous listener), but `setStyle()` is called by `@vis.gl/react-maplibre` independently on each prop change. The final `style.load` event may fire after the cleanup has already removed the listener, leaving no handler to call `syncLayersToMap()`.

The fix is to adopt the same persistent-listener pattern that `ViewerMap.tsx:457-477` already uses: register `map.on('style.load', ...)` once (not per-URL-change), reset managed sources inside the handler, and let it survive any number of rapid style swaps.

**Primary recommendation:** Replace the `once`-per-URL-change effect with a single persistent `style.load` listener (matching ViewerMap), fix the glyph URL to use OpenFreeMap's CORS-safe endpoint, and polish the BasemapPicker CSS.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Implementation Decisions
- **Polish current pattern**: Keep the dropdown grid approach. Fix thumbnail sizing, add a visible selected-state ring, improve expand/collapse animation, and clean up the "Show place labels" toggle placement.
- Do NOT redesign into a popover, sidebar panel, or fundamentally different interaction pattern.
- **Fix the race condition only**: Keep `styleDiffing={false}` + `style.load` event re-sync pattern. Fix the race by debouncing basemap changes, cancelling stale `style.load` listeners, and ensuring the final `style.load` always fires `syncLayersToMap()`.
- Do NOT switch to `transformStyle` callback approach.
- The blank basemap's fallback glyph URL (`demotiles.maplibre.org`) causes CORS errors -- fix by using a CORS-safe glyph URL or skipping glyphs for inline styles.

### Claude's Discretion
- Specific debounce timing and implementation details
- Exact thumbnail dimensions and selected-state styling
- Whether to animate the basemap grid expansion or keep it instant

</user_constraints>

## Race Condition Root Cause Analysis

### The Bug Mechanism

**Confidence: HIGH** [VERIFIED: source code analysis of BuilderMap.tsx, ViewerMap.tsx, and @vis.gl/react-maplibre internals]

The style switching pipeline has three participants:

1. **React state** (`localBasemap` in `use-builder-layers.ts`) -- set by `BasemapPicker.onChange`
2. **`@vis.gl/react-maplibre`** -- compares `mapStyle` prop on each render, calls `this._map.setStyle(normalizeStyle(mapStyle), { diff: false })` when it changes (line 363 of maplibre.js in the package)
3. **BuilderMap effect** (lines 205-234) -- watches `basemapEntry?.url`, registers `map.once('style.load', onStyleLoad)` to re-sync layers after the style wipe

When the user clicks 4 basemaps rapidly (A -> B -> C -> D):

| Step | What happens | Problem |
|------|-------------|---------|
| 1 | React queues render with URL=B | |
| 2 | Effect cleanup removes listener-A, registers `once` listener-B | |
| 3 | `setStyle(B)` called by react-maplibre | Style B starts loading (async for JSON URLs) |
| 4 | React queues render with URL=C before style B loads | |
| 5 | Effect cleanup removes listener-B, registers `once` listener-C | **listener-B never fired** |
| 6 | `setStyle(C)` called -- cancels style B load, starts style C | Style B's `style.load` never fires |
| 7 | Repeat for URL=D -- listener-C removed, listener-D registered | |
| 8 | Style D loads, fires `style.load` | listener-D fires, but... |
| 9 | `isStyleLoaded()` check at line 227 may also fire synchronously for inline styles | **Possible double-sync or missed sync** |

The critical failure: if the final `style.load` fires during or before React processes the effect cleanup/setup for URL=D, the listener may not be registered yet. React batches state updates and effects run after paint -- the timing gap between `setStyle()` (called during render reconciliation by react-maplibre) and the effect registration (runs after commit) is the window where events get lost.

### Why ViewerMap Doesn't Have This Bug

ViewerMap (lines 457-477) uses a different pattern:

```typescript
// ViewerMap: persistent listener, registered once
map.on('style.load', onStyleLoad);   // not .once()
return () => { map.off('style.load', onStyleLoad); };
// deps: [mapReady, runSync, reseedTerrainOnStyleLoad] -- NOT basemap URL
```

This listener survives all basemap changes because:
- It is registered once when the map is ready
- It is never torn down on URL changes
- It reads current layer state from `syncInputsRef.current` (a ref, not a closure)
- Every `style.load` event, regardless of which basemap triggered it, runs the sync

### Recommended Fix

Adopt the ViewerMap pattern in BuilderMap. Replace lines 205-234 with:

```typescript
// Re-add data layers after basemap switch (persistent listener)
useEffect(() => {
  const map = mapRef.current;
  if (!map) return;

  const onStyleLoad = () => {
    const { layers: l, tokenMap: t, tileConfig: tc, showBasemapLabels: sbl } = syncInputsRef.current;
    managedSourcesRef.current = new Set();
    lastOrderKeyRef.current = '';
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
    syncLayersToMap(map, l.map(toSyncInput), t, tileBaseUrl, managedSourcesRef, lastOrderKeyRef);
    reorderBasemapLabels(map, sbl);
    refreshQueryLayerIds();
  };

  map.on('style.load', onStyleLoad);
  return () => {
    map.off('style.load', onStyleLoad);
  };
}, [mapReady]);  // register once when map is ready
```

Key differences from current code:
- `map.on` instead of `map.once` -- survives multiple style changes
- No `basemapEntry?.url` dependency -- no teardown/re-register on each switch
- Resets `lastOrderKeyRef` so layer order is always re-applied
- Removes `prevBasemapUrlRef` guard (no longer needed)
- Removes the synchronous `isStyleLoaded()` fallback (lines 227-230) -- the persistent listener catches all events

**Debounce recommendation:** Debouncing is NOT needed with the persistent-listener fix. The root cause was listener lifecycle, not event frequency. Each `style.load` event will correctly trigger a full re-sync via `syncInputsRef.current`. However, if desired for performance (avoiding 4 rapid `setStyle` calls), a 150ms debounce on `setLocalBasemap` in the BasemapPicker's `onChange` callback would work -- but the UI should show the selected state immediately (optimistic UI).

## CORS Glyph Fix

**Confidence: HIGH** [VERIFIED: HTTP probes against both endpoints]

### Current Problem

`basemap-utils.ts` uses `https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf` as fallback glyphs for inline styles (blank basemap at line 76, raster basemaps at line 94). This endpoint:

- Returns 404 for font stacks like "Noto Sans Regular" (used by OpenFreeMap styles) [VERIFIED: curl probe returns HTTP 404]
- Works for "Open Sans Regular,Arial Unicode MS Regular" but not the fonts used by this project's basemap ecosystem
- The 404s surface as CORS errors in the browser console because the error response may not include proper CORS headers [VERIFIED: context evidence of 58 CORS errors]

### Fix

Replace with `https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf`:

- Returns 200 with `access-control-allow-origin: *` for individual fontstacks [VERIFIED: curl probe]
- Already used by the project's primary basemap provider (OpenFreeMap positron/dark styles)
- Serves "Noto Sans Regular", "Noto Sans Bold", etc. [VERIFIED: curl probe]

However, the blank basemap has zero symbol/text layers, so it will never request glyphs. The simplest fix for the blank basemap specifically is to omit the `glyphs` property entirely. For raster basemaps (line 83-96), keep the glyphs property but use the OpenFreeMap URL since data layers with labels may need it.

```typescript
const FALLBACK_GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
```

Update both occurrences: line 13 (constant) and line 94 (inline in raster style object, which should reference the constant instead of hardcoding a duplicate URL).

## BasemapPicker UX Polish

**Confidence: HIGH** [VERIFIED: source code analysis of BasemapPicker.tsx]

### Current Issues

1. **Thumbnails**: `w-8 h-8` (32px) in collapsed row is fine, but expanded grid uses `w-full aspect-square` which makes thumbnails as wide as 1/4 of the sidebar (~60px). No max constraint.

2. **Selected state**: Uses `ring-2 ring-primary bg-accent` which is functional but could be more prominent. The ring blends with the accent background.

3. **Expand/collapse**: Binary `{open && (...)}` -- no transition animation. Grid appears/disappears instantly.

4. **Labels toggle**: Positioned below the grid with `px-2 pt-1.5`. Feels disconnected from the basemap section. The native checkbox (`<input type="checkbox">`) looks inconsistent with the rest of the UI which uses Tailwind/shadcn patterns.

5. **Grid closes on select**: Line 60 calls `setOpen(false)` on select, which is good for single-pick but prevents quick comparison.

### Recommended Polish

| Area | Change | Detail |
|------|--------|--------|
| Collapsed thumbnail | Keep `w-8 h-8` | Appropriate for sidebar density |
| Grid thumbnails | Add `max-h-14` or similar | Prevent oversized thumbnails on wide sidebars |
| Selected ring | `ring-2 ring-primary ring-offset-2 ring-offset-background` | Ring offset creates visual separation, theme-aware offset color |
| Expand animation | CSS `grid-rows` transition or `max-height` transition | Smooth expand with `transition-[grid-template-rows] duration-200` using the `grid-rows-[0fr]`/`grid-rows-[1fr]` pattern |
| Labels toggle | Move inside the collapsed row (right side) or directly below the collapsed button | Keeps it spatially grouped with basemap controls |
| Labels toggle styling | Use a `Switch` component if available, or style the checkbox to match shadcn patterns | Visual consistency |

### Expand Animation Pattern

The `grid-rows-[0fr]` / `grid-rows-[1fr]` CSS technique is the cleanest for content-height transitions:

```tsx
<div className={cn(
  "grid transition-[grid-template-rows] duration-200 ease-out",
  open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
)}>
  <div className="overflow-hidden">
    {/* grid content */}
  </div>
</div>
```

This avoids measuring content height and works with Tailwind's transition utilities. [ASSUMED: Tailwind v3.4+ supports arbitrary grid-rows values via bracket notation]

## Common Pitfalls

### Pitfall 1: Initial style.load on map creation
**What goes wrong:** The persistent `style.load` listener fires on the initial map load too, before any basemap switch occurs.
**How to avoid:** This is actually fine -- `syncLayersToMap` is idempotent and safe to call multiple times. The initial load will run the sync effect anyway via the `[structuralKey, mapReady]` dependency. Double-syncing on initial load is harmless (sources already exist, adapter `syncPaint` handles updates).

### Pitfall 2: Stale closure in style.load handler
**What goes wrong:** If the handler captures `layers` or `tokenMap` from a closure, it reads stale data.
**How to avoid:** Read from `syncInputsRef.current` (already the pattern in both BuilderMap and ViewerMap). The ref is updated on every render at line 127.

### Pitfall 3: isStyleLoaded() race with inline styles
**What goes wrong:** Inline style objects (blank, raster basemaps) load synchronously. The `style.load` event may fire before the persistent listener is registered (if the effect runs after the render that triggers `setStyle`).
**How to avoid:** With a persistent listener (registered once on `mapReady`), the listener is already in place before any basemap switch occurs. The first style load (initial) also triggers the handler, so the timing is correct. This is only a problem with the `once`-per-switch pattern where the effect registers the listener after the render.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Tailwind v3.4+ supports `grid-rows-[0fr]`/`grid-rows-[1fr]` bracket notation for expand animation | BasemapPicker UX Polish | Low -- fallback to `max-height` transition or instant toggle |

## Sources

### Primary (HIGH confidence)
- `BuilderMap.tsx` lines 205-234 -- the buggy effect (direct source analysis)
- `ViewerMap.tsx` lines 457-477 -- the working persistent-listener pattern
- `@vis.gl/react-maplibre` dist/maplibre/maplibre.js line 354-363 -- setStyle call path
- `basemap-utils.ts` lines 13, 76, 94 -- FALLBACK_GLYPHS constant and usage
- curl probes of `tiles.openfreemap.org/fonts/` (200 OK, CORS `*`) and `demotiles.maplibre.org/font/` (404 for Noto Sans)
- OpenFreeMap positron style JSON -- confirms glyphs URL pattern `tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf`

### Secondary (MEDIUM confidence)
- MapLibre GL JS Context7 docs -- event handling patterns (`on`, `once`, `off`)

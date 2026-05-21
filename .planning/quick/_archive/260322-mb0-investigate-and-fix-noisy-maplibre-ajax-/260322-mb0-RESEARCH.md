# Quick Task: Noisy MapLibre AJAX Errors from Raster Tiles - Research

**Researched:** 2026-03-22
**Domain:** MapLibre raster tile error handling, Titiler no-data responses, nginx proxy behavior
**Confidence:** HIGH

## Summary

Raster tiles served via Titiler return HTTP errors (likely 404 or 500) for tile coordinates outside the raster extent. In production, nginx proxies these responses directly to the browser because `proxy_intercept_errors` is not configured in the `raster-tiles` location block. MapLibre logs every failed tile fetch as a console error via its internal `map.fire('error', ...)` mechanism.

The DatasetMap (detail page) already handles this via a `map.on('error', ...)` listener with a threshold (3 consecutive or >50% with 4+ total), but BuilderMap has **zero error handling** for tile fetch failures. With multiple raster layers in a builder session, every out-of-extent tile request generates a console error, and there is no suppression.

**Primary recommendation:** Add an `error` event listener to BuilderMap that silently absorbs expected raster tile 404s (Titiler no-data), and optionally configure nginx to return 204 (empty) for Titiler 404s to eliminate the AJAX errors at the proxy layer.

## Root Cause Analysis

### 1. Titiler Returns HTTP Errors for No-Data Tiles

When MapLibre requests a tile at coordinates outside the raster's spatial extent, the request flows:
- **Production (nginx):** Browser -> nginx `/raster-tiles/{id}/tiles/{z}/{x}/{y}.png` -> Titiler `/cog/tiles/...`
- **Dev (Vite proxy):** Browser -> Vite `/raster-tiles/...` -> API `/tiles/raster-proxy/...` -> Titiler

Titiler returns HTTP 404 (or sometimes 500) for tiles outside the raster extent. The API-side proxy (`raster_tile_proxy` at `backend/app/tiles/router.py:209-256`) converts 404 to 204, but **nginx does NOT** -- it passes the raw Titiler response through.

**Key evidence:**
- `backend/app/tiles/router.py:246-248`: API proxy handles 404 -> 204 conversion
- `frontend/nginx.conf:43-68`: No `proxy_intercept_errors` or `error_page` directives in the raster-tiles location

### 2. MapLibre Fires Error Events for Failed Tile Fetches

MapLibre-gl fires `error` events on the map instance for any tile HTTP error (4xx, 5xx). These also appear as console errors (`Error: AJAXError: ...`). There is no built-in way to suppress them at the source level.

### 3. BuilderMap Has No Error Handler

| Component | Error Handling | File:Line |
|-----------|---------------|-----------|
| DatasetMap | `map.on('error', ...)` with threshold logic | `frontend/src/components/dataset/DatasetMap.tsx:619-631` |
| BuilderMap | **None** | `frontend/src/components/builder/BuilderMap.tsx` (entire file) |

The DatasetMap error handler (lines 619-631) only fires `onTileError` after exceeding a threshold, but it does NOT suppress the console errors themselves. However, it at least gates the user-visible error state.

BuilderMap has no error listener at all. Every raster tile 404 goes to console unhandled.

### 4. Builder Multiplies the Problem

In a builder session with N raster layers, each zoomed/panned view can trigger M out-of-extent tile requests per layer. With N=3 raster layers and M=8 tiles per viewport, that is 24 console errors per pan/zoom action on areas outside the smallest raster extent.

## Fix Strategy

### Option A: nginx-level fix (recommended, eliminates errors at source)

Add `proxy_intercept_errors` and `error_page` to the nginx raster-tiles location to convert Titiler 404s into 204 (empty response with no body). This prevents the error from ever reaching MapLibre.

```nginx
location ~ ^/raster-tiles/... {
    # ... existing config ...
    proxy_intercept_errors on;
    error_page 404 = @empty_tile;
}

location @empty_tile {
    return 204;
}
```

**Confidence:** HIGH -- this is a standard nginx pattern for tile servers.

**Caveat:** This also suppresses legitimate 404s (e.g., bad dataset_id), but those are already gated by the auth_request subrequest which returns 404 before the proxy_pass fires.

### Option B: BuilderMap error listener (defense in depth)

Add `map.on('error', ...)` in BuilderMap's `handleLoad` to absorb raster tile errors. This mirrors DatasetMap's pattern but without necessarily needing the threshold/overlay logic (builder has no "error overlay" UX).

```typescript
// In handleLoad, after setting transformRequest:
map.on('error', (e: { error: { message?: string; status?: number } }) => {
  // Suppress expected raster tile errors (no-data tiles outside extent)
  // MapLibre fires these for any tile HTTP error; silence them to avoid console noise
});
```

MapLibre does not provide a way to truly suppress the console.error output from within the error event handler -- the error is logged before the event fires. The only way to fully silence it is to prevent the HTTP error (Option A).

### Option C: Combined (recommended)

1. nginx 204 for Titiler 404s (eliminates console noise)
2. BuilderMap error listener (graceful handling for non-404 errors like 500s, timeouts)

## Affected Files

| File | Change | Purpose |
|------|--------|---------|
| `frontend/nginx.conf:43-68` | Add `proxy_intercept_errors on` + `error_page 404` | Suppress Titiler 404s at proxy |
| `frontend/src/components/builder/BuilderMap.tsx` | Add `map.on('error', ...)` in `handleLoad` | Graceful error handling for non-404 tile errors |
| `frontend/vite.config.ts` | N/A (Vite proxy already routes through API which returns 204) | Dev path already correct |

## Common Pitfalls

### Pitfall 1: Suppressing All Errors
**What goes wrong:** Catching all map errors hides real problems (broken basemaps, auth failures)
**How to avoid:** Only suppress errors matching raster tile source IDs (`source-{layerId}`)

### Pitfall 2: MapLibre console.error Timing
**What goes wrong:** Assuming `map.on('error')` can prevent console output -- it cannot, the error is logged before the event fires
**How to avoid:** The nginx fix (Option A) is the only way to fully eliminate console noise. The JS handler is for application-level logic only.

### Pitfall 3: nginx error_page and auth_request interaction
**What goes wrong:** `error_page` could intercept auth_request 404s
**How to avoid:** The `error_page` only applies to the proxy_pass response (Titiler), not the auth_request subrequest. The auth_request uses a separate internal location.

## Validation

- Add a raster dataset with small spatial extent to builder
- Pan to area outside extent
- Verify: no console AJAX errors (with nginx fix)
- Verify: no user-visible error state in builder (with JS fix)
- Verify: raster tiles still load correctly within extent

## Sources

### Primary (HIGH confidence)
- `frontend/src/components/builder/BuilderMap.tsx` -- no error handler present
- `frontend/src/components/dataset/DatasetMap.tsx:619-631` -- existing error handler pattern
- `backend/app/tiles/router.py:246-248` -- API proxy 404->204 conversion
- `frontend/nginx.conf:43-68` -- no proxy_intercept_errors
- MapLibre-gl error event behavior verified via source code knowledge

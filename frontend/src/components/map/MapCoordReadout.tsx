import { memo, useEffect, useState, useRef } from 'react';
import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';
import { formatRepresentativeFraction } from '@/lib/representative-fraction';

interface MapCoordReadoutProps {
  map: MaplibreMap | null;
  /** When true, appends a "1:N" representative-fraction segment. Default: false. */
  showScale?: boolean;
}

/**
 * Live coordinate readout anchored to the top-right of the map canvas.
 * Shows lat, lon, and zoom level — updates on:
 *   - `move`        → tracks programmatic flyTo / fitBounds / inertial pan
 *                     (Phase 1045 SP-02 / M-01 fix: before this, lat/lng
 *                     never updated after auto-fit because only `mousemove`
 *                     fired setCoords; programmatic camera moves were invisible
 *                     to the readout).
 *   - `mousemove`   → tracks the cursor's geographic position while inside
 *                     the canvas (existing behavior — preserved).
 *   - canvas leave  → fall back to the current map center so the readout
 *                     reflects the viewport instead of stale cursor coords.
 *
 * Uses font-mono for an instrument/cartographic feel.
 *
 * Positioning contract (RESP-02 — Phase 1051 Plan 09):
 *   The pill anchors at `top-2 right-14` (8px from top, 56px from right edge).
 *   The 56px right offset exists to clear the MapLibre `NavigationControl`
 *   when it is anchored `top-right` — which is the case in `ViewerMap.tsx`.
 *   In `BuilderMap.tsx`, Phase 1051 Plan 08 (RESP-01, commit 391459bb) moved
 *   the NavigationControl to `top-left`, so the original RESP-02 collision
 *   surface no longer exists in the builder context — but `right-14` is
 *   load-bearing for the viewer and must NOT be reduced without first
 *   confirming the NavigationControl position at every call site.
 *   Top-right WidgetHost slot (`WidgetHost.tsx:17`) sits at `top-12 right-3`
 *   — 40px below this pill — so there is no vertical collision with any
 *   floating widget at the same horizontal band.
 */
export const MapCoordReadout = memo(function MapCoordReadout({
  map,
  showScale = false,
}: MapCoordReadoutProps) {
  const [coords, setCoords] = useState<{ lat: number; lng: number; zoom: number } | null>(null);
  const rafRef = useRef(0);

  useEffect(() => {
    if (!map) return;

    let disposed = false;

    // Initialize with map center
    const center = map.getCenter();
    setCoords({ lat: center.lat, lng: center.lng, zoom: map.getZoom() });

    const updateFromCenter = () => {
      if (disposed) return;
      const c = map.getCenter();
      const lat = parseFloat(c.lat.toFixed(2));
      const lng = parseFloat(c.lng.toFixed(2));
      const zoom = parseFloat(map.getZoom().toFixed(1));
      setCoords((prev) => {
        if (prev && prev.lat === lat && prev.lng === lng && prev.zoom === zoom) return prev;
        return { lat, lng, zoom };
      });
    };

    const onMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (disposed) return;
        const lat = parseFloat(e.lngLat.lat.toFixed(2));
        const lng = parseFloat(e.lngLat.lng.toFixed(2));
        const zoom = parseFloat(map.getZoom().toFixed(1));
        setCoords((prev) => {
          if (prev && prev.lat === lat && prev.lng === lng && prev.zoom === zoom) return prev;
          return { lat, lng, zoom };
        });
      });
    };

    // SP-02: `move` fires on every camera change — programmatic flyTo /
    // fitBounds, drag-pan, inertial pan, etc. — and is the canonical signal
    // for "viewport changed". Without it the readout starts at the map
    // center and never updates if the user never hovers the canvas.
    const onMove = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(updateFromCenter);
    };

    const onMouseLeave = () => {
      if (disposed) return;
      updateFromCenter();
    };

    map.on('move', onMove);
    map.on('mousemove', onMouseMove);
    const canvas = map.getCanvas?.();
    canvas?.addEventListener('mouseleave', onMouseLeave);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafRef.current);
      map.off('move', onMove);
      map.off('mousemove', onMouseMove);
      canvas?.removeEventListener('mouseleave', onMouseLeave);
    };
  }, [map]);

  if (!coords) return null;

  const latDir = coords.lat >= 0 ? 'N' : 'S';
  const lngDir = coords.lng >= 0 ? 'E' : 'W';

  // SP-12: derive RF value at render time from existing coords state.
  // Uses same coords.lat as the lat segment (mouse position during hover,
  // viewport center otherwise). No new subscription needed.
  // formatRepresentativeFraction returns e.g. "1:288k"; we strip the "1:" prefix
  // so we can render the prefix as a muted span (mirroring the "z" prefix at line 100).
  const rfValue = showScale
    ? formatRepresentativeFraction(coords.lat, coords.zoom).slice(2)
    : null;

  return (
    <div className="absolute top-2 right-14 z-10 pointer-events-none">
      <div className="font-mono text-2xs tracking-wide text-muted-foreground/70 bg-background/60 backdrop-blur-sm rounded px-1.5 py-0.5">
        {Math.abs(coords.lat).toFixed(2)}° {latDir}
        {' · '}
        {Math.abs(coords.lng).toFixed(2)}° {lngDir}
        {' · '}
        <span className="text-foreground/50">z</span> {coords.zoom.toFixed(1)}
        {showScale && rfValue != null && (
          <>
            {' · '}
            <span className="text-foreground/50">1:</span>
            {rfValue}
          </>
        )}
      </div>
    </div>
  );
});

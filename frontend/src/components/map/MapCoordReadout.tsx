import { memo, useEffect, useState, useRef } from 'react';
import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';

interface MapCoordReadoutProps {
  map: MaplibreMap | null;
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
 */
export const MapCoordReadout = memo(function MapCoordReadout({ map }: MapCoordReadoutProps) {
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

  return (
    <div className="absolute top-2 right-2 z-10 pointer-events-none">
      <div className="font-mono text-2xs tracking-wide text-muted-foreground/70 bg-background/60 backdrop-blur-sm rounded px-1.5 py-0.5">
        {Math.abs(coords.lat).toFixed(2)}° {latDir}
        {' · '}
        {Math.abs(coords.lng).toFixed(2)}° {lngDir}
        {' · '}
        <span className="text-foreground/50">z</span> {coords.zoom.toFixed(1)}
      </div>
    </div>
  );
});

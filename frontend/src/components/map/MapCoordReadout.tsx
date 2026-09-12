import { memo, useEffect, useState, useRef } from 'react';
import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';
import { formatRepresentativeFraction } from '@/lib/representative-fraction';

interface MapCoordReadoutProps {
  map: MaplibreMap | null;
  /** When true, appends a "1:N" representative-fraction segment. Default: false. */
  showScale?: boolean;
}

/**
 * Live coordinate readout that follows the cursor, camera movement, and canvas
 * exit. The `right-14` offset clears ViewerMap's
 * top-right navigation control. BuilderMap currently places that control on the
 * left; verify both call sites before changing the shared offset.
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

    // `move` also covers programmatic camera changes before the first hover.
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

  // Render the "1:" prefix separately so it can use muted styling.
  const rfValue = showScale
    ? formatRepresentativeFraction(coords.lat, coords.zoom).slice(2)
    : null;

  return (
    <div
      data-coord-readout="true"
      className="pointer-events-none absolute right-14 top-2 z-10 hidden sm:block"
    >
      <div className="rounded-sm border border-border bg-popover px-1.5 py-0.5 font-mono text-2xs tracking-wide text-popover-foreground shadow-sm">
        {Math.abs(coords.lat).toFixed(2)}° {latDir}
        {' · '}
        {Math.abs(coords.lng).toFixed(2)}° {lngDir}
        {' · '}
        <span className="text-muted-foreground">z</span> {coords.zoom.toFixed(1)}
        {showScale && rfValue != null && (
          <>
            {' · '}
            <span className="text-muted-foreground">1:</span>
            {rfValue}
          </>
        )}
      </div>
    </div>
  );
});

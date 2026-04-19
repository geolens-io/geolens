import { useEffect, useState, useRef } from 'react';
import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl';

interface MapCoordReadoutProps {
  map: MaplibreMap | null;
}

/**
 * Live coordinate readout anchored to the bottom-right of the map canvas.
 * Shows lat, lon, and zoom level — updates on mousemove and zoomend.
 * Uses font-mono for an instrument/cartographic feel.
 */
export function MapCoordReadout({ map }: MapCoordReadoutProps) {
  const [coords, setCoords] = useState<{ lat: number; lng: number; zoom: number } | null>(null);
  const rafRef = useRef(0);

  useEffect(() => {
    if (!map) return;

    let disposed = false;

    // Initialize with map center
    const center = map.getCenter();
    setCoords({ lat: center.lat, lng: center.lng, zoom: map.getZoom() });

    const onMouseMove = (e: MapMouseEvent) => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (disposed) return;
        const lat = parseFloat(e.lngLat.lat.toFixed(4));
        const lng = parseFloat(e.lngLat.lng.toFixed(4));
        const zoom = parseFloat(map.getZoom().toFixed(1));
        setCoords((prev) => {
          if (prev && prev.lat === lat && prev.lng === lng && prev.zoom === zoom) return prev;
          return { lat, lng, zoom };
        });
      });
    };

    const onZoom = () => {
      if (disposed) return;
      setCoords((prev) =>
        prev ? { ...prev, zoom: map.getZoom() } : { lat: map.getCenter().lat, lng: map.getCenter().lng, zoom: map.getZoom() },
      );
    };

    const onMouseLeave = () => {
      if (disposed) return;
      const center = map.getCenter();
      setCoords({ lat: center.lat, lng: center.lng, zoom: map.getZoom() });
    };

    map.on('mousemove', onMouseMove);
    map.on('zoomend', onZoom);
    const canvas = map.getCanvas?.();
    canvas?.addEventListener('mouseleave', onMouseLeave);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafRef.current);
      map.off('mousemove', onMouseMove);
      map.off('zoomend', onZoom);
      canvas?.removeEventListener('mouseleave', onMouseLeave);
    };
  }, [map]);

  if (!coords) return null;

  const latDir = coords.lat >= 0 ? 'N' : 'S';
  const lngDir = coords.lng >= 0 ? 'E' : 'W';

  return (
    <div className="absolute bottom-1.5 right-1.5 z-10 pointer-events-none">
      <div className="font-mono text-2xs tracking-wide text-muted-foreground/70 bg-background/60 backdrop-blur-sm rounded px-1.5 py-0.5">
        {Math.abs(coords.lat).toFixed(4)}° {latDir}
        {' · '}
        {Math.abs(coords.lng).toFixed(4)}° {lngDir}
        {' · '}
        <span className="text-foreground/50">z</span> {coords.zoom.toFixed(1)}
      </div>
    </div>
  );
}

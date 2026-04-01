import { useEffect, useState, type RefObject } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';

/**
 * Detect WebGL context loss on a MapLibre map and provide recovery state.
 * When context is lost, `contextLost` becomes true and an overlay should
 * be rendered. When context is restored, `contextLost` resets to false.
 */
export function useWebGLRecovery(
  mapRef: RefObject<MaplibreMap | null>,
  mapReady: boolean,
) {
  const [contextLost, setContextLost] = useState(false);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const canvas = map.getCanvas();
    if (!canvas) return;

    const onLost = (e: Event) => {
      e.preventDefault(); // allow context restoration
      setContextLost(true);
    };

    const onRestored = () => {
      setContextLost(false);
      // Force a full re-render of the map style
      try {
        const style = map.getStyle();
        if (style) map.setStyle(style);
      } catch {
        // map may be in a broken state — reload will handle it
      }
    };

    canvas.addEventListener('webglcontextlost', onLost);
    canvas.addEventListener('webglcontextrestored', onRestored);

    return () => {
      canvas.removeEventListener('webglcontextlost', onLost);
      canvas.removeEventListener('webglcontextrestored', onRestored);
    };
  }, [mapRef, mapReady]);

  return { contextLost, reload: () => window.location.reload() };
}

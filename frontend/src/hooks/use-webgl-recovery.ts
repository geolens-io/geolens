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
      // RES-N6: surface WebGL context loss as a structured console.warn so
      // production issues are detectable in browser logs / error trackers.
      // Common causes: GPU driver crash, GPU eviction under memory pressure,
      // extension blocking canvas2d interop, tab kill-switch under Chrome.
      console.warn('[map] WebGL context lost', {
        userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : 'unknown',
        timestamp: new Date().toISOString(),
      });
    };

    const onRestored = () => {
      setContextLost(false);
      console.warn('[map] WebGL context restored');
      // Force a full re-render of the map style
      try {
        const style = map.getStyle();
        if (style) map.setStyle(style);
      } catch (err) {
        console.error('WebGL recovery: style restoration failed', err);
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

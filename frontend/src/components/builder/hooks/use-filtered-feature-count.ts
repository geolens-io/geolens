/**
 * EASY-18 (Phase 1138-03): Hook that returns the rendered-feature count for
 * `layer` on `map` using map.queryRenderedFeatures, idle-debounced.
 *
 * READ-ONLY API: queryRenderedFeatures is not covered by Pitfall #9
 * (which forbids only write APIs: setPaintProperty / setLayoutProperty /
 * setFilter). This hook is allowed to call queryRenderedFeatures because
 * it never mutates the map — it only inspects rendered state.
 *
 * Returns null when:
 *   - map is null (no instance yet)
 *   - layer is null
 *   - layer has no filter (the zero-state hint only matters when a filter is set)
 *   - the layer's MapLibre layer id is not yet on the map (rendered count
 *     would be 0 incorrectly while the source is loading — treat as null)
 */
import { useEffect, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

export function useFilteredFeatureCount(
  map: MaplibreMap | null,
  layer: MapLayerResponse | null,
): number | null {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    if (!map) return;
    if (!layer) return;
    if (!layer.filter) {
      // No filter → "0 features after filter" hint should never fire.
      setCount(null);
      return;
    }

    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function recompute() {
      if (cancelled) return;
      if (!map) return;
      if (!layer) return;
      // queryRenderedFeatures returns [] when the layer id is not on the
      // map (source still loading, layer hidden, etc.) — treat as null
      // so the hint does not flash false positives during loading.
      const layerExistsOnMap = !!map.getLayer(layer.id);
      if (!layerExistsOnMap) {
        setCount(null);
        return;
      }
      const features = map.queryRenderedFeatures(undefined, { layers: [layer.id] });
      setCount(features.length);
    }

    function handleIdle() {
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(recompute, 250);
    }

    // Initial compute (in case the map is already idle/loaded).
    recompute();

    map.on('idle', handleIdle);
    return () => {
      cancelled = true;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      map.off('idle', handleIdle);
    };
  // Intentionally omits the full `layer` object — it is recreated by
  // dispatchLayerAction on every mutation (opacity, paint, visibility), which
  // would cause queryRenderedFeatures to fire at ~60 fps during slider drags.
  // `layer?.id` and `layer?.filter` cover all meaningful change conditions;
  // the closure still captures the current `layer` reference on each run.
  }, [map, layer?.id, layer?.filter]);

  return count;
}

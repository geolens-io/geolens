/**
 * Returns the rendered-feature count for `layer` on `map` via
 * map.queryRenderedFeatures, idle-debounced.
 *
 * Read-only: `pitfall-9-editor-polish.test.ts` forbids only write APIs
 * (setPaintProperty / setLayoutProperty / setFilter), and this hook only
 * inspects rendered state.
 *
 * Returns null when:
 *   - map is null (no instance yet)
 *   - layer is null
 *   - layer has no filter (the zero-state hint only matters when a filter is set)
 *   - the layer's MapLibre layer id is not yet on the map (the rendered count
 *     would be a false 0 while the source loads)
 */
import { useEffect, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import { getAdapter } from '../layer-adapters/registry';
import { resolveAdapterType } from '../layer-adapters/shared';

export function useFilteredFeatureCount(
  map: MaplibreMap | null,
  layer: MapLayerResponse | null,
): number | null {
  const [count, setCount] = useState<number | null>(null);
  const layerId = layer?.id ?? null;
  const layerFilter = layer?.filter ?? null;
  // Resolved adapter type (a stable string), so the count can query the
  // adapter's full sublayer-id set (mixed families, cluster bubbles).
  const adapterType = resolveAdapterType(
    layer?.dataset_geometry_type ?? null,
    layer?.style_config ?? null,
    (layer?.paint ?? undefined) as Record<string, unknown> | undefined,
  );

  useEffect(() => {
    if (!map) return;
    if (!layerId) return;
    if (!layerFilter) {
      // No filter: the "0 features after filter" hint must never fire.
      setCount(null);
      return;
    }

    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function recompute() {
      if (cancelled) return;
      if (!map) return;
      // queryRenderedFeatures returns [] when a layer id isn't on the map
      // (source still loading, layer hidden), so that is treated as null to
      // avoid false-positive hints. MapLibre layer ids are `layer-${uuid}` (see
      // use-layer-map-sync.ts), not the raw layer.id. Query the adapter's full
      // layer-id set, not just the primary id: a mixed layer's points/lines
      // render on sibling sublayers and a clustered layer's features on the
      // cluster bubbles, so a primary-only count would read 0 while the map
      // shows features and fire the destructive "0 features in view — Clear
      // filter" hint.
      const candidateIds = getAdapter(adapterType).getLayerIds(`layer-${layerId}`);
      const presentIds = candidateIds.filter((id) => !!map.getLayer(id));
      if (presentIds.length === 0) {
        setCount(null);
        return;
      }
      const features = map.queryRenderedFeatures(undefined, { layers: presentIds });
      setCount(features.length);
    }

    function handleIdle() {
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(recompute, 250);
    }

    // Initial compute (the map may already be idle/loaded).
    recompute();

    map.on('idle', handleIdle);
    return () => {
      cancelled = true;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      map.off('idle', handleIdle);
    };
  // Depends on scalar layer fields, not the `layer` object, which
  // dispatchLayerAction recreates on every mutation (opacity, paint,
  // visibility) and would fire queryRenderedFeatures at ~60 fps during slider
  // drags. `layerId` and `layerFilter` cover the meaningful changes.
  }, [map, layerId, layerFilter, adapterType]);

  return count;
}

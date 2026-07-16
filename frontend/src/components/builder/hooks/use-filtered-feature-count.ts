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
import { getAdapter } from '../layer-adapters/registry';
import { resolveAdapterType } from '../layer-adapters/shared';

export function useFilteredFeatureCount(
  map: MaplibreMap | null,
  layer: MapLayerResponse | null,
): number | null {
  const [count, setCount] = useState<number | null>(null);
  const layerId = layer?.id ?? null;
  const layerFilter = layer?.filter ?? null;
  // fix(#TBD B-046): resolved adapter type (a stable string) so the count can
  // query the adapter's full sublayer-id set (mixed families, cluster bubbles).
  const adapterType = resolveAdapterType(
    layer?.dataset_geometry_type ?? null,
    layer?.style_config ?? null,
    (layer?.paint ?? undefined) as Record<string, unknown> | undefined,
  );

  useEffect(() => {
    if (!map) return;
    if (!layerId) return;
    if (!layerFilter) {
      // No filter → "0 features after filter" hint should never fire.
      setCount(null);
      return;
    }

    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function recompute() {
      if (cancelled) return;
      if (!map) return;
      // queryRenderedFeatures returns [] when the layer id is not on the
      // map (source still loading, layer hidden, etc.) — treat as null
      // so the hint does not flash false positives during loading.
      // MapLibre layer ids are registered as `layer-${uuid}` (see
      // use-layer-map-sync.ts), NOT the raw layer.id UUID. Querying the bare
      // UUID always missed, so the count was permanently null and the
      // "0 features after filter" hint (EASY-18) never fired.
      // fix(#TBD B-046): query the adapter's FULL layer-id set, not just the
      // primary id — a mixed layer's points/lines render on sibling sublayers
      // and a clustered layer's features render on the cluster bubbles, so the
      // primary-only count read 0 while the map plainly showed features,
      // firing the destructive "0 features in view — Clear filter" hint.
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

    // Initial compute (in case the map is already idle/loaded).
    recompute();

    map.on('idle', handleIdle);
    return () => {
      cancelled = true;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      map.off('idle', handleIdle);
    };
  // Intentionally depends on scalar layer fields, not the full `layer` object.
  // The object is recreated by
  // dispatchLayerAction on every mutation (opacity, paint, visibility), which
  // would cause queryRenderedFeatures to fire at ~60 fps during slider drags.
  // `layerId` and `layerFilter` cover all meaningful change conditions.
  }, [map, layerId, layerFilter, adapterType]);

  return count;
}

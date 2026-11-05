import { useCallback, useEffect, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMapFeatureHighlight } from '@/components/dataset/hooks/use-map-feature-highlight';
import type { WidgetRenderProps } from '@/components/widgets/contract';
import type { SharedLayerResponse } from '@/types/api';
import { motionDuration } from '@/lib/reduced-motion';
import { layerHighlightSource } from '../map-data-table';

/** How long a zoomed-to feature stays highlighted once the map has come to rest. */
const FLASH_MS = 1000;
// A fit that never reports moveend must not leave the highlight on the map.
const MAX_FLIGHT_MS = 10_000;

const FIT_PADDING = 40;
const getFitPadding = () => FIT_PADDING;

/**
 * Fits the dashboard's map to a feature of a layer and flashes it with the
 * highlight a table row click paints. Null without a map or when the layer
 * isn't drawn, so a caller can leave the widget's zoom unset.
 */
export function useFeatureZoom(map: MaplibreMap | null) {
  const mapRef = useRef(map);
  mapRef.current = map;
  // The highlight hook watches the map's style from the first zoom on.
  const [zoomed, setZoomed] = useState(false);
  const { highlightFeature, clearHighlightedFeature } = useMapFeatureHighlight({
    mapRef,
    active: zoomed && map !== null,
    resetKey: 'dashboard',
    getFitPadding,
    highlightId: 'dashboard-feature-highlight',
  });
  const stopFlash = useRef<() => void>(() => undefined);
  useEffect(() => () => stopFlash.current(), []);

  return useCallback(
    (layer: SharedLayerResponse, feature: Parameters<NonNullable<WidgetRenderProps<unknown>['onZoomTo']>>[0]) => {
      const current = mapRef.current;
      if (!current) return;
      const source = layer.id ? layerHighlightSource(current, layer, layer.id) : null;
      setZoomed(true);
      stopFlash.current();
      void highlightFeature(Number(feature.id), source ? { ...source, bbox: feature.bbox } : null);
      // The countdown starts when the fit's flight ends; a jump has no flight.
      let flash: ReturnType<typeof setTimeout> | undefined;
      const arm = () => {
        clearTimeout(giveUp);
        current.off('moveend', arm);
        flash = setTimeout(clearHighlightedFeature, FLASH_MS);
      };
      stopFlash.current = () => {
        clearTimeout(giveUp);
        clearTimeout(flash);
        current.off('moveend', arm);
        stopFlash.current = () => undefined;
      };
      const jumps = motionDuration(1) === 0;
      const giveUp = jumps ? undefined : setTimeout(arm, MAX_FLIGHT_MS);
      if (jumps) arm();
      else current.once('moveend', arm);
    },
    [highlightFeature, clearHighlightedFeature],
  );
}

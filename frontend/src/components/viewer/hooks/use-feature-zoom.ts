import { useCallback, useEffect, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { fitFeatureBounds, useMapFeatureHighlight } from '@/components/dataset/hooks/use-map-feature-highlight';
import type { WidgetRenderProps } from '@/components/widgets/contract';
import type { SharedLayerResponse } from '@/types/api';
import { motionDuration } from '@/lib/reduced-motion';
import { layerHighlightSource } from '../map-data-table';

/** How long a zoomed-to feature stays highlighted once the map has come to rest. */
const FLASH_MS = 1000;
// A fit or load that never settles must not leave the highlight on the map.
const MAX_WAIT_MS = 10_000;

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
      stopFlash.current();
      if (!source) {
        clearHighlightedFeature();
        // The layer isn't drawn yet, so there is nothing to flash; the camera still moves.
        try {
          fitFeatureBounds(current, feature.bbox, FIT_PADDING);
        } catch {
          // Out-of-range coordinates leave the map where it is.
        }
        return;
      }
      setZoomed(true);
      void highlightFeature(Number(feature.id), { ...source, bbox: feature.bbox });
      // The countdown starts once the camera has stopped and the map has drawn
      // the destination, so late tiles still get a visible flash.
      let flash: ReturnType<typeof setTimeout> | undefined;
      const arm = () => {
        clearTimeout(giveUp);
        current.off('idle', arm);
        flash = setTimeout(clearHighlightedFeature, FLASH_MS);
      };
      const awaitDrawn = () => {
        current.off('moveend', awaitDrawn);
        current.once('idle', arm);
      };
      const giveUp = setTimeout(arm, MAX_WAIT_MS);
      stopFlash.current = () => {
        clearTimeout(giveUp);
        clearTimeout(flash);
        current.off('moveend', awaitDrawn);
        current.off('idle', arm);
        stopFlash.current = () => undefined;
      };
      if (motionDuration(1) === 0) awaitDrawn();
      else current.once('moveend', awaitDrawn);
    },
    [highlightFeature, clearHighlightedFeature],
  );
}

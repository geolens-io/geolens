import { useCallback, useEffect, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useMapFeatureHighlight } from '@/components/dataset/hooks/use-map-feature-highlight';
import type { WidgetRenderProps } from '@/components/widgets/contract';
import type { SharedLayerResponse } from '@/types/api';
import { layerHighlightSource } from '../map-data-table';

/** How long a zoomed-to feature stays highlighted. */
const FLASH_MS = 1000;

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
  });
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  return useCallback(
    (layer: SharedLayerResponse, feature: Parameters<NonNullable<WidgetRenderProps<unknown>['onZoomTo']>>[0]) => {
      const current = mapRef.current;
      if (!current) return;
      const source = layer.id ? layerHighlightSource(current, layer, layer.id) : null;
      setZoomed(true);
      clearTimeout(timer.current);
      void highlightFeature(Number(feature.id), source ? { ...source, bbox: feature.bbox } : null);
      timer.current = setTimeout(clearHighlightedFeature, FLASH_MS);
    },
    [highlightFeature, clearHighlightedFeature],
  );
}

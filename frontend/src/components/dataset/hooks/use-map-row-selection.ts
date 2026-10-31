import { useEffect, useRef } from 'react';
import { useMapSelectionStore } from '@/stores/map-selection-store';
import { useMapFeatureHighlight } from './use-map-feature-highlight';

type HighlightOptions = Parameters<typeof useMapFeatureHighlight>[0];

interface UseMapRowSelectionOptions extends Omit<HighlightOptions, 'resetKey'> {
  /** The table's layer; a new one clears the selection and the highlight. */
  layerKey: string;
  /**
   * A map click on another layer. Return true when the host switches the
   * table to that layer; the click's row is selected once it has.
   */
  onOtherLayer?: (layerKey: string) => boolean;
}

/**
 * Two-way selection between a map and its attribute table: a row click
 * highlights and fits its feature, and a feature clicked on the map (through
 * the selection store) selects its row. A click made before the table mounted
 * is ignored.
 */
export function useMapRowSelection({ layerKey, onOtherLayer, ...highlightOptions }: UseMapRowSelectionOptions) {
  const highlight = useMapFeatureHighlight({ ...highlightOptions, resetKey: layerKey });
  const { selectFeature } = highlight;

  const mapSelection = useMapSelectionStore((state) => state.selection);
  const handledNonceRef = useRef(mapSelection?.nonce);
  useEffect(() => {
    if (!mapSelection || mapSelection.nonce === handledNonceRef.current) return;
    if (mapSelection.layerId !== layerKey && onOtherLayer?.(mapSelection.layerId)) return;
    handledNonceRef.current = mapSelection.nonce;
    if (mapSelection.layerId === layerKey) selectFeature(mapSelection.featureId);
  }, [mapSelection, layerKey, selectFeature, onOtherLayer]);

  return highlight;
}

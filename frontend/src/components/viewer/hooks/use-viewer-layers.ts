import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';

interface LayerLike {
  id?: string | null;
  visible: boolean;
  dataset_id: string;
  table_name?: string | null;
  sort_order: number;
}

interface UseViewerLayersResult {
  visibleLayers: Set<string>;
  handleToggleVisibility: (layerKey: string) => void;
  isLegendOpen: boolean;
  setIsLegendOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
}

/**
 * Shared viewer layer visibility + responsive legend state.
 * Used by PublicMapViewerPage and PublicViewerPage (share-token viewer).
 */
export function useViewerLayers(
  layers: LayerLike[] | undefined,
  options?: { showLegend?: boolean },
): UseViewerLayersResult {
  const showLegend = options?.showLegend ?? true;

  const layerEntries = useMemo(() => createViewerLayerEntries(layers), [layers]);
  const [overriddenLayers, setOverriddenLayers] = useState<Set<string> | null>(null);

  const visibleLayers = useMemo(() => {
    if (overriddenLayers !== null) return overriddenLayers;
    return new Set(layerEntries.filter(({ layer }) => layer.visible).map(({ key }) => key));
  }, [overriddenLayers, layerEntries]);

  const handleToggleVisibility = useCallback((layerKey: string) => {
    setOverriddenLayers((prev) => {
      const current = prev ?? new Set(
        layerEntries.filter(({ layer }) => layer.visible).map(({ key }) => key),
      );
      const next = new Set(current);
      if (next.has(layerKey)) {
        next.delete(layerKey);
      } else {
        next.add(layerKey);
      }
      return next;
    });
  }, [layerEntries]);

  const [isLegendOpen, setIsLegendOpenRaw] = useState(() => {
    if (!showLegend) return false;
    return typeof window !== 'undefined' ? window.innerWidth >= 500 : true;
  });

  // Phase 20260526-builder-audit BLD-20260526-11: track whether the user has manually toggled the legend so the
  // resize handler doesn't override their preference.
  const userHasToggled = useRef(false);
  const setIsLegendOpen = useCallback(
    (value: boolean | ((prev: boolean) => boolean)) => {
      userHasToggled.current = true;
      setIsLegendOpenRaw(value);
    },
    [],
  );

  useEffect(() => {
    if (!showLegend) return;

    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const handleResize = () => {
      if (timeoutId) clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        if (userHasToggled.current) return;
        setIsLegendOpenRaw(window.innerWidth >= 500);
      }, 150);
    };

    window.addEventListener('resize', handleResize);
    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      window.removeEventListener('resize', handleResize);
    };
  }, [showLegend]);

  return { visibleLayers, handleToggleVisibility, isLegendOpen, setIsLegendOpen };
}

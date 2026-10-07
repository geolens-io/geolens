import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';

interface LayerLike {
  id?: string | null;
  visible: boolean;
  dataset_id: string;
  table_name?: string | null;
  sort_order: number;
}

const EMPTY_TOGGLES: ReadonlyMap<string, boolean> = new Map();

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
  options?: { showLegend?: boolean; mapKey?: string },
): UseViewerLayersResult {
  const showLegend = options?.showLegend ?? true;
  const mapKey = options?.mapKey;

  const layerEntries = useMemo(() => createViewerLayerEntries(layers), [layers]);
  // Explicit toggles only, tagged with the map they were made on. Layers
  // without a toggle follow their saved visibility, so a refetch that adds a
  // layer shows it, and a toggle on a layer that no longer exists is ignored.
  const [overrides, setOverrides] = useState<{ mapKey: string | undefined; toggles: ReadonlyMap<string, boolean> }>({
    mapKey,
    toggles: new Map(),
  });
  const toggles = overrides.mapKey === mapKey ? overrides.toggles : EMPTY_TOGGLES;

  // Drop toggles for layers that left the list, so one that comes back
  // starts from its saved visibility again.
  const hasStaleToggle = [...toggles.keys()].some((key) => !layerEntries.some((entry) => entry.key === key));
  if (hasStaleToggle) {
    setOverrides({
      mapKey,
      toggles: new Map([...toggles].filter(([key]) => layerEntries.some((entry) => entry.key === key))),
    });
  }

  const visibleLayers = useMemo(
    () =>
      new Set(
        layerEntries
          .filter(({ key, layer }) => toggles.get(key) ?? layer.visible)
          .map(({ key }) => key),
      ),
    [toggles, layerEntries],
  );

  const handleToggleVisibility = useCallback(
    (layerKey: string) => {
      const saved = layerEntries.find(({ key }) => key === layerKey)?.layer.visible ?? false;
      setOverrides((prev) => {
        const base = prev.mapKey === mapKey ? prev.toggles : EMPTY_TOGGLES;
        const next = new Map(base);
        next.set(layerKey, !(base.get(layerKey) ?? saved));
        return { mapKey, toggles: next };
      });
    },
    [layerEntries, mapKey],
  );

  const [isLegendOpen, setIsLegendOpenRaw] = useState(() => {
    if (!showLegend) return false;
    return typeof window !== 'undefined' ? window.innerWidth >= 500 : true;
  });

  // Phase 20260526-builder-audit #338 BLD-20260526-11: track whether the user has manually toggled the legend so the
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

import { useState, useCallback, useMemo, useEffect, useRef } from 'react';

interface LayerLike {
  visible: boolean;
  sort_order: number;
}

interface UseViewerLayersResult {
  visibleLayers: Set<number>;
  handleToggleVisibility: (sortOrder: number) => void;
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

  const [overriddenLayers, setOverriddenLayers] = useState<Set<number> | null>(null);

  const visibleLayers = useMemo(() => {
    if (overriddenLayers !== null) return overriddenLayers;
    if (!layers) return new Set<number>();
    return new Set(layers.filter((l) => l.visible).map((l) => l.sort_order));
  }, [overriddenLayers, layers]);

  const handleToggleVisibility = useCallback((sortOrder: number) => {
    setOverriddenLayers((prev) => {
      const current = prev ?? new Set(
        (layers ?? []).filter((l) => l.visible).map((l) => l.sort_order),
      );
      const next = new Set(current);
      if (next.has(sortOrder)) {
        next.delete(sortOrder);
      } else {
        next.add(sortOrder);
      }
      return next;
    });
  }, [layers]);

  const [isLegendOpen, setIsLegendOpenRaw] = useState(() => {
    if (!showLegend) return false;
    return typeof window !== 'undefined' ? window.innerWidth >= 500 : true;
  });

  // SH-21: Track whether the user has manually toggled the legend so the
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

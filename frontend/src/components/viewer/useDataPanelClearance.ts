import { useCallback, useEffect, useRef, type RefObject } from 'react';

const PROPERTY = '--viewer-data-panel-height';

// Open table heights by map, per viewport. A story keeps outgoing and standby
// maps under one viewport, so the value is the tallest open table and a map
// closing its own never clears another's.
const heights = new WeakMap<HTMLElement, Map<object, number>>();

/**
 * Publishes the docked Map data table's height on the enclosing `#map-viewport`
 * so the legend, a sibling of the map, can stay clear of the table.
 *
 * The viewport is captured at mount because a closing panel reports its zero
 * after React has detached the shell ref.
 */
export function useDataPanelClearance(
  shellRef: RefObject<HTMLElement | null>,
  onHeightChange?: (height: number) => void,
) {
  const viewportRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    viewportRef.current = shellRef.current?.closest<HTMLElement>('#map-viewport') ?? null;
  }, [shellRef]);
  const ownerRef = useRef({});
  return useCallback((height: number) => {
    const viewport = viewportRef.current;
    if (viewport) {
      const open = heights.get(viewport) ?? new Map<object, number>();
      heights.set(viewport, open);
      if (height > 0) open.set(ownerRef.current, height);
      else open.delete(ownerRef.current);
      viewport.style.setProperty(PROPERTY, `${Math.max(0, ...open.values())}px`);
    }
    onHeightChange?.(height);
  }, [onHeightChange]);
}

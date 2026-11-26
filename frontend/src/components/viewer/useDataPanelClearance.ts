import { useCallback, useEffect, useRef, type RefObject } from 'react';

const PROPERTY = '--viewer-data-panel-height';

// Which map last wrote each viewport, so only that map may reset it.
const owners = new WeakMap<HTMLElement, object>();

/**
 * Publishes the docked Map data table's height on the enclosing `#map-viewport`
 * so the legend, a sibling of the map, can stay clear of the table.
 *
 * The viewport is captured at mount because a closing panel reports its zero
 * after React has detached the shell ref. A story keeps outgoing and active maps
 * under one viewport, so a map resets the value only while it is still the one
 * it wrote; another map's later value is left alone.
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
    if (viewport && height > 0) {
      viewport.style.setProperty(PROPERTY, `${height}px`);
      owners.set(viewport, ownerRef.current);
    } else if (viewport && owners.get(viewport) === ownerRef.current) {
      viewport.style.setProperty(PROPERTY, '0px');
      owners.delete(viewport);
    }
    onHeightChange?.(height);
  }, [onHeightChange]);
}

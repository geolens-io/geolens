import { useCallback, useEffect, useRef, type RefObject } from 'react';

const PROPERTY = '--viewer-data-panel-height';

/**
 * Publishes the docked Map data table's height on the enclosing `#map-viewport`
 * so the legend, a sibling of the map, can stay clear of the table.
 *
 * The viewport is captured at mount because a closing panel reports its zero
 * after React has detached the shell ref. A map only ever writes while its own
 * panel is open, so a standby map unmounting leaves the active map's value alone.
 */
export function useDataPanelClearance(
  shellRef: RefObject<HTMLElement | null>,
  onHeightChange?: (height: number) => void,
) {
  const viewportRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    viewportRef.current = shellRef.current?.closest<HTMLElement>('#map-viewport') ?? null;
  }, [shellRef]);
  return useCallback((height: number) => {
    viewportRef.current?.style.setProperty(PROPERTY, `${height}px`);
    onHeightChange?.(height);
  }, [onHeightChange]);
}

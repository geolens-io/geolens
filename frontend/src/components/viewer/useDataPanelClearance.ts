import { useCallback, useEffect, useRef, type RefObject } from 'react';

const PROPERTY = '--viewer-data-panel-height';

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
  const writtenRef = useRef<string | null>(null);
  return useCallback((height: number) => {
    const style = viewportRef.current?.style;
    const value = `${height}px`;
    if (style && (height > 0 || style.getPropertyValue(PROPERTY) === writtenRef.current)) {
      style.setProperty(PROPERTY, value);
    }
    writtenRef.current = height > 0 ? value : null;
    onHeightChange?.(height);
  }, [onHeightChange]);
}

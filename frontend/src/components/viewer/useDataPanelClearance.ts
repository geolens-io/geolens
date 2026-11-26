import { useCallback, useEffect, useRef, type RefObject } from 'react';

const PROPERTY = '--viewer-data-panel-height';

/**
 * Publishes the docked Map data table's height on the enclosing
 * `[data-map-frame]`, the container that holds this map and its legend, so the
 * legend can stay clear of the table. Each frame has one map, hence one writer.
 *
 * The frame is captured at mount because a closing panel reports its zero
 * after React has detached the shell ref.
 */
export function useDataPanelClearance(
  shellRef: RefObject<HTMLElement | null>,
  onHeightChange?: (height: number) => void,
) {
  const frameRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    frameRef.current = shellRef.current?.closest<HTMLElement>('[data-map-frame]') ?? null;
  }, [shellRef]);
  return useCallback((height: number) => {
    frameRef.current?.style.setProperty(PROPERTY, `${height}px`);
    onHeightChange?.(height);
  }, [onHeightChange]);
}

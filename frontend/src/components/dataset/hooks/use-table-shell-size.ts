import { useCallback, useEffect, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';

const MIN_TABLE_HEIGHT = 120;
const MAX_TABLE_HEIGHT_RATIO = 0.7;
const DEFAULT_TABLE_HEIGHT = 320;
const DEFAULT_PANE_RATIO = 0.45;
// Map height kept above the table: a row fit pads 40px on each side.
const MIN_MAP_HEIGHT = 160;
// In a pane the map also carries page overlays (basemap toggle, scale bar),
// which collide below this.
const PANE_MIN_MAP_HEIGHT = 240;

interface PaneOptions {
  /** The element the table and the map share. */
  ref: React.RefObject<HTMLElement | null>;
  /** The table's floor; it wins over the map's when the pane is short. */
  minHeight?: number;
}

interface Bounds {
  min: number;
  max: number;
}

// Measured from the map's top edge, since the navbar and title bar above it
// vary in height; on a short window the table yields first, down to its minimum.
// Inside a pane, the pane's own height bounds it instead.
function tableBounds(map: MaplibreMap | null, pane: PaneOptions | undefined): Bounds {
  const element = pane?.ref.current;
  if (pane && element) {
    const min = pane.minHeight ?? MIN_TABLE_HEIGHT;
    return { min, max: Math.round(Math.max(min, element.clientHeight - PANE_MIN_MAP_HEIGHT)) };
  }
  const mapTop = map?.getContainer().getBoundingClientRect().top ?? 0;
  const available = window.innerHeight - mapTop - MIN_MAP_HEIGHT;
  const max = Math.min(available, window.innerHeight * MAX_TABLE_HEIGHT_RATIO);
  return { min: MIN_TABLE_HEIGHT, max: Math.round(Math.max(MIN_TABLE_HEIGHT, max)) };
}

function clampTableHeight(next: number, { min, max }: Bounds): number {
  return Math.round(Math.max(min, Math.min(max, next)));
}

function defaultTableHeight(bounds: Bounds, pane: PaneOptions | undefined): number {
  const element = pane?.ref.current;
  const preferred = element
    ? Math.min(DEFAULT_TABLE_HEIGHT, element.clientHeight * DEFAULT_PANE_RATIO)
    : DEFAULT_TABLE_HEIGHT;
  return clampTableHeight(preferred, bounds);
}

export interface TableShellSize {
  height: number;
  maxHeight: number;
  /** Always the latest height, for callbacks that must not re-create on a drag. */
  heightRef: React.RefObject<number>;
  /** Pointer and keyboard handlers plus aria-value* for the resize separator. */
  separatorProps: {
    'aria-valuenow': number;
    'aria-valuemin': number;
    'aria-valuemax': number;
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
    onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => void;
    onPointerUp: (e: React.PointerEvent<HTMLDivElement>) => void;
    onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
  };
}

/**
 * Height of a bottom-docked table and the handlers that resize it, in whole
 * pixels. MapLibre resizes the map from its own container observer, throttled
 * to 50ms; outside a pane the hook also calls resize() once per frame so the
 * canvas tracks a drag.
 *
 * With `pane`, the table and the map share that element's height: the table
 * starts at min(320, 45% of it) and leaves the map at least 240px, unless the
 * table's own floor needs more.
 */
export function useTableShellSize(
  mapRef: React.RefObject<MaplibreMap | null>,
  pane?: PaneOptions,
): TableShellSize {
  const paneRef = pane?.ref;
  const paneMinHeight = pane?.minHeight;
  const [bounds, setBounds] = useState(() => tableBounds(mapRef.current, pane));
  const [height, setHeight] = useState(() => defaultTableHeight(bounds, pane));
  const heightRef = useRef(height);
  heightRef.current = height;

  const dragOrigin = useRef<{ pointerY: number; height: number } | null>(null);
  const clampHeight = useCallback((next: number): number => clampTableHeight(next, bounds), [bounds]);
  // When the window or the pane shrinks, or the floor changes, an out-of-range
  // table reclamps.
  useEffect(() => {
    const options = paneRef ? { ref: paneRef, minHeight: paneMinHeight } : undefined;
    const onResize = () => {
      const next = tableBounds(mapRef.current, options);
      setBounds((current) => (current.min === next.min && current.max === next.max ? current : next));
      setHeight((current) => clampTableHeight(current, next));
    };
    onResize();
    window.addEventListener('resize', onResize);
    // A pane changes height without the window, e.g. as a dashboard collapses.
    const element = paneRef?.current;
    const observer = element && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(onResize) : null;
    if (element) observer?.observe(element);
    return () => {
      window.removeEventListener('resize', onResize);
      observer?.disconnect();
    };
  }, [mapRef, paneRef, paneMinHeight]);

  // map.resize() coalesced at most once per animation frame while the handle
  // drags, plus a final call on drag end.
  const resizeFrameRef = useRef<number | null>(null);
  const scheduleMapResize = useCallback(() => {
    if (paneRef || resizeFrameRef.current !== null) return;
    resizeFrameRef.current = window.requestAnimationFrame(() => {
      resizeFrameRef.current = null;
      mapRef.current?.resize();
    });
  }, [mapRef, paneRef]);
  useEffect(
    () => () => {
      if (resizeFrameRef.current !== null) window.cancelAnimationFrame(resizeFrameRef.current);
    },
    [],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = { pointerY: e.clientY, height: heightRef.current };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragOrigin.current) return;
    const delta = dragOrigin.current.pointerY - e.clientY;
    setHeight(clampHeight(dragOrigin.current.height + delta));
    scheduleMapResize();
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    // Final resize now; drop any queued frame so it cannot double-call.
    if (resizeFrameRef.current !== null) {
      window.cancelAnimationFrame(resizeFrameRef.current);
      resizeFrameRef.current = null;
    }
    if (!paneRef) mapRef.current?.resize();
  };
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // Proportional steps: a fixed ±px step returns to exactly the starting
    // height after up-then-down, while a proportional step scales the table
    // against its current size. Home/End still pin the exact bounds.
    const factor = e.shiftKey ? 0.25 : 0.1;
    let next: number | null = null;
    if (e.key === 'ArrowUp') next = heightRef.current * (1 + factor);
    else if (e.key === 'ArrowDown') next = heightRef.current * (1 - factor);
    else if (e.key === 'Home') next = bounds.max;
    else if (e.key === 'End') next = bounds.min;
    if (next === null) return;
    e.preventDefault();
    setHeight(clampHeight(next));
    scheduleMapResize();
  };

  return {
    height,
    maxHeight: bounds.max,
    heightRef,
    separatorProps: {
      'aria-valuenow': height,
      'aria-valuemin': bounds.min,
      'aria-valuemax': bounds.max,
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onKeyDown,
    },
  };
}

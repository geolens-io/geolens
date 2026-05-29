/**
 * Phase 1045 SP-02 — MapCoordReadout tests
 *
 * Smoke check 2026-05-15 (M-01): the readout never updated lat/lng after
 * auto-fit because only `mousemove` fired setCoords. These tests assert that
 * the component subscribes to the `move` event so programmatic flyTo /
 * fitBounds / drag-pan also update the displayed coords.
 */

import mapCoordReadoutSrc from '../MapCoordReadout.tsx?raw';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { MapCoordReadout } from '../MapCoordReadout';
import { formatRepresentativeFraction } from '@/lib/representative-fraction';

interface FakeMapState {
  lat: number;
  lng: number;
  zoom: number;
  handlers: Record<string, Array<() => void>>;
  canvas: HTMLCanvasElement;
}

function makeFakeMap(initial: { lat: number; lng: number; zoom: number }): {
  map: MaplibreMap;
  state: FakeMapState;
  fire: (event: string) => void;
  setCenter: (lat: number, lng: number) => void;
} {
  const canvas = document.createElement('canvas');
  const state: FakeMapState = {
    lat: initial.lat,
    lng: initial.lng,
    zoom: initial.zoom,
    handlers: {},
    canvas,
  };

  const map = {
    getCenter: () => ({ lat: state.lat, lng: state.lng }),
    getZoom: () => state.zoom,
    on: (event: string, handler: () => void) => {
      (state.handlers[event] ??= []).push(handler);
    },
    off: (event: string, handler: () => void) => {
      const list = state.handlers[event];
      if (!list) return;
      const idx = list.indexOf(handler);
      if (idx >= 0) list.splice(idx, 1);
    },
    getCanvas: () => canvas,
  } as unknown as MaplibreMap;

  function fire(event: string) {
    (state.handlers[event] ?? []).slice().forEach((h) => h());
  }

  function setCenter(lat: number, lng: number) {
    state.lat = lat;
    state.lng = lng;
  }

  return { map, state, fire, setCenter };
}

describe('MapCoordReadout — SP-02 move-event subscription', () => {
  let rafCallbacks: Array<() => void>;
  let originalRaf: typeof requestAnimationFrame;
  let originalCaf: typeof cancelAnimationFrame;

  beforeEach(() => {
    rafCallbacks = [];
    originalRaf = globalThis.requestAnimationFrame;
    originalCaf = globalThis.cancelAnimationFrame;
    // Synchronous rAF so we can flush updates within `act()`.
    globalThis.requestAnimationFrame = ((cb: () => void) => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    }) as typeof requestAnimationFrame;
    globalThis.cancelAnimationFrame = vi.fn();
  });

  afterEach(() => {
    globalThis.requestAnimationFrame = originalRaf;
    globalThis.cancelAnimationFrame = originalCaf;
  });

  function flushRaf() {
    const queued = rafCallbacks.slice();
    rafCallbacks = [];
    queued.forEach((cb) => cb());
  }

  it('renders initial lat / lng / zoom from map.getCenter()', () => {
    const { map } = makeFakeMap({ lat: 36.2, lng: -112.3, zoom: 9.7 });
    render(<MapCoordReadout map={map} />);
    // 36.20° N · 112.30° W · z 9.7
    expect(screen.getByText(/36\.20° N/)).toBeInTheDocument();
    expect(screen.getByText(/112\.30° W/)).toBeInTheDocument();
    expect(screen.getByText(/9\.7/)).toBeInTheDocument();
  });

  it('subscribes to the `move` event', () => {
    const { map, state } = makeFakeMap({ lat: 0, lng: 0, zoom: 2 });
    render(<MapCoordReadout map={map} />);
    expect(state.handlers.move?.length ?? 0).toBeGreaterThan(0);
  });

  it('updates lat / lng when a `move` event fires (programmatic flyTo / fitBounds)', () => {
    const { map, fire, setCenter } = makeFakeMap({ lat: 20, lng: 0, zoom: 2 });
    render(<MapCoordReadout map={map} />);

    // Stale initial state shown
    expect(screen.getByText(/20\.00° N/)).toBeInTheDocument();
    expect(screen.getByText(/0\.00° E/)).toBeInTheDocument();

    // Simulate fitBounds → camera moves to the Grand Canyon
    act(() => {
      setCenter(36.2, -112.3);
      fire('move');
      flushRaf();
    });

    expect(screen.getByText(/36\.20° N/)).toBeInTheDocument();
    expect(screen.getByText(/112\.30° W/)).toBeInTheDocument();
    expect(screen.queryByText(/20\.00° N/)).not.toBeInTheDocument();
  });

  it('unsubscribes from `move` on unmount', () => {
    const { map, state } = makeFakeMap({ lat: 0, lng: 0, zoom: 2 });
    const { unmount } = render(<MapCoordReadout map={map} />);
    expect(state.handlers.move?.length ?? 0).toBeGreaterThan(0);
    unmount();
    expect(state.handlers.move?.length ?? 0).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// SP-12 — representative-fraction scale segment
// ---------------------------------------------------------------------------

describe('MapCoordReadout — SP-12 representative-fraction segment', () => {
  let rafCallbacks: Array<() => void>;
  let originalRaf: typeof requestAnimationFrame;
  let originalCaf: typeof cancelAnimationFrame;

  beforeEach(() => {
    rafCallbacks = [];
    originalRaf = globalThis.requestAnimationFrame;
    originalCaf = globalThis.cancelAnimationFrame;
    globalThis.requestAnimationFrame = ((cb: () => void) => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    }) as typeof requestAnimationFrame;
    globalThis.cancelAnimationFrame = vi.fn();
  });

  afterEach(() => {
    globalThis.requestAnimationFrame = originalRaf;
    globalThis.cancelAnimationFrame = originalCaf;
  });

  function flushRaf() {
    const queued = rafCallbacks.slice();
    rafCallbacks = [];
    queued.forEach((cb) => cb());
  }

  it('does not render the scale segment by default (showScale omitted)', () => {
    const { map } = makeFakeMap({ lat: 0, lng: 0, zoom: 12 });
    render(<MapCoordReadout map={map} />);
    expect(screen.queryByText(/1:/)).toBeNull();
  });

  it('does not render the scale segment when showScale={false}', () => {
    const { map } = makeFakeMap({ lat: 0, lng: 0, zoom: 12 });
    render(<MapCoordReadout map={map} showScale={false} />);
    expect(screen.queryByText(/1:/)).toBeNull();
  });

  it('renders the 1:N segment when showScale={true} with the expected format at a known lat/zoom', () => {
    const { map } = makeFakeMap({ lat: 0, lng: 0, zoom: 12 });
    const { container } = render(<MapCoordReadout map={map} showScale />);

    // Derive the expected value the same way the component does.
    const expected = formatRepresentativeFraction(0, 12); // e.g. "1:144.4k"
    // The pill text content includes the full "1:N" string across the muted span + text node.
    // Use the container's full text to verify the segment appears.
    expect(container.textContent).toContain(expected.slice(2)); // the value part e.g. "144.4k"
    // The muted "1:" prefix renders as a span; the full pill should contain "1:" somewhere.
    expect(container.textContent).toMatch(/1:/);
  });

  it('updates the 1:N segment when the map moves to a different latitude (cos-lat changes)', () => {
    const { map, fire, setCenter, state } = makeFakeMap({ lat: 0, lng: 0, zoom: 12 });
    const { container } = render(<MapCoordReadout map={map} showScale />);

    // Capture initial RF value (equator)
    const initialValue = formatRepresentativeFraction(0, 12).slice(2); // e.g. "144.4k"
    expect(container.textContent).toContain(initialValue);

    // Move to lat 60 — cos(60°) = 0.5, so denominator halves → different value
    act(() => {
      setCenter(60, 0);
      fire('move');
      flushRaf();
    });

    const updatedValue = formatRepresentativeFraction(
      parseFloat((60).toFixed(2)),
      parseFloat(state.zoom.toFixed(1)),
    ).slice(2);

    expect(container.textContent).toContain(updatedValue);
    // Confirm the value changed (lat 60 vs lat 0 at same zoom)
    expect(updatedValue).not.toBe(initialValue);
  });
});

// ---------------------------------------------------------------------------
// MAP-08 — load-bearing positioning regression pin
//
// MAP-09 (basemap sheet single close button) is covered by
// `MapBuilderPage.sheet-close-button.test.tsx` Tests 1-7. The basemap sheet
// is the same `<SheetContent showCloseButton={false}>` wrapper pattern
// verified there; no additional test is needed here.
// ---------------------------------------------------------------------------

describe('MapCoordReadout — MAP-08 load-bearing positioning regression pin', () => {
  it('MAP-08 (RESP-02 regression): renders with right-14 / top-2 / z-10 positioning classes', () => {
    const { map } = makeFakeMap({ lat: 0, lng: 0, zoom: 5 });
    const { container } = render(<MapCoordReadout map={map} />);

    // The outer wrapper anchors at `top-2 right-14 z-10 pointer-events-none`.
    // right-14 = 56px — load-bearing to clear the NavigationControl when anchored
    // top-right in ViewerMap.tsx (see RESP-02 — Phase 1051 Plan 09 docstring).
    // In BuilderMap.tsx the NavigationControl is top-left (Pitfall #10), so the
    // 56px offset has visual slack in builder context, but must NOT be reduced
    // without auditing ViewerMap.tsx first.
    const pill = container.firstChild as HTMLElement;
    expect(pill).toHaveClass('right-14');
    expect(pill).toHaveClass('top-2');
    expect(pill).toHaveClass('z-10');
  });

  it('MAP-08 source-text pin: RESP-02 docstring references both BuilderMap and ViewerMap contexts', () => {
    const src = mapCoordReadoutSrc;
    // The docstring that ships the cross-context contract must be present.
    expect(src).toContain('RESP-02 — Phase 1051 Plan 09');
    // Both call sites are mentioned so future engineers know reducing right-14
    // in one context may break the other.
    expect(src).toContain('BuilderMap');
    expect(src).toContain('ViewerMap');
    // Guard against "px optimization" PRs that shrink the offset on the readout
    // pill's absolute-positioning line. The pill must not use a smaller offset
    // adjacent to top-2 on the same className.
    expect(src).not.toMatch(/top-2.*right-12/);
    expect(src).not.toMatch(/top-2.*right-10/);
    expect(src).not.toMatch(/top-2.*right-8/);
  });
});

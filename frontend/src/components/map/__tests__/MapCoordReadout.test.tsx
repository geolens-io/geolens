/**
 * Phase 1045 SP-02 — MapCoordReadout tests
 *
 * Smoke check 2026-05-15 (M-01): the readout never updated lat/lng after
 * auto-fit because only `mousemove` fired setCoords. These tests assert that
 * the component subscribes to the `move` event so programmatic flyTo /
 * fitBounds / drag-pan also update the displayed coords.
 */

import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { MapCoordReadout } from '../MapCoordReadout';

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
    originalRaf = global.requestAnimationFrame;
    originalCaf = global.cancelAnimationFrame;
    // Synchronous rAF so we can flush updates within `act()`.
    global.requestAnimationFrame = ((cb: () => void) => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    }) as typeof requestAnimationFrame;
    global.cancelAnimationFrame = vi.fn();
  });

  afterEach(() => {
    global.requestAnimationFrame = originalRaf;
    global.cancelAnimationFrame = originalCaf;
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

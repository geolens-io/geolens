// fix(#1778): Terra Draw undo history grew without bound and was never reset
// on the feature-edit (drag) path. These tests mock the `terra-draw` and
// `terra-draw-maplibre-gl-adapter` packages so the hook's `change`/`finish`
// handlers can be driven directly, without a real WebGL map.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useTerraDraw } from '@/components/drawing/hooks/use-terra-draw';

type Listener = (...args: unknown[]) => void;

class FakeTerraDraw {
  listeners: Record<string, Listener[]> = {};
  enabled = true;
  on(event: string, cb: Listener) {
    (this.listeners[event] ??= []).push(cb);
  }
  off(event: string, cb: Listener) {
    this.listeners[event] = (this.listeners[event] ?? []).filter((c) => c !== cb);
  }
  emit(event: string, ...args: unknown[]) {
    for (const cb of [...(this.listeners[event] ?? [])]) cb(...args);
  }
  start = vi.fn();
  stop = vi.fn();
  getSnapshot = vi.fn(() => [{ properties: { mode: 'point' } }] as unknown[]);
  getSnapshotFeature = vi.fn((id: string | number) => ({
    type: 'Feature',
    id,
    properties: { mode: 'point' },
    geometry: { type: 'Point', coordinates: [0, 0] },
  }));
  removeFeatures = vi.fn();
  addFeatures = vi.fn();
  clear = vi.fn();
  selectFeature = vi.fn();
  setMode = vi.fn();
}

let lastInstance: FakeTerraDraw | null = null;

vi.mock('terra-draw', () => ({
  TerraDraw: vi.fn().mockImplementation(function TerraDrawCtor() {
    lastInstance = new FakeTerraDraw();
    return lastInstance;
  }),
  TerraDrawPointMode: vi.fn(),
  TerraDrawLineStringMode: vi.fn(),
  TerraDrawPolygonMode: vi.fn(),
  TerraDrawRectangleMode: vi.fn(),
  TerraDrawCircleMode: vi.fn(),
  TerraDrawFreehandMode: vi.fn(),
  TerraDrawSelectMode: vi.fn(),
}));

vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: vi.fn(),
}));

function fakeMap(): MaplibreMap {
  return {
    getStyle: () => ({ layers: [], sources: {} }),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
  } as unknown as MaplibreMap;
}

afterEach(() => {
  lastInstance = null;
});

describe('useTerraDraw — undo history bound (fix #1778)', () => {
  it('caps history growth instead of retaining one snapshot per change event forever', () => {
    const map = fakeMap();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null));
    const td = lastInstance!;

    // Simulate a long drag/freehand trace: far more `change` events than the
    // 50-entry cap, with no 'finish' in between (mirrors the reported class:
    // one full store snapshot pushed per mousemove-derived update).
    act(() => {
      for (let i = 0; i < 200; i++) td.emit('change');
    });

    // Count how many undo steps are actually available. An unbounded ring
    // would allow 199 undos (200 pushes); a ring capped at 50 allows at
    // most 49.
    let undoCount = 0;
    while (result.current.canUndo && undoCount < 500) {
      act(() => {
        result.current.undo();
      });
      undoCount++;
    }
    expect(undoCount).toBeLessThanOrEqual(49);
    expect(undoCount).toBeGreaterThan(0);
  });

  it('resets undo history on a committed feature edit (dragFeature), not just on draw/setMode/clear', () => {
    const map = fakeMap();
    const onEditFinish = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), onEditFinish));
    const td = lastInstance!;

    // Push enough 'change' snapshots (as if dragging a feature) to make undo available.
    act(() => {
      td.emit('change');
      td.emit('change');
    });
    expect(result.current.canUndo).toBe(true);

    // Commit the drag — this is the 'finish' event with a drag action, which
    // previously reset nothing.
    act(() => {
      td.emit('finish', 'feat-1', { action: 'dragFeature', mode: 'select' });
    });

    expect(onEditFinish).toHaveBeenCalledWith('feat-1', expect.anything());
    expect(result.current.canUndo).toBe(false);
  });
});

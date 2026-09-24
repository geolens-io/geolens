// Paint edits to a layer coalesce into one write per animation frame, and every other edit writes at once.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLayerMapSync } from '../use-layer-map-sync';
import { __resetForTest } from '@/lib/builder/raf-coalesce';
import { syncLayersToMap, toSyncInput } from '@/components/builder/map-sync';
import { fillAdapter } from '@/components/builder/layer-adapters/fill-adapter';
import { SAVED_LAYERS } from '@/test/fixtures/saved-layers';
import { FIXTURE_TOKENS } from '@/test/fixtures/render-contexts';
import { RecordingMap } from '@/test/recording-map';
import type { MapLayerResponse } from '@/types/api';

// ---------------------------------------------------------------------------
// rAF mock helpers (same pattern as raf-coalesce.test.ts)
// ---------------------------------------------------------------------------
type RafCallback = (time: number) => void;

function mockRaf() {
  let _handle = 0;
  const _queue = new Map<number, RafCallback>();

  const requestAnimationFrame = vi.fn((cb: RafCallback): number => {
    const handle = ++_handle;
    _queue.set(handle, cb);
    return handle;
  });

  const cancelAnimationFrame = vi.fn((handle: number): void => {
    _queue.delete(handle);
  });

  function flush(time = 0): void {
    const entries = Array.from(_queue.entries());
    _queue.clear();
    for (const [, cb] of entries) {
      cb(time);
    }
  }

  return { requestAnimationFrame, cancelAnimationFrame, flush };
}

const { polygon, extrusion } = SAVED_LAYERS;

/** A map one sync pass drew for the layers. */
function syncedMap(layers: MapLayerResponse[]) {
  const recording = new RecordingMap();
  syncLayersToMap(recording.map, layers.map(toSyncInput), new Map(FIXTURE_TOKENS), undefined, { current: new Set() }, { current: '' });
  recording.calls.length = 0;
  return recording;
}

function paintOf(recording: RecordingMap, layer: MapLayerResponse) {
  return recording.layer(`layer-${layer.id}`)?.paint;
}

let raf: ReturnType<typeof mockRaf>;

beforeEach(() => {
  raf = mockRaf();
  vi.stubGlobal('requestAnimationFrame', raf.requestAnimationFrame);
  vi.stubGlobal('cancelAnimationFrame', raf.cancelAnimationFrame);
});

afterEach(() => {
  __resetForTest();
  raf.flush();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useLayerMapSync paint coalescing', () => {
  it('writes ten paint edits to one layer once, on the next frame', () => {
    const recording = syncedMap([polygon]);
    const write = vi.spyOn(fillAdapter, 'syncPaint');
    const { result } = renderHook(() => useLayerMapSync([polygon], vi.fn(), vi.fn(), { current: recording.map }));

    act(() => {
      for (let i = 0; i < 10; i++) result.current.handlePaintChange(polygon.id, { 'fill-color': `#00000${i}` });
    });
    expect(write).not.toHaveBeenCalled();

    act(() => raf.flush());

    expect(write).toHaveBeenCalledTimes(1);
    expect(paintOf(recording, polygon)?.['fill-color']).toBe('#000009');
  });

  it('writes paint edits to two layers on the same frame', () => {
    const recording = syncedMap([polygon, extrusion]);
    const write = vi.spyOn(fillAdapter, 'syncPaint');
    const { result } = renderHook(() => useLayerMapSync([polygon, extrusion], vi.fn(), vi.fn(), { current: recording.map }));

    act(() => {
      result.current.handlePaintChange(polygon.id, { 'fill-color': '#aaaaaa' });
      result.current.handlePaintChange(extrusion.id, { ...extrusion.paint, 'fill-color': '#bbbbbb' });
    });
    expect(write).not.toHaveBeenCalled();

    act(() => raf.flush());

    expect(write).toHaveBeenCalledTimes(2);
    expect(paintOf(recording, polygon)?.['fill-color']).toBe('#aaaaaa');
    expect(paintOf(recording, extrusion)?.['fill-color']).toBe('#bbbbbb');
  });

  it('writes a toggle without a frame', () => {
    const recording = syncedMap([polygon]);
    const { result } = renderHook(() => useLayerMapSync([polygon], vi.fn(), vi.fn(), { current: recording.map }));

    act(() => result.current.handleToggleVisibility(polygon.id, false));

    expect(recording.layer(`layer-${polygon.id}`)?.layout.visibility).toBe('none');
    expect(raf.requestAnimationFrame).not.toHaveBeenCalled();
  });

  it('lands a paint edit made during a style swap and an opacity edit made after the style loads', () => {
    const recording = syncedMap([polygon]);
    recording.styleLoaded = false;
    const { result, rerender } = renderHook(
      ({ layers }: { layers: MapLayerResponse[] }) => useLayerMapSync(layers, vi.fn(), vi.fn(), { current: recording.map }),
      { initialProps: { layers: [polygon] } },
    );

    act(() => result.current.handlePaintChange(polygon.id, { 'fill-color': '#00ff00' }));
    expect(paintOf(recording, polygon)?.['fill-color']).toBe(polygon.paint['fill-color']);

    recording.styleLoaded = true;
    rerender({ layers: [{ ...polygon, paint: { 'fill-color': '#00ff00' } }] });
    act(() => result.current.handleOpacityChange(polygon.id, 0.25));
    act(() => raf.flush());

    expect(paintOf(recording, polygon)).toMatchObject({ 'fill-color': '#00ff00', 'fill-layer-opacity': 0.25 });
  });
});

import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { recordTileSampling } from '@/lib/tile-sampling';
import { useSampledTileSources } from '../hooks/use-sampled-tile-sources';

const template = 'https://geolens.test/api/tiles/data.quakes/{z}/{x}/{y}.pbf?sig=s';
const tile = (z: number, x: number, y: number) => ({ canonical: { z, x, y } });

function fakeMap(sourceTemplate = template) {
  const handlers = new Set<() => void>();
  let view = [tile(5, 1, 2), tile(5, 2, 2)];
  const map = {
    getSource: vi.fn((id: string) =>
      id === 'source-quakes'
        ? { type: 'vector', tiles: [sourceTemplate], tileSize: 512, minzoom: 0, maxzoom: 14 }
        : undefined),
    coveringTiles: vi.fn(() => view),
    on: vi.fn((_event: string, handler: () => void) => handlers.add(handler)),
    off: vi.fn((_event: string, handler: () => void) => handlers.delete(handler)),
  };
  const moveTo = (tiles: ReturnType<typeof tile>[]) => {
    view = tiles;
    for (const handler of handlers) handler();
  };
  return { map: map as unknown as MapLibreMap, moveTo };
}

describe('useSampledTileSources', () => {
  it('marks a source while a sampled tile of it is in view and clears it when none is', () => {
    const { map, moveTo } = fakeMap();
    const sourceIds = new Set(['source-quakes', 'source-missing']);
    const { result } = renderHook(() => useSampledTileSources({ current: map }, true, sourceIds));
    const sampledUrl = template.replace('{z}', '5').replace('{x}', '2').replace('{y}', '2');

    expect(result.current.size).toBe(0);

    act(() => recordTileSampling(sampledUrl, true));
    expect([...result.current]).toEqual(['source-quakes']);

    act(() => moveTo([tile(5, 7, 7)]));
    expect(result.current.size).toBe(0);

    act(() => moveTo([tile(5, 2, 2)]));
    expect([...result.current]).toEqual(['source-quakes']);

    act(() => recordTileSampling(sampledUrl, false));
    expect(result.current.size).toBe(0);
  });

  it('matches a site-relative tile template to the absolute URL the protocol records', () => {
    const { map } = fakeMap('/api/tiles/data.quakes/{z}/{x}/{y}.pbf?sig=s');
    const { result } = renderHook(() => useSampledTileSources({ current: map }, true, new Set(['source-quakes'])));

    act(() => recordTileSampling(`${window.location.origin}/api/tiles/data.quakes/5/1/2.pbf?sig=s`, true));
    expect([...result.current]).toEqual(['source-quakes']);
  });
});

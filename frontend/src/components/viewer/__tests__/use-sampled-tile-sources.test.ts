import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { recordTileSampling } from '@/lib/tile-sampling';
import { useSampledTileSources } from '../hooks/use-sampled-tile-sources';

const template = 'https://geolens.test/api/tiles/data.quakes/{z}/{x}/{y}.pbf?sig=s';
const tile = (z: number, x: number, y: number) => ({ canonical: { z, x, y } });

function fakeMap(sourceTemplate = template, { sourceAdded = true } = {}) {
  const handlers = new Map<string, Set<() => void>>();
  let view = [tile(5, 1, 2), tile(5, 2, 2)];
  let added = sourceAdded;
  const map = {
    getSource: vi.fn((id: string) =>
      added && id === 'source-quakes'
        ? { type: 'vector', tiles: [sourceTemplate], tileSize: 512, minzoom: 0, maxzoom: 14 }
        : undefined),
    coveringTiles: vi.fn(() => view),
    on: vi.fn((event: string, handler: () => void) => {
      if (!handlers.has(event)) handlers.set(event, new Set());
      handlers.get(event)!.add(handler);
    }),
    off: vi.fn((event: string, handler: () => void) => handlers.get(event)?.delete(handler)),
  };
  const fire = (event: string) => {
    for (const handler of handlers.get(event) ?? []) handler();
  };
  const moveTo = (tiles: ReturnType<typeof tile>[]) => {
    view = tiles;
    fire('moveend');
  };
  const addSource = () => {
    added = true;
  };
  return { map: map as unknown as MapLibreMap, moveTo, fire, addSource };
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

  it('finds a tile recorded as sampled before its source was added once the map settles', () => {
    act(() => recordTileSampling('https://geolens.test/api/tiles/data.quakes/5/1/2.pbf?sig=s', true));
    const { map, fire, addSource } = fakeMap(template, { sourceAdded: false });
    const { result } = renderHook(() => useSampledTileSources({ current: map }, true, new Set(['source-quakes'])));
    expect(result.current.size).toBe(0);

    addSource();
    act(() => fire('idle'));
    expect([...result.current]).toEqual(['source-quakes']);
  });
});

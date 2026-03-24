import { describe, it, expect, vi } from 'vitest';
import { reorderDataLayers } from '@/components/builder/map-sync';

function createMockMap(existingLayerIds: string[] = []) {
  const existing = new Set(existingLayerIds);
  return {
    getLayer: vi.fn((id: string) => (existing.has(id) ? { id } : undefined)),
    moveLayer: vi.fn(),
  } as unknown as import('maplibre-gl').Map;
}

describe('reorderDataLayers', () => {
  it('moves layers in reverse order so first in array ends up on top', () => {
    const map = createMockMap([
      'layer-a', 'layer-a-outline',
      'layer-b', 'layer-b-outline',
      'layer-c', 'layer-c-outline',
    ]);
    const layers = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];

    reorderDataLayers(map, layers);

    const calls = (map.moveLayer as ReturnType<typeof vi.fn>).mock.calls.map(
      (c: string[]) => c[0],
    );
    // Data/outline layers moved in reverse: c, b, a (so a ends up on top)
    expect(calls).toEqual([
      'layer-c', 'layer-c-outline',
      'layer-b', 'layer-b-outline',
      'layer-a', 'layer-a-outline',
    ]);
  });

  it('skips layers not present on the map', () => {
    const map = createMockMap(['layer-a', 'layer-c']);
    const layers = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];

    reorderDataLayers(map, layers);

    const calls = (map.moveLayer as ReturnType<typeof vi.fn>).mock.calls.map(
      (c: string[]) => c[0],
    );
    // layer-b and all outlines/labels not on map — skipped
    expect(calls).toEqual(['layer-c', 'layer-a']);
  });

  it('does nothing for empty layers array', () => {
    const map = createMockMap([]);

    reorderDataLayers(map, []);

    expect(map.moveLayer).not.toHaveBeenCalled();
  });

  it('moves label layers after data layers so labels render on top', () => {
    const map = createMockMap([
      'layer-a', 'layer-a-label',
      'layer-b', 'layer-b-label',
    ]);
    const layers = [{ id: 'a' }, { id: 'b' }];

    reorderDataLayers(map, layers);

    const calls = (map.moveLayer as ReturnType<typeof vi.fn>).mock.calls.map(
      (c: string[]) => c[0],
    );
    // Data layers first (reverse), then label layers (reverse)
    expect(calls).toEqual([
      'layer-b', 'layer-a',         // data pass
      'layer-b-label', 'layer-a-label',  // label pass
    ]);
  });
});

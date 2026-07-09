import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useMapLayers } from '../use-map-layers';
import type { Map as MaplibreMap } from 'maplibre-gl';

vi.mock('@/lib/env', () => ({
  getEnvConfig: () => ({ TILE_BASE_URL: 'http://tiles.test' }),
}));

vi.mock('maplibre-gl', () => ({ default: {} }));

function fakeMap() {
  return {
    addSource: vi.fn(),
    addLayer: vi.fn(),
    getSource: vi.fn(() => undefined),
  } as unknown as MaplibreMap;
}

function addedLayers(map: MaplibreMap) {
  return (map.addLayer as ReturnType<typeof vi.fn>).mock.calls.map(
    (c) => c[0] as { id: string; type: string; filter?: unknown },
  );
}

function runHook(geometryType: string) {
  const mapRef = { current: null };
  const { result } = renderHook(() =>
    useMapLayers({
      tableName: 'sketch_table',
      geometryType,
      tileToken: null,
      mapRef,
    }),
  );
  const map = fakeMap();
  result.current.addVectorLayers(map);
  return map;
}

describe('useMapLayers generic-geometry rendering (fix #430 codex r21)', () => {
  it('installs all three family renderers with $type filters for GEOMETRY', () => {
    const map = runHook('GEOMETRY');
    const layers = addedLayers(map);
    expect(layers.map((l) => l.id)).toEqual([
      'vector-fill',
      'vector-outline',
      'vector-lines',
      'vector-points',
    ]);
    // Every generic layer filters by geometry family so no feature renders
    // through the wrong adapter.
    for (const layer of layers) {
      expect(layer.filter).toBeDefined();
    }
  });

  it('does the same for GEOMETRYCOLLECTION display types', () => {
    const map = runHook('GEOMETRYCOLLECTION');
    expect(addedLayers(map).map((l) => l.id)).toContain('vector-points');
    expect(addedLayers(map).map((l) => l.id)).toContain('vector-lines');
    expect(addedLayers(map).map((l) => l.id)).toContain('vector-fill');
  });

  it('keeps the single-renderer behavior for concrete types', () => {
    const point = runHook('MULTIPOINT');
    expect(addedLayers(point).map((l) => l.id)).toEqual(['vector-points']);
    expect(addedLayers(point)[0].filter).toBeUndefined();

    const line = runHook('LINESTRING');
    expect(addedLayers(line).map((l) => l.id)).toEqual(['vector-lines']);

    const polygon = runHook('POLYGON');
    expect(addedLayers(polygon).map((l) => l.id)).toEqual([
      'vector-fill',
      'vector-outline',
    ]);
  });
});

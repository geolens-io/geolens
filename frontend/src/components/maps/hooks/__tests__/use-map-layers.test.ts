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
    (c) => c[0] as { id: string; type: string; filter?: unknown; 'source-layer'?: string },
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

  it('waits for an async tenant prefix before installing immutable source-layer names', () => {
    const map = fakeMap();
    const mapRef = { current: map };
    const { rerender } = renderHook(
      ({ ready, prefix }: { ready: boolean; prefix?: string | null }) =>
        useMapLayers({
          tableName: 'roads',
          geometryType: 'LINESTRING',
          tileToken: null,
          mapRef,
          mvtSourceLayerReady: ready,
          mvtSourceLayerPrefix: prefix,
        }),
      { initialProps: { ready: false, prefix: undefined as string | null | undefined } },
    );

    expect(map.addSource).not.toHaveBeenCalled();
    expect(map.addLayer).not.toHaveBeenCalled();

    rerender({ ready: false, prefix: null });
    expect(map.addSource).not.toHaveBeenCalled();

    rerender({ ready: true, prefix: 'tenant_acme' });

    expect(map.addSource).toHaveBeenCalledOnce();
    expect(addedLayers(map)).toHaveLength(1);
    expect(addedLayers(map)[0]?.['source-layer']).toBe('tenant_acme.roads');
  });
});

// #1362 codex r2: the raster tile route is a fixed per-dataset path, and a
// public dataset's tile response carries `Cache-Control: public,
// max-age=3600` — so the browser's own HTTP cache can keep serving
// pre-replace bytes for an identical URL. tileVersion busts that the same
// way the vector source already does via buildSignedTileUrl.
describe('useMapLayers raster tile source cache-busting', () => {
  function runRasterHook(rasterTileUrl: string | null, tileVersion?: string | null) {
    const mapRef = { current: null };
    const { result } = renderHook(() =>
      useMapLayers({
        tableName: null,
        geometryType: null,
        rasterTileUrl,
        tileVersion,
        tileToken: null,
        mapRef,
      }),
    );
    const map = fakeMap();
    result.current.addRasterLayers(map);
    return map;
  }

  function addedSourceConfig(map: MaplibreMap) {
    const call = (map.addSource as ReturnType<typeof vi.fn>).mock.calls[0];
    return call?.[1] as { tiles: string[] } | undefined;
  }

  it('appends tileVersion as a cache-busting query param when present', () => {
    const map = runRasterHook(
      '/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png',
      '2026-08-10T00:00:00Z',
    );
    const source = addedSourceConfig(map);
    expect(source?.tiles[0]).toContain('/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png?v=');
    expect(source?.tiles[0]).toContain(encodeURIComponent('2026-08-10T00:00:00Z'));
  });

  it('omits the query param when tileVersion is absent', () => {
    const map = runRasterHook('/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png', null);
    const source = addedSourceConfig(map);
    expect(source?.tiles[0]).not.toContain('?v=');
  });
});

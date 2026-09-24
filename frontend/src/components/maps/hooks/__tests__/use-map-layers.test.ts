import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { VectorTileToken } from '@/api/tiles';
import { previewSourceId, useMapLayers } from '../use-map-layers';
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

function runHook(geometryType: string, elevationColumn?: string) {
  const mapRef = { current: null };
  const { result } = renderHook(() =>
    useMapLayers({
      tableName: 'sketch_table',
      geometryType,
      tileToken: null,
      mapRef,
      elevationColumn,
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
      'preview-layer-dataset',
      'preview-layer-dataset-outline',
      'preview-layer-dataset-lines',
      'preview-layer-dataset-points',
    ]);
    // Every generic layer filters by geometry family so no feature renders
    // through the wrong adapter.
    for (const layer of layers) {
      expect(layer.filter).toBeDefined();
    }
  });

  it('does the same for GEOMETRYCOLLECTION display types', () => {
    const map = runHook('GEOMETRYCOLLECTION');
    expect(addedLayers(map).map((l) => l.id)).toContain('preview-layer-dataset-points');
    expect(addedLayers(map).map((l) => l.id)).toContain('preview-layer-dataset-lines');
    expect(addedLayers(map).map((l) => l.id)).toContain('preview-layer-dataset');
  });

  it('keeps the single-renderer behavior for concrete types', () => {
    const point = runHook('MULTIPOINT');
    expect(addedLayers(point).map((l) => l.id)).toEqual(['preview-layer-dataset']);
    expect(addedLayers(point)[0].filter).toBeUndefined();

    const line = runHook('LINESTRING');
    expect(addedLayers(line).map((l) => l.id)).toEqual(['preview-layer-dataset']);

    const polygon = runHook('POLYGON');
    expect(addedLayers(polygon).map((l) => l.id)).toEqual([
      'preview-layer-dataset',
      'preview-layer-dataset-outline',
    ]);

    const extruded = runHook('POLYGON', 'height_m');
    expect(addedLayers(extruded).map((l) => l.id)).toEqual(['preview-layer-dataset-extrusion']);
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

describe('useMapLayers vector source', () => {
  function vectorToken(sig: string): VectorTileToken {
    return { kind: 'vector', sig, exp: 2000000000, scope: 'scope-1', expires_in: 900 };
  }

  it('requests tiles from z0 and overzooms z14 tiles past z14', () => {
    const map = runHook('POLYGON');
    expect(map.addSource).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ type: 'vector', minzoom: 0, maxzoom: 14 }),
    );
  });

  it('re-signs the source in place when the token changes', () => {
    const setTiles = vi.fn();
    const map = {
      ...fakeMap(),
      getSource: vi.fn((id: string) => (id === previewSourceId('roads') ? { setTiles } : undefined)),
    } as unknown as MaplibreMap;
    const mapRef = { current: map };
    const { rerender } = renderHook(
      ({ tileToken }: { tileToken: VectorTileToken }) =>
        useMapLayers({ tableName: 'roads', geometryType: 'LINESTRING', tileToken, mapRef }),
      { initialProps: { tileToken: vectorToken('first') } },
    );
    setTiles.mockClear();

    rerender({ tileToken: vectorToken('second') });

    expect(setTiles).toHaveBeenCalledExactlyOnceWith([
      'http://tiles.test/tiles/data.roads/{z}/{x}/{y}.pbf?sig=second&exp=2000000000&scope=scope-1',
    ]);
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

  // fix(#1372): the server now embeds `?v=<tile_cache_version>` in the raster
  // tile URL (the shared nginx cache keys on it). A second client-side `v`
  // would make nginx key on the wrong (first) value, so the append must yield
  // to a server-versioned URL.
  it('does not append a second v when the server URL already carries one', () => {
    const map = runRasterHook(
      '/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png?v=7&pv=3',
      '2026-08-10T00:00:00Z',
    );
    const source = addedSourceConfig(map);
    expect(source?.tiles[0]).toBe(
      `${window.location.origin}/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png?v=7&pv=3`,
    );
  });

  // fix(#2007): a legacy row with no tile_cache_version emits `?pv=` alone.
  // A `?` appended onto that is a malformed URL, not a second version.
  it('leaves a server URL carrying only the publication version alone', () => {
    const map = runRasterHook(
      '/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png?pv=3',
      '2026-08-10T00:00:00Z',
    );
    const source = addedSourceConfig(map);
    expect(source?.tiles[0]).toBe(
      `${window.location.origin}/raster-tiles/dataset-1/tiles/{z}/{x}/{y}.png?pv=3`,
    );
  });
});

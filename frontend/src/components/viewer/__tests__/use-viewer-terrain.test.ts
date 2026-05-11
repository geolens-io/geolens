import { act, renderHook, waitFor } from '@/test/test-utils';
import { useViewerTerrain } from '../hooks/use-viewer-terrain';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';

function createMap() {
  const sources = new Map<string, {
    type?: string;
    tiles?: string[];
    bounds?: number[];
    tileSize?: number;
    minzoom?: number;
    maxzoom?: number;
    serialize: () => {
      tiles?: string[];
      bounds?: number[];
      tileSize?: number;
      minzoom?: number;
      maxzoom?: number;
    };
  }>();
  return {
    isStyleLoaded: vi.fn(() => true),
    getSource: vi.fn((id: string) => sources.get(id)),
    addSource: vi.fn((id: string, spec: { type?: string; tiles?: string[] }) => {
      sources.set(id, { ...spec, serialize: () => spec });
    }),
    removeSource: vi.fn((id: string) => {
      sources.delete(id);
    }),
    setTerrain: vi.fn(),
  };
}

function layer(overrides: Partial<SharedLayerResponse>): SharedLayerResponse {
  return {
    dataset_id: overrides.dataset_id ?? 'dem-1',
    dataset_name: overrides.dataset_name ?? 'Elevation',
    display_name: overrides.display_name ?? null,
    table_name: overrides.table_name ?? 'dem_tiles',
    geometry_type: overrides.geometry_type ?? null,
    column_info: overrides.column_info ?? null,
    sort_order: overrides.sort_order ?? 1,
    visible: overrides.visible ?? true,
    opacity: overrides.opacity ?? 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: overrides.filter ?? null,
    label_config: overrides.label_config ?? null,
    popup_config: overrides.popup_config ?? null,
    style_config: overrides.style_config ?? null,
    show_in_legend: overrides.show_in_legend ?? true,
    layer_type: overrides.layer_type ?? 'raster_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'raster_dataset',
    is_dem: overrides.is_dem ?? true,
    dem_vertical_units: overrides.dem_vertical_units ?? 'meters',
    is_3d: overrides.is_3d ?? false,
    tile_url: overrides.tile_url ?? '/raster-tiles/dem-1/tiles/{z}/{x}/{y}.png',
    feature_count: overrides.feature_count ?? null,
    ...overrides,
  };
}

describe('useViewerTerrain', () => {
  it('applies persisted terrain source and exaggeration', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result } = renderHook(() => useViewerTerrain({
      layers: [layer({})],
      mapRef,
      mapReady: true,
      terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2.5 },
    }));

    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    expect(map.addSource).toHaveBeenCalledWith('terrain-dem', expect.objectContaining({
      type: 'raster-dem',
      tiles: [`${window.location.origin}/raster-tiles/dem-1/tiles/{z}/{x}/{y}.png`],
      encoding: 'mapbox',
    }));
    expect(map.setTerrain).toHaveBeenCalledWith({ source: 'terrain-dem', exaggeration: 2.5 });
  });

  it('uses raster tile tokens for public viewer DEM terrain', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result } = renderHook(() => useViewerTerrain({
      layers: [layer({ tile_url: '' })],
      mapRef,
      mapReady: true,
      terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2.5 },
      tokenMap: new Map([
        ['dem-1', {
          kind: 'raster',
          tile_url: '/raster-tiles/token-dem/tiles/{z}/{x}/{y}.png',
          bounds: [-113, 36, -111.5, 37],
          minzoom: 2,
          maxzoom: 14,
          tile_size: 512,
          format: 'png',
        }],
      ]),
    }));

    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    expect(map.addSource).toHaveBeenCalledWith('terrain-dem', expect.objectContaining({
      type: 'raster-dem',
      tiles: [`${window.location.origin}/raster-tiles/token-dem/tiles/{z}/{x}/{y}.png`],
      bounds: [-113, 36, -111.5, 37],
      minzoom: 2,
      maxzoom: 14,
      tileSize: 512,
    }));
  });

  it('can seed terrain from the saved source id and token before layer metadata is complete', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result } = renderHook(() => useViewerTerrain({
      layers: [],
      mapRef,
      mapReady: true,
      terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 2.5 },
      tokenMap: new Map([
        ['dem-1', {
          kind: 'raster',
          tile_url: '/raster-tiles/token-only-dem/tiles/{z}/{x}/{y}.png',
          bounds: null,
          minzoom: 0,
          maxzoom: 18,
          tile_size: 256,
          format: 'png',
        }],
      ]),
    }));

    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    expect(map.addSource).toHaveBeenCalledWith('terrain-dem', expect.objectContaining({
      tiles: [`${window.location.origin}/raster-tiles/token-only-dem/tiles/{z}/{x}/{y}.png`],
    }));
  });

  it('clears terrain when the saved config is disabled or unavailable', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result, rerender } = renderHook(
      ({ sourceId, enabled }: { sourceId: string; enabled: boolean }) => useViewerTerrain({
        layers: [layer({})],
        mapRef,
        mapReady: true,
        terrainConfig: { enabled, source_dataset_id: sourceId, exaggeration: 1 },
      }),
      { initialProps: { sourceId: 'dem-1', enabled: false } },
    );

    await waitFor(() => expect(result.current.terrainReady).toBe(false));
    expect(map.setTerrain).toHaveBeenCalledWith(null);

    rerender({ sourceId: 'missing-dem', enabled: true });
    await waitFor(() => expect(result.current.terrainReady).toBe(false));
    expect(map.setTerrain).toHaveBeenLastCalledWith(null);
  });

  it('reapplies persisted terrain after a style reload', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result } = renderHook(() => useViewerTerrain({
      layers: [layer({})],
      mapRef,
      mapReady: true,
      terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1.75 },
    }));

    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    map.setTerrain.mockClear();

    act(() => {
      result.current.reseedTerrainOnStyleLoad();
    });

    expect(map.setTerrain).toHaveBeenCalledWith({ source: 'terrain-dem', exaggeration: 1.75 });
  });
});

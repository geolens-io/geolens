import { act, renderHook, waitFor } from '@/test/test-utils';
import { isViewerTerrainExpected, useViewerTerrain } from '../hooks/use-viewer-terrain';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { SharedLayerResponse } from '@/types/api';

function createMap() {
  const handlers = new Map<string, Set<() => void>>();
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
    once: vi.fn((event: string, handler: () => void) => {
      const existing = handlers.get(event) ?? new Set();
      existing.add(handler);
      handlers.set(event, existing);
    }),
    off: vi.fn((event: string, handler: () => void) => {
      handlers.get(event)?.delete(handler);
    }),
    emit: (event: string) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) {
        // Delete BEFORE invoking (maplibre removes a once-listener before it
        // runs) so a handler that re-arms itself with the same identity — the
        // #454 re-arm — lands in the set instead of being swallowed by dedup.
        handlers.get(event)?.delete(handler);
        handler();
      }
    },
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

  // fix(#451): rows for the bound dataset exist but none is terrain-capable
  // (legacy/corrupt binding) — the mesh must stay off, matching the reveal
  // gate and legend, instead of silently draping from the raster token.
  it('clears terrain when the bound dataset has rows but no terrain-capable DEM rendering', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result } = renderHook(() => useViewerTerrain({
      layers: [layer({ is_dem: false, dataset_record_type: 'vector_dataset' })],
      mapRef,
      mapReady: true,
      terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 },
      tokenMap: new Map([
        ['dem-1', {
          kind: 'raster',
          tile_url: '/raster-tiles/token-dem/tiles/{z}/{x}/{y}.png',
          bounds: null,
          minzoom: 0,
          maxzoom: 18,
          tile_size: 256,
          format: 'png',
        }],
      ]),
    }));

    await waitFor(() => expect(result.current.terrainReady).toBe(false));
    expect(map.setTerrain).toHaveBeenCalledWith(null);
    expect(map.addSource).not.toHaveBeenCalled();
  });

  // fix(#452): the viewer legend's live eye toggle must flatten the mesh —
  // the saved `visible` flag never reflects that client-side override.
  it('clears terrain when the bound DEM is live-hidden and restores it on re-show', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result, rerender } = renderHook(
      ({ liveVisible }: { liveVisible: boolean }) => useViewerTerrain({
        layers: [layer({})],
        mapRef,
        mapReady: true,
        terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1.5 },
        demLayerLiveVisible: liveVisible,
      }),
      { initialProps: { liveVisible: true } },
    );

    await waitFor(() => expect(result.current.terrainReady).toBe(true));

    rerender({ liveVisible: false });
    await waitFor(() => expect(result.current.terrainReady).toBe(false));
    expect(map.setTerrain).toHaveBeenLastCalledWith(null);

    rerender({ liveVisible: true });
    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    expect(map.setTerrain).toHaveBeenLastCalledWith({ source: 'terrain-dem', exaggeration: 1.5 });
  });

  // fix(#454): same hole as BuilderMap — a reseed idle landing mid
  // style-transition used to no-op silently, leaving the viewer mesh flat.
  it('re-arms when the reseed idle lands mid style-transition (#454)', async () => {
    const map = createMap();
    const mapRef = { current: map as unknown as MaplibreMap };

    const { result } = renderHook(() => useViewerTerrain({
      layers: [layer({})],
      mapRef,
      mapReady: true,
      terrainConfig: { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 },
    }));
    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    map.setTerrain.mockClear();

    // Style swap: reseed defers to idle; that idle lands while the next
    // transition is still in flight.
    map.isStyleLoaded.mockReturnValue(false);
    act(() => {
      result.current.reseedTerrainOnStyleLoad();
    });
    act(() => {
      map.emit('idle');
    });
    expect(map.setTerrain).not.toHaveBeenCalled();

    // Style settles — the re-armed idle must reattach the mesh.
    map.isStyleLoaded.mockReturnValue(true);
    act(() => {
      map.emit('idle');
    });
    await waitFor(() => expect(result.current.terrainReady).toBe(true));
    expect(map.setTerrain).toHaveBeenLastCalledWith({ source: 'terrain-dem', exaggeration: 1 });
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

    expect(map.setTerrain).not.toHaveBeenCalled();
    act(() => {
      map.emit('idle');
    });

    expect(map.setTerrain).toHaveBeenCalledWith({ source: 'terrain-dem', exaggeration: 1.75 });
  });
});

// fix(#451): the ViewerMap reveal gate. A regression here degrades to a silent
// 4s veil on every terrain-enabled map with a hidden/unresolvable DEM — no
// other test observes that, so pin the predicate directly.
describe('isViewerTerrainExpected', () => {
  const enabled = { enabled: true, source_dataset_id: 'dem-1', exaggeration: 1 };

  it('expects terrain for an enabled config with a visible terrain-capable DEM', () => {
    expect(isViewerTerrainExpected([layer({})], enabled)).toBe(true);
  });

  it('does not expect terrain when the config is disabled or absent', () => {
    expect(isViewerTerrainExpected([layer({})], { ...enabled, enabled: false })).toBe(false);
    expect(isViewerTerrainExpected([layer({})], null)).toBe(false);
  });

  it('does not expect terrain when the bound DEM is saved hidden', () => {
    expect(isViewerTerrainExpected([layer({ visible: false })], enabled)).toBe(false);
  });

  it('does not expect terrain when no terrain-capable rendering resolves', () => {
    expect(isViewerTerrainExpected([], enabled)).toBe(false);
    expect(
      isViewerTerrainExpected([layer({ is_dem: false, dataset_record_type: 'vector_dataset' })], enabled),
    ).toBe(false);
  });
});

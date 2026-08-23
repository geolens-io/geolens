// fix(#890): the viewer's first-party 401/403 branch treated recoverTileAuth()'s
// `true` as recovery for every tile, raster included. A raster/DEM auth failure
// cannot be cured by a fresh tile token (its auth rides the Authorization header
// attached in setTransformRequest), so the surface stayed silent and the only
// trace was the red console row logUnhandledMapError still emits for
// `/raster-tiles/` URLs — a blank raster layer with no user-visible reason.
//
// The re-mint still runs (its apiFetch renews an expiring JWT, which IS what a
// raster 401 needs — codex P1 on this PR), but a raster failure no longer counts
// as recovered: it surfaces the tile-error toast. The vector path is unchanged.
import type { ReactNode } from 'react';
import { render, waitFor } from '@/test/test-utils';
import type { SharedLayerResponse } from '@/types/api';

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const tokenState = vi.hoisted(() => ({ refreshTokens: vi.fn() }));
vi.mock('@/components/viewer/hooks/use-viewer-tokens', () => ({
  useViewerTokens: () => ({
    tokenMap: new Map([['dataset-dem', { kind: 'raster', tile_url: '/raster-tiles/dataset-dem/tiles/{z}/{x}/{y}.png' }]]),
    tokenError: false,
    // The re-mint the recovery path kicks — it must still fire for raster (the
    // JWT refresh rides it) without silencing the surface.
    refreshTokens: tokenState.refreshTokens,
  }),
}));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: () => ({ data: [] }),
  useTileConfig: () => ({ data: { cdn_base_url: null } }),
  useBranding: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-webgl-recovery', () => ({
  useWebGLRecovery: () => ({ contextLost: false, reload: vi.fn() }),
}));
vi.mock('@/components/viewer/hooks/use-viewer-terrain', () => ({
  useViewerTerrain: () => ({ terrainReady: false, reseedTerrainOnStyleLoad: vi.fn() }),
  isViewerTerrainExpected: () => false,
}));
vi.mock('@/components/map/MapCoordReadout', () => ({ MapCoordReadout: () => null }));
vi.mock('@/components/builder/map-sync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/builder/map-sync')>();
  return { ...actual, applyBasemapConfigToMap: vi.fn(), syncLayersToMap: vi.fn() };
});
vi.mock('@/lib/builder/basemap-style-mutation', () => ({ applySublayerOverrides: vi.fn() }));

type FakeMap = Record<string, ReturnType<typeof vi.fn>> & {
  emit: (event: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => {
  const handlers = new Map<string, Set<(payload?: unknown) => void>>();
  const track = (event: string, handler: (payload?: unknown) => void) => {
    const existing = handlers.get(event) ?? new Set();
    existing.add(handler);
    handlers.set(event, existing);
  };
  const canvas = { style: { cursor: '' }, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const fakeMap = {
    isStyleLoaded: vi.fn(() => true),
    on: vi.fn(track),
    once: vi.fn(track),
    off: vi.fn((event: string, handler: (payload?: unknown) => void) => {
      handlers.get(event)?.delete(handler);
    }),
    setTransformRequest: vi.fn(),
    getLayer: vi.fn(() => ({ id: 'x' })),
    getSource: vi.fn(() => null),
    getStyle: vi.fn(() => ({ version: 8, sources: {}, layers: [] })),
    queryRenderedFeatures: vi.fn(() => []),
    getCanvas: vi.fn(() => canvas),
    getZoom: vi.fn(() => 5),
    easeTo: vi.fn(),
    moveLayer: vi.fn(),
    removeSource: vi.fn(),
    setTerrain: vi.fn(),
    setMissingStyleImageResolver: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFilter: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn(),
    removeLayer: vi.fn(),
    triggerRepaint: vi.fn(),
    setLayerZoomRange: vi.fn(),
    hasImage: vi.fn(() => true),
    addImage: vi.fn(),
    emit: (event: string, payload?: unknown) => {
      for (const handler of Array.from(handlers.get(event) ?? [])) handler(payload);
    },
  } as unknown as FakeMap;
  return { fakeMap, reset: () => handlers.clear() };
});

vi.mock('@vis.gl/react-maplibre', async () => {
  const React = await import('react');
  return {
    Map: ({ children, onLoad }: { children?: ReactNode; onLoad?: (e: { target: FakeMap }) => void }) => {
      React.useEffect(() => {
        onLoad?.({ target: mapState.fakeMap });
      }, [onLoad]);
      return <div data-testid="mapgl">{children}</div>;
    },
    NavigationControl: () => null,
    ScaleControl: () => null,
    FullscreenControl: () => null,
    AttributionControl: () => null,
    TerrainControl: () => null,
    Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  };
});

import { toast } from 'sonner';
import { ViewerMap } from '../ViewerMap';

const LAYER = {
  id: 'dem-layer',
  dataset_id: 'dataset-dem',
  dataset_name: 'Elevation',
  display_name: 'Elevation',
  table_name: 'elevation',
  geometry_type: 'RASTER',
  column_info: null,
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: {},
  layout: {},
  filter: null,
  label_config: null,
  popup_config: null,
  style_config: null,
  tile_url: '',
} as unknown as SharedLayerResponse;

const RASTER_URL = `${window.location.origin}/raster-tiles/dataset-dem/tiles/9/151/191.png`;

async function renderViewer() {
  render(
    <ViewerMap
      layers={[LAYER]}
      basemapStyle="openfreemap-positron"
      basemapConfig={null}
      showBasemapLabels={true}
      terrainConfig={null}
      initialViewState={{ center_lng: 0, center_lat: 0, zoom: 2, bearing: 0, pitch: 0 }}
      visibleLayers={new Set(['dem-layer'])}
    />,
  );
  await waitFor(() => {
    expect(mapState.fakeMap.on).toHaveBeenCalledWith('error', expect.any(Function));
  });
}

describe('ViewerMap raster/DEM tile auth errors (fix #890)', () => {
  beforeEach(() => {
    mapState.reset();
    tokenState.refreshTokens.mockClear();
    vi.mocked(toast.error).mockClear();
  });

  it('surfaces the tile-error toast for a raster 403 instead of reading the re-mint as recovery', async () => {
    await renderViewer();

    mapState.fakeMap.emit('error', { error: { status: 403, url: RASTER_URL } });

    // fix(#890) (codex P1): the re-mint still runs — its apiFetch renews an
    // expiring JWT, which is what a raster 401/403 actually needs — but its
    // `true` must not silence the surface the way it does for a vector tile.
    expect(tokenState.refreshTokens).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ id: 'viewer-map-error' }),
    );
  });

  it('still re-mints for a first-party vector 403 and stays quiet (fix #621 intact)', async () => {
    await renderViewer();

    mapState.fakeMap.emit('error', {
      error: { status: 403, url: `${window.location.origin}/api/tiles/data.elevation/9/151/191.pbf?sig=stale` },
    });

    expect(tokenState.refreshTokens).toHaveBeenCalledTimes(1);
    expect(toast.error).not.toHaveBeenCalled();
  });
});
